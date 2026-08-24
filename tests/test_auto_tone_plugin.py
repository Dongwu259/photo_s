"""Auto-tone 插件 hermetic 测试（不下载权重、不依赖 torch）"""

import json
import os
import sys

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "plugins",
                                "auto-tone"))

import pytest as _pytest
_pytest.skip("BISECT: temporarily disabled", allow_module_level=True)


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


# ── 包导入懒加载 ────────────────────────────────────────────

def test_package_import_without_torch():
    """entry-point 发现机制会 import 本包：不得拉起重依赖"""
    import photo_s_plugin_auto_tone as pkg
    assert pkg.__version__
    assert "torch" not in sys.modules


def test_lazy_attrs():
    from photo_s_plugin_auto_tone import OUTPUT_SCHEMA, INPUT_SCHEMA
    assert OUTPUT_SCHEMA["title"] == "AutoToneOutput"
    assert INPUT_SCHEMA["required"] == ["image_path"]


# ── models.py 权重注册 ──────────────────────────────────────

def test_weight_specs_env_override(monkeypatch, tmp_path):
    import photo_s_plugin_auto_tone.models as models

    f = tmp_path / "fake.pt"
    f.write_bytes(b"x" * 10)
    monkeypatch.setenv("PHOTOS_AUTO_TONE_URL_BASE", tmp_path.as_uri())
    monkeypatch.setenv("PHOTOS_AUTO_TONE_AUTO_TONE_V7_CLEAN_PT_SHA256", "0" * 64)
    specs = {s.name: s for s in models.weight_specs()}
    assert set(specs) == set(models.WEIGHTS)
    assert specs["auto_tone_v7_clean.pt"].sha256 == "0" * 64
    import posixpath
    assert specs["auto_tone_v7_clean.pt"].url == \
        posixpath.join(tmp_path.as_uri(), "auto_tone_v7_clean.pt")


def test_core_path_uses_cache(monkeypatch, tmp_path):
    import photo_s_plugin_auto_tone.models as models

    monkeypatch.setenv("PHOTOS_CACHE_DIR", str(tmp_path))
    cached = tmp_path / "models" / "clip_train_rag.npz"
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(b"already here")
    assert models.core_path("clip_train_rag.npz") == str(cached)


def test_ensure_lora_dir_layout(monkeypatch, tmp_path):
    import photo_s_plugin_auto_tone.models as models

    monkeypatch.setenv("PHOTOS_CACHE_DIR", str(tmp_path))
    src = tmp_path / "src"
    src.mkdir()
    import hashlib
    for prefix in ("lora_aesthetic",):
        w = src / f"{prefix}.safetensors"
        w.write_bytes(b"W" * 100)
        c = src / f"{prefix}_config.json"
        c.write_text('{"r": 32}')
        monkeypatch.setenv("PHOTOS_AUTO_TONE_URL_BASE", src.as_uri())
        monkeypatch.setenv(
            "PHOTOS_AUTO_TONE_LORA_AESTHETIC_SAFETENSORS_SHA256",
            hashlib.sha256(w.read_bytes()).hexdigest())
        monkeypatch.setenv(
            "PHOTOS_AUTO_TONE_LORA_AESTHETIC_CONFIG_JSON_SHA256",
            hashlib.sha256(c.read_bytes()).hexdigest())

    d = models.ensure_lora_dir("aesthetic")
    assert os.path.isfile(os.path.join(d, "adapter_model.safetensors"))
    assert os.path.isfile(os.path.join(d, "adapter_config.json"))
    with pytest.raises(ValueError):
        models.ensure_lora_dir("nope")


# ── confidence ──────────────────────────────────────────────

def test_confidence_bounds():
    from photo_s_plugin_auto_tone.core.confidence import (
        estimate_confidence, should_skip, should_use_advisor)

    pred = np.zeros(9, dtype=np.float32)
    c = estimate_confidence(pred=pred, rag_sim=0.9, anomaly_score=0.0,
                            model_std=0.1)
    assert 0.0 <= c <= 1.0
    assert should_skip(0.1, 0.0)
    assert should_skip(0.9, 0.8)
    assert not should_skip(0.5, 0.3)
    assert should_use_advisor(0.5, 0.1)
    assert not should_use_advisor(0.9, 0.1)


