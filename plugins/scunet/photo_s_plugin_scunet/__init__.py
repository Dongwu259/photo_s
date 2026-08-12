"""
PhotoS official SCUNet strong-denoise plugin.

Registers a ``denoise`` slot provider. When installed, ``photo-s --denoise N``
prefers this plugin over the core OpenCV NLM fallback.

The ONNX model weight is NOT shipped in the wheel. It is downloaded on first
use from a canonical URL into the model cache with sha256 verification — see
``photo_s.modelstore``.

Weights: SCUNet color noise-25 checkpoint, re-exported to ONNX from the
official cszn/SCUNet PyTorch weights (MIT license retained). Hosted on
HuggingFace ``Heliosoph/scunet-onnx``. External-data format → TWO files
(``.onnx`` graph + ``.onnx.data`` weights) are fetched; the sibling name is
baked into the graph so both must keep their canonical names in the cache.

Maintainer note: the default below points at a community HF mirror. If you
prefer first-party hosting, re-host the two files on your own GitHub Release
and update the DEFAULT_* constants (or keep the PHOTOS_SCUNET_MODEL_* env
overrides, which tests use).
"""

import os

from photo_s.hooks import PhotoSPlugin
from photo_s.modelstore import WeightSpec, ensure

# ── Canonical weight files (external-data format, both required) ───────────
HF_BASE = "https://huggingface.co/Heliosoph/scunet-onnx/resolve/main/"
DEFAULT_MODEL_URL = HF_BASE + "scunet_color_25.onnx"
DEFAULT_MODEL_SHA256 = "76170f1fcb84d3b3d38c4e7133a658bbbb70504e3dc5e4e4d1f7b0c395c093be"
DEFAULT_MODEL_SIZE = 3795638
DEFAULT_DATA_URL = HF_BASE + "scunet_color_25.onnx.data"
DEFAULT_DATA_SHA256 = "f46aa0f533e5bb8b2485a6531a205e270f4a7be2447880a12d97f5f00b1e70c9"
DEFAULT_DATA_SIZE = 73138176


class ScunetPlugin(PhotoSPlugin):
    """SCUNet strong-denoise provider for the engine's denoise slot."""

    provides = ("denoise",)

    def weight_specs(self):
        # canonical names MUST match the external-data locations baked into
        # the graph, so onnxruntime resolves the sibling .data correctly
        return [
            WeightSpec(
                name="scunet_color_25.onnx",
                url=os.environ.get("PHOTOS_SCUNET_MODEL_URL",
                                   DEFAULT_MODEL_URL),
                sha256=os.environ.get("PHOTOS_SCUNET_MODEL_SHA256",
                                      DEFAULT_MODEL_SHA256),
                size=int(os.environ.get("PHOTOS_SCUNET_MODEL_SIZE",
                                        DEFAULT_MODEL_SIZE) or 0),
            ),
            WeightSpec(
                name="scunet_color_25.onnx.data",
                url=os.environ.get("PHOTOS_SCUNET_MODEL_DATA_URL",
                                   DEFAULT_DATA_URL),
                sha256=os.environ.get("PHOTOS_SCUNET_MODEL_DATA_SHA256",
                                      DEFAULT_DATA_SHA256),
                size=int(os.environ.get("PHOTOS_SCUNET_MODEL_DATA_SIZE",
                                        DEFAULT_DATA_SIZE) or 0),
            ),
        ]

    def denoise(self, img, strength, ctx):
        from .onnx import run_scunet
        # ensure BOTH graph + external-data files land in the cache
        specs = self.weight_specs()
        paths = [ensure(s) for s in specs]
        return run_scunet(img, float(strength), paths[0])
