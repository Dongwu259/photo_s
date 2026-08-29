"""v2.4 tests: AI auto-tone GUI + WYSIWYG unification + library perf.

Covers:
* AI auto-tone button: fake plugin module → 9 predicted params land in the
  per-photo overlay (exposure→ev mapping), undo history seeded, sliders
  reflect them; strength combobox reaches the plugin; plugin-missing and
  inference-failure paths give clear hints instead of crashes
"""

import os
import sys
import time

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
    app._show_module("develop")
    yield root, app, paths
    try:
        app._on_main_close()
    except Exception:
        pass
    try:
        root.destroy()
    except Exception:
        pass


class _FakePlugin:
    """Deterministic stand-in for photo_s_plugin_auto-tone's auto_tone()."""

    calls = []
    fail_with = None

    @staticmethod
    def auto_tone(path, strength=1.0, render=True, **kw):
        _FakePlugin.calls.append({"path": path, "strength": strength,
                                  "render": render})
        if _FakePlugin.fail_with is not None:
            raise _FakePlugin.fail_with
        return {
            "schema_version": 1,
            "options": {
                "exposure": 0.35, "contrast": 1.08, "saturation": 1.12,
                "vibrance": 0.2, "wb_temp": 5400.0, "wb_tint": -3.0,
                "clarity": 0.1, "texture": 0.05, "dehaze": 0.0,
            },
            "confidence": 0.83,
            "warnings": [],
        }


@pytest.fixture
def fake_plugin(monkeypatch):
    _FakePlugin.calls = []
    _FakePlugin.fail_with = None
    monkeypatch.setitem(sys.modules, "photo_s_plugin_auto_tone", _FakePlugin)
    return _FakePlugin


def _drain_ai(app, timeout=5.0):
    """Wait for the worker + bus delivery (no mainloop in tests)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        app._dev_bus.drain_pending()
        if not app._dev_ai_busy:
            return True
        time.sleep(0.02)
    app._dev_bus.drain_pending()
    return not app._dev_ai_busy


class TestAiTone:
    def test_writes_overlay_history_sliders(self, app_with_photos,
                                             fake_plugin):
        root, app, paths = app_with_photos
        app._dev_select(paths[1])
        assert paths[1] not in app._photo_adjust  # untouched baseline

        app._dev_ai_tone()
        assert _drain_ai(app)

        assert fake_plugin.calls[0]["path"] == paths[1]
        assert fake_plugin.calls[0]["render"] is False
        ov = app._photo_adjust[paths[1]]
        # exposure (LR stops) maps onto the ev develop field; the other
        # eight targets share their ProcessOptions names
        assert ov["ev"] == pytest.approx(0.35)
        assert ov["contrast"] == pytest.approx(1.08)
        assert ov["wb_temp"] == pytest.approx(5400.0)
        assert ov["dehaze"] == pytest.approx(0.0)
        # history: pre-edit baseline + the AI state → undo available
        assert app._dev_undo_available()
        # sliders reflect the prediction for the photo in the viewer
        assert float(app.ev.get()) == pytest.approx(0.35)
        assert float(app.wb_tint.get()) == pytest.approx(-3.0)

    def test_undo_reverts_ai_params(self, app_with_photos, fake_plugin):
        root, app, paths = app_with_photos
        app._dev_select(paths[0])
        app._dev_ai_tone()
        assert _drain_ai(app)
        assert app._photo_adjust[paths[0]]["ev"] == pytest.approx(0.35)
        app._dev_undo()
        ov = app._photo_adjust[paths[0]]
        assert ov["ev"] != pytest.approx(0.35)  # baseline restored
        assert float(app.ev.get()) == pytest.approx(float(ov["ev"]))

    def test_strength_combobox_reaches_plugin(self, app_with_photos,
                                              fake_plugin):
        root, app, paths = app_with_photos
        app._dev_select(paths[0])
        app._dev_ai_strength.set("0.4")
        app._dev_ai_tone()
        assert _drain_ai(app)
        assert fake_plugin.calls[0]["strength"] == pytest.approx(0.4)

    def test_ai_merges_into_existing_overlay(self, app_with_photos,
                                              fake_plugin):
        root, app, paths = app_with_photos
        app._dev_select(paths[0])
        app.curves.set("r:0,0;128,140;255,255")   # a non-AI dev edit
        app._dev_ai_tone()
        assert _drain_ai(app)
        # curves survive beside the AI-written fields
        assert "r:0,0;128,140;255,255" in app._photo_adjust[paths[0]]["curves"]

    def test_need_photo_hint(self, app_with_photos, fake_plugin):
        root, app, paths = app_with_photos
        app._dev_selected = ""
        app._dev_ai_tone()
        assert not fake_plugin.calls
        assert (app._dev_status_lbl.cget("text")
                == app._t("dev_ai_need_photo"))

    def test_plugin_missing_shows_install_hint(self, app_with_photos,
                                               monkeypatch):
        root, app, paths = app_with_photos
        app._dev_select(paths[0])
        # None in sys.modules forces ImportError even where installed
        monkeypatch.setitem(sys.modules, "photo_s_plugin_auto_tone", None)
        shown = []
        monkeypatch.setattr(
            "photo_s.gui.app.messagebox.showwarning",
            lambda *a, **k: shown.append(a))
        app._dev_ai_tone()
        assert _drain_ai(app)
        assert shown  # install instructions surfaced
        assert (app._dev_status_lbl.cget("text")
                == app._t("dev_ai_need_plugin"))
        assert not app._dev_ai_busy

    def test_inference_failure_reports_error(self, app_with_photos,
                                             fake_plugin):
        root, app, paths = app_with_photos
        app._dev_select(paths[0])
        fake_plugin.fail_with = RuntimeError(
            "auto-tone 插件需要 open_clip: pip install "
            "'photo-s-plugin-auto-tone[model]'")
        app._dev_ai_tone()
        assert _drain_ai(app)
        assert "open_clip" in app._dev_status_lbl.cget("text")
        assert not app._dev_ai_busy

    def test_busy_guard_blocks_reentry(self, app_with_photos, fake_plugin):
        root, app, paths = app_with_photos
        app._dev_select(paths[0])
        app._dev_ai_busy = True
        app._dev_ai_tone()  # must be a no-op
        assert not fake_plugin.calls


def _drain_until(app, pred, timeout=6.0):
    """Pump the dev bus until pred() is true (no mainloop in tests)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        app._dev_bus.drain_pending()
        if pred():
            return True
        time.sleep(0.02)
    app._dev_bus.drain_pending()
    return pred()


