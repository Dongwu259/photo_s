"""v2.4 词汇表扩展 + verifier + ModelScope 塔源（auto-tone 插件 hermetic 测试）

不下载大权重、不依赖 torch 的部分全走；torch 部分（局部头 / verifier
头）用合成 checkpoint 在 CPU 上小规模验证。
"""

import json
import os
import sys

import numpy as np
import pytest
from PIL import Image

# 追加而非插到最前：不干扰 GUI 测试的模块解析（Windows CI 实测敏感）
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "plugins",
                            "auto-tone"))


@pytest.fixture()
def tiny_img(tmp_path):
    img = Image.new("RGB", (16, 16))
    px = img.load()
    for y in range(16):
        for x in range(16):
            px[x, y] = (x * 16, y * 16, (x + y) * 8)
    p = tmp_path / "in.jpg"
    img.save(p)
    return str(p)


# ── 塔解析器（ModelScope 源）───────────────────────────────


class TestTowerResolver:
    def test_passthrough_local_path_and_url(self):
        from photo_s_plugin_auto_tone import models
        assert models.resolve_tower_pretrained(
            "ViT-L-16-SigLIP-384", "/tmp/x.pt") == "/tmp/x.pt"
        assert models.resolve_tower_pretrained(
            "ViT-L-16-SigLIP-384", "https://e/x.pt") == "https://e/x.pt"
        assert models.resolve_tower_pretrained("ViT-L-16-SigLIP-384",
                                               None) is None

    def test_unknown_tower_passthrough(self):
        from photo_s_plugin_auto_tone import models
        # 未登记的塔：透传给 open_clip 维持旧行为
        assert models.resolve_tower_pretrained(
            "ViT-B-32", "laion2b_s34b_b79k") == "laion2b_s34b_b79k"

    def test_registry_pins_shas_and_modelscope_ids(self):
        from photo_s_plugin_auto_tone import models
        for repo, meta in models.TOWERS.items():
            assert len(meta["sha256"]) == 64
            assert meta["size"] > 1_000_000
            assert meta["modelscope"], repo
            assert meta["filename"] == "open_clip_pytorch_model.bin"

    def test_tower_spec_urls(self, monkeypatch):
        from photo_s_plugin_auto_tone import models
        for k in ("PHOTOS_AUTO_TONE_TOWER_URL",
                  "PHOTOS_AUTO_TONE_TOWER_SHA256"):
            monkeypatch.delenv(k, raising=False)
        spec = models._tower_spec("timm/ViT-L-16-SigLIP-384", "hf")
        assert spec.url == ("https://huggingface.co/timm/ViT-L-16-SigLIP-384"
                            "/resolve/main/open_clip_pytorch_model.bin")
        assert spec.name == ("towers/timm__ViT-L-16-SigLIP-384/"
                             "open_clip_pytorch_model.bin")
        spec_ms = models._tower_spec("timm/ViT-L-16-SigLIP-384",
                                     "modelscope")
        assert spec_ms.url.startswith("https://modelscope.cn/models/")
        assert "/resolve/master/" in spec_ms.url

    def test_modelscope_source_skips_hf(self, monkeypatch, tmp_path):
        """TOWER_SOURCE=modelscope：直接走 MS URL（不碰 huggingface.co）。"""
        from photo_s_plugin_auto_tone import models

        monkeypatch.setenv("PHOTOS_AUTO_TONE_TOWER_SOURCE", "modelscope")
        monkeypatch.setenv("PHOTOS_CACHE_DIR", str(tmp_path))
        urls = []

        def fake_ensure(spec):
            urls.append(spec.url)
            raise RuntimeError("offline test")

        import photo_s.modelstore as ms_mod
        monkeypatch.setattr(ms_mod, "ensure", fake_ensure)
        # 让 HF 缓存必不命中
        monkeypatch.setattr(models, "_hf_cache_hit", lambda repo: None)
        with pytest.raises(RuntimeError, match="modelscope"):
            models.resolve_tower_pretrained("ViT-L-16-SigLIP-384", "webli")
        assert urls and all(u.startswith("https://modelscope.cn/")
                            for u in urls)

    def test_auto_chain_falls_back_to_modelscope(self, monkeypatch, tmp_path):
        from photo_s_plugin_auto_tone import models

        monkeypatch.delenv("PHOTOS_AUTO_TONE_TOWER_SOURCE", raising=False)
        monkeypatch.setenv("PHOTOS_CACHE_DIR", str(tmp_path))
        monkeypatch.setattr(models, "_hf_cache_hit", lambda repo: None)
        tried = []

        def fake_ensure(spec):
            tried.append(spec.url)
            if "huggingface.co" in spec.url:
                raise RuntimeError("SSL: CERTIFICATE_VERIFY_FAILED")
            return "/downloaded/tower.bin"

        import photo_s.modelstore as ms_mod
        monkeypatch.setattr(ms_mod, "ensure", fake_ensure)
        out = models.resolve_tower_pretrained("ViT-L-16-SigLIP-384", "webli")
        assert out == "/downloaded/tower.bin"
        assert any("huggingface.co" in u for u in tried)
        assert any("modelscope.cn" in u for u in tried)

    def test_hf_cache_hit_short_circuits(self, monkeypatch):
        from photo_s_plugin_auto_tone import models
        monkeypatch.setattr(models, "_hf_cache_hit",
                            lambda repo: f"/hf/{repo}/model.bin")
        out = models.resolve_tower_pretrained("ViT-L-14", "openai")
        assert out == ("/hf/timm/vit_large_patch14_clip_224.openai/"
                       "model.bin")

    def test_all_sources_failed_error_mentions_knobs(self, monkeypatch,
                                                     tmp_path):
        from photo_s_plugin_auto_tone import models

        monkeypatch.setenv("PHOTOS_AUTO_TONE_TOWER_SOURCE", "hf")
        monkeypatch.setenv("PHOTOS_CACHE_DIR", str(tmp_path))
        monkeypatch.setattr(models, "_hf_cache_hit", lambda repo: None)

        import photo_s.modelstore as ms_mod
        monkeypatch.setattr(ms_mod, "ensure",
                            lambda spec: (_ for _ in ()).throw(
                                RuntimeError("boom")))

        with pytest.raises(RuntimeError) as ei:
            models.resolve_tower_pretrained("ViT-L-16-SigLIP-384", "webli")
        assert "PHOTOS_AUTO_TONE_TOWER_SOURCE=modelscope" in str(ei.value)


