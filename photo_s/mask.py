"""Local-adjustment masks (linear / radial / color range).

Masks are modeled as compact strings so they serialize into
``ProcessOptions`` and reach CLI / REST / MCP / presets with zero glue:

    masks       = "sky:linear:0.5,0,0.5,1,feather=0.3; face:color:255,200,180,tol=0.15"
    mask_adjust = "sky:exposure=-0.7,sat=0.2; face:brightness=0.1,clarity=0.3"

Each ``masks`` entry is ``[name:]type:params`` (unnamed entries get the
sequential name "1", "2", ...). Coordinates are relative 0-1, so one spec
applies to every image in a batch regardless of resolution. ``mask_adjust``
entries reference masks by name and carry ``key=value`` scalar adjustments
applied under the mask (see :func:`apply_local`).

AI segmentation types (``subject:`` / ``person:`` / ``object:`` /
``brush:``) are reserved for v1.8 - parsing them raises a clear
:class:`MaskError` instead of silently doing nothing.

Pure numpy + PIL, no optional deps. Conventions match ``grade.py``:
functions never mutate inputs and ``img.info`` is copied onto results.
"""

import numpy as np
from PIL import Image, ImageFilter

__all__ = [
    "MaskError", "MaskSpec",
    "parse_masks", "parse_mask_adjust",
    "render_mask", "render_all", "combine",
    "apply_local", "ADJUST_KEYS",
]


class MaskError(ValueError):
    """Invalid or unparseable mask spec."""


# Reserved for v1.8 (AI segmentation via opencv DNN + ONNX, and brush
# strokes). Parsing them now fails loudly so users know they exist but
# aren't silently ignored.
_V18_TYPES = ("subject", "person", "object", "brush")


class MaskSpec:
    """One parsed mask: kind + params + feather + invert + name."""

    __slots__ = ("kind", "params", "feather", "invert", "name")

    def __init__(self, kind, params, feather=0.0, invert=False, name=""):
        self.kind = kind
        self.params = params
        self.feather = feather
        self.invert = invert
        self.name = name

    def __repr__(self):
        return (f"MaskSpec({self.kind!r}, {self.params!r}, "
                f"feather={self.feather}, invert={self.invert}, "
                f"name={self.name!r})")

    def to_string(self) -> str:
        """Serialize back to compact spec form (round-trips)."""
        if self.kind == "color":
            base = ",".join(_fmt_num(v) for v in self.params[:3])
            base += f",tol={_fmt_num(self.params[3])}"
        else:
            base = ",".join(_fmt_num(v) for v in self.params)
        s = f"{self.kind}:{base}"
        if self.feather:
            s += f",feather={_fmt_num(self.feather)}"
        if self.invert:
            s += ",invert"
        if self.name and not self.name.isdigit():
            s = f"{self.name}:{s}"
        return s


def _fmt_num(v) -> str:
    if float(v) == int(v):
        return str(int(v))
    return f"{float(v):.4g}"


