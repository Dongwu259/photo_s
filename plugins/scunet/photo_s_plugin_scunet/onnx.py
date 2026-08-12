"""
PhotoS SCUNet plugin - ONNX inference (onnxruntime, optional dependency).

SCUNet is a fixed-noise-level blind denoiser: one model handles a range of
ISO/noise levels, so ``--denoise N`` acts as the on/off trigger (strength is
accepted and currently passed through but not used to scale the model).

Contract mirrors photo_s/denoise.py: alpha preserved, ``img.info`` (EXIF/ICC)
copied onto the result. Raises RuntimeError if onnxruntime is missing.
"""

import numpy as np
from PIL import Image

_SESSIONS = {}


def _ort():
    try:
        import onnxruntime
        return onnxruntime
    except ImportError:
        raise RuntimeError(
            "scunet plugin requires the optional dependency: "
            "pip install onnxruntime")


def _session(path):
    ort = _ort()
    if path not in _SESSIONS:
        providers = ort.get_available_providers()
        try:
            sess = ort.InferenceSession(path, providers=providers)
        except Exception:
            # External-data models can fail to init on some accelerators
            # (e.g. CoreML); CPU is the reliable fallback.
            sess = ort.InferenceSession(path,
                                        providers=["CPUExecutionProvider"])
        _SESSIONS[path] = sess
    return _SESSIONS[path]


def run_scunet(img: Image.Image, strength: float, model_path: str) -> Image.Image:
    """Denoise ``img`` through the SCUNet ONNX model at ``model_path``.

    ``strength`` is accepted for interface parity; SCUNet is a fixed-noise
    model so it currently just triggers denoising. Alpha is preserved;
    EXIF/ICC in ``img.info`` is copied onto the result.
    """
    alpha = None
    if img.mode == "RGBA":
        alpha = img.split()[-1]
        rgb = img.convert("RGB")
    elif img.mode == "L":
        rgb = img.convert("RGB")
    else:
        rgb = img.convert("RGB")

    # PIL → float32 NCHW [1,3,H,W] normalized to 0..1
    arr = np.asarray(rgb, dtype=np.float32) / 255.0
    tensor = np.transpose(arr, (2, 0, 1))[None, ...]

    sess = _session(model_path)
    input_name = sess.get_inputs()[0].name
    out = sess.run(None, {input_name: tensor})[0]

    # [1,C,H,W] → [H,W,C], clamp, back to 0..255 uint8
    out = np.transpose(out[0], (1, 2, 0))
    out = np.clip(out, 0.0, 1.0) * 255.0
    result = Image.fromarray(out.astype(np.uint8), mode="RGB")
    result.info = dict(img.info)

    if alpha is not None:
        result.putalpha(alpha)
    return result
