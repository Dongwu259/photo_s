"""
PhotoS - Image Quality Metrics

Pure-Python SSIM (Structural Similarity Index) with zero third-party
dependencies. Both images are downscaled to a small grayscale sample before
comparison, so the score stays fast even for very large photos.
"""

from PIL import Image


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
        win_size: Sliding window size, must be odd (default 7).

    Returns:
        Mean SSIM over all windows, a float in [0, 1].
    """
    a = _load_sample(path_a, sample_size)
    b = _load_sample(path_b, sample_size)

    if a.size != b.size:
        b = b.resize(a.size, Image.LANCZOS)

    # get_flattened_data replaces getdata (deprecated, removed in Pillow 14)
    pixels_a = list(a.get_flattened_data())
    pixels_b = list(b.get_flattened_data())
    width, height = a.size

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

    pixels = list(img.get_flattened_data())  # getdata removed in Pillow 14
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
    pixels = list(img.get_flattened_data())
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
