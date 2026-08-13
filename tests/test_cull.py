"""Tests for photo_s.cull — exposure/sharpness classification.

Shared by the CLI `cull` command, the REST surface, and the GUI cull dialog.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PIL import Image

from photo_s.cull import cull_files


def _img(path, color=None, noise=False, size=(64, 64)):
    if noise:
        import numpy as np
        rng = np.random.default_rng(7)
        arr = rng.integers(0, 256, (size[1], size[0], 3), dtype=np.uint8)
        Image.fromarray(arr).save(str(path), quality=95)
    else:
        Image.new("RGB", size, color).save(str(path), quality=95)
    return str(path)


class TestCull:
    def test_all_kept_no_thresholds(self, tmp_path):
        files = [_img(tmp_path / f"n{i}.png", color=(90, 90, 90))
                 for i in range(3)]
        results = cull_files(files)
        assert all(r["kept"] for r in results)
        assert all(r["ok"] for r in results)
        # blur_score only present when sharpness_min is set
        assert all("blur_score" not in r for r in results)

    def test_overexposed_filter(self, tmp_path):
        white = _img(tmp_path / "w.png", color=(255, 255, 255))
        gray = _img(tmp_path / "g.png", color=(90, 90, 90))
        results = cull_files([white, gray], overexposed_max=10)
        by = {os.path.basename(r["path"]): r for r in results}
        assert by["w.png"]["overexposed_pct"] == 100.0
        assert by["w.png"]["kept"] is False
        assert by["g.png"]["kept"] is True

    def test_underexposed_filter(self, tmp_path):
        black = _img(tmp_path / "b.png", color=(0, 0, 0))
        gray = _img(tmp_path / "g.png", color=(90, 90, 90))
        results = cull_files([black, gray], underexposed_max=10)
        by = {os.path.basename(r["path"]): r for r in results}
        assert by["b.png"]["kept"] is False
        assert by["g.png"]["kept"] is True

    def test_luminance_bounds(self, tmp_path):
        dark = _img(tmp_path / "d.png", color=(30, 30, 30))
        bright = _img(tmp_path / "br.png", color=(220, 220, 220))
        hi = cull_files([dark, bright], luminance_min=0.8)
        by = {os.path.basename(r["path"]): r for r in hi}
        assert by["br.png"]["kept"] is True
        assert by["d.png"]["kept"] is False
        lo = cull_files([dark, bright], luminance_max=0.2)
        by = {os.path.basename(r["path"]): r for r in lo}
        assert by["d.png"]["kept"] is True
        assert by["br.png"]["kept"] is False

    def test_sharpness_filter(self, tmp_path):
        sharp = _img(tmp_path / "s.png", noise=True)
        flat = _img(tmp_path / "f.png", color=(100, 100, 100))
        results = cull_files([sharp, flat], sharpness_min=10)
        by = {os.path.basename(r["path"]): r for r in results}
        assert "blur_score" in by["s.png"]
        assert by["s.png"]["kept"] is True, \
            "noise has high Laplacian variance → sharp"
        assert by["f.png"]["kept"] is False

    def test_unreadable_kept_false(self, tmp_path):
        bad = tmp_path / "corrupt.jpg"
        bad.write_bytes(b"not an image")
        results = cull_files([str(bad)])
        assert results[0]["ok"] is False
        assert results[0]["kept"] is False

    def test_progress_callback(self, tmp_path):
        files = [_img(tmp_path / f"n{i}.png", color=(90, 90, 90))
                 for i in range(4)]
        calls = []
        cull_files(files, progress_callback=lambda c, t: calls.append((c, t)))
        assert calls == [(1, 4), (2, 4), (3, 4), (4, 4)]

    def test_empty_input(self, tmp_path):
        assert cull_files([]) == []
