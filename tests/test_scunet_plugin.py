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


def _make_tiny_onnx(path):
    """Build a tiny identity 1x1-Conv ONNX model (~200 bytes)."""
    import numpy as np
    from onnx import helper, numpy_helper, TensorProto

    X = helper.make_tensor_value_info("X", TensorProto.FLOAT, [1, 3, 64, 64])
    Y = helper.make_tensor_value_info("Y", TensorProto.FLOAT, [1, 3, 64, 64])
    W = numpy_helper.from_array(
        np.eye(3, dtype=np.float32).reshape(3, 3, 1, 1), name="W")
    node = helper.make_node("Conv", ["X", "W"], ["Y"],
                            kernel_shape=[1, 1], pads=[0, 0, 0, 0])
    graph = helper.make_graph([node], "tiny", [X], [Y], initializer=[W])
    model = helper.make_model(
        graph, opset_imports=[helper.make_opsetid("", 11)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    onnx.save(model, str(path))
    return path


def _setup_env(tmp_path, monkeypatch):
    """Point the plugin at local synthetic weights in an isolated cache.

    The plugin fetches TWO specs (graph + external-data companion); the tiny
    model is self-contained, so the .data companion is a dummy file with a
    matching sha256 (onnxruntime never reads it for a self-contained graph).
    """
    model_path = _make_tiny_onnx(tmp_path / "scunet.onnx")
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
