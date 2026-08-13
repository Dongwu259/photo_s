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
        assert list(app._row_widgets) == [a]
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
        assert self._poll(root, lambda: _find_text(win, "第 1 组")), \
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
        ok, _ = app._review_save(p, rating=4, keywords="beach,trip",
                                 title="Summer Trip")
        assert ok
        m = read_exif_metadata(p)
        assert m["keywords"] == ["beach", "trip"]
        app._undo()
        m2 = read_exif_metadata(p)
        assert m2["keywords"] == [] and m2["title"] == "", \
            "keywords/title restored (rating had no previous value)"
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

    def test_refresh_renders_checkbox_rows(self, tmp_path):
        from tkinter import ttk
        root, app = _make_app()
        a = _img(tmp_path / "a.jpg")
        b = _img(tmp_path / "b.jpg", seed=2)
        app._append_files([a, b])
        app._toggle_check(b)
        # one real ttk.Checkbutton per row, state from self._checked
        assert len(app._row_vars) == 2
        assert app._row_vars[a].get() is True
        assert app._row_vars[b].get() is False
        row = app._row_widgets[a]["row"]
        assert any(isinstance(c, ttk.Checkbutton)
                   for c in row.winfo_children()), \
            "rows must host real ttk.Checkbuttons (settings-panel look)"
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
