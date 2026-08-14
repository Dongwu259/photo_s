"""End-to-end tests for the SCUNet reference plugin (plugins/scunet).

The real SCUNet ONNX model (~10-40MB) is not hostable in this repo, so the
tests synthesize a tiny identity Conv model (~200 bytes) with onnx, point the
plugin at it via PHOTOS_SCUNET_MODEL_* env vars, and prove the full chain:
weight download/verify/cache → onnxruntime inference → engine denoise slot.

Skipped cleanly when onnx / onnxruntime are absent.
"""

import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# make the plugin package importable (it lives in plugins/scunet/)
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "plugins", "scunet"))

import pytest

onnx = pytest.importorskip("onnx")
pytest.importorskip("onnxruntime")

from PIL import Image

from photo_s.cli import run_cli
from photo_s import plugin as plugin_mod
from photo_s_plugin_scunet import ScunetPlugin


def _make_tiny_onnx(path, scale=1.0):
    """Build a tiny scale*identity 1x1-Conv ONNX model (~200 bytes).

    ``scale=1`` is the identity (output == input); ``scale=2`` doubles every
    pixel so strength-blend tests can assert exact mix ratios.
    """
    import numpy as np
    from onnx import helper, numpy_helper, TensorProto

    X = helper.make_tensor_value_info("X", TensorProto.FLOAT, [1, 3, 64, 64])
    Y = helper.make_tensor_value_info("Y", TensorProto.FLOAT, [1, 3, 64, 64])
    W = numpy_helper.from_array(
        np.eye(3, dtype=np.float32).reshape(3, 3, 1, 1) * scale, name="W")
    node = helper.make_node("Conv", ["X", "W"], ["Y"],
                            kernel_shape=[1, 1], pads=[0, 0, 0, 0])
    graph = helper.make_graph([node], "tiny", [X], [Y], initializer=[W])
    model = helper.make_model(
        graph, opset_imports=[helper.make_opsetid("", 11)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    onnx.save(model, str(path))
    return path


def _setup_env(tmp_path, monkeypatch, scale=1.0):
    """Point the plugin at local synthetic weights in an isolated cache.

    The plugin fetches TWO specs (graph + external-data companion); the tiny
    model is self-contained, so the .data companion is a dummy file with a
    matching sha256 (onnxruntime never reads it for a self-contained graph).
    """
    model_path = _make_tiny_onnx(tmp_path / "scunet.onnx", scale=scale)
    data_path = tmp_path / "scunet.onnx.data"
    data_path.write_bytes(b"dummy-external-data")
    model_data = model_path.read_bytes()
    dummy_data = data_path.read_bytes()
    monkeypatch.setenv("PHOTOS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("PHOTOS_SCUNET_MODEL_URL", model_path.as_uri())
    monkeypatch.setenv("PHOTOS_SCUNET_MODEL_SHA256",
                       hashlib.sha256(model_data).hexdigest())
    monkeypatch.setenv("PHOTOS_SCUNET_MODEL_SIZE", str(len(model_data)))
    monkeypatch.setenv("PHOTOS_SCUNET_MODEL_DATA_URL", data_path.as_uri())
    monkeypatch.setenv("PHOTOS_SCUNET_MODEL_DATA_SHA256",
                       hashlib.sha256(dummy_data).hexdigest())
    monkeypatch.setenv("PHOTOS_SCUNET_MODEL_DATA_SIZE", str(len(dummy_data)))
    return model_path


class TestScunetDenoise:
    def test_denoise_end_to_end(self, tmp_path, monkeypatch):
        _setup_env(tmp_path, monkeypatch)
        plugin = ScunetPlugin()
        img = Image.new("RGB", (64, 64), (120, 100, 80))
        ctx = type("Ctx", (), {})()
        out = plugin.denoise(img, 10.0, ctx)
        assert out.size == (64, 64)
        assert out.mode == "RGB"
        # identity conv → output ≈ input
        assert abs(out.getpixel((30, 30))[0] - 120) <= 3

    def test_alpha_preserved(self, tmp_path, monkeypatch):
        _setup_env(tmp_path, monkeypatch)
        plugin = ScunetPlugin()
        img = Image.new("RGBA", (64, 64), (120, 100, 80, 200))
        out = plugin.denoise(img, 10.0, type("C", (), {})())
        assert out.mode == "RGBA"
        assert out.getpixel((30, 30))[3] == 200

    def test_weight_cached_after_denoise(self, tmp_path, monkeypatch):
        model_path = _setup_env(tmp_path, monkeypatch)
        plugin = ScunetPlugin()
        plugin.denoise(Image.new("RGB", (64, 64), (50, 50, 50)), 10.0,
                       type("C", (), {})())
        models_dir = os.path.join(os.environ["PHOTOS_CACHE_DIR"], "models")
        # both graph + companion cached under their canonical names
        cached = os.path.join(models_dir, "scunet_color_25.onnx")
        assert os.path.isfile(cached)
        assert open(cached, "rb").read() == model_path.read_bytes()
        assert os.path.isfile(
            os.path.join(models_dir, "scunet_color_25.onnx.data"))

    def test_strength_zero_returns_original(self, tmp_path, monkeypatch):
        """t(0)=0: the blend must return the untouched input."""
        _setup_env(tmp_path, monkeypatch, scale=2.0)
        plugin = ScunetPlugin()
        img = Image.new("RGB", (64, 64), (120, 100, 80))
        out = plugin.denoise(img, 0.0, type("C", (), {})())
        px = out.getpixel((30, 30))
        assert abs(px[0] - 120) <= 3 and abs(px[1] - 100) <= 3 \
            and abs(px[2] - 80) <= 3

    def test_strength_full_returns_model_output(self, tmp_path, monkeypatch):
        """t(15)=1: the full 2x model output must come through."""
        _setup_env(tmp_path, monkeypatch, scale=2.0)
        plugin = ScunetPlugin()
        img = Image.new("RGB", (64, 64), (120, 100, 80))
        out = plugin.denoise(img, 15.0, type("C", (), {})())
        px = out.getpixel((30, 30))
        assert abs(px[0] - 240) <= 3 and abs(px[1] - 200) <= 3 \
            and abs(px[2] - 160) <= 3

    def test_strength_half_blends_50_50(self, tmp_path, monkeypatch):
        """t(7.5)=0.5: output must sit exactly between input and model."""
        _setup_env(tmp_path, monkeypatch, scale=2.0)
        plugin = ScunetPlugin()
        img = Image.new("RGB", (64, 64), (120, 100, 80))
        out = plugin.denoise(img, 7.5, type("C", (), {})())
        px = out.getpixel((30, 30))
        assert abs(px[0] - 180) <= 3 and abs(px[1] - 150) <= 3 \
            and abs(px[2] - 120) <= 3

    def test_strength_out_of_range_clamped(self, tmp_path, monkeypatch):
        """t clamps: strength 99 == 15 (full), -3 == 0 (original)."""
        _setup_env(tmp_path, monkeypatch, scale=2.0)
        plugin = ScunetPlugin()
        img = Image.new("RGB", (64, 64), (120, 100, 80))
        full = plugin.denoise(img, 99.0, type("C", (), {})()).getpixel((30, 30))
        orig = plugin.denoise(img, -3.0, type("C", (), {})()).getpixel((30, 30))
        assert abs(full[0] - 240) <= 3
        assert abs(orig[0] - 120) <= 3

    def test_img_info_preserved(self, tmp_path, monkeypatch):
        """EXIF/ICC in img.info must survive the blend (contract parity)."""
        _setup_env(tmp_path, monkeypatch)
        plugin = ScunetPlugin()
        img = Image.new("RGB", (64, 64), (120, 100, 80))
        img.info["icc_profile"] = b"fake-icc"
        out = plugin.denoise(img, 10.0, type("C", (), {})())
        assert out.info.get("icc_profile") == b"fake-icc"

    def test_non_multiple_of_8_dims_padded(self, tmp_path, monkeypatch):
        """SCUNet needs H,W divisible by 8: odd dims must be padded to the
        model and cropped back, so output size always equals input size."""
        _setup_env(tmp_path, monkeypatch)
        plugin = ScunetPlugin()
        # 61x59 pads to 64x64 — exactly the tiny test model's input shape
        img = Image.new("RGB", (61, 59), (120, 100, 80))
        out = plugin.denoise(img, 10.0, type("C", (), {})())
        assert out.size == (61, 59)
        assert out.mode == "RGB"
        # identity conv → interior pixels ≈ input
        assert abs(out.getpixel((30, 30))[0] - 120) <= 3


class TestBlend:
    """Pure math of the strength→t mapping (no model, no runtime)."""

    def test_blend_mapping(self):
        import numpy as np
        import photo_s_plugin_scunet.onnx as onnx_mod
        orig = np.full((2, 2, 3), 0.4, dtype=np.float32)
        den = np.full((2, 2, 3), 0.8, dtype=np.float32)
        assert np.allclose(onnx_mod._blend(orig, den, 0.0), 0.4)
        assert np.allclose(onnx_mod._blend(orig, den, 7.5), 0.6)
        assert np.allclose(onnx_mod._blend(orig, den, 15.0), 0.8)
        assert np.allclose(onnx_mod._blend(orig, den, 99.0), 0.8)   # clamp up
        assert np.allclose(onnx_mod._blend(orig, den, -3.0), 0.4)   # clamp down


class TestScunetInEngine:
    def test_batch_uses_provider(self, tmp_path, monkeypatch, capsys):
        _setup_env(tmp_path, monkeypatch)
        src = tmp_path / "a.jpg"
        Image.new("RGB", (64, 64), (120, 100, 80)).save(str(src), quality=95)
        out = tmp_path / "out"
        plugin = ScunetPlugin()
        monkeypatch.setattr(plugin_mod, "discover_plugins", lambda: [plugin])
        rc = run_cli(["batch", str(src), "-o", str(out), "--denoise", "10",
                      "--json"])
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["results"][0]["status"] == "ok"

    def test_missing_onnxruntime_hint(self, tmp_path, monkeypatch):
        _setup_env(tmp_path, monkeypatch)
        import photo_s_plugin_scunet.onnx as onnx_mod

        class _NoOrt:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        monkeypatch.setattr(onnx_mod, "_ort", _raise_no_ort)
        plugin = ScunetPlugin()
        with pytest.raises(RuntimeError, match="onnxruntime"):
            plugin.denoise(Image.new("RGB", (64, 64), (50, 50, 50)), 10.0,
                           type("C", (), {})())


def _raise_no_ort():
    raise RuntimeError("scunet plugin requires the optional dependency: "
                       "pip install onnxruntime")


class TestTiledInference:
    """Tiled inference: ramp weights, fake-sess reconstruction, validation."""

    def test_tile_starts_flush_with_edge(self):
        """Stride tile-overlap; the last tile must align to the far edge."""
        import photo_s_plugin_scunet.onnx as onnx_mod
        # 128 with tile 64 / overlap 16: stride 48 → 0, 48, then flush 64
        assert onnx_mod._tile_starts(128, 64, 16) == [0, 48, 64]
        assert onnx_mod._tile_starts(64, 32, 8) == [0, 24, 32]
        assert onnx_mod._tile_starts(64, 64, 16) == [0]   # single tile
        assert onnx_mod._tile_starts(32, 64, 16) == [0]   # smaller than tile

    def test_ramp_weights_sum_to_one(self):
        """At every pixel the per-tile weights must sum to exactly 1."""
        import numpy as np
        import photo_s_plugin_scunet.onnx as onnx_mod
        cases = [
            (64, 64, 32, 8),      # 3x3 tiles, flush-aligned last tile
            (128, 128, 64, 16),   # the end-to-end config below
            (192, 96, 64, 16),    # rectangular, uneven overlaps
            (64, 64, 64, 16),     # single tile → flat weights
        ]
        for h, w, tile, overlap in cases:
            positions, weights = onnx_mod._ramp_weights(h, w, tile, overlap)
            acc = np.zeros((h, w), dtype=np.float64)
            for (y, x), wt in zip(positions, weights):
                assert wt.shape == (tile, tile)
                acc[y:y + tile, x:x + tile] += wt
            assert np.allclose(acc, 1.0), (h, w, tile, overlap)

    def test_tiled_identity_reconstructs(self):
        """Fake sess returning its input: weighted blend must reproduce the
        input exactly (64x64 tensor, tile 32 / overlap 8 → 9 tiles)."""
        import numpy as np
        import photo_s_plugin_scunet.onnx as onnx_mod

        class _FakeSess:
            def run(self, _outputs, feed):
                return [feed["X"]]

        rng = np.random.default_rng(0)
        tensor = rng.random((1, 3, 64, 64), dtype=np.float32)
        out = onnx_mod._tiled_inference(_FakeSess(), "X", tensor,
                                        tile=32, overlap=8)
        assert out.shape == tensor.shape
        assert np.allclose(out, tensor, atol=1e-5)

    def test_invalid_overlap_rejected(self):
        """overlap must satisfy 0 <= overlap < tile."""
        import photo_s_plugin_scunet.onnx as onnx_mod
        img = Image.new("RGB", (64, 64))
        with pytest.raises(ValueError):
            onnx_mod.run_scunet(img, 10.0, "x.onnx", tile=64, overlap=64)
        with pytest.raises(ValueError):
            onnx_mod.run_scunet(img, 10.0, "x.onnx", tile=32, overlap=64)
        with pytest.raises(ValueError):
            onnx_mod.run_scunet(img, 10.0, "x.onnx", tile=64, overlap=-1)


class TestTiledEndToEnd:
    def test_tiled_run_matches_identity(self, tmp_path, monkeypatch):
        """128x128 image through the fixed 64x64 tiny model, forced tiled:
        tile=64 → 3x3 = 9 tiles (starts 0/48/64), identity conv ⇒ output
        size and pixels ≈ input."""
        model_path = _setup_env(tmp_path, monkeypatch)
        import photo_s_plugin_scunet.onnx as onnx_mod
        img = Image.new("RGB", (128, 128), (120, 100, 80))
        out = onnx_mod.run_scunet(img, 15.0, str(model_path),
                                  tile=64, overlap=16)
        assert out.size == (128, 128)
        assert out.mode == "RGB"
        # (50, 50) sits in the 4-tile overlap corner (starts 0/48/64);
        # (100, 100) is covered by the single flush-aligned tile only
        for xy in [(50, 50), (100, 100), (0, 0), (127, 127)]:
            px = out.getpixel(xy)
            assert abs(px[0] - 120) <= 3 and abs(px[1] - 100) <= 3 \
                and abs(px[2] - 80) <= 3, (xy, px)
