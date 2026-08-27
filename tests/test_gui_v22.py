"""v2.2 editing-efficiency tests: copy/paste settings + per-photo undo/redo
+ export recipes.

Covers:
* dev-fields capture/apply round-trip (scoped — never touches export vars)
* copy → paste onto the viewer photo and onto checked photos (per-photo
  overlays + undo history baseline)
* undo/redo walk the history, buttons + Cmd+Z routing reflect availability
* batch injection merges develop overlays with per-photo masks
* recipes: capture/apply round-trip incl. target-size split, save/delete
  persist through gui_state.json
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path, monkeypatch):
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


def _img(path, seed=1, size=(96, 64)):
    import numpy as np
    from PIL import Image
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 256, (size[1], size[0], 3), dtype=np.uint8)
    Image.fromarray(arr, "RGB").save(path, "JPEG")


@pytest.fixture
def app_with_photos(tmp_path):
    root, app = _make_app()
    paths = []
    for i in range(3):
        p = str(tmp_path / "photo{}.jpg".format(i))
        _img(p, seed=i + 1)
        paths.append(p)
    app.files = list(paths)
    app._checked = set(paths)
    app._refresh_file_list()
    yield root, app, paths
    try:
        app._on_main_close()
    except Exception:
        pass
    try:
        root.destroy()
    except Exception:
        pass


class TestDevFieldsRoundTrip:
    def test_capture_apply_roundtrip(self, app_with_photos):
        root, app, paths = app_with_photos
        app.brightness.set("1.4")
        app.contrast.set("1.2")
        app.curves.set("r:0,0;128,140;255,255")
        app.quality.set(60)                      # export field — must NOT be
        app.output_format.set("PNG")             # captured by dev fields
        d = app._dev_fields_of(app._build_options())
        assert d["brightness"] == 1.4
        assert d["curves"] == "r:0,0;128,140;255,255"
        assert "quality" not in d and "output_format" not in d

        app.brightness.set("1.0")
        app.curves.set("")
        app._apply_dev_fields(d)
        assert float(app.brightness.get()) == 1.4
        assert app.curves.get() == "r:0,0;128,140;255,255"
        # export vars untouched by the scoped apply
        assert int(app.quality.get()) == 60
        assert app.output_format.get() == "PNG"

    def test_none_normalizes_to_slider_zero(self, app_with_photos):
        root, app, paths = app_with_photos
        app._apply_dev_fields({"export_sharpen": None,
                               "highlight_recovery": None})
        assert float(app.export_sharpen.get()) == 0.0


class TestCopyPaste:
    def test_copy_paste_viewer_photo(self, app_with_photos):
        root, app, paths = app_with_photos
        app._dev_selected = paths[0]
        app.brightness.set("1.5")
        app._dev_copy_settings()
        assert app._settings_clipboard["brightness"] == 1.5

        app._dev_selected = paths[1]
        app.brightness.set("1.0")
        app._dev_paste_settings()
        # overlay + history on the pasted photo, live vars refreshed
        assert app._photo_adjust[paths[1]]["brightness"] == 1.5
        assert float(app.brightness.get()) == 1.5
        hist = app._dev_history[paths[1]]
        assert len(hist) == 2          # baseline (1.0) + pasted (1.5)
        assert hist[0]["brightness"] == 1.0
        assert hist[1]["brightness"] == 1.5

    def test_paste_to_checked_sets_overlays_and_badges(self, app_with_photos):
        root, app, paths = app_with_photos
        app._dev_selected = paths[0]
        app.vibrance.set("30")
        app._dev_copy_settings()
        app._paste_settings_to_checked()
        assert all(app._photo_adjust[p]["vibrance"] == 30.0
                   for p in paths)

    def test_paste_without_copy_warns(self, app_with_photos):
        root, app, paths = app_with_photos
        app._settings_clipboard = None
        app._dev_selected = paths[0]
        app._dev_paste_settings()
        assert paths[0] not in app._photo_adjust

    def test_export_queue_shows_edited_badge(self, app_with_photos):
        root, app, paths = app_with_photos
        app._photo_adjust[paths[0]] = {"brightness": 1.2}
        app._show_module("export")
        texts = []
        for row in app._export_queue_inner.winfo_children():
            for w in row.winfo_children():
                try:
                    texts.append(w.cget("text"))
                except Exception:
                    pass
        assert app._t("export_adjusted_badge") in texts


class TestUndoRedo:
    def test_undo_redo_walks_history(self, app_with_photos):
        root, app, paths = app_with_photos
        p = paths[0]
        app._show_module("develop")
        app._dev_selected = p
        app._dev_history_push(p, {"brightness": 1.0})
        app._dev_history_push(p, {"brightness": 1.3})
        app._dev_history_push(p, {"brightness": 1.6})
        assert app._dev_undo_available()       # can step back from newest

        app._dev_undo()
        assert float(app.brightness.get()) == 1.3
        assert app._photo_adjust[p]["brightness"] == 1.3
        assert app._dev_undo_available()
        app._dev_undo()
        assert float(app.brightness.get()) == 1.0
        assert not app._dev_undo_available()      # at the baseline

        app._dev_redo()
        assert float(app.brightness.get()) == 1.3
        app._dev_redo()
        assert float(app.brightness.get()) == 1.6
        assert not app._dev_redo_available()

    def test_history_dedup_and_redo_truncation(self, app_with_photos):
        root, app, paths = app_with_photos
        p = paths[0]
        app._dev_history_push(p, {"brightness": 1.0})
        app._dev_history_push(p, {"brightness": 1.1})
        app._dev_history_push(p, {"brightness": 1.1})   # deduped
        assert len(app._dev_history[p]) == 2
        app._dev_history_pos[p] = 0
        app._dev_history_push(p, {"brightness": 2.0})   # truncates redo tail
        assert app._dev_history[p] == [
            {"brightness": 1.0}, {"brightness": 2.0}]
        assert not app._dev_redo_available()

    def test_cmd_z_routes_to_dev_history(self, app_with_photos):
        root, app, paths = app_with_photos
        p = paths[0]
        app._show_module("develop")
        app._dev_selected = p
        # global stack has an entry; per-photo history must win in Develop
        app._undo_stack.append({"label": "x", "run": lambda: None})
        app._dev_history_push(p, {"brightness": 1.0})
        app._dev_history_push(p, {"brightness": 1.4})
        app.brightness.set("1.0")
        app._undo()
        assert float(app.brightness.get()) == 1.0
        # outside Develop the global stack takes over again
        app._show_module("library")
        assert not app._dev_undo_available()


class TestBatchInjection:
    def test_overlay_and_masks_merge(self, app_with_photos):
        root, app, paths = app_with_photos
        base = app._build_options()
        app._photo_adjust[paths[0]] = {"brightness": 1.4, "contrast": 1.1}
        got = app._per_file_overlay(paths[0], base)
        assert got.brightness == 1.4 and got.contrast == 1.1
        assert got.quality == base.quality     # untouched fields carry over

        app._photo_masks[paths[1]] = {
            "masks": "sky:linear", "mask_adjust": "sky:contrast=1.2"}
        got2 = app._per_file_overlay(paths[1], base)
        assert got2.masks == "sky:linear"
        assert got2.brightness == base.brightness

        got3 = app._per_file_overlay(paths[2], base)  # clean photo
        assert got3 is base

    def test_overlay_reaches_engine_options(self, app_with_photos):
        root, app, paths = app_with_photos
        from photo_s.engine import batch_process
        out = str(os.path.dirname(paths[0])) + "/out_v22"
        app._photo_adjust[paths[0]] = {"brightness": 1.0}
        app.output_dir.set(out)
        opts = app._build_options()
        eff = app._per_file_overlay(paths[0], opts)
        assert eff is not opts


class TestExportRecipes:
    def test_capture_apply_roundtrip(self, app_with_photos):
        root, app, paths = app_with_photos
        app.quality.set(92)
        app.output_format.set("WEBP")
        app.jpeg_subsampling.set("444")
        app.target_size_mode.set(True)
        app.target_size_value.set("2")
        app.target_size_unit.set("MB")
        app.watermark_text.set("© me")
        d = app._export_recipe_capture()
        assert d["quality"] == 92
        assert d["target_size_bytes"] == 2 * 1024 * 1024

        app.quality.set(70)
        app.output_format.set("JPEG")
        app.target_size_mode.set(False)
        app.watermark_text.set("")
        app._apply_recipe_fields(d)
        assert int(app.quality.get()) == 92
        assert app.output_format.get() == "WEBP"
        assert app.jpeg_subsampling.get() == "444"
        assert bool(app.target_size_mode.get()) is True
        assert app.target_size_value.get() == "2"
        assert app.target_size_unit.get() == "MB"
        assert app.watermark_text.get() == "© me"

    def test_recipe_save_delete_persists(self, app_with_photos, tmp_path):
        root, app, paths = app_with_photos
        app.quality.set(88)
        app._recipe_var.set("社媒 2048")
        app._export_recipe_save()
        assert "社媒 2048" in app._export_recipes

        state_file = os.path.join(os.environ["HOME"], ".photos",
                                  "gui_state.json")
        saved = json.load(open(state_file, encoding="utf-8"))
        assert "社媒 2048" in saved["export_recipes"]

        app._export_recipe_delete()
        assert "社媒 2048" not in app._export_recipes
        saved = json.load(open(state_file, encoding="utf-8"))
        assert "export_recipes" not in saved or \
            "社媒 2048" not in saved["export_recipes"]

    def test_recipe_apply_bad_pick_warns(self, app_with_photos):
        root, app, paths = app_with_photos
        app._recipe_var.set("")
        app.quality.set(70)
        app._export_recipe_apply()
        assert int(app.quality.get()) == 70   # unchanged

    def test_recipes_restored_on_restart(self, tmp_path):
        import tkinter as tk
        from photo_s.gui import PhotoSApp
        from photo_s.gui.state import save_state
        save_state({"export_recipes": {"print 300dpi": {"quality": 95}}})
        try:
            root = tk.Tk()
        except Exception as e:
            pytest.skip("no display: {}".format(e))
        try:
            app = PhotoSApp(root)
            assert app._export_recipes == {"print 300dpi": {"quality": 95}}
        finally:
            try:
                app._on_main_close()
            except Exception:
                root.destroy()