def _parse_mask_segment(seg: str, index: int) -> MaskSpec:
    """Parse one ``[name:]type:params`` segment into a MaskSpec."""
    seg = seg.strip()
    if not seg:
        raise MaskError("empty mask segment")
    parts = seg.split(":")
    if len(parts) == 3:
        name, mtype, params = parts[0].strip(), parts[1].strip().lower(), parts[2]
    elif len(parts) == 2:
        name, mtype, params = str(index), parts[0].strip().lower(), parts[1]
    else:
        raise MaskError(
            f"mask segment {seg!r} must be '[name:]type:params' "
            f"(colons separate name/type/params)")
    if mtype in _V18_TYPES:
        raise MaskError(
            f"mask type {mtype!r} requires PhotoS v1.8 (AI segmentation / "
            f"brush); v1.7 supports linear, radial and color masks")
    if mtype not in ("linear", "radial", "color"):
        raise MaskError(
            f"unknown mask type {mtype!r} (expected linear, radial or color)")
    if not name or any(c in name for c in ":;,= "):
        raise MaskError(f"invalid mask name {name!r} in segment {seg!r}")

    # Params: positional floats plus feather=/tol= keywords and the
    # "invert" flag, comma-separated.
    positional: list = []
    feather = 0.0
    tol = None
    invert = False
    for tok in params.split(","):
        tok = tok.strip()
        if not tok:
            continue
        low = tok.lower()
        if low == "invert":
            invert = True
            continue
        if low.startswith("feather="):
            feather = float(low.split("=", 1)[1])
            continue
        if low.startswith("tol="):
            tol = float(low.split("=", 1)[1])
            continue
        try:
            positional.append(float(tok))
        except ValueError:
            raise MaskError(f"bad numeric param {tok!r} in mask {seg!r}") from None

    feather = max(0.0, min(1.0, feather))
    if mtype == "linear":
        if len(positional) < 4:
            raise MaskError(f"linear mask needs x0,y0,x1,y1 (got {seg!r})")
        if len(positional) > 5:
            raise MaskError(f"too many params in mask {seg!r}")
        if len(positional) == 5:  # positional 5th = feather
            feather = max(0.0, min(1.0, positional[4]))
        vals = tuple(max(0.0, min(1.0, v)) for v in positional[:4])
        if vals[0] == vals[2] and vals[1] == vals[3]:
            raise MaskError(f"linear mask axis has zero length (got {seg!r})")
        return MaskSpec("linear", vals, feather, invert, name)
    if mtype == "radial":
        if len(positional) < 4:
            raise MaskError(f"radial mask needs cx,cy,rx,ry (got {seg!r})")
        if len(positional) > 5:
            raise MaskError(f"too many params in mask {seg!r}")
        if len(positional) == 5:
            feather = max(0.0, min(1.0, positional[4]))
        cx, cy = max(0.0, min(1.0, positional[0])), max(0.0, min(1.0, positional[1]))
        rx, ry = positional[2], positional[3]
        if rx <= 0 or ry <= 0:
            raise MaskError(f"radial mask radii must be > 0 (got {seg!r})")
        return MaskSpec("radial", (cx, cy, rx, ry), feather, invert, name)
    # color
    if len(positional) < 3:
        raise MaskError(f"color mask needs r,g,b (got {seg!r})")
    if len(positional) > 4:
        raise MaskError(f"too many params in mask {seg!r}")
    r, g, b = (int(round(max(0.0, min(255.0, v)))) for v in positional[:3])
    if tol is None:
        tol = positional[3] if len(positional) == 4 else 0.15
    tol = max(0.02, min(1.0, tol))
    return MaskSpec("color", (r, g, b, tol), feather, invert, name)


def parse_masks(s: str) -> list:
    """Parse the ``masks`` option string into a list of MaskSpec."""
    if not s or not s.strip():
        return []
    specs = []
    names = set()
    for i, seg in enumerate(s.split(";")):
        seg = seg.strip()
        if not seg:
            continue
        spec = _parse_mask_segment(seg, i + 1)
        if spec.name in names:
            raise MaskError(f"duplicate mask name {spec.name!r}")
        names.add(spec.name)
        specs.append(spec)
    return specs


# Supported per-mask scalar adjustments. Values are additive deltas unless
# noted; temp is an absolute Kelvin value, tint the G(-)/M(+) axis, blur a
# Gaussian radius in pixels, sharpen a multiplier offset from 1.0.
ADJUST_KEYS = (
    "exposure", "brightness", "contrast", "saturation", "vibrance",
    "clarity", "texture", "sharpen", "temp", "tint", "blur",
)


