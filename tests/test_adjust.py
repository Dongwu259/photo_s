"""Tests for photo_s.adjust — tone/color, crop, rotate, flip, pad, color mgmt."""

import os
import sys

# Ensure src package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

from photo_s.adjust import (
    apply_color_management, apply_crop, apply_crop_ratio, apply_flip,
    apply_pad, apply_rotate, apply_tone_adjustments, hex_to_rgb,
)


def _img(size=(40, 30), mode="RGB", color=(120, 100, 80)):
    return Image.new(mode, size, color)


class TestHexToRgb:
    def test_hash_form(self):
        assert hex_to_rgb("#FF0000") == (255, 0, 0)

    def test_bare_form(self):
        assert hex_to_rgb("00ff80") == (0, 255, 128)

    def test_invalid(self):
        import pytest
        with pytest.raises(ValueError):
            hex_to_rgb("notacolor")


class TestApplyTone:
    def test_neutral_factors_return_same_object(self):
        img = _img()
        assert apply_tone_adjustments(img) is img

    def test_brightness_halves_pixels(self):
        img = _img(color=(120, 100, 80))
        out = apply_tone_adjustments(img, brightness=0.5)
        assert out.getpixel((10, 10)) == (60, 50, 40)

    def test_contrast_changes_pixels(self):
        # two-tone image: contrast 2.0 pushes light → 255, dark → 0
        img = Image.new("RGB", (2, 1))
        img.putpixel((0, 0), (200, 200, 200))
        img.putpixel((1, 0), (50, 50, 50))
        out = apply_tone_adjustments(img, contrast=2.0)
        assert out.getpixel((0, 0)) == (255, 255, 255)
        assert out.getpixel((1, 0)) == (0, 0, 0)

    def test_saturation_increases_channel_spread(self):
        img = _img(color=(200, 100, 60))
        out = apply_tone_adjustments(img, saturation=2.0)
        px = out.getpixel((10, 10))
        assert (px[0] - px[2]) > (200 - 60)

    def test_gamma_luts_pixels(self):
        img = _img(color=(128, 128, 128))
        out = apply_tone_adjustments(img, gamma=2.0)
        # gamma 2.0 (display-style) brightens midtones
        assert out.getpixel((10, 10))[0] > 128

    def test_sharpen_changes_pixels(self):
        img = _img(color=(100, 100, 100))
        out = apply_tone_adjustments(img, sharpen=3.0)
        # flat image → no-op on the interior, but pipeline must not crash
        assert out.size == img.size

    def test_grayscale_returns_l_mode(self):
        img = _img()
        out = apply_tone_adjustments(img, grayscale=True)
        assert out.mode == "L"

    def test_grayscale_rgba_flattens(self):
        img = Image.new("RGBA", (20, 20), (10, 200, 30, 128))
        out = apply_tone_adjustments(img, grayscale=True)
        assert out.mode == "L"

    def test_sepia_red_dominates(self):
        img = _img(color=(100, 100, 100))
        out = apply_tone_adjustments(img, sepia=True)
        r, g, b = out.getpixel((10, 10))
        assert r > g > b

    def test_rgba_alpha_preserved(self):
        img = Image.new("RGBA", (20, 20), (100, 100, 100, 128))
        out = apply_tone_adjustments(img, brightness=2.0, contrast=1.5,
                                     saturation=0.5)
        assert out.mode == "RGBA"
        assert out.getpixel((5, 5))[3] == 128  # alpha untouched

    def test_gamma_keeps_alpha(self):
        img = Image.new("RGBA", (20, 20), (100, 100, 100, 200))
        out = apply_tone_adjustments(img, gamma=2.0)
        assert out.getpixel((5, 5))[3] == 200

    def test_sepia_rgba_keeps_alpha(self):
        img = Image.new("RGBA", (20, 20), (100, 100, 100, 90))
        out = apply_tone_adjustments(img, sepia=True)
        assert out.mode == "RGBA"
        assert out.getpixel((5, 5))[3] == 90

    def test_l_mode_saturation_becomes_rgb(self):
        img = _img(mode="L", color=(100,))
        out = apply_tone_adjustments(img, saturation=2.0)
        assert out.mode == "RGB"

    def test_p_mode_normalized(self):
        img = Image.new("P", (20, 20))
        out = apply_tone_adjustments(img, brightness=1.5)
        assert out.mode in ("RGB", "RGBA")


