"""Tests for photo_s.contact — contact sheet montage."""

import math
import os
import sys

# Ensure src package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

from photo_s.contact import build_contact_sheet


def _make_images(tmp_path, count=5):
    paths = []
    for i in range(count):
        p = tmp_path / f"img_{i}.jpg"
        Image.new("RGB", (60, 40), (i * 40, 100, 200)).save(p)
        paths.append(str(p))
    return paths


class TestBuildContactSheet:
    def test_grid_dims(self, tmp_path):
        paths = _make_images(tmp_path, count=5)
        out = str(tmp_path / "sheet.png")
        build_contact_sheet(paths, out, cols=2, thumb_size=(240, 240),
                            captions=False, padding=8)
        with Image.open(out) as img:
            # 5 images, 2 cols → 3 rows; cell = 240+16 wide, 240+16 tall
            assert img.size == (2 * 256, 3 * 256)

    def test_caption_adds_height(self, tmp_path):
        paths = _make_images(tmp_path, count=2)
        out = str(tmp_path / "capped.png")
        build_contact_sheet(paths, out, cols=1, thumb_size=(100, 100),
                            captions=True, padding=0)
        from photo_s.contact import CAPTION_H
        with Image.open(out) as img:
            assert img.size == (100, 2 * (100 + CAPTION_H))

    def test_output_exists_and_parses(self, tmp_path):
        paths = _make_images(tmp_path, count=3)
        out = str(tmp_path / "sheet.jpg")
        result = build_contact_sheet(paths, out, cols=3)
        assert os.path.isfile(result)
        with Image.open(result) as img:
            img.verify()

    def test_empty_input_creates_blank_sheet(self, tmp_path):
        out = str(tmp_path / "empty.png")
        build_contact_sheet([], out, cols=2, captions=False)
        with Image.open(out) as img:
            assert img.size == (2 * 256, 1 * 256)

    def test_unreadable_file_placeholder(self, tmp_path):
        paths = _make_images(tmp_path, count=1)
        bad = tmp_path / "bad.jpg"
        bad.write_bytes(b"not an image")
        out = str(tmp_path / "mixed.png")
        build_contact_sheet(paths + [str(bad)], out, cols=2)
        assert os.path.isfile(out)