def parse_mask_adjust(s: str) -> dict:
    """Parse ``mask_adjust`` -> ``{name: {key: value}}``.

    ``"sky:exposure=-0.7,sat=0.2"`` -> ``{"sky": {"exposure": -0.7,
    "sat": 0.2}}``. Unknown keys raise :class:`MaskError` (a typo in a
    mask adjustment must not be silently ignored).
    """
    out: dict = {}
    if not s or not s.strip():
        return out
    for seg in s.split(";"):
        seg = seg.strip()
        if not seg:
            continue
        if ":" not in seg:
            raise MaskError(
                f"mask_adjust segment {seg!r} must be 'name:key=value,...'")
        name, rest = seg.split(":", 1)
        name = name.strip()
        adjust = {}
        for item in rest.split(","):
            item = item.strip()
            if not item:
                continue
            if "=" not in item:
                raise MaskError(
                    f"mask_adjust item {item!r} must be 'key=value'")
            key, val = item.split("=", 1)
            key = key.strip().lower()
            if key not in ADJUST_KEYS:
                raise MaskError(
                    f"unknown mask adjustment {key!r} "
                    f"(expected {','.join(ADJUST_KEYS)})")
            try:
                adjust[key] = float(val)
            except ValueError:
                raise MaskError(
                    f"mask_adjust value for {key!r} must be numeric "
                    f"(got {val!r})") from None
        if not name or not adjust:
            raise MaskError(f"bad mask_adjust segment {seg!r}")
        out[name] = adjust
    return out


# ── Rendering ────────────────────────────────────────────────────────────────

def _coords(w: int, h: int):
    """Normalized coordinate grids (x in 0..1 columns, y in 0..1 rows)."""
    ys, xs = np.mgrid[0:h, 0:w]
    x = xs.astype(np.float32) / max(1, w - 1)
    y = ys.astype(np.float32) / max(1, h - 1)
    return x, y