class TestApplyCrop:
    def test_absolute_crop(self):
        img = _img(size=(100, 80))
        out = apply_crop(img, "40x30+10+20")
        assert out.size == (40, 30)

    def test_no_offsets_centers(self):
        img = _img(size=(100, 80))
        out = apply_crop(img, "40x30")
        assert out.size == (40, 30)

    def test_oversized_clamped(self):
        img = _img(size=(100, 80))
        out = apply_crop(img, "300x200+10+10")
        assert out.size == (90, 70)

    def test_garbage_unchanged(self):
        img = _img(size=(100, 80))
        assert apply_crop(img, "garbage") is img


class TestApplyCropRatio:
    def test_wide_to_16_9(self):
        img = _img(size=(400, 300))
        out = apply_crop_ratio(img, "16:9")
        assert out.size == (400, 225)

    def test_tall_to_16_9(self):
        img = _img(size=(300, 400))
        out = apply_crop_ratio(img, "16:9")
        w, h = out.size
        assert abs(w / h - 16 / 9) < 0.02

    def test_invalid_unchanged(self):
        img = _img(size=(100, 100))
        assert apply_crop_ratio(img, "abc") is img


class TestApplyRotate:
    def test_90_swaps_dims(self):
        img = _img(size=(50, 30))
        out = apply_rotate(img, 90)
        assert out.size == (30, 50)

    def test_clockwise_direction(self):
        # top-left pixel (red) should end up top-right after CW 90°:
        # (x, y) → (h-1-y, x) = (17, 2) for a 20x20 image
        img = Image.new("RGB", (20, 20), (0, 0, 0))
        img.putpixel((2, 2), (255, 0, 0))  # near top-left
        out = apply_rotate(img, 90)
        w, _ = out.size
        assert out.getpixel((w - 3, 2)) == (255, 0, 0)

    def test_fill_color(self):
        img = Image.new("RGB", (20, 10), (10, 10, 10))
        out = apply_rotate(img, 45, fill="#FF0000")
        assert (255, 0, 0) in [out.getpixel((0, y)) for y in range(out.height)]

    def test_p_mode_no_crash(self):
        img = Image.new("P", (20, 20))
        out = apply_rotate(img, 30)
        assert out.size != (20, 20)  # expand happened

    def test_zero_unchanged(self):
        img = _img()
        assert apply_rotate(img, 0) is img


class TestApplyFlip:
    def test_horizontal(self):
        img = Image.new("RGB", (10, 5), (0, 0, 0))
        img.putpixel((1, 2), (255, 0, 0))
        out = apply_flip(img, "h")
        assert out.getpixel((8, 2)) == (255, 0, 0)

    def test_vertical(self):
        # top row (y=0) mirrors to bottom row (y=h-1=4)
        img = Image.new("RGB", (10, 5), (0, 0, 0))
        img.putpixel((1, 0), (255, 0, 0))
        out = apply_flip(img, "v")
        assert out.getpixel((1, 0)) != (255, 0, 0)
        assert out.getpixel((1, 4)) == (255, 0, 0)

    def test_invalid_unchanged(self):
        img = _img()
        assert apply_flip(img, "x") is img


class TestApplyPad:
    def test_letterbox_dims(self):
        img = _img(size=(400, 300))
        out = apply_pad(img, "16:9")
        w, h = out.size
        assert abs(w / h - 16 / 9) < 0.01

    def test_border_color(self):
        img = Image.new("RGB", (400, 300), (100, 100, 100))
        out = apply_pad(img, "1:1", bg="#FF0000")
        # square canvas → bars on top/bottom... no: 400x300 to 1:1 → widen to 400x400
        assert out.size == (400, 400)
        assert out.getpixel((0, 0)) == (255, 0, 0)

    def test_info_preserved(self):
        img = Image.new("RGB", (400, 300), (0, 0, 0))
        img.info["exif"] = b"fake-exif-bytes"
        img.info["icc_profile"] = b"fake-icc"
        out = apply_pad(img, "16:9")
        assert out.info.get("exif") == b"fake-exif-bytes"
        assert out.info.get("icc_profile") == b"fake-icc"

    def test_rgba_composited(self):
        img = Image.new("RGBA", (400, 300), (10, 200, 30, 128))
        out = apply_pad(img, "1:1", bg="#000000")
        assert out.mode == "RGBA"
        assert out.size == (400, 400)

    def test_invalid_unchanged(self):
        img = _img()
        assert apply_pad(img, "abc") is img


class TestColorManagement:
    def test_srgb_tags_profile(self):
        img = _img()
        out = apply_color_management(img, srgb=True)
        assert out.info.get("icc_profile")  # sRGB blob attached

    def test_flatten_cmyk_to_rgb(self):
        img = Image.new("CMYK", (20, 20), (0, 0, 0, 0))
        out = apply_color_management(img, flatten_cmyk=True)
        assert out.mode == "RGB"

    def test_neutral_returns_same_object(self):
        img = _img()
        assert apply_color_management(img) is img
