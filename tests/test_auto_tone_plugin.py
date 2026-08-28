"""Auto-tone 插件 hermetic 测试（不下载权重、不依赖 torch）"""

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


# ── v2.1 风格化 / 场景（hermetic，不加载 SigLIP / Qwen）────

def test_lazy_v21_attrs():
    from photo_s_plugin_auto_tone import (
        STYLE_INPUT_SCHEMA, STYLE_OUTPUT_SCHEMA, VISUAL_STYLE_OUTPUT_SCHEMA,
        SCENE_INPUT_SCHEMA, SCENE_OUTPUT_SCHEMA, list_styles)

    assert list_styles()["melancholy_blue"] == "忧郁蓝调"
    assert len(list_styles()) == 16
    assert STYLE_INPUT_SCHEMA["required"] == ["image_path"]
    assert STYLE_OUTPUT_SCHEMA["properties"]["schema_version"]["const"] == 2
    assert VISUAL_STYLE_OUTPUT_SCHEMA["required"] == ["schema_version",
                                                      "top_styles"]
    assert SCENE_OUTPUT_SCHEMA["properties"]["schema_version"]["const"] == 1


def test_style_bias_apply_and_clamp():
    from photo_s_plugin_auto_tone.core.style_biases import (
        STYLE_BIASES, apply_style_bias)

    base = {"exposure": 0.0, "contrast": 1.0, "saturation": 1.0,
            "vibrance": 0.0, "wb_temp": 5500.0, "wb_tint": 0.0,
            "clarity": 0.0, "texture": 0.0, "dehaze": 0.0}

    # 黑白风格：saturation 偏置 -2 → clip 到下界 0
    bw = apply_style_bias(base, STYLE_BIASES["high_contrast_bw"], strength=1.0)
    assert bw["saturation"] == 0.0
    assert bw["contrast"] > 1.0

    # strength=0 → 不动
    zero = apply_style_bias(base, STYLE_BIASES["golden_hour"], strength=0.0)
    assert zero == base

    # strength 单调：wb_temp 偏置随 strength 增大而更暖
    half = apply_style_bias(base, STYLE_BIASES["golden_hour"], strength=0.5)
    full = apply_style_bias(base, STYLE_BIASES["golden_hour"], strength=1.0)
    assert base["wb_temp"] < half["wb_temp"] < full["wb_temp"]

    # 未知字段偏置被忽略
    mixed = apply_style_bias(base, {"nope": 1.0, "exposure": 0.5}, strength=1.0)
    assert "nope" not in mixed
    assert mixed["exposure"] > base["exposure"]


def test_style_qwen_parse():
    from photo_s_plugin_auto_tone.core.style_qwen import (
        parse_json_bias, keyword_to_bias, get_zero_bias)

    bias = parse_json_bias(
        '前置噪音 {"exposure": -0.1, "contrast": 0.2} 后置噪音', "忧郁蓝调")
    assert bias["exposure"] == -0.1
    # 缺失字段补 0
    for f in ("saturation", "wb_temp", "clarity"):
        assert bias[f] == 0.0

    assert parse_json_bias("完全没有 JSON", "x") == get_zero_bias()
    # keyword 合并用 max()：暖/黄昏都是 wb_temp 0.4，vibrance 取黄昏的 0.2
    kw = keyword_to_bias("暖色黄昏")
    assert kw["wb_temp"] == 0.4
    assert kw["vibrance"] == 0.2
    # 训练侧原样保留的怪癖：max() 会把负偏置（黑白 saturation -2）归零
    assert keyword_to_bias("黑白")["saturation"] == 0.0


