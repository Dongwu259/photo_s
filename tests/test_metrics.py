"""Tests for the pure-Python SSIM metric in photo_s.metrics."""

import os
import sys

# Ensure src package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageFilter

from photo_s.metrics import compute_ssim, compute_blur_score


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
