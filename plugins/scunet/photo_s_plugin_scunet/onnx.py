"""
PhotoS SCUNet plugin - ONNX inference (onnxruntime, optional dependency).

SCUNet is a fixed-noise-level blind denoiser: one model handles a range of
ISO/noise levels, so the model itself has no strength knob. ``--denoise N``
is therefore mapped onto a linear blend between the original and the fully
denoised output: ``out = orig * (1 - t) + denoised * t`` with
``t = clip(N / 15, 0, 1)`` — N >= 15 gives the full model output, N = 0 the
untouched original (the core NLM's useful range is ~3-20, so 15+ = "strong"
feels consistent).

Contract mirrors photo_s/denoise.py: alpha preserved, ``img.info`` (EXIF/ICC)
copied onto the result. Raises RuntimeError if onnxruntime is missing.
"""

import numpy as np
from PIL import Image

_SESSIONS = {}


def _blend(orig, denoised, strength):
    """Linear mix of the original and denoised float arrays by strength.

    ``t = clip(strength / 15, 0, 1)``: strength 0 keeps the original
    untouched, strength >= 15 returns the full model output. Strength is
    clamped, so out-of-range values degrade gracefully.
    """
    t = min(max(strength / 15.0, 0.0), 1.0)
    return orig * (1.0 - t) + denoised * t


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

    ``strength`` scales the effect by linearly blending the model output
    with the original (see :func:`_blend`): 0 = untouched, >= 15 = full
    model output. Alpha is preserved; EXIF/ICC in ``img.info`` is copied
    onto the result.
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

    # SCUNet reshapes H,W into (n, 8) window blocks at EVERY scale, and its
    # encoder downsamples 3 times (÷8): scale dims are H, H/2, H/4, H/8, so
    # the input dims must be multiples of 64. Pad by edge replication (safe
    # even for tiny dims), run inference, then crop the padding off.
    h, w = arr.shape[:2]
    pad_h = (64 - h % 64) % 64
    pad_w = (64 - w % 64) % 64
    if pad_h or pad_w:
        padded = np.pad(arr, ((0, pad_h), (0, pad_w), (0, 0)), mode="edge")
    else:
        padded = arr
    tensor = np.transpose(padded, (2, 0, 1))[None, ...]

    sess = _session(model_path)
    input_name = sess.get_inputs()[0].name
    out = sess.run(None, {input_name: tensor})[0]

    # [1,C,H,W] → [H,W,C], crop padding, mix by strength, clamp, → uint8
    denoised = np.transpose(out[0], (1, 2, 0))[:h, :w]
    mixed = _blend(arr, denoised, float(strength))
    out = np.clip(mixed, 0.0, 1.0) * 255.0
    result = Image.fromarray(out.astype(np.uint8), mode="RGB")
    result.info = dict(img.info)

    if alpha is not None:
        result.putalpha(alpha)
    return result
