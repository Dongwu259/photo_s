"""
PhotoS official SCUNet strong-denoise plugin.

Registers a ``denoise`` slot provider. When installed, ``photo-s --denoise N``
prefers this plugin over the core OpenCV NLM fallback.

The ONNX model weight is NOT shipped in the wheel. It is downloaded on first
use from a canonical URL (GitHub Release asset) into the model cache with
sha256 verification — see ``photo_s.modelstore``.

Maintainer note (before publishing to PyPI): point DEFAULT_MODEL_URL at the
real GitHub Release asset and fill in DEFAULT_MODEL_SHA256 / DEFAULT_MODEL_SIZE.
Tests override all three via PHOTOS_SCUNET_MODEL_* env vars.
"""

import os

from photo_s.hooks import PhotoSPlugin
from photo_s.modelstore import WeightSpec, ensure

# ── Placeholder values — update before publishing ──────────────────────────
DEFAULT_MODEL_URL = ("https://github.com/<org>/photo-s/releases/download/"
                     "scunet-v1/scunet.onnx")
DEFAULT_MODEL_SHA256 = "0" * 64
DEFAULT_MODEL_SIZE = 0


class ScunetPlugin(PhotoSPlugin):
    """SCUNet strong-denoise provider for the engine's denoise slot."""

    provides = ("denoise",)

    def weight_specs(self):
        return [WeightSpec(
            name="scunet.onnx",
            url=os.environ.get("PHOTOS_SCUNET_MODEL_URL", DEFAULT_MODEL_URL),
            sha256=os.environ.get("PHOTOS_SCUNET_MODEL_SHA256",
                                  DEFAULT_MODEL_SHA256),
            size=int(os.environ.get("PHOTOS_SCUNET_MODEL_SIZE",
                                    DEFAULT_MODEL_SIZE) or 0),
        )]

    def denoise(self, img, strength, ctx):
        from .onnx import run_scunet
        path = ensure(self.weight_specs()[0])
        return run_scunet(img, float(strength), path)