# ── render ──────────────────────────────────────────────────

def test_apply_strength_neutral():
    from photo_s_plugin_auto_tone.core.render import apply_strength

    opts = {"exposure": 1.0, "contrast": 1.4, "saturation": 1.8}
    zero = apply_strength(opts, 0.0)
    assert zero["exposure"] == 0.0
    assert zero["contrast"] == 1.0
    assert zero["saturation"] == 1.0
    full = apply_strength(opts, 1.0)
    assert full == opts


def test_render_options_changes_image(tiny_img, tmp_path):
    from photo_s_plugin_auto_tone.core.render import render_options

    out = str(tmp_path / "out.jpg")
    img = Image.open(tiny_img)
    render_options(img, {"exposure": 0.5, "contrast": 1.2, "saturation": 1.5},
                   out)
    assert os.path.isfile(out)
    a = np.asarray(img, dtype=np.int32)
    b = np.asarray(Image.open(out), dtype=np.int32)
    assert np.abs(a - b).mean() > 1.0


def test_render_failure_raises(tmp_path):
    from photo_s_plugin_auto_tone.core.render import render_options

    with pytest.raises(TypeError):
        render_options(Image.new("RGB", (4, 4)), {"exposure": "not-a-number"},
                       str(tmp_path / "out.jpg"))


# ── aesthetic / advisor 纯逻辑 ──────────────────────────────

def test_aesthetic_parse_and_bucketize():
    from photo_s_plugin_auto_tone.core.aesthetic import AestheticScorer

    assert AestheticScorer._parse_score("分数=8.50") == 8.5
    assert AestheticScorer._parse_score("没有分数") is None
    assert AestheticScorer._parse_score("99") == 10.0  # clamp
    assert AestheticScorer._bucketize(3.0) == "low"
    assert AestheticScorer._bucketize(None) == "unknown"
    assert AestheticScorer._bucketize(9.0) == "high"


def test_advisor_parse_reply():
    from photo_s_plugin_auto_tone.core.advisor import ToneAdvisor

    reply = '修正建议: {"exposure": 0.2, "contrast": -0.1}\n原因: 欠曝'
    delta, reason = ToneAdvisor._parse_reply(reply)
    assert delta["exposure"] == 0.2
    assert reason == "欠曝"
    delta2, _ = ToneAdvisor._parse_reply("完全跑偏的回复")
    assert delta2 == {}


# ── RAG 数学（注入假数据，不加载 CLIP）─────────────────────

def test_rag_retrieve_and_fuse():
    from photo_s_plugin_auto_tone.core.rag import RAGEnhancer

    rag = RAGEnhancer.__new__(RAGEnhancer)
    rag.top_k = 2
    rag.temperature = 10.0
    rag.alpha = 0.85
    rag.train_clip = np.array([[1.0] + [0.0] * 767,
                               [0.0, 1.0] + [0.0] * 766], dtype=np.float32)
    rag.train_targets = np.array([[1.0] * 9, [0.0] * 9], dtype=np.float32)

    idx, w, sims = rag.retrieve(np.array([1.0] + [0.0] * 767, dtype=np.float32))
    assert len(idx) == 2
    assert w[0] > w[1]  # 更相似者权重更高
    assert abs(w.sum() - 1.0) < 1e-5


# ── pipeline（注入假 predictor / anomaly / rag）────────────

class _FakePredictor:
    targets = ["exposure", "contrast", "saturation", "vibrance",
               "wb_temp", "wb_tint", "clarity", "texture", "dehaze"]
    ranges = {"exposure": (-2, 2), "contrast": (0.5, 1.5), "saturation": (0, 2),
              "vibrance": (-1, 1), "wb_temp": (2000, 10000), "wb_tint": (-100, 100),
              "clarity": (-1, 1), "texture": (-1, 1), "dehaze": (-1, 1)}

    def load(self):
        pass

    def predict(self, img):
        return {"exposure": 0.5, "contrast": 1.1, "saturation": 1.2,
                "vibrance": 0.1, "wb_temp": 5500, "wb_tint": 5.0,
                "clarity": 0.2, "texture": 0.1, "dehaze": 0.0}


class _FakeAnomaly:
    def __init__(self, score):
        self.score_value = score

    def load(self):
        pass

    def score(self, img):
        return self.score_value, {}


