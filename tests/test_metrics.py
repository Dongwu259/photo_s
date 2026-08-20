"""Tests for the pure-Python SSIM metric in photo_s.metrics."""

import os
import sys

# Ensure src package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageFilter

from photo_s.metrics import compute_ssim, compute_psnr, compute_blur_score

import pytest


def _solid(path, size=(64, 64), color=(100, 150, 200), fmt="PNG"):
    Image.new("RGB", size, color).save(path, format=fmt)
    return str(path)


class TestComputeSsim:
    def test_identical_png_is_one(self, tmp_path):
        a = _solid(tmp_path / "a.png", size=(64, 64))
        b = _solid(tmp_path / "b.png", size=(64, 64))
        assert compute_ssim(a, b) == 1.0

    def test_identical_jpeg_near_one(self, tmp_path):
        # Lossy JPEG round-trip of the same solid color stays essentially 1.0
        a = _solid(tmp_path / "a.jpg", size=(64, 64), fmt="JPEG")
        b = _solid(tmp_path / "b.jpg", size=(64, 64), fmt="JPEG")
        assert compute_ssim(a, b) > 0.99

    def test_different_images_below_one(self, tmp_path):
        a = _solid(tmp_path / "red.png", color=(200, 0, 0))
        b = _solid(tmp_path / "blue.png", color=(0, 0, 200))
        assert compute_ssim(a, b) < 1.0

    def test_different_sizes_handled(self, tmp_path):
        a = _solid(tmp_path / "big.png", size=(128, 128), color=(120, 90, 40))
        b = _solid(tmp_path / "small.png", size=(32, 32), color=(120, 90, 40))
        # resized to a's sample size internally; identical color → ~1.0
        assert compute_ssim(a, b) > 0.99

    def test_bounds(self, tmp_path):
        a = _solid(tmp_path / "a.png")
        b = _solid(tmp_path / "b.png", color=(10, 200, 90))
        score = compute_ssim(a, b)
        assert 0.0 <= score <= 1.0

    def test_tiny_images_fallback(self, tmp_path):
        # Smaller than the window → global-comparison fallback, no crash
        a = _solid(tmp_path / "tiny_a.png", size=(2, 2), color=(5, 5, 5))
        b = _solid(tmp_path / "tiny_b.png", size=(2, 2), color=(5, 5, 5))
        assert compute_ssim(a, b) == 1.0

    def test_even_window_size_bumped_to_odd(self, tmp_path):
        # An even window cannot be centered on a pixel and mixed win_size+1
        # rows with win_size columns (wrong statistics) — it is bumped up.
        a = _solid(tmp_path / "a.png", color=(100, 150, 200))
        b = _solid(tmp_path / "b.png", color=(10, 200, 90))
        assert compute_ssim(a, b, win_size=8) == compute_ssim(a, b, win_size=9)
        assert 0.0 <= compute_ssim(a, b, win_size=8) <= 1.0

    def test_even_sized_images(self, tmp_path):
        # Even pixel dimensions are fine with the (odd) sliding window.
        a = _solid(tmp_path / "ea.png", size=(50, 40), color=(77, 88, 99))
        b = _solid(tmp_path / "eb.png", size=(50, 40), color=(77, 88, 99))
        c = _solid(tmp_path / "ec.png", size=(50, 40), color=(200, 30, 60))
        assert compute_ssim(a, b) == 1.0
        assert 0.0 <= compute_ssim(a, c) <= 1.0

    def test_image_smaller_than_window(self, tmp_path):
        # 6x6 < default 7x7 window but >= 3 → window shrinks to 3, no crash.
        a = _solid(tmp_path / "sa.png", size=(6, 6), color=(5, 5, 5))
        b = _solid(tmp_path / "sb.png", size=(6, 6), color=(5, 5, 5))
        assert compute_ssim(a, b) == 1.0


