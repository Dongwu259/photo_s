"""Tests for bracketed-exposure HDR merge (exposure fusion via opencv)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

pytest.importorskip("cv2")
import numpy as np
from PIL import Image

from photo_s.hdr import merge_hdr


def _bracket(tmp_path, prefix="a", size=(64, 48), evs=(30, 128, 230)):
    """Three synthetic exposures of the same scene at different EV."""
    paths = []
    for i, v in enumerate(evs):
        arr = np.full((size[1], size[0], 3), v, dtype="uint8")
        # a gradient so Mertens has structure to weight
        arr[:, :, 0] = np.linspace(0, v, size[0], dtype="uint8")
        p = tmp_path / f"{prefix}{i}.jpg"
        Image.fromarray(arr).save(str(p))
        paths.append(str(p))
    return paths


class TestHdr:
    def test_merge_dims_and_mode(self, tmp_path):
        paths = _bracket(tmp_path)
        out = merge_hdr(paths)
        assert out.size == (64, 48)
        assert out.mode == "RGB"

    def test_merge_with_align(self, tmp_path):
        # Some OpenCV builds (Homebrew 5.x) have a broken AlignMTB binding;
        # the module raises a clear RuntimeError there — skip, don't fail.
        try:
            out = merge_hdr(_bracket(tmp_path), align=True)
        except RuntimeError as e:
            pytest.skip(f"AlignMTB broken in this OpenCV build: {e}")
        assert out.size == (64, 48)

    def test_needs_two_images(self, tmp_path):
        p = _bracket(tmp_path, evs=(128,))[0]
        with pytest.raises(ValueError):
            merge_hdr([p])

    def test_missing_file(self, tmp_path):
        p = _bracket(tmp_path)[0]
        with pytest.raises(ValueError):
            merge_hdr([p, str(tmp_path / "nope.jpg")])

    def test_missing_cv2_clear_error(self, tmp_path, monkeypatch):
        import builtins
        from photo_s import hdr as hdr_mod
        real = builtins.__import__

        def fake(name, *a, **k):
            if name == "cv2":
                raise ImportError("No module named 'cv2'")
            return real(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake)
        paths = _bracket(tmp_path)
        with pytest.raises(RuntimeError, match="enhance"):
            hdr_mod.merge_hdr(paths)
