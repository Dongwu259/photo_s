"""PhotoS official plugin: LUT color grading (tetrahedral + film presets).

Overrides the core built-in trilinear ``.cube`` engine via the ``lut``
provider slot (``provides = ("lut",)``). Pure numpy — no model weights, no
modelstore.

``--lut <preset>`` accepts any of the built-in film presets below by name;
``--lut <file.cube>`` still works (applied with tetrahedral interpolation,
smoother than the built-in trilinear).
"""

import numpy as np
from PIL import Image

from photo_s.hooks import PhotoSPlugin
from photo_s.lut import LutError, load_cube

_LUT_SIZE = 33


# ── preset generation ────────────────────────────────────────────────────────

def _build_preset(contrast=1.0, sat=1.0, tint_r=1.0, tint_b=1.0,
                  gamma=1.0):
    """Build a 33³ RGB table from tonal/saturation/tint params.

    Tonal response is a smoothstep S-curve applied hue-preservingly
    (per-channel value scaled by curve/luminance), then saturation, a warm/cool
    tint on R/B, then a per-channel gamma.
    """
    n = _LUT_SIZE
    idx = np.linspace(0.0, 1.0, n, dtype=np.float32)
    # axes [b, g, r] — red varies fastest, matching .cube row ordering
    r = idx.reshape(1, 1, n)
    g = idx.reshape(1, n, 1)
    b = idx.reshape(n, 1, 1)

    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    x = np.clip((lum - 0.5) * contrast + 0.5, 0.0, 1.0)
    curve = x * x * (3.0 - 2.0 * x)  # smoothstep S-curve

    ratio = np.divide(curve, np.maximum(lum, 1e-6),
                      out=np.ones_like(curve), where=lum > 1e-6)
    out_r = np.clip(curve + (r * ratio - curve) * sat, 0.0, 1.0) * tint_r
    out_g = np.clip(curve + (g * ratio - curve) * sat, 0.0, 1.0)
    out_b = np.clip(curve + (b * ratio - curve) * sat, 0.0, 1.0) * tint_b

    out_r = np.clip(out_r ** gamma, 0.0, 1.0)
    out_g = np.clip(out_g ** gamma, 0.0, 1.0)
    out_b = np.clip(out_b ** gamma, 0.0, 1.0)

    return np.stack((out_r, out_g, out_b), axis=-1)


_PRESET_PARAMS = {
    "filmic-v1":      dict(contrast=1.15, sat=1.05),
    "filmic-warm":    dict(contrast=1.20, sat=1.05, tint_r=1.04, tint_b=0.95,
                           gamma=0.97),
    "cinema-cool":    dict(contrast=1.25, sat=0.92, tint_r=0.97, tint_b=1.05,
                           gamma=0.95),
    "portrait-soft":  dict(contrast=0.90, sat=1.00, tint_r=1.02, gamma=1.08),
    "punchy":         dict(contrast=1.32, sat=1.18, gamma=0.98),
}

PRESETS = {name: _build_preset(**params)
           for name, params in _PRESET_PARAMS.items()}


# ── tetrahedral interpolation ────────────────────────────────────────────────

def _apply_tetrahedral(img, table):
    """Apply a 3D LUT with tetrahedral interpolation (smoother than
    trilinear). Chunked by rows to bound memory on very large images."""
    n = table.shape[0]
    arr = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    h, w = arr.shape[:2]
    chunk_rows = 512

    def _chunk(c):
        pos = c * (n - 1)
        lo = np.floor(pos).astype(np.int32)
        hi = np.minimum(lo + 1, n - 1)
        i0, j0, k0 = lo[..., 0], lo[..., 1], lo[..., 2]
        i1, j1, k1 = hi[..., 0], hi[..., 1], hi[..., 2]
        r, g, b = (pos[..., 0] - i0), (pos[..., 1] - j0), (pos[..., 2] - k0)
        w1 = np.maximum(np.maximum(r, g), b)
        w3 = np.minimum(np.minimum(r, g), b)
        w2 = (r + g + b) - w1 - w3

        c000 = table[k0, j0, i0]
        c111 = table[k1, j1, i1]
        # Tetrahedral decomposition: v1 = max-axis corner, v2 = max+mid axes
        # corner. Ties (r==g etc.) fall on a degenerate tetrahedron and stay
        # smooth, so plain argmax is safe.
        amax = np.argmax(np.stack((r, g, b), axis=-1), axis=-1)[..., None]
        v1 = np.where(amax == 0, table[k0, j0, i1],
              np.where(amax == 1, table[k0, j1, i0], table[k1, j0, i0]))
        v2 = np.where(amax == 0,
                      np.where((g >= b)[..., None], table[k0, j1, i1],
                               table[k1, j0, i1]),
              np.where(amax == 1,
                       np.where((r >= b)[..., None], table[k0, j1, i1],
                                table[k1, j1, i0]),
                       np.where((r >= g)[..., None], table[k1, j0, i1],
                                table[k1, j1, i0])))
        return (c000 * (1 - w1)[..., np.newaxis]
                + v1 * (w1 - w2)[..., np.newaxis]
                + v2 * (w2 - w3)[..., np.newaxis]
                + c111 * w3[..., np.newaxis])

    out = np.empty((h, w, 3), dtype=np.float32)
    for start in range(0, h, chunk_rows):
        end = min(start + chunk_rows, h)
        out[start:end] = np.clip(_chunk(arr[start:end]), 0.0, 1.0)
    return Image.fromarray((out * 255).astype(np.uint8), "RGB")


# ── plugin ───────────────────────────────────────────────────────────────────

class LutPlugin(PhotoSPlugin):
    """LUT color grading provider: film presets + tetrahedral .cube apply."""

    provides = ("lut",)

    def lut(self, img, lut_path, ctx):
        """Apply a preset (by name) or a .cube file to ``img``.

        Exceptions (bad preset name / unreadable file) propagate as per-file
        errors, matching the denoise-provider contract.
        """
        table, kind = self._resolve(lut_path)
        if kind == "1d":
            from photo_s.lut import _apply_1d  # 1D needs no interpolation
            return _apply_1d(img, table)
        return _apply_tetrahedral(img, table)

    def _resolve(self, ref):
        if ref in PRESETS:
            return PRESETS[ref], "3d"
        if not isinstance(ref, str):
            raise LutError(
                f"lut reference must be a preset name or path: {ref!r}")
        kind, _size, table = load_cube(ref)
        return table, kind
