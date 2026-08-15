"""Tests for the keeper workflow: sort rated photos into selects/rejects.

Covers the dual-threshold rule (rating >= keep_min → keep, <= reject_max →
reject, else in place), move/copy modes, dry-run zero-write guarantee,
path-flattening safety, and threshold validation.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from photo_s.engine import apply_exif_tags
from photo_s.select import select_files

pytest.importorskip("piexif")

from PIL import Image


def _img(path, color=(120, 100, 80)):
    Image.new("RGB", (32, 24), color).save(str(path), quality=95)
    return str(path)


def _rate(path, rating):
    apply_exif_tags(path, {"rating": rating})


class TestSelect:
    def test_dual_threshold_classification(self, tmp_path):
        keep = _img(tmp_path / "keep.jpg")
        mid = _img(tmp_path / "mid.jpg")
        rej = _img(tmp_path / "rej.jpg")
        unrated = _img(tmp_path / "unrated.jpg")
        _rate(keep, 5)
        _rate(mid, 3)
        _rate(rej, 1)
        rows = select_files([keep, mid, rej, unrated],
                            selects_dir=str(tmp_path / "sel"),
                            rejects_dir=str(tmp_path / "rej2"),
                            dry_run=True)
        by = {os.path.basename(r["path"]): r for r in rows}
        assert by["keep.jpg"]["status"] == "keep"
        assert by["mid.jpg"]["status"] == "skip"      # 3-star stays in place
        assert by["rej.jpg"]["status"] == "reject"
        assert by["unrated.jpg"]["status"] == "skip"  # unrated stays in place

    def test_adjustable_thresholds(self, tmp_path):
        a = _img(tmp_path / "a.jpg")
        b = _img(tmp_path / "b.jpg")
        _rate(a, 3)
        _rate(b, 2)
        rows = select_files([a, b], keep_min=3, reject_max=1,
                            selects_dir=str(tmp_path / "sel"),
                            dry_run=True)
        by = {os.path.basename(r["path"]): r for r in rows}
        assert by["a.jpg"]["status"] == "keep"   # 3 now counts as keeper
        assert by["b.jpg"]["status"] == "skip"   # 2 > reject_max(1)

    def test_move_removes_source(self, tmp_path):
        a = _img(tmp_path / "a.jpg")
        _rate(a, 4)
        sel = tmp_path / "sel"
        rows = select_files([a], selects_dir=str(sel))
        assert rows[0]["action"] == "move"
        assert rows[0]["ok"] is True
        assert os.path.isfile(str(sel / "a.jpg"))
        assert not os.path.exists(a)  # moved, not copied

    def test_copy_preserves_source(self, tmp_path):
        a = _img(tmp_path / "a.jpg")
        _rate(a, 4)
        sel = tmp_path / "sel"
        rows = select_files([a], selects_dir=str(sel), mode="copy")
        assert rows[0]["action"] == "copy"
        assert os.path.isfile(str(sel / "a.jpg"))
        assert os.path.isfile(a)  # original kept

    def test_dry_run_zero_writes(self, tmp_path):
        a = _img(tmp_path / "a.jpg")
        _rate(a, 5)
        sel = tmp_path / "sel"
        rej = tmp_path / "rej"
        before = {str(f): os.path.getsize(f) for f in tmp_path.iterdir()}
        rows = select_files([a], selects_dir=str(sel), rejects_dir=str(rej),
                            dry_run=True)
        assert rows[0]["action"] == "would_move"
        assert rows[0]["dest"].endswith("a.jpg")
        # nothing created, nothing changed
        assert not sel.exists() and not rej.exists()
        after = {str(f): os.path.getsize(f) for f in tmp_path.iterdir()}
        assert after == before

    def test_basename_flattened_no_traversal(self, tmp_path):
        # a hostile EXIF value can't escape: dest is basename-only
        a = _img(tmp_path / "a.jpg")
        _rate(a, 5)
        sel = tmp_path / "sel"
        rows = select_files([a], selects_dir=str(sel / ".." / "sel"))
        dest = rows[0]["dest"]
        assert os.path.basename(dest) == "a.jpg"
        assert os.path.abspath(dest).startswith(
            os.path.abspath(str(sel / ".." / "sel")))

    def test_keep_min_le_reject_max_rejected(self, tmp_path):
        a = _img(tmp_path / "a.jpg")
        with pytest.raises(ValueError):
            select_files([a], keep_min=2, reject_max=3)

    def test_unrated_and_unreadable_are_skip(self, tmp_path):
        a = _img(tmp_path / "a.jpg")          # no rating
        missing = str(tmp_path / "nope.jpg")  # doesn't exist
        rows = select_files([a, missing], selects_dir=str(tmp_path / "sel"),
                            dry_run=True)
        assert all(r["status"] == "skip" for r in rows)

    def test_progress_callback(self, tmp_path):
        a = _img(tmp_path / "a.jpg")
        b = _img(tmp_path / "b.jpg")
        _rate(a, 4)
        calls = []
        select_files([a, b], selects_dir=str(tmp_path / "sel"),
                     progress_callback=lambda c, t, p: calls.append((c, t)))
        assert calls == [(1, 2), (2, 2)]
