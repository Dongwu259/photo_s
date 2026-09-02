"""v2.5 语义搜索 — photo_s.search 核心 + CLI/MCP 接线。

核心用确定性 stub embed provider 验证（假插件 + plugin.clear_cache 注入，
不依赖 torch/塔）；内置 hist84 走真实直方图路径（以图搜图）。插件 SigLIP
embedder 的 torch 部分在无 torch 环境 skip（CI pytest jobs 无 torch）。
"""

import json
import os
import sys

import numpy as np
import pytest

from photo_s import plugin as plugin_mod
from photo_s.search import (HIST_NAME, INDEX_FILENAME, auto_tag,
                            build_index, find_similar, get_extractor,
                            load_index)

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))


def _img(path, color, size=(48, 48)):
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(str(path), quality=95)
    return str(path)


class _StubEmbed:
    """确定性 stub：8 维，前 4 维 = 色块 RGB+1，后 4 维文本哈希位。"""

    embed_name = "stub:test"
    embed_dim = 8

    def __init__(self):
        self.embedded_images = []

    def embed_images(self, paths):
        from PIL import Image
        self.embedded_images.extend(paths)
        rows = []
        for p in paths:
            with Image.open(p) as im:
                r, g, b = im.convert("RGB").getpixel((2, 2))
            rows.append([r / 255, g / 255, b / 255, 0.0, 0, 0, 0, 0])
        return np.asarray(rows, dtype=np.float32)

    def embed_texts(self, texts):
        # "red"/"blue" 直映到颜色位——确定性文本→图像匹配
        rows = []
        for t in texts:
            t = t.lower()
            row = [0, 0, 0, 0.0, 0, 0, 0, 0]
            if "red" in t:
                row[0] = 1.0
            if "blue" in t:
                row[2] = 1.0
            rows.append(row)
        return np.asarray(rows, dtype=np.float32)


@pytest.fixture()
def stub_provider(monkeypatch):
    """注入 stub embed provider（真实发现机制走一遍）。"""
    from photo_s.hooks import PhotoSPlugin

    class StubPlugin(PhotoSPlugin):
        name = "stub_embed"
        provides = ("embed",)
        embed_name = "stub:test"
        embed_dim = 8
        _embedder = _StubEmbed()

        def embed_images(self, paths, batch_size=8):
            return self._embedder.embed_images(paths)

        def embed_texts(self, texts):
            return self._embedder.embed_texts(texts)

    inst = StubPlugin()
    monkeypatch.setattr(plugin_mod, "discover_plugins", lambda: [inst])
    monkeypatch.setattr(plugin_mod, "find_provider",
                        lambda op: inst if op == "embed" else None)
    plugin_mod.clear_cache()
    yield inst
    plugin_mod.clear_cache()


class TestExtractor:
    def test_auto_prefers_provider(self, stub_provider):
        ext = get_extractor()
        assert ext.name == "stub:test"
        assert ext.dim == 8

    def test_fallback_hist_without_provider(self, monkeypatch):
        monkeypatch.setattr(plugin_mod, "find_provider", lambda op: None)
        plugin_mod.clear_cache()
        ext = get_extractor()
        assert ext.name == HIST_NAME
        assert ext.dim == 84
        assert ext.embed_texts(["x"]) is None

    def test_named_mismatch_refuses(self, stub_provider, monkeypatch):
        monkeypatch.setattr(plugin_mod, "find_provider",
                            lambda op: None)
        plugin_mod.clear_cache()
        with pytest.raises(RuntimeError, match="rebuild"):
            get_extractor("stub:test")