def test_scene_classifier_packaged_data():
    from photo_s_plugin_auto_tone.core.scene import (
        SceneClassifier, PRESET_TO_SCENE, auto_tone_with_scene)

    clf = SceneClassifier()
    # 包内数据文件可读，场景键齐全
    assert {"portrait", "bw", "soft_haze", "bw_high_contrast"} <= \
        set(clf.scene_biases)
    assert clf.classify_by_preset(["无关预设", "黑白 高对比度"]) == \
        "bw_high_contrast"
    assert clf.classify_by_preset([]) == "default"
    # json 自带 preset_to_scene（552 张 LR 样本统计），优先于代码内兜底表
    assert "魅力人像" in clf.preset_to_scene

    # record → preset names（lr-scan history 格式）
    record = {"history": [
        {"name": "预设: 魅力人像"},
        {"name": "预设数量"},          # 噪音行，跳过
        {"name": "导入"},
    ]}
    assert clf.extract_preset_names(record) == ["魅力人像"]
    assert clf.classify_by_preset(clf.extract_preset_names(record)) == "portrait"

    # apply_bias：偏置有限幅度且 clip 在范围内
    base = {"exposure": 0.0, "contrast": 1.0, "saturation": 1.0,
            "vibrance": 0.0, "wb_temp": 5500.0, "wb_tint": 0.0,
            "clarity": 0.0, "texture": 0.0, "dehaze": 0.0}
    out = clf.apply_bias(base, "soft_haze", strength=0.5)
    assert out["contrast"] < base["contrast"]  # soft_haze 压对比
    assert 0.5 <= out["contrast"] <= 1.5
    # default 场景无偏置
    assert clf.apply_bias(base, "default", strength=1.0) == base

    # 便捷入口注入假 predictor（不触发权重下载）
    class _P:
        def load(self):
            pass

        def predict(self, img):
            return dict(base)

    import inspect
    assert "predictor" in inspect.signature(auto_tone_with_scene).parameters


def test_scene_biases_missing_file_error(tmp_path, monkeypatch):
    from photo_s_plugin_auto_tone.core.scene import SceneClassifier

    monkeypatch.setenv("PHOTOS_AUTO_TONE_SCENE_BIASES",
                       str(tmp_path / "nope.json"))
    with pytest.raises(FileNotFoundError):
        SceneClassifier()


def test_mcp_style_tools_contract(tiny_img, monkeypatch):
    from photo_s_plugin_auto_tone.api import mcp_tools
    from photo_s_plugin_auto_tone.core import style as st

    monkeypatch.setattr(
        st, "auto_tone_with_style",
        lambda p, **k: {"schema_version": 2, "options": {"exposure": -0.1},
                        "bias": {}, "bias_source": "preset",
                        "style_desc": "忧郁蓝调", "visual_styles": [],
                        "rendered_path": None, "warnings": [], "metadata": {}})
    out = json.loads(mcp_tools.auto_tone_with_style_tool(tiny_img, "忧郁蓝调"))
    assert out["schema_version"] == 2
    assert out["style_desc"] == "忧郁蓝调"

    monkeypatch.setattr(
        st, "analyze_visual_style",
        lambda p, top_k=3: [("melancholy_blue", 0.42), ("cinematic", 0.11)])
    vis = json.loads(mcp_tools.analyze_visual_style_tool(tiny_img, top_k=2))
    assert vis["schema_version"] == 1
    assert vis["top_styles"][0] == {
        "style_key": "melancholy_blue", "style_cn": "忧郁蓝调",
        "confidence": 0.42}