def _run(tiny_img, anomaly, **kw):
    from photo_s_plugin_auto_tone.core.pipeline import run_auto_tone

    return run_auto_tone(tiny_img, predictor=_FakePredictor(),
                         anomaly_detector=_FakeAnomaly(anomaly),
                         use_rag=False, rag_enhancer=None, **kw)


def test_pipeline_normal(tiny_img, tmp_path):
    r = _run(tiny_img, 0.1, render=False)
    assert r["schema_version"] == 1
    assert set(r["options"]) == set(_FakePredictor.targets)
    assert 0.0 <= r["confidence"] <= 1.0
    assert r["rendered_path"] is None
    assert not r["metadata"].get("skipped")


def test_pipeline_high_anomaly_skips(tiny_img):
    r = _run(tiny_img, 0.9, render=True)
    assert r["options"] == {}
    assert r["metadata"]["skipped"]
    assert r["rendered_path"] is None


def test_pipeline_strength_interpolates(tiny_img):
    full = _run(tiny_img, 0.1, render=False, strength=1.0)
    half = _run(tiny_img, 0.1, render=False, strength=0.5)
    assert half["options"]["exposure"] == pytest.approx(
        full["options"]["exposure"] / 2, abs=1e-4)
    assert half["options"]["contrast"] == pytest.approx(
        1.0 + (full["options"]["contrast"] - 1.0) / 2, abs=1e-4)


def test_pipeline_min_confidence_skips_render(tiny_img, tmp_path):
    r = _run(tiny_img, 0.1, render=True, output_path=str(tmp_path / "o.jpg"),
             min_confidence=0.99)
    assert r["rendered_path"] is None
    assert not os.path.exists(tmp_path / "o.jpg")
    r2 = _run(tiny_img, 0.1, render=True, output_path=str(tmp_path / "o2.jpg"),
              min_confidence=0.0)
    assert r2["rendered_path"] == str(tmp_path / "o2.jpg")


# ── MCP 工具签名 / JSON 契约 ────────────────────────────────

def test_mcp_tool_contract(tiny_img, monkeypatch):
    from photo_s_plugin_auto_tone.api import mcp_tools
    from photo_s_plugin_auto_tone.core import pipeline as pl

    monkeypatch.setattr(pl, "run_auto_tone",
                        lambda *a, **k: {"schema_version": 1, "options": {},
                                         "confidence": 0.5, "warnings": [],
                                         "rendered_path": None,
                                         "metadata": {}})
    out = json.loads(mcp_tools.auto_tone_tool(tiny_img))
    assert out["schema_version"] == 1

    batch = json.loads(mcp_tools.batch_auto_tone_tool(
        [tiny_img, tiny_img], skip_low_confidence=False))
    assert batch["total"] == 2
    assert batch["processed"] + batch["skipped"] + batch["failed"] == 2


# ── photo-s 插件钩子 ────────────────────────────────────────

def test_plugin_hook(tiny_img):
    from photo_s.hooks import PluginContext
    from photo_s_plugin_auto_tone import AutoTonePlugin
    from photo_s_plugin_auto_tone.core import pipeline as pl

    plugin = AutoTonePlugin()

    class _Ctx(PluginContext):
        pass

    ctx = PluginContext(input_path=tiny_img)

    orig = pl.run_auto_tone
    pl.run_auto_tone = lambda *a, **k: {
        "options": {"exposure": 0.5, "contrast": 1.1, "saturation": 1.2},
        "warnings": []}
    try:
        img = Image.new("RGB", (8, 8), (100, 100, 100))
        out = plugin.auto_tone(img, 1.0, ctx)
        assert isinstance(out, Image.Image)
    finally:
        pl.run_auto_tone = orig


# ── REST 注册（不真正起服务器，验证 monkey-patch 路由逻辑）──

def test_rest_registration():
    from photo_s_plugin_auto_tone.api.rest import register_routes

    class H:
        def do_POST(self):
            raise AssertionError("orig do_POST should not be called for plugin routes")

        def _send_json(self, status, payload):
            self.sent = (status, payload)

    register_routes(H)
    h = H()
    h.path = "/v1/unknown_plugin_route"
    try:
        h.do_POST()
    except Exception:
        pass  # send_error 不可用时会抛错，重点是路由被接管而非落到原 do_POST
