"""Tests for photo_s.dedup — perceptual-hash duplicate detection."""

import os
import shutil
import sys

# Ensure src package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

from photo_s.dedup import find_duplicates, handle_duplicates


def _img(path, color=(120, 100, 80)):
    Image.new("RGB", (32, 32), color).save(str(path))


class TestFindDuplicatesSkipped:
    """Regression: files that cannot be opened/hashed (RAW, corrupt) were
    silently skipped — an all-skipped scan reported "未发现重复 no
    duplicates found", which read as "archive verified clean"."""

    def test_skipped_count_exposed(self, tmp_path):
        good = tmp_path / "a.png"
        _img(good)
        raw = tmp_path / "b.cr2"
        raw.write_bytes(b"not really a raw file")
        broken = tmp_path / "c.jpg"
        broken.write_bytes(b"junk")
        groups = find_duplicates([str(good), str(raw), str(broken)])
        assert groups == {}  # no duplicates among one readable image
        assert groups.skipped == 2

    def test_all_readable_skipped_zero(self, tmp_path):
        a = tmp_path / "a.png"
        b = tmp_path / "b.png"
        _img(a)
        _img(b)
        groups = find_duplicates([str(a), str(b)])
        assert groups.skipped == 0
        assert len(groups) == 1  # identical images → one duplicate group


class TestHandleDuplicatesMove:
    """Regression: action="move" used os.rename — a cross-device move died
    with OSError errno 18 (EXDEV) mid-batch, leaving a half-moved set.
    Now shutil.move + OSError → counted as failed, batch continues."""

    def test_move_failure_counted_not_fatal(self, tmp_path, monkeypatch):
        a = tmp_path / "a.png"
        b = tmp_path / "b.png"
        c = tmp_path / "c.png"
        for p in (a, b, c):
            _img(p)
        groups = {"h": [str(a), str(b), str(c)]}

        def _exdev(src, dst):
            raise OSError(18, "Invalid cross-device link")

        monkeypatch.setattr(shutil, "move", _exdev)
        res = handle_duplicates(groups, action="move")
        kept, removed = res  # 2-tuple unpacking contract unchanged
        assert (kept, removed) == (1, 0)
        assert res.failed == 2  # both dupes failed, no crash, no half-move
        assert b.exists() and c.exists()

    def test_move_success_still_counts_removed(self, tmp_path):
        a = tmp_path / "a.png"
        b = tmp_path / "b.png"
        _img(a)
        _img(b)
        res = handle_duplicates({"h": [str(a), str(b)]}, action="move")
        assert tuple(res) == (1, 1)
        assert res.failed == 0
        assert (tmp_path / "_duplicates" / "b.png").exists()
        assert not b.exists()