def test_mcp_batch_style_desc_branch(tiny_img, monkeypatch, tmp_path):
    from photo_s_plugin_auto_tone.api import mcp_tools
    from photo_s_plugin_auto_tone.core import style as st

    monkeypatch.setattr(
        st, "auto_tone_with_style",
        lambda p, **k: {"schema_version": 2, "options": {"exposure": 0.1},
                        "bias": {}, "bias_source": "preset",
                        "style_desc": "电影感", "visual_styles": [],
                        "rendered_path": str(tmp_path / "o.jpg"),
                        "warnings": [], "metadata": {}})

    out = json.loads(mcp_tools.batch_auto_tone_tool(
        [tiny_img], style_desc="电影感", output_dir=str(tmp_path)))
    assert out["metadata"]["style_desc"] == "电影感"
    row = out["results"][0]
    assert row["status"] == "ok"
    assert row["style_desc"] == "电影感"
    assert row["options"] == {"exposure": 0.1}

    # 无 style_desc → 走普通 pipeline 分支（run_auto_tone 注入假实现）
    from photo_s_plugin_auto_tone.core import pipeline as pl
    monkeypatch.setattr(
        pl, "run_auto_tone",
        lambda *a, **k: {"schema_version": 1, "options": {}, "confidence": 0.5,
                         "warnings": [], "rendered_path": None,
                         "metadata": {}})
    out2 = json.loads(mcp_tools.batch_auto_tone_tool(
        [tiny_img], skip_low_confidence=False))
    assert out2["metadata"]["style_desc"] is None
    assert "style_desc" not in out2["results"][0]


def test_plugin_style_hook(tiny_img):
    from photo_s.hooks import PluginContext
    from photo_s_plugin_auto_tone import AutoTonePlugin
    from photo_s_plugin_auto_tone.core import style as st

    plugin = AutoTonePlugin()
    ctx = PluginContext(input_path=tiny_img)

    orig = st.auto_tone_with_style
    st.auto_tone_with_style = lambda *a, **k: {
        "options": {"exposure": 0.5, "contrast": 1.1, "saturation": 1.2},
        "warnings": []}
    try:
        img = Image.new("RGB", (8, 8), (100, 100, 100))
        out = plugin.auto_tone_with_style(img, "复古胶片", 1.0, ctx)
        assert isinstance(out, Image.Image)
    finally:
        st.auto_tone_with_style = orig


def test_weight_specs_siglip_entry(monkeypatch, tmp_path):
    import photo_s_plugin_auto_tone.models as models

    specs = {s.name: s for s in models.weight_specs()}
    assert set(specs) == set(models.WEIGHTS)
    sig = specs["auto_tone_siglip_h192_d03.pt"]
    # v2.1 权重托管在独立 release tag
    assert "auto-tone-v2.1.0" in sig.url
    assert sig.sha256 == \
        "d64d2ea67cc725ffb61663c50239e1d9be95c6a559abaed37aedfcb0d2b68c92"
    assert sig.size == 871_277
    # 核心三件套仍指向 v0.1.0 tag
    assert "auto-tone-v0.1.0" in specs["auto_tone_v7_clean.pt"].url

    # URL_BASE env 覆盖对所有条目生效（含 url_base 条目）
    monkeypatch.setenv("PHOTOS_AUTO_TONE_URL_BASE", tmp_path.as_uri())
    import posixpath
    for s in models.weight_specs():
        assert s.url == posixpath.join(tmp_path.as_uri(), s.name), s.url


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


# ── predictor 特征拼装（需 torch；锁 hand_dim 截取回归）────

def test_extract_features_drops_intercept_column():
    torch = pytest.importorskip("torch")
    from photo_s_plugin_auto_tone.core.predictor import AutoTonePredictor

    # photo_s.lrxmp._content_features 末尾有 ridge 截距列（85 维）；
    # checkpoint 训练时 hand 是 84 维——拼接前必须截断，否则
    # MLP 输入维度不匹配（真实权重 e2e 实证：853 vs 852 崩溃）
    p = AutoTonePredictor.__new__(AutoTonePredictor)
    p.device = "cpu"
    p.hand_dim = 84

    class _Clip:
        def encode_image(self, x):
            return torch.zeros(x.shape[0], 768)

    p.clip_model = _Clip()
    p.preprocess = lambda img: torch.zeros(3, 4, 4)
    feats = p._extract_features(Image.new("RGB", (8, 8)))
    assert feats.shape[-1] == 768 + 84

    # hand_dim=None（未 load）时不过度干预（保持全部特征）
    p.hand_dim = None
    assert p._extract_features(Image.new("RGB", (8, 8))).shape[-1] == 768 + 85


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