class TestBuildAndFind:
    def test_build_and_text_query(self, tmp_path, stub_provider):
        red = _img(tmp_path / "red.jpg", (220, 30, 30))
        blue = _img(tmp_path / "blue.jpg", (30, 30, 220))
        res = build_index([str(tmp_path)])
        assert res["total"] == 2 and res["indexed"] == 2
        assert res["extractor"] == "stub:test"
        out = find_similar(res["index"], text="a red sunset", k=2)
        assert out["hits"][0]["path"].endswith("red.jpg")
        assert out["hits"][0]["score"] > 0.9  # stub 色位余弦 ≈0.98
        assert out["hits"][1]["path"].endswith("blue.jpg")

    def test_image_query(self, tmp_path, stub_provider):
        red = _img(tmp_path / "red.jpg", (220, 30, 30))
        blue = _img(tmp_path / "blue.jpg", (30, 30, 220))
        q = _img(tmp_path / "sub" / "query.jpg", (200, 40, 40))
        res = build_index([red, blue])   # 显式文件清单——查询图不在索引内
        out = find_similar(res["index"], image=q, k=2)
        assert out["hits"][0]["path"].endswith("red.jpg")

    def test_incremental_and_vanish(self, tmp_path, stub_provider):
        a = _img(tmp_path / "a.jpg", (220, 30, 30))
        res1 = build_index([str(tmp_path)])
        stub_provider._embedder.embedded_images.clear()
        res2 = build_index([str(tmp_path)])
        assert res2["kept"] == 1 and res2["indexed"] == 0
        assert not stub_provider._embedder.embedded_images  # 未变不重算
        _img(tmp_path / "b.jpg", (30, 30, 220))
        os.remove(a)
        res3 = build_index([str(tmp_path)])
        assert res3["total"] == 1 and res3["removed"] == 1
        assert res3["indexed"] == 1

    def test_extractor_switch_demands_rebuild(self, tmp_path, stub_provider):
        _img(tmp_path / "a.jpg", (220, 30, 30))
        res = build_index([str(tmp_path)])
        # 换内置抽取器重建 → 再用 stub 名查询 → 报错（不混用空间）
        build_index([str(tmp_path)], rebuild=True,
                    index_path=res["index"], extractor_name=HIST_NAME)
        with pytest.raises(RuntimeError, match="image-only"):
            find_similar(res["index"], text="red")

    def test_index_file_layout(self, tmp_path, stub_provider):
        _img(tmp_path / "a.jpg", (10, 200, 10))
        res = build_index([str(tmp_path)])
        assert res["index"].endswith(INDEX_FILENAME)
        idx = load_index(res["index"])
        assert idx["extractor"] == "stub:test"
        assert idx["paths"] == ["a.jpg"]           # 相对根存储
        assert idx["feats"].shape == (1, 8)
        assert abs(np.linalg.norm(idx["feats"][0]) - 1.0) < 1e-5  # L2 归一

    def test_hist_builtin_real_path(self, tmp_path, monkeypatch):
        """无插件：真实 84 维直方图，以图搜图可用、文本报安装指引。"""
        monkeypatch.setattr(plugin_mod, "find_provider", lambda op: None)
        plugin_mod.clear_cache()
        _img(tmp_path / "dark.jpg", (20, 20, 20))
        _img(tmp_path / "bright.jpg", (230, 230, 230))
        q = _img(tmp_path / "sub" / "q.jpg", (25, 25, 25))  # 索引外参考图
        res = build_index([str(tmp_path)])
        assert res["extractor"] == HIST_NAME and res["dim"] == 84
        out = find_similar(res["index"], image=q, k=2)
        assert out["hits"][0]["path"].endswith("dark.jpg")
        with pytest.raises(RuntimeError, match="photo-s-plugin-auto-tone"):
            find_similar(res["index"], text="dark moody night")


class TestAutoTag:
    def test_threshold_and_exif(self, tmp_path, stub_provider):
        red = _img(tmp_path / "red.jpg", (220, 30, 30))
        _img(tmp_path / "gray.jpg", (128, 128, 128))
        res = build_index([str(tmp_path)])
        out = auto_tag(res["index"], ["red wall", "blue sky"],
                       min_score=0.7, max_tags=2)
        assert out["tagged"] == 1  # 纯红 0.98 过阈；灰 0.58 被拒
        assert out["assigned"][red] == ["red wall"]
        from photo_s.engine import read_exif_metadata
        # EXIF UserComment 按空白切分——多词标签下划线连接写入
        assert read_exif_metadata(red).get("keywords") == ["red_wall"]

    def test_write_xmp_subject(self, tmp_path, stub_provider):
        red = _img(tmp_path / "r.jpg", (220, 30, 30))
        res = build_index([str(tmp_path)])
        auto_tag(res["index"], ["red wall"], min_score=0.7, write_xmp=True)
        sidecar = tmp_path / "r.xmp"
        assert sidecar.exists()
        text = sidecar.read_text(encoding="utf-8")
        assert "red wall" in text and "dc:subject" in text

    def test_no_text_encoder_refuses(self, tmp_path, monkeypatch):
        monkeypatch.setattr(plugin_mod, "find_provider", lambda op: None)
        plugin_mod.clear_cache()
        _img(tmp_path / "a.jpg", (1, 2, 3))
        res = build_index([str(tmp_path)])
        with pytest.raises(RuntimeError, match="auto-tone"):
            auto_tag(res["index"], ["x"])


class TestCli:
    def test_index_and_find(self, tmp_path, capsys, monkeypatch):
        from photo_s.cli import run_cli
        monkeypatch.setattr(plugin_mod, "find_provider", lambda op: None)
        plugin_mod.clear_cache()
        _img(tmp_path / "dark.jpg", (20, 20, 20))
        _img(tmp_path / "bright.jpg", (235, 235, 235))
        rc = run_cli(["index", str(tmp_path), "--json"])
        out = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert out["extractor"] in (HIST_NAME, "stub:test")
        rc = run_cli(["find", "--image", str(tmp_path / "dark.jpg"),
                      "--index", out["index"], "--json"])
        res = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert res["hits"][0]["path"].endswith("dark.jpg")

    def test_find_no_query_errors(self, tmp_path, capsys):
        from photo_s.cli import run_cli
        rc = run_cli(["find"])
        assert rc == 2