class _FakeResult:
    def __init__(self, ok=True, out=""):
        self.success = ok
        self.output_path = out
        self.error = "" if ok else "boom"


class TestWysiwygRender:
    def test_render_adjusted_async_applies_overlay(self, app_with_photos):
        """The shared WYSIWYG renderer produces a real processed file for
        the photo's overlay (brighter overlay → brighter pixels)."""
        root, app, paths = app_with_photos
        import numpy as np
        from PIL import Image
        from photo_s.gui import workflows
        import tempfile
        tmp = tempfile.mkdtemp()
        baseline = workflows.preview_render(
            paths[0], workflows.preview_options(app._build_options(), tmp))
        assert baseline.success

        app._photo_adjust[paths[0]] = {"brightness": 2.0}
        got = {}
        app._render_adjusted_async(
            paths[0], lambda r, e: got.update(r=r, e=e))
        assert _drain_until(app, lambda: got)
        assert got["e"] is None and got["r"] and got["r"].success
        m0 = np.asarray(
            Image.open(baseline.output_path).convert("L")).mean()
        m1 = np.asarray(
            Image.open(got["r"].output_path).convert("L")).mean()
        assert m1 > m0 + 5

    def test_render_adjusted_async_masks_toggle(self, app_with_photos):
        """include_masks=False strips the per-photo masks from the render
        (mask editors blend their own overlays); True bakes them in."""
        root, app, paths = app_with_photos
        app._photo_adjust[paths[0]] = {"brightness": 1.5}
        app._photo_masks[paths[0]] = {
            "masks": "m1:linear:0,0,1,1",
            "mask_adjust": "m1:exposure=-1.5",
        }
        got = {}
        app._render_adjusted_async(
            paths[0], lambda r, e: got.update(no_mask=(r, e)),
            include_masks=False)
        assert _drain_until(app, lambda: got)
        assert got["no_mask"][0] and got["no_mask"][0].success

        got2 = {}
        app._render_adjusted_async(
            paths[0], lambda r, e: got2.update(with_mask=(r, e)))
        assert _drain_until(app, lambda: got2)
        import numpy as np
        from PIL import Image
        a = np.asarray(Image.open(got["no_mask"][0].output_path)
                       .convert("L")).mean()
        b = np.asarray(Image.open(got2["with_mask"][0].output_path)
                       .convert("L")).mean()
        assert b < a - 5  # full-frame -1.5EV mask only when included

    def test_review_lightbox_requests_adjusted_render(self,
                                                      app_with_photos):
        """The lightbox asks for a pipeline render of overlaid photos and
        badges them in the info line."""
        import tkinter as tk
        root, app, paths = app_with_photos
        app._photo_adjust[paths[0]] = {"brightness": 1.5}
        calls = []

        def fake_rra(path, deliver, include_masks=True):
            calls.append((path, include_masks))

        app._render_adjusted_async = fake_rra
        app._show_review()
        deadline = time.time() + 5.0
        while time.time() < deadline and not calls:
            root.update()
            time.sleep(0.02)
        tops = [w for w in root.winfo_children()
                if isinstance(w, tk.Toplevel)]
        try:
            assert calls and calls[0][0] == paths[0]
            assert calls[0][1] is True  # lightbox shows the full truth
            badge = app._t("export_adjusted_badge")
            found = []

            def walk(w):
                for c in w.winfo_children():
                    if isinstance(c, tk.Label):
                        t = c.cget("text") or ""
                        if badge in t:
                            found.append(t)
                    walk(c)
            for tp in tops:
                walk(tp)
            assert found, "badge missing from the lightbox info line"
        finally:
            for tp in tops:
                try:
                    tp.destroy()
                except tk.TclError:
                    pass