def render_mask(spec: MaskSpec, w: int, h: int,
                img: Image.Image = None) -> np.ndarray:
    """Render one mask as a float32 ``h x w`` array in 0..1.

    ``img`` is required for color masks (they measure the image's own
    pixels); geometric masks ignore it.
    """
    x, y = _coords(w, h)
    if spec.kind == "linear":
        x0, y0, x1, y1 = spec.params
        dx, dy = x1 - x0, y1 - y0
        length2 = dx * dx + dy * dy
        # Projection of each pixel onto the gradient axis, 0 at the start
        # point and 1 at the end point: a linear ramp perpendicular to the
        # axis (the Lightroom linear-gradient shape).
        t = ((x - x0) * dx + (y - y0) * dy) / length2
        mask = np.clip(t, 0.0, 1.0)
    elif spec.kind == "radial":
        cx, cy, rx, ry = spec.params
        d = np.sqrt(((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2)
        feather = spec.feather if spec.feather > 0 else 0.05
        inner = max(0.0, 1.0 - feather)
        mask = np.clip((1.0 - d) / (1.0 - inner), 0.0, 1.0)
    else:  # color
        if img is None:
            raise MaskError(
                "color mask needs the image to measure against")
        mask = _color_mask(img, spec)
    if spec.feather > 0 and spec.kind != "color":
        mask = _feather_mask(mask, spec.feather, w, h)
    if spec.invert:
        mask = 1.0 - mask
    return mask.astype(np.float32)


def _color_mask(img: Image.Image, spec: MaskSpec) -> np.ndarray:
    """Soft mask by perceptual distance from a sampled color.

    Distance combines angular hue distance with saturation and value
    deltas (each normalized to 0..1), so a saturated sample ignores gray
    pixels via the saturation term instead of via noisy hue readings.
    """
    import colorsys
    r, g, b, tol = spec.params
    th, ts, tv = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    target_h = th * 360.0
    from .grade import _to_hsv
    arr = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    hue, sat, val = _to_hsv(arr)
    hue_deg = hue * 360.0
    d = (hue_deg - target_h) % 360.0
    dh = np.where(d > 180.0, d - 360.0, d) / 180.0
    ds = np.abs(sat - ts)
    dv = np.abs(val - tv)
    dist = np.sqrt(dh * dh + ds * ds + dv * dv)
    mask = np.exp(-(dist ** 2) / (2.0 * tol * tol))
    # Gray pixels (sat near 0) have meaningless hue - zero them out unless
    # the target itself is near-gray.
    if ts > 0.1:
        mask = mask * np.clip(sat / 0.1, 0.0, 1.0)
    return mask


def _feather_mask(mask: np.ndarray, feather: float, w: int, h: int):
    """Gaussian-feather a mask; sigma scales with the shorter image side."""
    sigma = max(0.5, feather * min(w, h) / 8.0)
    m = Image.fromarray((mask * 255.0).astype(np.uint8), mode="L")
    m = m.filter(ImageFilter.GaussianBlur(radius=sigma))
    return np.asarray(m, dtype=np.float32) / 255.0


def render_all(specs, w: int, h: int, img: Image.Image = None) -> dict:
    """Render every spec -> ``{name: float32 h x w array}``.

    ``img`` is required when any spec is a color mask.
    """
    return {spec.name: render_mask(spec, w, h, img=img) for spec in specs}


def combine(masks) -> np.ndarray:
    """Combine rendered masks with union (max) semantics."""
    out = None
    for m in masks:
        out = m if out is None else np.maximum(out, m)
    if out is None:
        raise MaskError("combine() needs at least one mask")
    return out


# ── Local adjustments ────────────────────────────────────────────────────────

def apply_local(img: Image.Image, mask: np.ndarray,
                adjust: dict) -> Image.Image:
    """Apply scalar adjustments under a mask: ``out = mix(orig, adjusted)``.

    ``adjust`` keys come from :data:`ADJUST_KEYS`; each engine function is
    reused as-is so local and global grading stay numerically identical.
    The mask is a float32 0..1 array matching the image size; the result
    is the original outside the mask and the fully-adjusted image inside.
    """
    if not adjust:
        return img
    m = np.asarray(mask, dtype=np.float32)
    if m.shape != (img.height, img.width):
        raise MaskError(
            f"mask shape {m.shape} does not match image "
            f"({img.width}x{img.height})")
    if not m.any():
        return img  # empty mask - nothing to adjust

    out = img
    if adjust.get("exposure"):
        from .adjust import apply_exposure
        out = apply_exposure(out, ev=adjust["exposure"])
    if any(adjust.get(k) for k in ("brightness", "contrast", "saturation",
                                   "sharpen")):
        from .adjust import apply_tone_adjustments
        out = apply_tone_adjustments(
            out,
            brightness=1.0 + adjust.get("brightness", 0.0),
            contrast=1.0 + adjust.get("contrast", 0.0),
            saturation=1.0 + adjust.get("saturation", 0.0),
            sharpen=1.0 + adjust.get("sharpen", 0.0))
    if adjust.get("temp"):
        from .adjust import apply_white_balance
        out = apply_white_balance(out, temp=adjust["temp"])
    if adjust.get("tint"):
        from .adjust import apply_white_balance
        out = apply_white_balance(out, tint=adjust["tint"])
    if adjust.get("vibrance"):
        from .grade import apply_vibrance
        out = apply_vibrance(out, adjust["vibrance"])
    if adjust.get("clarity"):
        from .grade import apply_clarity
        out = apply_clarity(out, adjust["clarity"])
    if adjust.get("texture"):
        from .grade import apply_texture
        out = apply_texture(out, adjust["texture"])
    if adjust.get("blur", 0) > 0:
        radius = max(0.1, min(50.0, adjust["blur"]))
        if out.mode not in ("RGB", "RGBA", "L"):
            out = out.convert("RGBA")
        out = out.filter(ImageFilter.GaussianBlur(radius=radius))

    if out is img:  # nothing actually adjusted
        return img
    # Blend: fully-adjusted inside the mask, original outside.
    a = np.asarray(img.convert("RGBA"), dtype=np.float32)
    b = np.asarray(out.convert("RGBA"), dtype=np.float32)
    mixed = a * (1.0 - m[..., np.newaxis]) + b * m[..., np.newaxis]
    result = Image.fromarray(np.round(mixed).astype(np.uint8), mode="RGBA")
    if img.mode in ("RGB", "RGBA", "L"):
        result = result.convert(img.mode)
    else:
        result = result.convert("RGB")
    result.info = img.info.copy()
    return result
