"""Tests for photo_s.gallery — HTML gallery generation."""

import ntpath
import os
import sys

# Ensure src package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

from photo_s.gallery import build_gallery


def _img(path):
    Image.new("RGB", (32, 32), (10, 20, 30)).save(str(path))


class TestBuildGallery:
    def test_basic_gallery(self, tmp_path):
        src = tmp_path / "a.jpg"
        _img(src)
        out = tmp_path / "gallery"
        res = build_gallery([str(src)], str(out))
        assert res["count"] == 1
        html_text = (out / "index.html").read_text(encoding="utf-8")
        assert "thumbs/1.jpg" in html_text

    def test_cross_drive_relpath_falls_back(self, tmp_path, monkeypatch):
        """Regression: on Windows, os.path.relpath(src, out) raises
        ValueError when src and out live on different drives, killing the
        whole build halfway. Must fall back to an absolute file:// link."""
        src = tmp_path / "a.jpg"
        _img(src)

        def _cross_drive_relpath(path, start):
            # ntpath models the Windows failure: no relative path between
            # two different drive letters.
            return ntpath.relpath(r"D:\photos\a.jpg", r"C:\gallery")

        monkeypatch.setattr(os.path, "relpath", _cross_drive_relpath)
        out = tmp_path / "gallery"
        res = build_gallery([str(src)], str(out))
        assert res["count"] == 1
        html_text = (out / "index.html").read_text(encoding="utf-8")
        assert 'href="file://' in html_text
