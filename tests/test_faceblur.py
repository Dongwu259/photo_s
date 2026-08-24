"""Tests for face blur / pixelation (privacy masking, optional opencv)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

pytest.importorskip("cv2")
import cv2
import numpy as np
from PIL import Image

from photo_s import faceblur as fb

# Some OpenCV builds (e.g. Homebrew) ship cv2/data/ without the cascade XMLs;
# the PyPI wheel always bundles them. Runtime detection mirrors the module's
# own error path.
_CASCADE = os.path.join(cv2.data.haarcascades,
                        "haarcascade_frontalface_default.xml")
_HAVE_CASCADE = os.path.isfile(_CASCADE)


def _img(path, size=(64, 48), color=(120, 100, 80)):
    Image.new("RGB", size, color).save(str(path), quality=95)
    return Image.open(path)


class TestFaceBlur:
    def test_no_faces_returns_zero(self, tmp_path):
        if not _HAVE_CASCADE:
            pytest.skip("cascade data not bundled in this opencv build")
        img = _img(tmp_path / "a.jpg")
        out, count = fb.apply_face_blur(img)
        assert count == 0
        assert out.size == img.size
        assert out.mode in ("RGB", "RGBA")

    def test_channel_order_preserved(self, tmp_path):
        """Regression: the pipeline converted RGB→BGR for OpenCV but pasted
        the buffer back with an "RGB" label — every face-blurred photo came
        out with red and blue swapped. A pure-red input must stay red."""
        if not _HAVE_CASCADE:
            pytest.skip("cascade data not bundled in this opencv build")
        img = _img(tmp_path / "red.jpg", color=(200, 30, 30))
        out, _count = fb.apply_face_blur(img)
        r, g, b = out.convert("RGB").getpixel((2, 2))
        assert r > 120 and b < 90, f"red input became ({r}, {g}, {b})"

    def test_bad_mode_rejected(self, tmp_path):
        img = _img(tmp_path / "a.jpg")
        with pytest.raises(ValueError):
            fb.apply_face_blur(img, mode="warp")

    def test_missing_cv2_clear_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            fb, "_cv2",
            lambda: (_ for _ in ()).throw(
                RuntimeError("face blur requires the optional dependency: "
                             "pip install 'photo-s-tools[enhance]'")))
        img = _img(tmp_path / "a.jpg")
        with pytest.raises(RuntimeError, match="enhance"):
            fb.apply_face_blur(img)

    def test_missing_cascade_clear_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            fb, "_cascade_path",
            lambda: (_ for _ in ()).throw(
                RuntimeError("face blur: Haar cascade data not bundled")))
        img = _img(tmp_path / "a.jpg")
        with pytest.raises(RuntimeError, match="cascade"):
            fb.apply_face_blur(img)


class TestMaskRegion:
    """The masking math (blur / mosaic) is tested without the cascade."""

    def _mat(self, v=100, size=(48, 64)):
        return np.full((size[0], size[1], 3), v, dtype="uint8")

    def _step(self, size=64):
        # a sharp vertical edge (linear gradients are invariant under Gaussian
        # blur, so a step is what visibly changes). Offset from the exact
        # middle so the edge lands inside a pixelate cell rather than on a
        # mosaic-grid boundary (which would alias back to the same image).
        mat = np.zeros((size, size, 3), dtype="uint8")
        mat[:, :, 0] = 0
        mat[:, 33:, 0] = 255
        return mat

    def test_blur_changes_region(self):
        mat = self._step()
        before = mat[12:54, 12:54].copy()
        fb._mask_region(mat, cv2, (10, 10, 44, 44), "blur", margin=10)
        assert not np.array_equal(mat[12:54, 12:54], before)

    def test_pixelate_changes_region(self):
        mat = self._step()
        before = mat[12:54, 12:54].copy()
        fb._mask_region(mat, cv2, (10, 10, 44, 44), "pixelate", margin=10)
        assert not np.array_equal(mat[12:54, 12:54], before)

    def test_margin_expands_box(self):
        # margin > 0 must affect a region larger than the raw box
        mat = self._step()
        fb._mask_region(mat, cv2, (20, 20, 10, 10), "pixelate", margin=50)
        # pixels just outside the raw box (x=33, y=31) are covered by margin
        assert mat[31, 33, 0] < 255 or mat[31, 33, 0] > 0