class TestComputePsnr:
    def _noisy(self, path, size=(64, 64)):
        import random
        random.seed(42)
        img = Image.new("RGB", size)
        px = img.load()
        for y in range(size[1]):
            for x in range(size[0]):
                px[x, y] = (random.randint(0, 255), random.randint(0, 255),
                            random.randint(0, 255))
        img.save(path, format="PNG")
        return str(path)

    def test_identical_is_inf(self, tmp_path):
        a = _solid(tmp_path / "a.png", color=(100, 150, 200))
        b = _solid(tmp_path / "b.png", color=(100, 150, 200))
        assert compute_psnr(a, b) == float("inf")

    def test_tiny_change_scores_higher_than_big_change(self, tmp_path):
        orig = self._noisy(tmp_path / "orig.png")
        img = Image.open(orig)
        tiny = str(tmp_path / "tiny.png")
        big = str(tmp_path / "big.png")
        img.point(lambda v: min(255, v + 1)).save(tiny, format="PNG")
        img.point(lambda v: 255 - v).save(big, format="PNG")
        small_change = compute_psnr(orig, tiny)
        big_change = compute_psnr(orig, big)
        assert 0 < big_change < small_change < float("inf")

    def test_symmetric(self, tmp_path):
        a = _solid(tmp_path / "a.png", color=(100, 150, 200))
        b = _solid(tmp_path / "b.png", color=(10, 200, 90))
        assert compute_psnr(a, b) == compute_psnr(b, a)

    def test_different_sizes_handled(self, tmp_path):
        a = _solid(tmp_path / "big.png", size=(128, 128), color=(120, 90, 40))
        b = _solid(tmp_path / "small.png", size=(32, 32), color=(120, 90, 40))
        # b resized to a's sample size internally; identical color → inf
        assert compute_psnr(a, b) == float("inf")

    def test_tiny_images(self, tmp_path):
        a = _solid(tmp_path / "ta.png", size=(2, 2), color=(5, 5, 5))
        b = _solid(tmp_path / "tb.png", size=(2, 2), color=(5, 5, 5))
        c = _solid(tmp_path / "tc.png", size=(2, 2), color=(250, 250, 250))
        assert compute_psnr(a, b) == float("inf")
        assert compute_psnr(a, c) < 10

    def test_even_sized_images(self, tmp_path):
        a = _solid(tmp_path / "ea.png", size=(50, 40), color=(77, 88, 99))
        b = _solid(tmp_path / "eb.png", size=(50, 40), color=(77, 88, 99))
        assert compute_psnr(a, b) == float("inf")


class TestComputeBlurScore:
    def test_flat_image_zero(self, tmp_path):
        a = _solid(tmp_path / "flat.png", size=(64, 64), color=(100, 100, 100))
        assert compute_blur_score(a) == 0.0

    def test_noisy_sharper_than_blurred(self, tmp_path):
        import random
        random.seed(42)
        img = Image.new("L", (64, 64))
        px = img.load()
        for x in range(64):
            for y in range(64):
                px[x, y] = random.randint(0, 255)
        noisy = str(tmp_path / "noisy.png")
        blurred = str(tmp_path / "blurred.png")
        img.save(noisy)
        img.filter(ImageFilter.GaussianBlur(3)).save(blurred)
        assert compute_blur_score(noisy) > compute_blur_score(blurred)

    def test_non_negative(self, tmp_path):
        a = _solid(tmp_path / "a.png", size=(32, 32), color=(10, 200, 90))
        assert compute_blur_score(a) >= 0

    def test_tiny_image_no_crash(self, tmp_path):
        a = _solid(tmp_path / "tiny.png", size=(2, 2), color=(5, 5, 5))
        assert compute_blur_score(a) == 0.0

    def test_missing_file_zero(self, tmp_path):
        assert compute_blur_score(str(tmp_path / "nope.png")) == 0.0


# ── analyze_image (v1.7.0) ───────────────────────────────────────────────────

from photo_s.metrics import analyze_image, _estimate_kelvin


def test_analyze_image_shape(tmp_path):
    p = tmp_path / "a.png"
    Image.new("RGB", (64, 48), (100, 150, 200)).save(p)
    r = analyze_image(str(p))
    assert r["ok"] is True
    assert r["size"] == [64, 48]
    for ch in ("r", "g", "b", "luma"):
        assert len(r["histogram"][ch]) == 32
        assert sum(r["histogram"][ch]) == 64 * 48
    assert r["stats"]["mean"]["r"] == 100
    assert r["stats"]["mean"]["g"] == 150
    assert r["stats"]["mean"]["b"] == 200


def test_analyze_image_exposure_and_contrast(tmp_path):
    p = tmp_path / "half.png"
    img = Image.new("RGB", (8, 8))
    for y in range(8):
        for x in range(8):
            img.putpixel((x, y), (250, 250, 250) if x < 4 else (2, 2, 2))
    img.save(p)
    r = analyze_image(str(p))
    assert r["exposure"]["overexposed_pct"] == pytest.approx(50, abs=1)
    assert r["exposure"]["underexposed_pct"] == pytest.approx(50, abs=1)
    assert r["stats"]["contrast"] > 0.4  # half black / half white


def test_analyze_image_kelvin_direction():
    # Warm (R-heavy) image estimates a LOWER kelvin than a cool one.
    assert _estimate_kelvin(220, 100) < _estimate_kelvin(100, 220)
    assert 2000 <= _estimate_kelvin(128, 128) <= 12000


def test_analyze_image_unreadable():
    r = analyze_image("/nonexistent/img.png")
    assert r["ok"] is False


def test_analyze_image_saturation(tmp_path):
    p = tmp_path / "sat.png"
    Image.new("RGB", (16, 16), (200, 20, 20)).save(p)
    r = analyze_image(str(p))
    assert r["stats"]["saturation_mean"] > 0.8
    grey = tmp_path / "grey.png"
    Image.new("RGB", (16, 16), (128, 128, 128)).save(grey)
    assert analyze_image(str(grey))["stats"]["saturation_mean"] < 0.01