class TestMcpTools:
    def test_index_find_roundtrip(self, tmp_path, stub_provider):
        from photo_s.mcp_server import find_tool, index_tool
        _img(tmp_path / "red.jpg", (220, 30, 30))
        built = index_tool(paths=[str(tmp_path)])
        assert built["ok"] is True
        found = find_tool(query="red thing", index=built["index"], k=5)
        assert found["ok"] is True
        assert found["hits"][0]["path"].endswith("red.jpg")

    def test_index_with_tags(self, tmp_path, stub_provider):
        from photo_s.mcp_server import index_tool
        _img(tmp_path / "red.jpg", (220, 30, 30))
        res = index_tool(paths=[str(tmp_path)], tags=["red wall", "sky"],
                         min_score=0.7)
        assert res["ok"] is True
        assert res["tags"]["tagged"] == 1

    def test_find_missing_index(self, tmp_path):
        from photo_s.mcp_server import find_tool
        res = find_tool(query="x", index=str(tmp_path / "nope.npz"))
        assert res["ok"] is False
        assert "index not found" in res["error"]


class TestRestRoutes:
    def test_index_and_find(self, tmp_path, stub_provider):
        import threading
        import urllib.request
        from photo_s.engine import ProcessOptions
        from photo_s.server import create_server
        _img(tmp_path / "red.jpg", (220, 30, 30))
        httpd = create_server("127.0.0.1", 0, ProcessOptions())
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            def post(path, obj):
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}{path}",
                    data=json.dumps(obj).encode(),
                    headers={"Content-Type": "application/json",
                             "Host": "127.0.0.1"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    return json.loads(r.read())

            built = post("/v1/index", {"paths": [str(tmp_path)]})
            assert built["ok"] is True
            found = post("/v1/find", {"query": "red thing",
                                      "index": built["index"]})
            assert found["ok"] is True
            assert found["hits"][0]["path"].endswith("red.jpg")
        finally:
            httpd.shutdown()


class TestPluginEmbedder:
    """SigLIP embedder：有 torch 才跑（合成小塔不打真权重）。"""

    def test_shapes_and_normalization(self, tmp_path, monkeypatch):
        pytest.importorskip("torch")
        sys.path.append(os.path.join(os.path.dirname(__file__),
                                     "..", "plugins", "auto-tone"))
        try:
            from photo_s_plugin_auto_tone.core.embed import SigLIPEmbedder
        except ImportError:
            pytest.skip("plugin package not importable")

        import torch
        from PIL import Image

        class FakeTok:
            def __call__(self, texts, **kw):
                n = len(texts)
                class B:
                    input_ids = torch.zeros(n, 8, dtype=torch.long)
                return B()

        class FakeModel(torch.nn.Module):
            def encode_image(self, x):
                return torch.ones(x.shape[0], 8)

            def encode_text(self, ids):
                return torch.ones(ids.shape[0], 8)

        def fake_preprocess(img):
            return torch.zeros(3, 8, 8)

        SigLIPEmbedder._instance = None
        emb = SigLIPEmbedder()
        emb._loaded = True
        emb.device = "cpu"
        emb.model = FakeModel()
        emb.preprocess = fake_preprocess
        emb.tokenizer = FakeTok()

        p = _img(tmp_path / "x.jpg", (90, 90, 90))
        feats = emb.embed_images([p])
        assert feats.shape == (1, 8)
        assert abs(float(np.linalg.norm(feats[0])) - 1.0) < 1e-5
        t = emb.embed_texts(["hello"])
        assert t.shape == (1, 8)
        assert abs(float(np.linalg.norm(t[0])) - 1.0) < 1e-5

    def test_no_torch_clear_error(self, monkeypatch):
        import builtins
        real_import = builtins.__import__

        def no_torch(name, *a, **k):
            if name == "torch":
                raise ImportError("torch disabled")
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", no_torch)
        sys.path.append(os.path.join(os.path.dirname(__file__),
                                     "..", "plugins", "auto-tone"))
        try:
            from photo_s_plugin_auto_tone.core.embed import SigLIPEmbedder
        except ImportError:
            pytest.skip("plugin package not importable")
        SigLIPEmbedder._instance = None
        emb = SigLIPEmbedder()
        with pytest.raises(RuntimeError, match="torch"):
            emb.embed_images(["whatever.jpg"])
