"""Unit tests for watermark positioning functions."""

import sys
import os

# Ensure src package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

from photo_s.watermark import _get_position_xy


class TestGetPositionXY:
    """Tests for _get_position_xy() — calculates watermark anchor coordinates."""

    IMG_W, IMG_H = 1920, 1080
    WM_W, WM_H = 200, 50
    MARGIN = 20

    def _pos(self, position, margin=20):
        return _get_position_xy(self.IMG_W, self.IMG_H, self.WM_W, self.WM_H,
                                position, margin)

    def test_center(self):
        x, y = self._pos("CENTER")
        assert x == (1920 - 200) // 2  # 860
        assert y == (1080 - 50) // 2   # 515

    def test_top_left(self):
        x, y = self._pos("TOP_LEFT")
        assert x == 20
        assert y == 20

    def test_top_right(self):
        x, y = self._pos("TOP_RIGHT")
        assert x == 1920 - 200 - 20  # 1700
        assert y == 20

    def test_bottom_left(self):
        x, y = self._pos("BOTTOM_LEFT")
        assert x == 20
        assert y == 1080 - 50 - 20  # 1010

    def test_bottom_right(self):
        x, y = self._pos("BOTTOM_RIGHT")
        assert x == 1920 - 200 - 20  # 1700
        assert y == 1080 - 50 - 20  # 1010

    def test_top(self):
        x, y = self._pos("TOP")
        assert x == (1920 - 200) // 2
        assert y == 20

    def test_bottom(self):
        x, y = self._pos("BOTTOM")
        assert x == (1920 - 200) // 2
        assert y == 1080 - 50 - 20  # 1010

    def test_unknown_position_defaults_to_bottom_right(self):
        x, y = self._pos("INVALID")
        bx, by = self._pos("BOTTOM_RIGHT")
        assert x == bx
        assert y == by

    def test_custom_margin(self):
        x, y = _get_position_xy(1920, 1080, 200, 50, "TOP_LEFT", margin=50)
        assert x == 50
        assert y == 50


class TestPositionCaseInsensitive:
    """Regression: lowercase position silently landed in the wrong corner."""

    def test_lowercase_top_left(self):
        assert _get_position_xy(400, 400, 20, 20, "top_left") == (20, 20)

    def test_lowercase_bottom_right(self):
        assert _get_position_xy(400, 400, 20, 20, "bottom_right") == \
            (400 - 20 - 20, 400 - 20 - 20)

    def test_unknown_falls_back(self):
        assert _get_position_xy(400, 400, 20, 20, "wibble") == \
            (400 - 20 - 20, 400 - 20 - 20)


class TestImageWatermarkScaleGuard:
    """Regression: scale <= 0 crashed Pillow resize (0-size target)."""

    def test_scale_zero_no_crash(self, tmp_path):
        from photo_s.watermark import apply_image_watermark
        logo = tmp_path / "logo.png"
        Image.new("RGBA", (32, 32), (255, 0, 0, 255)).save(logo)
        im = Image.new("RGB", (100, 100), (0, 0, 0))
        out = apply_image_watermark(im, str(logo), scale=0)
        assert out is im or out.mode == "RGBA"