# ── predictor 局部头（合成 checkpoint，CPU）─────────────────


def _fake_local_checkpoint(tmp_path, regions=("subject", "person"),
                           params=("exposure", "clarity")):
    torch = pytest.importorskip("torch")
    torch.manual_seed(7)
    in_dim = 32
    head = torch.nn.Sequential(
        torch.nn.Linear(in_dim, 16), torch.nn.GELU(),
        torch.nn.Linear(16, len(regions) * len(params)))
    # 让输出非中性：末层权重清零、偏置推离 0（输出恒定可断言）
    with torch.no_grad():
        head[2].weight.zero_()
        head[2].bias.fill_(0.8)
    # 模拟训练侧保存（Dropout 槽位占索引）：net.<idx*2>.<param>
    sd = {}
    for name, t in head.state_dict().items():
        idx, rest = name.split(".", 1)
        sd[f"net.{int(idx) * 2}.{rest}"] = t
    ck = {
        "feat_dim": in_dim, "state_dict": dict(sd),
        "targets": ["exposure"], "ranges": {"exposure": (-2.0, 2.0)},
        "local_regions": list(regions), "local_params": list(params),
        "local_ranges": {"exposure": (-1.0, 1.0), "clarity": (-1.0, 1.0)},
        "local_state_dict": dict(sd),
    }
    p = tmp_path / "local_head.pt"
    torch.save(ck, p)
    return str(p), head


class TestPredictorLocalHead:
    def test_load_and_predict_local(self, tmp_path, monkeypatch, tiny_img):
        torch = pytest.importorskip("torch")
        ck_path, head = _fake_local_checkpoint(tmp_path)

        from photo_s_plugin_auto_tone import models as pkg_models
        from photo_s_plugin_auto_tone.core import predictor as pred_mod

        # 不走真塔：塔与特征全部用桩
        monkeypatch.setattr(pkg_models, "get_shared_clip",
                            lambda mn, pt, dev: (None, None))
        monkeypatch.setattr(
            pred_mod.AutoTonePredictor, "_extract_features",
            lambda self, img: torch.ones(1, 32).to(self.device))
        p = pred_mod.AutoTonePredictor(model_path=ck_path)
        p.load()
        assert p.local_mlp is not None
        assert p.local_regions == ["subject", "person"]
        assert p.local_params == ["exposure", "clarity"]

        out = p.predict_local(Image.new("RGB", (8, 8)))
        assert out and out[0]["region"] == "subject"
        assert set(out[0]["params"]) <= {"exposure", "clarity"}
        for item in out:
            for v in item["params"].values():
                assert -1.0 <= v <= 1.0

    def test_no_local_head_returns_empty(self, tmp_path, monkeypatch):
        torch = pytest.importorskip("torch")
        ck_path, _ = _fake_local_checkpoint(tmp_path)

        from photo_s_plugin_auto_tone import models as pkg_models
        from photo_s_plugin_auto_tone.core import predictor as pred_mod

        monkeypatch.setattr(pkg_models, "get_shared_clip",
                            lambda mn, pt, dev: (None, None))
        # 抹掉 local_state_dict → 旧 checkpoint 行为
        ck = torch.load(ck_path, weights_only=True)
        ck.pop("local_state_dict")
        torch.save(ck, ck_path)
        p = pred_mod.AutoTonePredictor(model_path=ck_path)
        monkeypatch.setattr(
            pred_mod.AutoTonePredictor, "_extract_features",
            lambda self, img: torch.ones(1, 32))
        p.load()
        assert p.local_mlp is None
        assert p.predict_local(Image.new("RGB", (8, 8))) == []


