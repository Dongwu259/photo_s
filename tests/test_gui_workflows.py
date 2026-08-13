"""GUI workflow tests: review / dedup / gallery dialogs.

The sync compute helpers (_review_scan / _review_save / _dedup_scan /
_dedup_move_to_trash / _gallery_build) are exercised directly; the
dialogs themselves get smoke tests on a real display (skipped headless).
No test clicks buttons that spawn work, and nothing can hang: daemon
threads are drained with a bounded root.update() poll.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


def _make_app():
    import tkinter as tk
    from photo_s.gui import PhotoSApp
    try:
        root = tk.Tk()
    except Exception as e:
        pytest.skip("no display: {}".format(e))
    app = PhotoSApp(root)
    root.update_idletasks()
    return root, app


def _img(path, seed=1, size=(64, 48)):
    """Noise image from a seed. Identical seeds are pixel-identical
    (duplicates); different seeds have distinct perceptual hashes.
    (Flat-color images are useless for dedup tests: every flat color
    dhashes to the same all-zero hash.)"""
    import numpy as np
    from PIL import Image
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 256, (size[1], size[0], 3), dtype=np.uint8)
    Image.fromarray(arr).save(str(path), quality=95)
    return str(path)


def _find_text(widget, needle, max_depth=6):
    """True if any descendant Label/Text contains ``needle`` (bounded walk)."""
    import tkinter as tk

    def walk(w, depth):
        if depth < 0:
            return False
        for c in w.winfo_children():
            try:
                if isinstance(c, tk.Label) and needle in str(c.cget("text")):
                    return True
                if isinstance(c, tk.Text) and needle in c.get("1.0", "end"):
                    return True
            except Exception:
                pass
            if walk(c, depth - 1):
                return True
        return False

    return walk(widget, max_depth)


class TestReviewHelpers:
    def test_review_scan_reads_meta(self, tmp_path):
        pytest.importorskip("piexif")
        from photo_s.engine import apply_exif_tags
        root, app = _make_app()
        a = _img(tmp_path / "a.jpg")
        apply_exif_tags(a, {"rating": 4, "keywords": "beach,trip",
                            "title": "Summer"})
        meta = app._review_scan([a])
        assert meta[a]["rating"] == 4
        assert meta[a]["keywords"] == ["beach", "trip"]
        assert meta[a]["title"] == "Summer"
        root.destroy()

    def test_review_save_roundtrip_jpeg(self, tmp_path):
        pytest.importorskip("piexif")
        from photo_s.engine import read_exif_metadata
        root, app = _make_app()
        p = _img(tmp_path / "a.jpg")
        ok, msg = app._review_save(p, rating=4, keywords="portrait,night",
                                   title="T1")
        assert ok, msg
        m = read_exif_metadata(p)
        assert m["rating"] == 4
        assert m["keywords"] == ["portrait", "night"]
        assert m["title"] == "T1"
        # an unchanged second save must be a no-op
        ok2, msg2 = app._review_save(p, rating=4, keywords="portrait,night",
                                     title="T1")
        assert ok2 and msg2 == ""
        root.destroy()

    def test_review_save_partial_preserves_other_tags(self, tmp_path):
        pytest.importorskip("piexif")
        from photo_s.engine import read_exif_metadata
        root, app = _make_app()
        p = _img(tmp_path / "a.jpg")
        ok, _ = app._review_save(p, rating=4, keywords="beach",
                                 title="Summer")
        assert ok
        # rating-only update must keep keywords + title intact
        ok2, _ = app._review_save(p, rating=5, keywords="beach",
                                  title="Summer")
        assert ok2
        m = read_exif_metadata(p)
        assert m["rating"] == 5
        assert m["keywords"] == ["beach"]
        assert m["title"] == "Summer"
        root.destroy()

    def test_review_save_png_error_caught(self, tmp_path):
        pytest.importorskip("piexif")
        root, app = _make_app()
        p = _img(tmp_path / "a.png")
        ok, msg = app._review_save(p, rating=3, keywords="x", title=None)
        assert not ok, "PNG has no EXIF container — save must fail cleanly"
        assert msg
        root.destroy()

    def test_review_save_piexif_missing_message(self, tmp_path, monkeypatch):
        import photo_s.engine as engine_mod
        monkeypatch.setattr(engine_mod, "_HAS_PIEXIF", False)
        root, app = _make_app()
        p = _img(tmp_path / "a.jpg")
        ok, msg = app._review_save(p, rating=3, keywords="x", title=None)
        assert not ok and "piexif" in msg
        root.destroy()


class TestDedupHelpers:
    def test_dedup_scan_groups_and_scores(self, tmp_path):
        root, app = _make_app()
        a = _img(tmp_path / "a.jpg")
        b = _img(tmp_path / "b.jpg")           # identical pixels
        c = _img(tmp_path / "c.jpg", seed=2)
        groups, scores = app._dedup_scan([a, b, c])
        assert len(groups) == 1
        assert sorted(groups[0]) == sorted([a, b])
        assert set(scores) == {a, b}
        for p in (a, b):
            assert isinstance(scores[p], float)
        root.destroy()

    def test_dedup_scan_no_duplicates(self, tmp_path):
        root, app = _make_app()
        a = _img(tmp_path / "a.jpg")
        b = _img(tmp_path / "b.jpg", seed=2)
        groups, scores = app._dedup_scan([a, b])
        assert groups == [] and scores == {}
        root.destroy()

    def test_dedup_move_collision_suffix(self, tmp_path):
        root, app = _make_app()
        a = _img(tmp_path / "a.jpg")
        trash = tmp_path / "_duplicates_trash"
        trash.mkdir()
        (trash / "a.jpg").write_bytes(b"existing")
        moved, failed = app._dedup_move_to_trash([a], str(trash))
        assert (moved, failed) == (1, 0)
        assert not os.path.exists(a)
        assert os.path.exists(trash / "a.jpg")      # pre-existing kept
        assert os.path.exists(trash / "a_1.jpg")    # moved with suffix
        root.destroy()

    def test_dedup_move_updates_file_list(self, tmp_path):
        root, app = _make_app()
        a = _img(tmp_path / "a.jpg")
        b = _img(tmp_path / "b.jpg")
        app.files = [a, b]
        app._refresh_file_list()
        trash = tmp_path / "_duplicates_trash"
        moved, failed = app._dedup_move_to_trash([b], str(trash))
        assert (moved, failed) == (1, 0)
        app.files = [f for f in app.files if os.path.exists(f)]
        app._refresh_file_list()
        assert app.files == [a]
        assert app.file_tree.get_children() == (a,)
        root.destroy()


class TestGalleryHelper:
    def test_gallery_build_sync(self, tmp_path):
        root, app = _make_app()
        a = _img(tmp_path / "a.jpg")
        b = _img(tmp_path / "b.jpg", seed=2)
        out = tmp_path / "gal"
        res = app._gallery_build([a, b], str(out), title="T", thumb_size=240)
        assert res["count"] == 2
        assert os.path.isfile(res["output"])
        assert os.path.isfile(out / "thumbs" / "1.jpg")
        root.destroy()


class TestDialogSmokes:
    def _poll(self, root, pred, seconds=5.0):
        deadline = time.time() + seconds
        while time.time() < deadline:
            root.update()
            if pred():
                return True
            time.sleep(0.05)
        return False

    def test_review_dialog_smoke(self, tmp_path):
        import tkinter as tk
        root, app = _make_app()
        a = _img(tmp_path / "a.jpg")
        app.files = [a]
        app._refresh_file_list()
        app._show_review()
        win = [w for w in root.winfo_children()
               if isinstance(w, tk.Toplevel)][0]
        # wait for the metadata scan to finish and render "1 / 1"
        assert self._poll(root, lambda: _find_text(win, "1 / 1")), \
            "review dialog must render position 1 / 1 after the scan"
        root.destroy()

    def test_dedup_dialog_smoke(self, tmp_path):
        import tkinter as tk
        root, app = _make_app()
        a = _img(tmp_path / "a.jpg")
        b = _img(tmp_path / "b.jpg")           # duplicate of a
        app.files = [a, b]
        app._refresh_file_list()
        app._show_dedup()
        win = [w for w in root.winfo_children()
               if isinstance(w, tk.Toplevel)][0]
        assert self._poll(root, lambda: _find_text(win, "第 1 组")), \
            "dedup dialog must render group 1 after the scan"
        root.destroy()

    def test_gallery_dialog_smoke(self, tmp_path):
        import tkinter as tk
        root, app = _make_app()
        a = _img(tmp_path / "a.jpg")
        app.files = [a]
        app._refresh_file_list()
        app._show_gallery_export()
        win = [w for w in root.winfo_children()
               if isinstance(w, tk.Toplevel)][0]
        assert app._t("gallery_title") in win.title()
        root.destroy()  # destroy without generating (no worker thread)

    def test_summary_dialog_shows_errors(self):
        import tkinter as tk
        from photo_s.engine import BatchResult, ProcessResult
        root, app = _make_app()
        r = ProcessResult(
            input_path="/tmp/bad.jpg", output_path="",
            input_size=100, output_size=0,
            input_format="JPEG", output_format="JPEG",
            input_dims=(10, 10), output_dims=(0, 0),
            success=False, error="boom: broken file")
        res = BatchResult(results=[r], total_input_size=100,
                          total_output_size=0, success_count=0,
                          fail_count=1)
        app._show_summary(res)
        win = [w for w in root.winfo_children()
               if isinstance(w, tk.Toplevel)][0]
        assert _find_text(win, "boom: broken file"), \
            "summary dialog must show per-file errors"
        root.destroy()


class TestProcessingLockout:
    def test_workflow_buttons_state_during_processing(self):
        root, app = _make_app()
        app._toggle_settings(False)
        assert app.review_btn.cget("state") == "disabled"
        assert app.dedup_btn.cget("state") == "disabled"
        assert app.gallery_btn.cget("state") == "normal", \
            "gallery export is read-only and must stay enabled"
        app._toggle_settings(True)
        assert app.review_btn.cget("state") == "normal"
        root.destroy()