class TestLibraryVirtualGrid:
    def test_model_reflects_files_and_culls(self, app_with_photos):
        """The list is a data model + a drawn window: refresh fills the
        model for every file, but only the visible rows materialize as
        canvas items (a 5k library never creates 5k rows of widgets)."""
        root, app, paths = app_with_photos
        app._refresh_file_list()
        assert [r["path"] for r in app._lib_model] == paths
        first, last = app._lib_visible
        assert first == 0
        assert last <= len(paths)  # headless canvas is tiny
        assert app.file_list_canvas.find_all()  # rows actually drawn

    def test_toggle_check_updates_state_and_count(self, app_with_photos):
        root, app, paths = app_with_photos
        app._toggle_check(paths[0])            # fixture checks all three
        assert paths[0] not in app._checked
        assert paths[1] in app._checked
        assert "2" in app.file_count_label.cget("text")
        app._toggle_check(paths[0])            # toggle back
        assert paths[0] in app._checked

    def test_row_hit_testing(self, app_with_photos):
        root, app, paths = app_with_photos
        rh = app._lib_row_h()
        assert app._lib_row_at(rh * 0 + rh // 2) == 0
        assert app._lib_row_at(rh * 2 + 5) == 2
        assert app._lib_row_at(-1) == -1
        assert app._lib_row_at(rh * 99) == -1

    def test_5k_rows_draw_only_visible_window(self, app_with_photos):
        """VirtualGrid contract: 5k model rows, canvas items stay in the
        dozens, scroll window transitions are cheap."""
        root, app, paths = app_with_photos
        model = app._lib_model
        big = [dict(model[0], path="/x/p%05d.jpg" % i,
                    name="p%05d.jpg" % i) for i in range(5000)]
        app._lib_model = big
        import time
        t0 = time.time()
        app._lib_draw()
        root.update_idletasks()
        elapsed = time.time() - t0
        n_items = len(app.file_list_canvas.find_all())
        assert n_items < 200          # dozens, not thousands
        assert elapsed < 2.0          # generous CI bound (local: ~20ms)

    def test_removed_files_drop_selection(self, app_with_photos):
        root, app, paths = app_with_photos
        app._selected_rows = {paths[0], paths[1]}
        app.files = [paths[2]]
        app._refresh_file_list()
        assert app._selected_rows == set()


class TestLibraryKeyboardRating:
    def test_rate_selected_rows_writes_exif(self, app_with_photos):
        root, app, paths = app_with_photos
        from photo_s.engine import read_exif_metadata
        app._selected_rows = {paths[0], paths[1]}
        app._lib_rate(4)
        assert read_exif_metadata(paths[0]).get("rating") == 4
        assert read_exif_metadata(paths[1]).get("rating") == 4
        assert app._lib_rating(paths[0]) == 4

    def test_p_clears_rating(self, app_with_photos):
        root, app, paths = app_with_photos
        from photo_s.engine import read_exif_metadata
        app._selected_rows = {paths[0]}
        app._lib_rate(5)
        app._lib_rate(0)              # P = reject → clear
        assert not read_exif_metadata(paths[0]).get("rating")

    def test_no_selection_is_noop(self, app_with_photos):
        root, app, paths = app_with_photos
        from photo_s.engine import read_exif_metadata
        app._selected_rows = set()
        app._lib_rate(3)
        assert not read_exif_metadata(paths[0]).get("rating")

    def test_enter_opens_selection_in_develop(self, app_with_photos):
        root, app, paths = app_with_photos
        app._selected_rows = {paths[2]}
        app._lib_open_in_viewer()
        assert app._active_module == "develop"
        assert app._dev_selected == paths[2]


class TestKeyboardGuards:
    def test_rating_keys_guarded_by_module(self, app_with_photos):
        """Root-level 1-5 only rate while the Library module is active —
        the fixture starts in Develop, where digits must be inert."""
        root, app, paths = app_with_photos
        from photo_s.engine import read_exif_metadata
        app._selected_rows = {paths[0]}
        app._lib_key_rate(3)
        assert not read_exif_metadata(paths[0]).get("rating")
        app._show_module("library")
        app._lib_key_rate(3)
        assert read_exif_metadata(paths[0]).get("rating") == 3

    def test_rating_keys_guarded_by_entry_focus(self, app_with_photos):
        """Typing in the filter box (an Entry holding focus) never rates."""
        root, app, paths = app_with_photos
        from photo_s.engine import read_exif_metadata
        app._show_module("library")
        app._selected_rows = {paths[0]}
        app.filter_entry.focus_set()
        root.update_idletasks()
        app._lib_key_rate(5)
        focused = root.focus_get()
        if focused is app.filter_entry:  # headless focus can be refused
            assert not read_exif_metadata(paths[0]).get("rating")

    def test_shortcuts_dialog_lists_keys(self, app_with_photos):
        import tkinter as tk
        root, app, paths = app_with_photos
        app._show_shortcuts()
        tops = [w for w in root.winfo_children()
                if isinstance(w, tk.Toplevel)]
        texts = []

        def walk(w):
            for c in w.winfo_children():
                if isinstance(c, tk.Label):
                    texts.append(c.cget("text") or "")
                walk(c)
        try:
            for tp in tops:
                walk(tp)
            assert any("⌘P" in t or "1-5" in t for t in texts)
        finally:
            for tp in tops:
                try:
                    tp.destroy()
                except tk.TclError:
                    pass


class TestDevelopCompare:
    def _pair_ready(self, app, paths):
        """Drive a real render so before_pil/after_pil both exist."""
        app._dev_select(paths[0])
        st = app._dev_render_state
        deadline = time.time() + 6.0
        while time.time() < deadline:
            app._dev_bus.drain_pending()
            root_update(app)
            if st.get("after_pil") is not None and \
                    st.get("before_pil") is not None:
                return True
            time.sleep(0.03)
        return False

    def test_cycle_and_compose(self, app_with_photos):
        root, app, paths = app_with_photos
        assert self._pair_ready(app, paths)
        # off → split: canvas placed, divider at the default midpoint
        app._dev_compare_toggle()
        assert app._dev_compare_mode == "split"
        app._dev_compare_render()
        root_update(app)
        assert app._dev_compare_canvas.winfo_manager() == "place"
        items = app._dev_compare_canvas.find_all()
        assert len(items) >= 3  # image + divider line + handle
        # split → side → off
        app._dev_compare_toggle()
        assert app._dev_compare_mode == "side"
        app._dev_compare_render()
        root_update(app)
        assert app._dev_compare_canvas.find_all()
        app._dev_compare_toggle()
        assert app._dev_compare_mode == "off"
        assert app._dev_compare_canvas.winfo_manager() == ""

    def test_drag_moves_divider(self, app_with_photos):
        root, app, paths = app_with_photos
        assert self._pair_ready(app, paths)
        app._dev_compare_toggle()          # split
        app._dev_compare_render()
        root_update(app)

        class _Ev:
            pass
        ev = _Ev()
        ev.x = 30                            # near the left edge
        app._dev_compare_drag(ev)
        assert app._dev_split_frac < 0.2
        ev.x = 900                           # far right
        app._dev_compare_drag(ev)
        assert app._dev_split_frac > 0.5

    def test_no_pair_falls_back_to_label(self, app_with_photos):
        root, app, paths = app_with_photos
        app._dev_compare_mode = "split"      # no PIL pair loaded yet
        app._dev_display_current()
        root_update(app)
        assert app._dev_compare_canvas.winfo_manager() == ""


class TestSettingsSearch:
    def test_search_highlights_and_clears(self, app_with_photos):
        root, app, paths = app_with_photos
        app._settings_search_var.set("白平衡")
        app._settings_search()
        assert app._settings_search_hits, "白平衡 labels must be found"
        assert app._settings_search_marked
        app._settings_search_var.set("")
        app._settings_search()
        assert not app._settings_search_hits
        assert not app._settings_search_marked

    def test_search_develop_tab_jumps_module(self, app_with_photos):
        root, app, paths = app_with_photos
        app._show_module("export")
        # 自然饱和度 lives in the Develop adjust panel
        app._settings_search_var.set("自然饱和度")
        app._settings_search()
        assert app._settings_search_hits
        assert app._active_module == "develop"

    def test_search_no_match(self, app_with_photos):
        root, app, paths = app_with_photos
        app._settings_search_var.set("zzz不存在的设置项")
        app._settings_search()
        assert not app._settings_search_hits


class TestPresetBrowser:
    def test_hover_preview_and_leave(self, app_with_photos, tmp_path,
                                     monkeypatch):
        root, app, paths = app_with_photos
        from dataclasses import replace
        from photo_s.engine import ProcessOptions
        from photo_s.gui import app as app_mod
        fake = replace(ProcessOptions(), brightness=1.9,
                       contrast=1.0, saturation=1.0)

        class _FakePresets:
            @staticmethod
            def list_presets():
                return ["demo"]

            @staticmethod
            def load_preset(name):
                return fake if name == "demo" else None

        patch_presets(monkeypatch, _FakePresets)
        app._dev_refresh_presets()
        assert app._dev_preset_list.get(0, "end") == ("demo",)

        class _Ev:
            y = 5
        app._dev_preset_hover(_Ev())
        assert app._dev_preset_preview is fake
        # the sig now renders the preset, not the live sliders
        sig_opts, _p = app._dev_current_sig()
        assert sig_opts is fake
        app._dev_preset_leave()
        assert app._dev_preset_preview is None
        sig_opts, _p = app._dev_current_sig()
        assert sig_opts is not fake

    def test_apply_writes_vars(self, app_with_photos, monkeypatch):
        root, app, paths = app_with_photos
        from dataclasses import replace
        from photo_s.engine import ProcessOptions

        class _FakePresets:
            @staticmethod
            def list_presets():
                return ["demo"]

            @staticmethod
            def load_preset(name):
                return replace(ProcessOptions(), brightness=1.7)

        patch_presets(monkeypatch, _FakePresets)
        app._dev_refresh_presets()
        app._dev_preset_list.selection_set(0)
        app._dev_preset_apply()
        assert float(app.brightness.get()) == pytest.approx(1.7)
        assert app._dev_preset_preview is None


class TestFirstRunGuide:
    def test_guide_shows_once_and_persists(self, app_with_photos):
        import tkinter as tk
        root, app, paths = app_with_photos
        assert not app._first_run_done
        app._show_first_run_guide()
        tops = [w for w in root.winfo_children()
                if isinstance(w, tk.Toplevel)]
        assert tops, "guide card must open"
        # dismiss via protocol (the documented path) sets the flag
        tops[0].tk.call(tops[0].wm_protocol("WM_DELETE_WINDOW"))
        assert app._first_run_done
        app._show_first_run_guide()  # second call is a no-op
        tops2 = [w for w in root.winfo_children()
                 if isinstance(w, tk.Toplevel)]
        assert len(tops2) == len(tops) - 1
        # persisted for next boot
        from photo_s.gui.state import load_state
        assert load_state().get("first_run_done") is True



def patch_presets(monkeypatch, fake):
    """Point BOTH sys.modules and the photo_s.presets package attribute
    at the fake — `from .. import presets` resolves the parent attribute
    first when the submodule was already imported."""
    import photo_s as photo_s_pkg
    monkeypatch.setitem(sys.modules, "photo_s.presets", fake)
    monkeypatch.setattr(photo_s_pkg, "presets", fake)


def root_update(app):
    try:
        app.root.update_idletasks()
        app.root.update()
    except Exception:
        pass