# ── verifier（合成头，CPU）──────────────────────────────────


def _fake_verifier_head(tmp_path, score_logit=1.5):
    torch = pytest.importorskip("torch")
    torch.manual_seed(3)
    head = torch.nn.Sequential(
        torch.nn.Linear(32, 16), torch.nn.GELU(), torch.nn.Linear(16, 1))
    with torch.no_grad():
        head[2].weight.zero_()
        head[2].bias.fill_(score_logit)
    sd = {}
    for name, t in head.state_dict().items():
        idx, rest = name.split(".", 1)
        sd[f"net.{int(idx) * 2}.{rest}"] = t
    ck = {"schema": 1, "type": "aesthetic_head",
          "model_name": "ViT-L-16-SigLIP-384", "pretrained": "webli",
          "sig_dim": 32, "state_dict": sd,
          "norm": {"mean": 6.0, "std": 1.0}}
    p = tmp_path / "aesthetic_head.pt"
    torch.save(ck, p)
    return str(p), head


class TestVerifier:
    def test_head_scores_within_bounds(self, tmp_path, monkeypatch):
        torch = pytest.importorskip("torch")
        head_path, _ = _fake_verifier_head(tmp_path)

        from photo_s_plugin_auto_tone.core import verifier as v_mod

        ver = v_mod.AestheticVerifier(path=head_path, device="cpu")
        # 塔嵌入桩：单位向量（head 末层 bias 主导 → 分数稳定）
        monkeypatch.setattr(
            v_mod.AestheticVerifier, "head_tower_encode",
            lambda self, x: torch.ones(1, 32))
        r = ver.score(Image.new("RGB", (8, 8)))
        assert r["loaded"] and r["source"] == "siglip-head"
        assert 1.0 <= r["score"] <= 10.0
        assert r["bucket"] in ("low", "medium-low", "medium",
                               "medium-high", "high")

    def test_untrained_head_reports_unavailable(self, monkeypatch, tmp_path):
        from photo_s_plugin_auto_tone.core import verifier as v_mod

        monkeypatch.setenv("PHOTOS_CACHE_DIR", str(tmp_path))  # 无缓存头
        monkeypatch.delenv("PHOTOS_AUTO_TONE_AESTHETIC_HEAD", raising=False)
        r = v_mod.verify_aesthetic(Image.new("RGB", (8, 8)))
        assert r["score"] is None and r["loaded"] is False
        assert "train_verifier" in r["raw"] or "qwen" in r["raw"]

    def test_head_path_env_override(self, tmp_path, monkeypatch):
        from photo_s_plugin_auto_tone.core import verifier as v_mod

        f = tmp_path / "my_head.pt"
        f.write_bytes(b"x")
        monkeypatch.setenv("PHOTOS_AUTO_TONE_AESTHETIC_HEAD", str(f))
        assert v_mod.head_path() == str(f)

    def test_prefer_qwen_without_extra_fails_closed(self):
        from photo_s_plugin_auto_tone.core import verifier as v_mod

        r = v_mod.verify_aesthetic(Image.new("RGB", (8, 8)),
                                   prefer="qwen")
        assert r["score"] is None and r["loaded"] is False

    def test_bucketize_matches_qwen_buckets(self):
        from photo_s_plugin_auto_tone.core.verifier import bucketize
        assert bucketize(2.0) == "low"
        assert bucketize(5.0) == "medium-low"
        assert bucketize(6.0) == "medium"
        assert bucketize(7.0) == "medium-high"
        assert bucketize(9.0) == "high"
        assert bucketize(None) == "unknown"


# ── 协议 / schema / 渲染委托 ────────────────────────────────


