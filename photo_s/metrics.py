"""
PhotoS - Image Quality Metrics

Pure-Python SSIM (Structural Similarity Index) and PSNR with zero third-party
dependencies. Both images are downscaled to a small sample before comparison,
so the scores stay fast even for very large photos.
"""

import math

from PIL import Image


def _flattened(img):
    """Pixel data with Pillow version compat.

    ``get_flattened_data`` exists in Pillow 12+; older Pillows (down to the
    ``>=10.4.0`` floor) only have ``getdata``. Both return identical data
    (per-pixel tuples for RGB, flat ints for L) — fall back to keep py3.9
    (which resolves to Pillow 11) working.
    """
    gfd = getattr(img, "get_flattened_data", None)
    if gfd is not None:
        return gfd()
    return img.getdata()


def _load_sample(path: str, sample_size: int) -> Image.Image:
    """Open an image, downscale to ≤sample_size on the longest side, convert to grayscale."""
    with Image.open(path) as img:
        if img.size[0] > sample_size or img.size[1] > sample_size:
            img = img.copy()
            img.thumbnail((sample_size, sample_size), Image.LANCZOS)
        return img.convert("L")


def _window_ssim(win_a, win_b, n, c1, c2):
    """SSIM for a single window using the standard formulas from Wang et al. (2004)."""
    mu_a = sum(win_a) / n
    mu_b = sum(win_b) / n
    var_a = sum((v - mu_a) ** 2 for v in win_a) / n
    var_b = sum((v - mu_b) ** 2 for v in win_b) / n
    cov = sum((win_a[i] - mu_a) * (win_b[i] - mu_b) for i in range(n)) / n

    num = (2 * mu_a * mu_b + c1) * (2 * cov + c2)
    den = (mu_a ** 2 + mu_b ** 2 + c1) * (var_a + var_b + c2)
    return num / den


def compute_ssim(path_a: str, path_b: str, sample_size: int = 64,
                 win_size: int = 7) -> float:
    """Structural Similarity Index between two image files, in [0.0, 1.0].

    Higher is more similar; 1.0 means perceptually identical at the sample
    resolution. Uses a sliding uniform window with the standard SSIM
    constants (C1, C2) from Wang et al. (2004).

    Args:
        path_a: Path to the first image.
        path_b: Path to the second image.
        sample_size: Max dimension of the grayscale sample (default 64).
        win_size: Sliding window size (default 7). Even values are bumped to
            the next odd size — an even window cannot be centered on a pixel
            and would mix win_size+1 rows with win_size columns, skewing the
            statistics.

    Returns:
        Mean SSIM over all windows, a float in [0, 1].
    """
    a = _load_sample(path_a, sample_size)
    b = _load_sample(path_b, sample_size)

    if a.size != b.size:
        b = b.resize(a.size, Image.LANCZOS)

    pixels_a = list(_flattened(a))
    pixels_b = list(_flattened(b))
    width, height = a.size

    if win_size % 2 == 0:
        win_size += 1
    if win_size < 3 or win_size > min(width, height):
        win_size = 3 if min(width, height) >= 3 else 1

    half = win_size // 2
    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2

    total_ssim = 0.0
    count = 0

    for y in range(half, height - half):
        base_a = y * width
        base_b = y * width
        for x in range(half, width - half):
            win_a = []
            win_b = []
            for dy in range(-half, half + 1):
                row_start = (base_a + dy * width) + x - half
                win_a.extend(pixels_a[row_start:row_start + win_size])
                win_b.extend(pixels_b[row_start:row_start + win_size])
            total_ssim += _window_ssim(win_a, win_b, win_size * win_size, c1, c2)
            count += 1

    if count == 0:
        # Image too small for any window — fall back to a global comparison.
        n = len(pixels_a)
        return _window_ssim(pixels_a, pixels_b, n, c1, c2)

    return total_ssim / count


def _load_sample_rgb(path: str, sample_size: int) -> Image.Image:
    """Open an image, downscale to ≤sample_size on the longest side, convert to RGB."""
    with Image.open(path) as img:
        if img.size[0] > sample_size or img.size[1] > sample_size:
            img = img.copy()
            img.thumbnail((sample_size, sample_size), Image.LANCZOS)
        return img.convert("RGB")


def compute_psnr(path_a: str, path_b: str, sample_size: int = 256) -> float:
    """Peak Signal-to-Noise Ratio between two image files, in dB.

    Higher means closer to the reference; identical images return
    ``float("inf")``. Computed over all three RGB channels of a downscaled
    sample (peak = 255), so it stays fast even for very large photos.

    Args:
        path_a: Path to the reference image.
        path_b: Path to the image to score against the reference.
        sample_size: Max dimension of the RGB sample (default 256).

    Returns:
        PSNR in dB (negative values are possible for very different
        images), or ``float("inf")`` when the samples are identical.
    """
    a = _load_sample_rgb(path_a, sample_size)
    b = _load_sample_rgb(path_b, sample_size)

    if a.size != b.size:
        b = b.resize(a.size, Image.LANCZOS)

    pixels_a = list(_flattened(a))
    pixels_b = list(_flattened(b))
    n = len(pixels_a) * 3
    if n == 0:
        return float("inf")

    sq = 0
    for pa, pb in zip(pixels_a, pixels_b):
        sq += ((pa[0] - pb[0]) ** 2 + (pa[1] - pb[1]) ** 2
               + (pa[2] - pb[2]) ** 2)
    if sq == 0:
        return float("inf")

    mse = sq / n
    return 10 * math.log10((255 * 255) / mse)


