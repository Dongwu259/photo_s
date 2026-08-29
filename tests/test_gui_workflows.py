"""GUI workflow tests: review / dedup / gallery dialogs.

The sync compute helpers (_review_scan / _review_save / _dedup_scan /
_dedup_move_to_trash / _gallery_build) are exercised directly; the
dialogs themselves get smoke tests on a real display (skipped headless).
No test clicks buttons that spawn work, and nothing can hang: daemon
threads are drained with a bounded root.update() poll.
"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path, monkeypatch):
    """Hermetic gui_state: the app restores geometry/thumb-size/active
    module from ~/.photos/gui_state.json — a polluted real file once
    flipped the startup module, made the Develop panel auto-render in
    unrelated tests (its lazy tempdir then tripped other files'
    mkdtemp-tracking assertions) and leaked live Tk roots that cascaded
    into focus-event storms on later tests."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))



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
        ok, msg, _, _ = app._review_save(p, rating=4, keywords="portrait,night",
                                   title="T1")
        assert ok, msg
        m = read_exif_metadata(p)
        assert m["rating"] == 4
        assert m["keywords"] == ["portrait", "night"]
        assert m["title"] == "T1"
        # an unchanged second save must be a no-op
        ok2, msg2, _, _ = app._review_save(p, rating=4, keywords="portrait,night",
                                     title="T1")
        assert ok2 and msg2 == ""
        root.destroy()

    def test_review_save_partial_preserves_other_tags(self, tmp_path):
        pytest.importorskip("piexif")
        from photo_s.engine import read_exif_metadata
        root, app = _make_app()
        p = _img(tmp_path / "a.jpg")
        ok, _, _, _ = app._review_save(p, rating=4, keywords="beach",
                                 title="Summer")
        assert ok
        # rating-only update must keep keywords + title intact
        ok2, _, _, _ = app._review_save(p, rating=5, keywords="beach",
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
        ok, msg, _, _ = app._review_save(p, rating=3, keywords="x", title=None)
        assert not ok, "PNG has no EXIF container — save must fail cleanly"
        assert msg
        root.destroy()

    def test_review_save_piexif_missing_message(self, tmp_path, monkeypatch):
        import photo_s.engine as engine_mod
        monkeypatch.setattr(engine_mod, "_HAS_PIEXIF", False)
        root, app = _make_app()
        p = _img(tmp_path / "a.jpg")
        ok, msg, _, _ = app._review_save(p, rating=3, keywords="x", title=None)
        assert not ok and "piexif" in msg
        root.destroy()


class TestReviewExifEditor:
    """Camera/lens/shooting-field editing via _review_save: diff-only
    writes, aperture→fnumber / date→datetime mapping, undo restore."""

    def _fixed_meta(self, **over):
        m = {"rating": None, "keywords": [], "title": "", "caption": "",
             "date": "", "time": "", "camera": "", "make": "", "iso": "",
             "focal": "", "lens": "", "fnumber": "", "shutter": ""}
        m.update(over)
        return m

    def _capture_engine(self, monkeypatch, meta):
        """Monkeypatch the engine: fixed metadata read + tag-dict capture."""
        import photo_s.engine as engine_mod
        monkeypatch.setattr(engine_mod, "read_exif_metadata",
                            lambda path: meta)
        calls = []
        monkeypatch.setattr(engine_mod, "apply_exif_tags",
                            lambda path, tags: calls.append(tags) or "ok")
        return calls

    def test_new_fields_mapped_into_tags(self, tmp_path, monkeypatch):
        root, app = _make_app()
        p = _img(tmp_path / "a.jpg")
        calls = self._capture_engine(monkeypatch, self._fixed_meta())
        ok, msg, revert, entry = app._review_save(
            p, make="Canon", model="EOS R5", lens="RF50mm F1.2L",
            iso="400", shutter="1/250", aperture="2.8",
            date="2024:01:02 03:04:05")
        assert ok
        assert calls == [{"make": "Canon", "model": "EOS R5",
                          "lens": "RF50mm F1.2L", "iso": "400",
                          "shutter": "1/250", "fnumber": "2.8",
                          "datetime": "2024:01:02 03:04:05"}], \
            "aperture→fnumber and date→datetime, nothing else"
        assert revert is not None and entry is not None
        root.destroy()

    def test_none_and_unchanged_fields_not_written(self, tmp_path,
                                                   monkeypatch):
        root, app = _make_app()
        p = _img(tmp_path / "a.jpg")
        calls = self._capture_engine(
            monkeypatch,
            self._fixed_meta(make="Canon", iso="400",
                             date="2024-01-02", time="03-04-05"))
        # identical values (int iso included) and None args → no write
        ok, msg, _, _ = app._review_save(
            p, make="Canon", iso=400, date="2024:01:02 03:04:05",
            lens=None, shutter=None, aperture=None, model=None)
        assert ok and msg == "" and calls == [], \
            "no diff → engine must not be called at all"
        # clearing a field that has a value IS a write
        ok2, _, _, _ = app._review_save(p, make="")
        assert ok2 and calls == [{"make": ""}]
        root.destroy()

    def test_revert_restores_old_values(self, tmp_path, monkeypatch):
        root, app = _make_app()
        p = _img(tmp_path / "a.jpg")
        calls = self._capture_engine(
            monkeypatch,
            self._fixed_meta(make="Nikon", camera="Z6", lens="24-70",
                             iso="100", shutter="1/60", fnumber="4.0",
                             date="2023-05-06", time="07-08-09"))
        ok, _, revert, _ = app._review_save(
            p, make="Sony", iso="800", aperture="1.8",
            date="2025:11:12 13:14:15")
        assert ok and revert is not None
        assert calls[0] == {"make": "Sony", "iso": "800",
                            "fnumber": "1.8",
                            "datetime": "2025:11:12 13:14:15"}
        revert()
        assert calls[1] == {"rating": None, "keywords": "", "title": "",
                            "make": "Nikon", "iso": "100",
                            "fnumber": "4.0",
                            "datetime": "2023:05:06 07:08:09"}, \
            "revert writes the pre-save values back (plus the usual " \
            "rating/keywords/title full restore); untouched fields " \
            "(lens/shutter) stay out of both writes"
        root.destroy()

    def test_exif_fields_roundtrip_jpeg(self, tmp_path):
        pytest.importorskip("piexif")
        from photo_s.engine import read_exif_metadata
        root, app = _make_app()
        p = _img(tmp_path / "a.jpg")
        ok, msg, _, _ = app._review_save(
            p, make="Canon", model="EOS R5", lens="RF50mm F12L",
            iso="400", shutter="1/250", aperture="2.8",
            date="2024:01:02 03:04:05")
        assert ok, msg
        m = read_exif_metadata(p)
        assert m["make"] == "Canon"
        assert m["camera"] == "EOS R5"
        assert m["lens"] == "RF50mm F12L"
        assert m["iso"] == "400"
        assert m["shutter"] == "1/250"
        assert m["fnumber"] == "2.8"
        assert m["date"] == "2024-01-02"
        # undo restores the empty pre-edit state
        app._undo()
        m2 = read_exif_metadata(p)
        assert m2["make"] == "" and m2["lens"] == "" \
            and m2["iso"] == "" and m2["fnumber"] == "" \
            and m2["shutter"] == "" and m2["date"] == ""
        root.destroy()

    def test_review_scan_fallback_meta_has_new_keys(self, tmp_path,
                                                    monkeypatch):
        import photo_s.engine as engine_mod
        root, app = _make_app()

        def boom(path):
            raise RuntimeError("unreadable")
        monkeypatch.setattr(engine_mod, "read_exif_metadata", boom)
        meta = app._review_scan(["/nonexistent.jpg"])
        m = meta["/nonexistent.jpg"]
        for key in ("make", "camera", "lens", "iso", "shutter",
                    "fnumber", "date", "time"):
            assert key in m, "fallback meta must carry " + key
        root.destroy()

    def test_review_dialog_shooting_fields_smoke(self, tmp_path):
        """Real-Tk smoke: the shooting-info editor renders and fills
        from the scanned metadata."""
        pytest.importorskip("piexif")
        import tkinter as tk
        from tkinter import ttk
        from photo_s.engine import apply_exif_tags
        root, app = _make_app()
        a = _img(tmp_path / "a.jpg")
        apply_exif_tags(a, {"make": "Canon", "iso": "400"})
        app.files = [a]
        app._checked = {a}
        app._refresh_file_list()
        app._show_review()
        win = [w for w in root.winfo_children()
               if isinstance(w, tk.Toplevel)][0]

        def values():
            out = []

            def walk(w, depth=8):
                if depth < 0:
                    return
                for c in w.winfo_children():
                    if isinstance(c, ttk.Entry):
                        try:
                            out.append(c.get())
                        except Exception:
                            pass
                    walk(c, depth - 1)

            walk(win)
            return out

        # Poll the FILLED entries, not the "1 / 1" position text — the
        # position may render before the metadata scan lands (a real race
        # on slow Windows CI, where the old poll passed immediately and the
        # subsequent walk saw empty entries).
        assert _poll(root, lambda: "Canon" in values()
                     and "400" in values()), \
            "make/ISO entries must be filled from the image metadata"
        assert _find_text(win, app._t("review_shooting")), \
            "shooting-info section label must render"
        root.destroy()


def _poll(root, pred, seconds=20.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        root.update()
        if pred():
            return True
        time.sleep(0.05)
    return False


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
        moved, failed, moved_map = app._dedup_move_to_trash([a], str(trash))
        assert (moved, failed) == (1, 0)
        assert moved_map == {a: str(trash / "a_1.jpg")}
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
        moved, failed, _ = app._dedup_move_to_trash([b], str(trash))
        assert (moved, failed) == (1, 0)
        app.files = [f for f in app.files if os.path.exists(f)]
        app._refresh_file_list()
        assert app.files == [a]
        assert [r["path"] for r in app._lib_model] == [a]
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
    def _poll(self, root, pred, seconds=20.0):
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
        app._checked = {a}
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
        app._checked = {a, b}
        app._refresh_file_list()
        app._show_dedup()
        win = [w for w in root.winfo_children()
               if isinstance(w, tk.Toplevel)][0]
        # language-agnostic: the group label renders the localized template
        # with the group number filled in
        group_lbl = app._t("dedup_group", i=1)
        assert self._poll(root, lambda: _find_text(win, group_lbl)), \
            "dedup dialog must render group 1 after the scan"
        root.destroy()

    def test_gallery_dialog_smoke(self, tmp_path):
        import tkinter as tk
        root, app = _make_app()
        a = _img(tmp_path / "a.jpg")
        app.files = [a]
        app._checked = {a}
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


class TestFileDialogWorkarounds:
    """macOS Tk native file-dialog focus bugs: after the dialog closes,
    the button stays stuck in its hover fill and any click can re-open
    the dialog until the window loses focus."""

    def test_dialog_cooldown_blocks_reattempt(self, tmp_path, monkeypatch):
        from photo_s import gui as gui_mod
        calls = []
        monkeypatch.setattr(gui_mod.filedialog, "askopenfilenames",
                            lambda **k: calls.append(1) or [])
        root, app = _make_app()
        app._dlg_guard_until = time.monotonic() + 1.0   # dialog just closed
        app._add_files()
        assert calls == [], "re-entry within the cooldown must be a no-op"
        root.destroy()

    def test_after_file_dialog_resets_hover(self):
        from photo_s.gui import FlatButton, COLORS
        root, app = _make_app()
        btn = FlatButton(root, text="Add", command=lambda: None,
                         bg="#111111", hover_bg="#555555")
        btn.pack()
        root.update()
        btn._on_enter(None)
        assert btn.cget("bg") == "#555555", "hover fill applied"
        app._after_file_dialog(btn)
        assert btn.cget("bg") == "#111111", "hover must reset after dialog"
        assert app._dlg_cooldown_active()
        root.destroy()

    def test_after_file_dialog_sets_cooldown_then_expires(self):
        root, app = _make_app()
        app._after_file_dialog()
        assert app._dlg_cooldown_active()
        app._dlg_guard_until = time.monotonic() - 0.1
        assert not app._dlg_cooldown_active()
        root.destroy()


class TestRawPreview:
    def test_open_image_safe_pil_path(self, tmp_path):
        from photo_s.gui import _open_image_safe
        root, app = _make_app()
        p = _img(tmp_path / "a.jpg")
        img = _open_image_safe(p)
        assert img.size == (64, 48)
        root.destroy()

    def test_open_image_safe_raw_fallback(self, tmp_path, monkeypatch):
        """PIL cannot open RAW — the helper must fall back to the engine
        loader (regression: the review dialog showed 'cannot load' for
        RAW files)."""
        import photo_s.engine as engine_mod
        from PIL import Image
        from photo_s.gui import _open_image_safe
        fake = tmp_path / "x.cr2"
        fake.write_bytes(b"not really raw")
        calls = []
        real = engine_mod._get_image

        def fake_get_image(path, options=None):
            calls.append(path)
            return Image.new("RGB", (10, 10), (1, 2, 3))
        monkeypatch.setattr(engine_mod, "_get_image", fake_get_image)
        img = _open_image_safe(str(fake))
        assert img.size == (10, 10)
        assert calls == [str(fake)]
        # a normal JPEG must not touch the engine loader
        p = _img(tmp_path / "a.jpg")
        monkeypatch.setattr(engine_mod, "_get_image", real)
        img2 = _open_image_safe(p)
        assert img2.size == (64, 48)


class TestGlobalShortcuts:
    def test_bindings_registered(self):
        root, app = _make_app()
        for seq in ("<Command-o>", "<Control-o>", "<Command-r>",
                    "<Control-r>", "<Command-p>", "<Command-e>",
                    "<Command-d>", "<Command-g>", "<Command-z>",
                    "<Escape>"):
            assert root.bind(seq), f"{seq} must be bound"
        root.destroy()

    def test_shortcut_dispatches(self, monkeypatch):
        from photo_s.gui import PhotoSApp
        calls = []
        # the bindings capture the method reference at __init__ time,
        # so patch the class BEFORE creating the app
        monkeypatch.setattr(PhotoSApp, "_preview",
                            lambda self: calls.append("preview"))
        root, app = _make_app()
        root.update()
        root.focus_force()   # synthesized key events need a key window
        root.update()
        root.event_generate("<Control-p>")
        assert calls == ["preview"]
        root.destroy()

    def test_shortcut_locked_during_processing(self, monkeypatch):
        from photo_s import gui as gui_mod
        from photo_s.gui import PhotoSApp
        dedup_calls = []
        monkeypatch.setattr(PhotoSApp, "_show_dedup",
                            lambda self: dedup_calls.append(1))
        root, app = _make_app()
        app.processing = True
        monkeypatch.setattr(gui_mod.filedialog, "askopenfilenames",
                            lambda **k: [])
        root.update()
        root.focus_force()
        root.update()
        root.event_generate("<Control-d>")
        assert dedup_calls == [], "review/dedup shortcuts lock during batch"
        root.event_generate("<Control-o>")
        assert app.processing is True, "add-files stays available"
        root.destroy()

    def test_escape_cancels_processing(self, monkeypatch):
        root, app = _make_app()
        cancels = []
        monkeypatch.setattr(app, "_cancel_processing",
                            lambda: cancels.append(1))
        app.processing = False
        root.update()
        root.focus_force()
        root.update()
        root.event_generate("<Escape>")
        assert cancels == [], "Esc is a no-op when idle"
        app.processing = True
        root.event_generate("<Escape>")
        assert cancels == [1], "Esc cancels a running batch"
        root.destroy()


class TestReviewDialogUndo:
    def test_in_lightbox_undo_via_shortcut(self, tmp_path):
        """The user's exact flow: rate inside the lightbox, press ⌘Z
        there — the rating must revert AND the global stack must stay
        coherent (root shortcuts never reach Toplevel windows)."""
        pytest.importorskip("piexif")
        import tkinter as tk
        from photo_s.engine import read_exif_metadata
        root, app = _make_app()
        p = _img(tmp_path / "a.jpg")
        app.files = [p]
        app._checked = {p}
        app._refresh_file_list()
        app._show_review()
        win = [w for w in root.winfo_children()
               if isinstance(w, tk.Toplevel)][0]
        deadline = time.time() + 20
        while time.time() < deadline:
            root.update()
            if _find_text(win, "1 / 1"):
                break
            time.sleep(0.05)
        win.focus_force()
        root.update()
        win.event_generate("3")           # rate 3 stars (writes EXIF)
        root.update()
        assert read_exif_metadata(p)["rating"] == 3
        assert len(app._undo_stack) == 1
        win.event_generate("<Command-z>")  # undo inside the lightbox
        root.update()
        m = read_exif_metadata(p)
        assert m["rating"] is None, "rating cleared back to unrated"
        assert app._undo_stack == [], "global entry removed (LIFO coherent)"
        root.destroy()


class TestUndo:
    def test_undo_remove_rows(self, tmp_path):
        root, app = _make_app()
        a = _img(tmp_path / "a.jpg")
        b = _img(tmp_path / "b.jpg", seed=2)
        app._append_files([a, b])
        app._selected_rows = {a}
        app._remove_selected()
        assert app.files == [b]
        assert app.undo_btn.cget("state") == "normal"
        app._undo()
        assert app.files == [a, b], "undo restores the removed rows"
        assert app._checked == {a, b}, "check state restored too"
        assert app.undo_btn.cget("state") == "disabled"
        root.destroy()

    def test_undo_dedup_restores_files_and_list(self, tmp_path):
        root, app = _make_app()
        a = _img(tmp_path / "a.jpg")
        b = _img(tmp_path / "b.jpg")
        app._append_files([a, b])
        trash = str(tmp_path / "_duplicates_trash")
        moved, failed, moved_map = app._dedup_move_to_trash([b], trash)
        assert (moved, failed) == (1, 0)
        app.files = [a]
        app._checked = {a}
        app._refresh_file_list()
        app._push_undo(app._t("undo_dedup", n=1),
                       lambda: app._restore_dedup(dict(moved_map)))
        app._undo()
        assert os.path.exists(b), "file moved back to its original spot"
        assert app.files == [a, b], "restored to the list"
        root.destroy()

    def test_undo_stack_capped(self):
        root, app = _make_app()
        for i in range(12):
            app._push_undo("op{}".format(i), lambda: None)
        assert len(app._undo_stack) == app._undo_max == 10
        assert app._undo_stack[-1]["label"] == "op11"
        root.destroy()

    def test_undo_none_message(self, monkeypatch):
        from photo_s import gui as gui_mod
        shown = []
        monkeypatch.setattr(gui_mod.messagebox, "showinfo",
                            lambda *a, **k: shown.append(a))
        root, app = _make_app()
        app._undo()
        assert len(shown) == 1
        assert "撤销" in str(shown[0]) or "Undo" in str(shown[0])
        root.destroy()

    def test_undo_tag_restores_keywords_title(self, tmp_path):
        pytest.importorskip("piexif")
        from photo_s.engine import read_exif_metadata
        root, app = _make_app()
        p = _img(tmp_path / "a.jpg")
        ok, _, _, _ = app._review_save(p, rating=4, keywords="beach,trip",
                                 title="Summer Trip")
        assert ok
        m = read_exif_metadata(p)
        assert m["keywords"] == ["beach", "trip"]
        app._undo()
        m2 = read_exif_metadata(p)
        assert m2["rating"] is None and m2["keywords"] == [] \
            and m2["title"] == "", \
            "full restore — first-time rating is cleared back to unrated"
        root.destroy()

    def test_undo_tag_restores_previous_rating(self, tmp_path):
        pytest.importorskip("piexif")
        from photo_s.engine import read_exif_metadata
        root, app = _make_app()
        p = _img(tmp_path / "a.jpg")
        app._review_save(p, rating=4, keywords="beach", title="S")
        app._review_save(p, rating=5, keywords="beach", title="S")
        m = read_exif_metadata(p)
        assert m["rating"] == 5
        app._undo()
        assert read_exif_metadata(p)["rating"] == 4, \
            "undo restores the previous rating"
        root.destroy()


class TestProcessingLockout:
    def test_workflow_buttons_state_during_processing(self):
        root, app = _make_app()
        app._toggle_settings(False)
        assert app.review_btn.cget("state") == "disabled"
        assert app.dedup_btn.cget("state") == "disabled"
        assert app.gallery_btn.cget("state") == "normal", \
            "gallery export is read-only and must stay enabled"
        assert app.more_btn.cget("state") == "disabled", \
            "the whole More Tools menu locks during processing"
        assert app.preview_btn.cget("state") == "normal", \
            "visual preview only writes to a temp dir → stays enabled"
        app._toggle_settings(True)
        assert app.review_btn.cget("state") == "normal"
        root.destroy()


class TestCheckList:
    """The check-column contract: all workflow actions run on the checked
    files, checks survive rebuilds, and list maintenance keeps the set
    consistent."""

    def test_append_seeds_checked(self, tmp_path):
        root, app = _make_app()
        a = _img(tmp_path / "a.jpg")
        b = _img(tmp_path / "b.jpg", seed=2)
        assert app._append_files([a, b]) == 2
        assert app._checked == {a, b}, "new files start checked"
        root.destroy()

    def test_append_folder_scans_subfolders(self, tmp_path):
        """Regression: adding a folder used to scan only the top level —
        a folder whose photos live in subfolders reported 'no images'."""
        root, app = _make_app()
        sub = tmp_path / "作业" / "子文件夹"
        sub.mkdir(parents=True)
        top = _img(tmp_path / "作业" / "顶层.jpg", seed=1)
        deep = _img(sub / "深层.jpg", seed=2)
        assert app._append_files([str(tmp_path / "作业")]) == 2
        assert set(app.files) == {top, deep}
        assert app._checked == {top, deep}
        root.destroy()

    def test_append_skips_unsupported_and_counts(self, tmp_path):
        """Unsupported files are skipped (not fatal); hidden files are
        not counted; the count lands in _last_skipped for the caller."""
        root, app = _make_app()
        a = _img(tmp_path / "a.jpg")
        (tmp_path / "说明.txt").write_bytes(b"not an image")
        (tmp_path / ".DS_Store").write_bytes(b"junk")
        added = app._append_files([str(tmp_path)])
        assert added == 1
        assert app.files == [a]
        assert app._last_skipped == 1, "txt counted, hidden file not"
        root.destroy()

    def test_append_unsupported_file_paths_skipped(self, tmp_path):
        root, app = _make_app()
        a = _img(tmp_path / "a.jpg")
        txt = tmp_path / "readme.txt"
        txt.write_bytes(b"x")
        added = app._append_files([a, str(txt)])
        assert added == 1
        assert app.files == [a]
        assert app._last_skipped == 1
        root.destroy()

    def test_add_folder_notifies_skipped(self, tmp_path, monkeypatch):
        """Adding a folder with mixed content imports the images and
        pops a reminder about the skipped files."""
        from photo_s import gui as gui_mod
        a = _img(tmp_path / "a.jpg")
        (tmp_path / "x.txt").write_bytes(b"nope")
        shown = []
        monkeypatch.setattr(gui_mod.filedialog, "askdirectory",
                            lambda **k: str(tmp_path))
        monkeypatch.setattr(gui_mod.messagebox, "showinfo",
                            lambda *a, **k: shown.append(a))
        root, app = _make_app()
        app._add_folder()
        assert app.files == [a]
        assert len(shown) == 1
        assert "跳过 1" in shown[0][1] or "skipped 1" in shown[0][1]
        root.destroy()

    def test_toggle_and_checked_files(self, tmp_path):
        root, app = _make_app()
        a = _img(tmp_path / "a.jpg")
        b = _img(tmp_path / "b.jpg", seed=2)
        app._append_files([a, b])
        app._toggle_check(a)
        assert app._checked_files() == [b]
        app._toggle_check(a)
        assert app._checked_files() == [a, b]
        root.destroy()

    def test_toggle_all(self, tmp_path):
        root, app = _make_app()
        a = _img(tmp_path / "a.jpg")
        b = _img(tmp_path / "b.jpg", seed=2)
        app._append_files([a, b])
        app._toggle_all_checks()          # all checked -> none
        assert app._checked_files() == []
        app._toggle_all_checks()          # none -> all
        assert app._checked_files() == [a, b]
        root.destroy()

    def test_refresh_renders_checkbox_rows(self, tmp_path, monkeypatch):
        # the label assertion checks Chinese wording — pin zh so a locale-less
        # CI runner (Windows resolves en) is deterministic
        monkeypatch.setenv("PHOTO_S_LANG", "zh")
        from tkinter import ttk
        root, app = _make_app()
        a = _img(tmp_path / "a.jpg")
        b = _img(tmp_path / "b.jpg", seed=2)
        app._append_files([a, b])
        app._toggle_check(b)
        # v2.4 VirtualGrid: one model row per file, checkbox state drawn
        # from self._checked (b toggled OFF by the seam call above)
        assert [r["path"] for r in app._lib_model] == [a, b]
        assert a in app._checked
        assert b not in app._checked
        assert "已勾选 1" in app.file_count_label.cget("text")
        root.destroy()

    def test_palette_applied_per_instance(self):
        """Regression: COLORS is a module-global palette and used to be
        left flipped by a previous app instance — a second instance then
        built with the wrong palette. Each PhotoSApp must apply the
        palette for its own dark_mode."""
        from photo_s.gui import COLORS, _system_dark_mode
        root, app = _make_app()
        app._toggle_theme()          # leave the global palette flipped
        root2, app2 = _make_app()
        assert app2.dark_mode == _system_dark_mode()
        light = COLORS["accent"] == "#007aff"
        assert light == (not app2.dark_mode), \
            "COLORS must match the fresh instance's dark_mode"
        root.destroy()
        root2.destroy()

    def test_remove_selected_discards(self, tmp_path):
        root, app = _make_app()
        a = _img(tmp_path / "a.jpg")
        b = _img(tmp_path / "b.jpg", seed=2)
        app._append_files([a, b])
        app._selected_rows = {a}
        app._remove_selected()
        assert app._checked == {b}
        assert app.files == [b]
        assert app._selected_rows == set()
        root.destroy()

    def test_clear_files_resets(self, tmp_path, monkeypatch):
        from photo_s import gui as gui_mod
        monkeypatch.setattr(gui_mod.messagebox, "askyesno",
                            lambda *a, **k: True)
        root, app = _make_app()
        a = _img(tmp_path / "a.jpg")
        app._append_files([a])
        app._clear_files()
        assert app.files == [] and app._checked == set()
        root.destroy()

    def test_start_processing_requires_checked(self, tmp_path, monkeypatch):
        from photo_s import gui as gui_mod
        warned = []
        monkeypatch.setattr(gui_mod.messagebox, "showwarning",
                            lambda *a, **k: warned.append(a))
        root, app = _make_app()
        a = _img(tmp_path / "a.jpg")
        app._append_files([a])
        app._toggle_check(a)               # nothing checked
        app._start_processing()
        assert not app.processing, "must refuse to run with no checked files"
        assert len(warned) == 1
        root.destroy()

    def test_preview_requires_checked(self, tmp_path, monkeypatch):
        from photo_s import gui as gui_mod
        warned = []
        monkeypatch.setattr(gui_mod.messagebox, "showwarning",
                            lambda *a, **k: warned.append(a))
        root, app = _make_app()
        a = _img(tmp_path / "a.jpg")
        app._append_files([a])
        app._toggle_check(a)
        app._preview()
        assert len(warned) == 1
        root.destroy()


class TestSyncSeams:
    """Tk-free sync helpers for the new tools — exercised directly."""

    def test_preview_options_never_removes_original(self, tmp_path):
        root, app = _make_app()
        opts = app._preview_options(str(tmp_path))
        assert opts.remove_original is False, \
            "preview must never delete the source"
        assert opts.output_dir == str(tmp_path)
        assert opts.suffix == "" and opts.prefix == ""
        assert opts.overwrite is True
        root.destroy()

    def test_preview_render_keeps_source(self, tmp_path):
        root, app = _make_app()
        src = tmp_path / "a.png"
        _img(src)
        out = tmp_path / "out"
        out.mkdir()
        opts = app._preview_options(str(out))
        result = app._preview_render(str(src), opts)
        assert result.success, result.error
        assert os.path.dirname(result.output_path) == str(out)
        assert os.path.exists(src), "source file must be untouched"
        root.destroy()

    def test_contact_sheet_build(self, tmp_path):
        root, app = _make_app()
        files = [_img(tmp_path / f"n{i}.png", seed=i + 1) for i in range(3)]
        out = tmp_path / "sheet.png"
        result = app._contact_sheet_build(files, str(out), cols=2,
                                          thumb_size=(60, 60))
        assert result == str(out)
        assert os.path.exists(out)
        root.destroy()

    def test_cull_scan(self, tmp_path):
        root, app = _make_app()
        sharp = _img(tmp_path / "s.png", seed=5)
        results = app._cull_scan([sharp], {})
        assert results[0]["kept"] is True
        root.destroy()

    def test_hash_generate_verify_roundtrip(self, tmp_path):
        root, app = _make_app()
        files = [_img(tmp_path / f"n{i}.png", seed=i + 1) for i in range(2)]
        manifest = tmp_path / "m.csv"
        app._hash_generate(files, str(manifest))
        assert manifest.exists()
        report = app._hash_verify(str(manifest))
        assert report["total"] == 2
        assert report["ok"] == 2
        assert report["missing"] == [] and report["mismatched"] == []
        # tamper one file → mismatch reported
        with open(files[0], "ab") as f:
            f.write(b"x")
        report = app._hash_verify(str(manifest))
        assert len(report["mismatched"]) == 1
        root.destroy()


class TestPresetsRoundtrip:
    def test_apply_options_to_ui_roundtrip(self, tmp_path, monkeypatch):
        root, app = _make_app()
        # set a spread of vars
        app.quality.set(90)
        app.output_format.set("WebP")
        app.max_width.set("1920")
        app.brightness.set(1.1)
        app.grayscale.set(True)
        app.target_size_mode.set(True)
        app.target_size_value.set("500")
        app.target_size_unit.set("KB")
        app.output_sizes.set("thumb:320x240,full:1600x1200")
        opts = app._build_options()
        assert opts.quality == 90
        assert opts.target_size_bytes == 500 * 1024
        # wipe, then apply back
        app.quality.set(85)
        app.max_width.set("")
        app.grayscale.set(False)
        app._apply_options_to_ui(opts)
        assert app.quality.get() == 90
        assert app.max_width.get() == "1920"
        assert app.grayscale.get() is True
        assert app.target_size_mode.get() is True
        assert app.target_size_value.get() == "500"
        assert app.output_sizes.get() == "thumb:320x240,full:1600x1200"
        root.destroy()

    def test_preset_save_load_roundtrip(self, tmp_path, monkeypatch):
        import photo_s.presets as presets_mod
        monkeypatch.setattr(presets_mod, "PRESETS_DIR", tmp_path / "presets")
        root, app = _make_app()
        app.quality.set(77)
        app.output_format.set("PNG")
        app.suffix.set("_web")
        opts = app._build_options()
        presets_mod.save_preset("mytest", opts, "desc")
        loaded = presets_mod.load_preset("mytest")
        assert loaded is not None
        app.quality.set(85)
        app._apply_options_to_ui(loaded)
        assert app.quality.get() == 77
        assert app.output_format.get() == "PNG"
        assert app.suffix.get() == "_web"
        names = [n.split(" — ", 1)[0] for n in presets_mod.list_presets()]
        assert "mytest" in names
        assert presets_mod.delete_preset("mytest") is True
        root.destroy()


class TestMoreToolDialogs:
    def _open_dialog(self, root, app, method, title_key):
        import tkinter as tk
        getattr(app, method)()
        wins = [w for w in root.winfo_children()
                if isinstance(w, tk.Toplevel)]
        assert wins, f"{method} opened no dialog"
        assert app._t(title_key) in wins[-1].title()
        return wins[-1]

    def test_contact_sheet_dialog(self, tmp_path):
        root, app = _make_app()
        app._append_files([_img(tmp_path / "a.png", seed=1)])
        win = self._open_dialog(root, app, "_show_contact_sheet",
                                "contact_title")
        win.destroy()
        root.destroy()

    def test_hash_dialog(self, tmp_path):
        root, app = _make_app()
        win = self._open_dialog(root, app, "_show_hash", "hash_title")
        win.destroy()
        root.destroy()

    def test_watch_dialog(self, tmp_path):
        root, app = _make_app()
        win = self._open_dialog(root, app, "_show_watch", "watch_title")
        win.destroy()
        root.destroy()

    def test_cull_dialog(self, tmp_path):
        root, app = _make_app()
        app._append_files([_img(tmp_path / "a.png", seed=1)])
        win = self._open_dialog(root, app, "_show_cull", "cull_title")
        win.destroy()
        root.destroy()

    def test_presets_dialog(self, tmp_path):
        root, app = _make_app()
        win = self._open_dialog(root, app, "_show_presets", "presets_title")
        win.destroy()
        root.destroy()


class TestPreviewDialog:
    def test_preview_dialog_renders(self, tmp_path):
        """The visual preview opens, renders the source through the real
        pipeline, and cleans up its temp dir on close."""
        import tkinter as tk
        import glob
        root, app = _make_app()
        app._append_files([_img(tmp_path / "a.png", seed=1)])
        app._preview()
        wins = [w for w in root.winfo_children()
                if isinstance(w, tk.Toplevel)
                and w.title() == app._t("preview_title")]
        assert wins, "preview dialog did not open"
        win = wins[0]
        # let the drain loop debounce + render; the "after" panel fills
        deadline = time.time() + 25
        rendered = False
        while time.time() < deadline:
            root.update()
            # processed label got an image (photo reference kept on .image)
            for lbl in _walk_labels(win):
                if getattr(lbl, "image", None):
                    rendered = True
            if rendered:
                break
            time.sleep(0.05)
        assert rendered, "preview never rendered the processed image"
        win.destroy()
        # root-drain cleans the temp dir once no render is in flight
        # (generous settle: slow CI runners may still be mid-render)
        for _ in range(100):
            root.update()
            if not glob.glob(os.path.join(
                    tempfile.gettempdir(), "photos_preview_*")):
                break
            time.sleep(0.05)
        assert not glob.glob(os.path.join(
            tempfile.gettempdir(), "photos_preview_*")), \
            "preview temp dir must be cleaned up"
        root.destroy()


def _walk_labels(widget):
    for c in widget.winfo_children():
        yield c
        yield from _walk_labels(c)


class TestRenamePreview:
    """Batch rename live-preview: the Tk-free _rename_preview helper
    (dry-run mapping + in-batch collision replay) plus one dialog smoke."""

    def test_preview_maps_without_touching_files(self, tmp_path):
        root, app = _make_app()
        a = _img(tmp_path / "a.jpg")
        b = _img(tmp_path / "b.jpg", seed=2)
        rows = app._rename_preview([a, b], "photo_{seq}")
        assert [r["status"] for r in rows] == ["ok", "ok"]
        assert rows[0]["output"] == str(tmp_path / "photo_001.jpg")
        assert rows[1]["output"] == str(tmp_path / "photo_002.jpg")
        assert rows[0]["input"] == a and rows[1]["input"] == b
        # dry-run: nothing on disk may change
        assert os.path.exists(a) and os.path.exists(b)
        assert not os.path.exists(tmp_path / "photo_001.jpg")
        assert not os.path.exists(tmp_path / "photo_002.jpg")
        root.destroy()

    def test_preview_marks_in_batch_conflicts(self, tmp_path):
        """EXIF-less files + a constant template all map to one target;
        rows after the first get the suffix the real run would use — a
        clean counter on the ORIGINAL stem, so the third row is
        photo_2.jpg (not the old photo_1_2.jpg re-suffix quirk)."""
        root, app = _make_app()
        a = _img(tmp_path / "a.jpg")
        b = _img(tmp_path / "b.jpg", seed=2)
        c = _img(tmp_path / "c.jpg", seed=3)
        rows = app._rename_preview([a, b, c], "photo")
        assert [r["status"] for r in rows] == ["ok", "conflict", "conflict"]
        assert rows[0]["output"] == str(tmp_path / "photo.jpg")
        assert rows[1]["output"] == str(tmp_path / "photo_1.jpg")
        assert rows[2]["output"] == str(tmp_path / "photo_2.jpg")
        assert rows[1]["error"] and rows[2]["error"], \
            "conflict rows must explain the auto suffix"
        root.destroy()

    def test_preview_matches_real_run(self, tmp_path):
        """The simulated conflict suffixes must be exactly what a real
        rename produces (dry-run _unique_target can't see the batch)."""
        from photo_s.rename import rename_files
        root, app = _make_app()
        a = _img(tmp_path / "a.jpg")
        b = _img(tmp_path / "b.jpg", seed=2)
        c = _img(tmp_path / "c.jpg", seed=3)
        preview = app._rename_preview([a, b, c], "photo")
        real = rename_files([a, b, c], "photo")
        assert [r["output"] for r in preview] == \
               [r["output"] for r in real]
        root.destroy()

    def test_preview_empty_exif_falls_back_to_original(self, tmp_path):
        """A pure-EXIF template on an EXIF-less file renders an empty
        stem and must fall back to the original filename."""
        root, app = _make_app()
        a = _img(tmp_path / "a.jpg")
        out = tmp_path / "out"
        rows = app._rename_preview([a], "{date}{year}{month}",
                                   output_dir=str(out))
        assert rows[0]["status"] == "ok"
        assert rows[0]["output"] == str(out / "a.jpg")
        root.destroy()

    def test_preview_overwrite_clears_conflicts(self, tmp_path):
        """With overwrite=True no _N suffixing happens — same target for
        both rows, no conflict marks."""
        root, app = _make_app()
        a = _img(tmp_path / "a.jpg")
        b = _img(tmp_path / "b.jpg", seed=2)
        rows = app._rename_preview([a, b], "photo", overwrite=True)
        assert [r["status"] for r in rows] == ["ok", "ok"]
        assert rows[0]["output"] == rows[1]["output"] == \
            str(tmp_path / "photo.jpg")
        root.destroy()

    def test_rename_dialog_smoke(self, tmp_path):
        """Real-Tk smoke: dialog opens, debounced preview fills the tree."""
        import tkinter as tk
        from tkinter import ttk
        root, app = _make_app()
        a = _img(tmp_path / "a.jpg")
        app.files = [a]
        app._checked = {a}
        app._refresh_file_list()
        app._show_rename()
        win = [w for w in root.winfo_children()
               if isinstance(w, tk.Toplevel)][-1]
        assert app._t("rename_title") in win.title()

        trees = []

        def walk(w, depth=8):
            if depth < 0:
                return
            for c in w.winfo_children():
                if isinstance(c, ttk.Treeview):
                    trees.append(c)
                walk(c, depth - 1)

        walk(win)
        assert trees, "rename dialog must host a preview Treeview"
        tree = trees[0]
        assert _poll(root, lambda: len(tree.get_children()) == 1), \
            "debounced preview must map the one checked file"
        vals = tree.item(tree.get_children()[0], "values")
        assert vals[0] == "a.jpg" and vals[1], \
            "row shows original -> new name"
        root.destroy()


class TestZoomPanState:
    """Pure-math zoom/pan state, one instance per compare-viewer panel
    (no Tk needed — the class must stay headless-instantiable)."""

    def test_initial_state_is_fit(self):
        from photo_s.gui import _ZoomPanState
        s = _ZoomPanState()
        assert s.zoom == 1.0
        assert (s.fx, s.fy) == (0.5, 0.5)

    def test_zoom_at_clamps_to_max(self):
        from photo_s.gui import _ZoomPanState
        s = _ZoomPanState()
        s.zoom_at(100.0)
        assert s.zoom == 16.0

    def test_zoom_at_clamps_to_min(self):
        from photo_s.gui import _ZoomPanState
        s = _ZoomPanState()
        s.zoom_at(0.01)
        assert s.zoom == 1.0
        assert (s.fx, s.fy) == (0.5, 0.5)

    def test_zoom_back_to_fit_resets_center(self):
        from photo_s.gui import _ZoomPanState
        s = _ZoomPanState()
        s.zoom_at(2.0)
        s.pan(0.2, -0.2)
        assert (s.fx, s.fy) == (0.7, 0.3)
        s.zoom_at(0.5)
        assert s.zoom == 1.0
        assert (s.fx, s.fy) == (0.5, 0.5)

    def test_pan_is_noop_at_fit(self):
        """At zoom 1 the whole image is visible — panning must not move
        the center off (0.5, 0.5)."""
        from photo_s.gui import _ZoomPanState
        s = _ZoomPanState()
        s.pan(0.4, -0.4)
        assert (s.fx, s.fy) == (0.5, 0.5)

    def test_pan_clamps_at_zoom2(self):
        """At zoom 2 the visible half-extent is 0.25, so the center is
        clamped to [0.25, 0.75] on both axes."""
        from photo_s.gui import _ZoomPanState
        s = _ZoomPanState()
        s.zoom_at(2.0)
        s.pan(1.0, -1.0)
        assert s.fx == 0.75 and s.fy == 0.25
        s.pan(-3.0, 3.0)
        assert s.fx == 0.25 and s.fy == 0.75

    def test_zoom_out_reclamps_center(self):
        """Zooming out tightens the allowed center range; a center that
        was valid at zoom 16 must be re-clamped at zoom 8."""
        from photo_s.gui import _ZoomPanState
        s = _ZoomPanState()
        s.zoom_at(16.0)
        s.pan(-1.0, 1.0)  # clamped into [1/32, 31/32]
        assert s.fx == pytest.approx(1 / 32)
        assert s.fy == pytest.approx(31 / 32)
        s.zoom_at(0.5)  # zoom 8 → range tightens to [1/16, 15/16]
        assert s.zoom == 8.0
        assert s.fx == pytest.approx(1 / 16)
        assert s.fy == pytest.approx(15 / 16)

    def test_combined_sequence(self):
        from photo_s.gui import _ZoomPanState
        s = _ZoomPanState()
        s.zoom_at(1.1)
        s.zoom_at(1.1)
        assert s.zoom == pytest.approx(1.21)
        s.pan(0.1, 0.05)
        m = 0.5 / s.zoom
        assert m <= s.fx <= 1 - m and m <= s.fy <= 1 - m
        s.fit()
        assert s.zoom == 1.0
        assert (s.fx, s.fy) == (0.5, 0.5)

    def test_zoom_and_pan_are_per_panel_by_default(self):
        """The compare viewer's interaction contract: each panel owns its
        own state — wheel zoom and drag pan target only the panel under
        the cursor; sync-zoom mode applies zoom to every instance;
        double-click resets all."""
        from photo_s.gui import _ZoomPanState
        panels = [_ZoomPanState() for _ in range(3)]
        # default wheel: zoom only the hovered panel
        panels[1].zoom_at(2.0)
        assert [s.zoom for s in panels] == [1.0, 2.0, 1.0]
        # sync-zoom on: zoom applied to all
        for s in panels:
            s.zoom_at(2.0)
        assert [s.zoom for s in panels] == [1.0 * 2, 2.0 * 2, 1.0 * 2]
        # drag: pan only the hovered panel
        panels[1].pan(0.1, 0.0)
        assert (panels[0].fx, panels[2].fx) == (0.5, 0.5)
        assert panels[1].fx == pytest.approx(0.5 + 0.1)
        # double-click: global reset
        for s in panels:
            s.fit()
        assert all((s.zoom, s.fx, s.fy) == (1.0, 0.5, 0.5) for s in panels)


class TestCompareDialog:
    """Real-Tk smokes for the multi-image compare viewer (headless skip)."""

    @staticmethod
    def _image_canvases(win):
        """All canvases in the dialog except FlatButton pills (which are
        canvases too)."""
        import tkinter as tk
        from photo_s.gui import FlatButton
        found = []

        def walk(w, depth=8):
            if depth < 0:
                return
            for c in w.winfo_children():
                if isinstance(c, tk.Canvas) and not isinstance(c, FlatButton):
                    found.append(c)
                walk(c, depth - 1)

        walk(win)
        return found

    @staticmethod
    def _painted(canvas):
        return any(canvas.type(i) == "image" for i in canvas.find_all())

    def _open_dialog(self, root, app, paths):
        import tkinter as tk
        app.files = list(paths)
        app._checked = set(paths)
        app._refresh_file_list()
        app._show_compare()
        wins = [w for w in root.winfo_children()
                if isinstance(w, tk.Toplevel)]
        assert wins, "compare dialog must open"
        return wins[-1]

    def test_smoke_three_panels(self, tmp_path):
        root, app = _make_app()
        paths = [_img(tmp_path / "{}.jpg".format(n), seed=i)
                 for i, n in enumerate("abc")]
        win = self._open_dialog(root, app, paths)
        assert app._t("compare_view_title") in win.title()
        canvases = self._image_canvases(win)
        assert len(canvases) == 3, "one canvas per checked image"
        assert _poll(root, lambda: all(self._painted(c) for c in canvases)), \
            "worker-loaded images must paint on every canvas"
        # sync-zoom checkbox must be present and off by default
        import tkinter.ttk as ttk
        boxes = []

        def _walk(w, depth=8):
            if depth < 0:
                return
            for c in w.winfo_children():
                if isinstance(c, ttk.Checkbutton):
                    boxes.append(c)
                _walk(c, depth - 1)

        _walk(win)
        sync = [b for b in boxes
                if b.cget("text") == app._t("compare_sync_zoom")]
        assert sync, "sync-zoom checkbox must exist"
        assert "selected" not in sync[0].state(), \
            "sync zoom must be off by default"
        root.destroy()

    def test_caps_at_four_panels(self, tmp_path):
        root, app = _make_app()
        paths = [_img(tmp_path / "{}.jpg".format(i), seed=i)
                 for i in range(5)]
        win = self._open_dialog(root, app, paths)
        assert len(self._image_canvases(win)) == 4, \
            "five checked images must be capped at four panels"
        root.destroy()

    def test_fewer_than_two_warns(self, tmp_path, monkeypatch):
        import tkinter as tk
        root, app = _make_app()
        p = _img(tmp_path / "a.jpg")
        app.files = [p]
        app._checked = {p}
        app._refresh_file_list()
        calls = []
        import photo_s.gui as gui_mod
        monkeypatch.setattr(gui_mod.messagebox, "showinfo",
                            lambda *a, **k: calls.append(a))
        app._show_compare()
        assert calls, "must warn when fewer than 2 images are checked"
        assert not [w for w in root.winfo_children()
                    if isinstance(w, tk.Toplevel)], \
            "no dialog may open below the 2-image minimum"
        root.destroy()