class TestContract:
    def test_output_schema_has_additive_local(self):
        from photo_s_plugin_auto_tone import OUTPUT_SCHEMA
        props = OUTPUT_SCHEMA["properties"]
        assert "local" in props
        item = props["local"]["items"]
        assert item["required"] == ["region", "params"]

    def test_plugin_provides_verify_and_params(self):
        from photo_s_plugin_auto_tone import AutoTonePlugin
        assert "verify" in AutoTonePlugin.provides
        assert hasattr(AutoTonePlugin, "auto_tone_params")
        assert hasattr(AutoTonePlugin, "verify")

    def test_auto_tone_params_without_ctx(self):
        from photo_s_plugin_auto_tone import AutoTonePlugin
        out = AutoTonePlugin().auto_tone_params(0.8, None)
        assert out["options"] == {} and out["local"] == []
        assert out["warnings"]

    def test_render_options_delegates_to_real_pipeline(self, monkeypatch,
                                                       tiny_img, tmp_path):
        """photo_s.autotone 可用 → 全字段渲染（不再只有 3 字段简化路径）。"""
        from photo_s_plugin_auto_tone.core import render as r_mod

        called = {}

        import photo_s.autotone as at_mod

        def spy(img, params):
            called["params"] = params
            return img

        monkeypatch.setattr(at_mod, "apply_auto_tone_params", spy)
        out_path = str(tmp_path / "out.jpg")
        r_mod.render_options(
            Image.open(tiny_img),
            {"exposure": 0.3, "wb_tint": 4.0, "clarity": 0.1},
            out_path)
        assert "params" in called
        assert called["params"]["options"]["wb_tint"] == 4.0
        assert os.path.exists(out_path)

    def test_render_options_falls_back_without_photo_s(
            self, monkeypatch, tiny_img, tmp_path):
        from photo_s_plugin_auto_tone.core import render as r_mod

        real_import = __import__

        def no_photo_s(name, *a, **k):
            if name == "photo_s.autotone":
                raise ImportError("photo_s missing")
            return real_import(name, *a, **k)

        monkeypatch.setattr("builtins.__import__", no_photo_s)
        out_path = str(tmp_path / "out2.jpg")
        r_mod.render_options(Image.open(tiny_img),
                             {"exposure": 0.5}, out_path)
        assert os.path.exists(out_path)

    def test_mcp_registers_verify_tool(self):
        from photo_s_plugin_auto_tone.api import mcp_tools

        added = []

        class FakeMCP:
            def add_tool(self, fn, name=None, description=None):
                added.append(name or fn.__name__)

        mcp_tools.register_mcp_tools(FakeMCP())
        assert "verify_aesthetic" in added
        assert "auto_tone" in added and "aesthetic_score" in added

    def test_rest_route_table_includes_verify(self):
        from photo_s_plugin_auto_tone.api import rest

        handler = type("H", (), {"do_POST": lambda self: None})
        rest.register_routes(handler)
        assert hasattr(handler, "_do_aesthetic_verify")
        assert getattr(handler, "_auto_tone_routes_patched", False)


# ── pipeline local 贯通（桩 predictor）──────────────────────


class TestPipelineLocal:
    def test_local_flows_to_result_and_scales_with_strength(
            self, tiny_img):
        from photo_s_plugin_auto_tone.core import pipeline as pipe_mod

        class StubPredictor:
            targets = ["exposure"]
            ranges = {"exposure": (-2.0, 2.0)}

            def load(self):
                pass

            def predict(self, img):
                return {"exposure": 0.4}

            def predict_local(self, img):
                return [{"region": "subject",
                         "params": {"exposure": -0.4, "clarity": 0.2}}]

        class StubAnomaly:
            def load(self):
                pass

            def score(self, img):
                return 0.0, {}

        class StubRAG:
            train_clip = None

            def load(self):
                pass

        r = pipe_mod.run_auto_tone(
            tiny_img, strength=1.0, render=False,
            predictor=StubPredictor(), anomaly_detector=StubAnomaly(),
            rag_enhancer=StubRAG())
        assert r["local"] == [{"region": "subject",
                               "params": {"exposure": -0.4,
                                          "clarity": 0.2}}]

        r_half = pipe_mod.run_auto_tone(
            tiny_img, strength=0.5, render=False,
            predictor=StubPredictor(), anomaly_detector=StubAnomaly(),
            rag_enhancer=StubRAG())
        assert r_half["local"][0]["params"]["exposure"] == \
            pytest.approx(-0.2)
        assert r_half["local"][0]["params"]["clarity"] == \
            pytest.approx(0.1)

    def test_no_local_key_when_head_predicts_nothing(self, tiny_img):
        from photo_s_plugin_auto_tone.core import pipeline as pipe_mod

        class StubPredictor:
            targets = ["exposure"]
            ranges = {"exposure": (-2.0, 2.0)}

            def load(self):
                pass

            def predict(self, img):
                return {"exposure": 0.4}

            def predict_local(self, img):
                return []

        class StubAnomaly:
            def load(self):
                pass

            def score(self, img):
                return 0.0, {}

        class StubRAG:
            train_clip = None

            def load(self):
                pass

        r = pipe_mod.run_auto_tone(
            tiny_img, strength=1.0, render=False,
            predictor=StubPredictor(), anomaly_detector=StubAnomaly(),
            rag_enhancer=StubRAG())
        assert "local" not in r  # 加性键：空则不携带