def compute_blur_score(path: str, sample_size: int = 128) -> float:
    """A blur heuristic: the variance of a 3x3 Laplacian response.

    Higher values mean more high-frequency detail (sharper); a flat image
    scores 0.0. This is the classic variance-of-Laplacian focus measure,
    computed in pure Python on a downscaled grayscale sample. Unreadable or
    tiny images score 0.0.
    """
    try:
        img = _load_sample(path, sample_size)
    except Exception:
        return 0.0
    width, height = img.size
    if width < 3 or height < 3:
        return 0.0

    pixels = list(_flattened(img))
    # 3x3 Laplacian kernel [0,1,0; 1,-4,1; 0,1,0]
    values = []
    for y in range(1, height - 1):
        base = y * width
        for x in range(1, width - 1):
            center = pixels[base + x]
            lap = (pixels[base + x - 1] + pixels[base + x + 1]
                   + pixels[base - width + x] + pixels[base + width + x]
                   - 4 * center)
            values.append(lap)

    n = len(values)
    if n == 0:
        return 0.0
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    return variance


def compute_exposure_stats(path: str, sample_size: int = 256) -> dict:
    """Exposure statistics for culling, from a small grayscale sample.

    Returns {"ok": bool, "luminance": 0-1 mean, "overexposed_pct": % pixels
    ≥ 250, "underexposed_pct": % pixels ≤ 5}. Unreadable images → all 0, ok=False.
    """
    try:
        img = _load_sample(path, sample_size)
    except Exception:
        return {"ok": False, "luminance": 0.0,
                "overexposed_pct": 0.0, "underexposed_pct": 0.0}
    pixels = list(_flattened(img))
    n = len(pixels)
    if n == 0:
        return {"ok": False, "luminance": 0.0,
                "overexposed_pct": 0.0, "underexposed_pct": 0.0}
    over = sum(1 for p in pixels if p >= 250) / n * 100
    under = sum(1 for p in pixels if p <= 5) / n * 100
    mean = sum(pixels) / n
    return {"ok": True,
            "luminance": round(mean / 255, 3),
            "overexposed_pct": round(over, 2),
            "underexposed_pct": round(under, 2)}


# ── Perceptual analysis (v1.7.0): the "eyes" for LLM closed-loop grading ─────

def _estimate_kelvin(r_mean: float, b_mean: float) -> int:
    """Crude color-temperature heuristic from R/B channel means.

    Maps the R/B ratio around neutral (6500K at ratio 1) monotonically to
    2000..12000K. Not a calibrated measurement - it tells an agent which
    way the white balance leans, not the exact CCT.
    """
    import math as _math
    t = r_mean / max(1.0, b_mean)
    kelvin = 6500.0 * (t ** -1.5)
    return int(round(max(2000.0, min(12000.0, kelvin))))


def analyze_image(path: str, sample_size: int = 256) -> dict:
    """Perceptual image analysis for grading feedback loops.

    One call returns what an agent (or a future grading model) needs to
    judge a result: per-channel + luma histograms (32 bins), channel
    mean/median/std, contrast, saturation, a white-balance lean estimate,
    exposure stats and the blur score. Sampling is capped at
    ``sample_size`` on the longest side, so this stays fast on any photo.

    ``analyze -> adjust params -> process -> analyze`` is the intended
    loop (see docs/AGENT_API.md). Unreadable images return ``ok=False``.
    """
    try:
        img = _load_sample_rgb(path, sample_size)
    except Exception:
        return {"ok": False, "path": path, "error": "unreadable image"}

    import numpy as np
    arr = np.asarray(img, dtype=np.float32)
    h, w = arr.shape[:2]
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    # Luma (Rec. 601) - matches what the exposure/blur heuristics see.
    luma = 0.299 * r + 0.587 * g + 0.114 * b

    def hist(channel):
        counts, _ = np.histogram(channel, bins=32, range=(0, 255))
        return [int(c) for c in counts]

    # Saturation mean via max/min per pixel (fast, no HSV roundtrip).
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0.0)

    n = float(luma.size) or 1.0
    return {
        "ok": True,
        "path": path,
        "size": [w, h],
        "histogram": {
            "r": hist(r), "g": hist(g), "b": hist(b), "luma": hist(luma),
        },
        "stats": {
            "mean": {"r": round(float(r.mean()), 1),
                     "g": round(float(g.mean()), 1),
                     "b": round(float(b.mean()), 1),
                     "luma": round(float(luma.mean()), 1)},
            "median": {"r": round(float(np.median(r)), 1),
                       "g": round(float(np.median(g)), 1),
                       "b": round(float(np.median(b)), 1),
                       "luma": round(float(np.median(luma)), 1)},
            "std": {"r": round(float(r.std()), 1),
                    "g": round(float(g.std()), 1),
                    "b": round(float(b.std()), 1),
                    "luma": round(float(luma.std()), 1)},
            "contrast": round(float(luma.std()) / 255.0, 3),
            "saturation_mean": round(float(sat.mean()), 3),
        },
        "white_balance": {
            "kelvin_estimate": _estimate_kelvin(float(r.mean()),
                                                float(b.mean())),
            "tint_gm": round(float(g.mean() - (r.mean() + b.mean()) / 2.0), 1),
        },
        "exposure": {
            "luminance": round(float(luma.mean()) / 255.0, 3),
            "overexposed_pct": round(float((luma >= 250).sum()) / n * 100, 2),
            "underexposed_pct": round(float((luma <= 5).sum()) / n * 100, 2),
        },
        "blur_score": round(compute_blur_score(path, sample_size=128), 2),
    }
