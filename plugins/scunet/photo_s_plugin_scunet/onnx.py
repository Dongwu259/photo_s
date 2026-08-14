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


def _tile_starts(size, tile, overlap):
    """Top-left offsets of ``tile``-sized tiles covering ``[0, size)``.

    Stride is ``tile - overlap``; the last tile is flush with the far edge
    (``size - tile``) so coverage never runs out of bounds.
    """
    if size <= tile:
        return [0]
    stride = tile - overlap
    starts = list(range(0, size - tile + 1, stride))
    if starts[-1] != size - tile:
        starts.append(size - tile)
    return starts


def _axis_weights(starts, tile):
    """1D linear-ramp blend weights (len ``tile``) per tile along one axis.

    A side touching the image edge stays flat at 1; a side overlapping a
    neighbour ramps linearly over the actual overlap length L. Overlapping
    ramps are midpoint-symmetric (w_up(j) = (j + .5) / L, w_down = 1 - w_up),
    so two neighbouring tiles sum to 1 at every position of their overlap
    (triple overlaps only occur when overlap >= tile / 2; the final
    normalization in :func:`_tiled_inference` absorbs those).
    """
    weights = []
    for k, s in enumerate(starts):
        w1 = np.ones(tile, dtype=np.float32)
        if k > 0:
            left = starts[k - 1] + tile - s  # actual overlap with previous
            if left > 0:
                w1[:left] *= (np.arange(left, dtype=np.float32) + 0.5) / left
        if k < len(starts) - 1:
            right = s + tile - starts[k + 1]  # actual overlap with next
            if right > 0:
                w1[tile - right:] *= (
                    np.arange(right, 0, -1, dtype=np.float32) - 0.5) / right
        weights.append(w1)
    return weights


def _ramp_weights(h, w, tile, overlap):
    """Tile positions and 2D blend weights for an HxW tensor.

    Returns ``(positions, weights)``: ``positions`` is a list of ``(y, x)``
    top-left offsets covering the image; ``weights`` is a float32 array of
    shape ``[len(positions), tile, tile]`` — each entry the outer product of
    the two per-axis ramps. Since tiles form the full cartesian product and
    each axis sums to 1, the weights of all tiles sum to 1 at every pixel.
    """
    ys = _tile_starts(h, tile, overlap)
    xs = _tile_starts(w, tile, overlap)
    ramp_y = _axis_weights(ys, tile)
    ramp_x = _axis_weights(xs, tile)
    positions = [(y, x) for y in ys for x in xs]
    weights = np.stack([ry[:, None] * rx[None, :]
                        for ry in ramp_y for rx in ramp_x])
    return positions, weights


def _tiled_inference(sess, input_name, tensor, tile, overlap):
    """Run ``sess`` on ``tensor`` [1,3,H,W] tile by tile and blend.

    Tiles of ``tile``x``tile`` (stride ``tile - overlap``, last tile flush
    with the far edge) are inferred independently and accumulated with
    linear-ramp weights (see :func:`_ramp_weights`); the result is divided
    by the summed weights, so the blend is a proper weighted average even
    where ramps cannot be perfectly complementary. Peak activation memory
    stays ~one tile regardless of H, W.
    """
    _, _, h, w = tensor.shape
    positions, weights = _ramp_weights(h, w, tile, overlap)
    acc = None
    wsum = np.zeros((h, w), dtype=np.float32)
    for (y, x), wt in zip(positions, weights):
        out = sess.run(None, {input_name: tensor[:, :, y:y + tile,
                                                    x:x + tile]})[0]
        if acc is None:
            acc = np.zeros((1, out.shape[1], h, w), dtype=np.float32)
        acc[:, :, y:y + tile, x:x + tile] += out * wt
        wsum[y:y + tile, x:x + tile] += wt
    return acc / wsum


def run_scunet(img: Image.Image, strength: float, model_path: str,
               *, tile: int = 512, overlap: int = 64) -> Image.Image:
    """Denoise ``img`` through the SCUNet ONNX model at ``model_path``.

    ``strength`` scales the effect by linearly blending the model output
    with the original (see :func:`_blend`): 0 = untouched, >= 15 = full
    model output. Alpha is preserved; EXIF/ICC in ``img.info`` is copied
    onto the result.

    When the padded tensor exceeds ``tile`` in either spatial dim, inference
    runs in overlapping tiles (see :func:`_tiled_inference`) to cap peak
    memory; otherwise the whole image goes through in one shot. ``overlap``
    must satisfy ``0 <= overlap < tile`` (ValueError otherwise).
    """
    if overlap < 0 or overlap >= tile:
        raise ValueError(
            f"overlap must satisfy 0 <= overlap < tile, "
            f"got tile={tile}, overlap={overlap}")
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
    _, _, ph, pw = tensor.shape
    if ph <= tile and pw <= tile:
        out = sess.run(None, {input_name: tensor})[0]
    else:
        out = _tiled_inference(sess, input_name, tensor, tile, overlap)

    # [1,C,H,W] → [H,W,C], crop padding, mix by strength, clamp, → uint8
    denoised = np.transpose(out[0], (1, 2, 0))[:h, :w]
    mixed = _blend(arr, denoised, float(strength))
    out = np.clip(mixed, 0.0, 1.0) * 255.0
    result = Image.fromarray(out.astype(np.uint8), mode="RGB")
    result.info = dict(img.info)

    if alpha is not None:
        result.putalpha(alpha)
    return result
