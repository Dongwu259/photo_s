"""v2.0 workspace tests: module shell + Develop preview panel.

* four modules built at startup, pack-switching keeps widget identity
* active module persists across restarts (gui_state.json)
* Develop: filmstrip auto-builds, the selected photo renders through the
  REAL pipeline (debounced), histogram + exposure readout populate,
  before/after toggle flips the displayed PhotoImage
* Cmd/Ctrl+1..4 switch modules
* Tools module holds one launcher card per workflow
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path, monkeypatch):
    """Hermetic gui_state: without this the app restores the developer's
    real ~/.photos/gui_state.json (geometry, thumbnail size, active
    module) — a polluted 'module' key once flipped the default-module
    assertion, leaked a live Tk root (assertion beat root.destroy) and
    the follow-up focus_force test spun in a native event storm."""
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


def _pump(root, cond, timeout=8.0):
    """Pump the Tk loop until cond() or timeout (after-loop driven code
    needs wall-clock time for the 160ms ticks)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        root.update()
        if cond():
            return True
        time.sleep(0.05)
    return cond()


class TestModuleShell:
    def test_four_modules_built_default_library(self):
        root, app = _make_app()
        assert set(app._module_frames) == {"library", "develop",
                                           "export", "tools"}
        root.update()
        assert app._active_module == "library"
        assert app._module_frames["library"].winfo_ismapped()
        assert not app._module_frames["export"].winfo_ismapped()
        root.destroy()

    def test_switch_keeps_widget_identity(self):
        root, app = _make_app()
        settings_widget = app.quality
        file_lbl = app.file_count_label
        for name in ("develop", "export", "tools", "library"):
            app._show_module(name)
            root.update()
            assert app._active_module == name
            assert app._module_frames[name].winfo_ismapped()
        # nothing destroyed by switching
        assert app.file_count_label is file_lbl
        assert app.quality is settings_widget
        root.destroy()

    def test_module_persists_across_instances(self, monkeypatch, tmp_path):
        import tkinter as tk
        from photo_s.gui import PhotoSApp
        monkeypatch.setenv("HOME", str(tmp_path))
        root, app = _make_app()
        app._show_module("develop")
        app._save_gui_state()
        root.destroy()
        root2 = tk.Tk()
        app2 = PhotoSApp(root2)
        root2.update_idletasks()
        assert app2._active_module == "develop"
        root2.destroy()

    def test_shortcuts_switch_modules(self):
        root, app = _make_app()
        root.update()
        root.focus_force()
        root.update()
        root.event_generate("<Command-2>")
        root.update()
        assert app._active_module == "develop"
        root.event_generate("<Control-4>")
        root.update()
        assert app._active_module == "tools"
        root.destroy()


class TestDevelopPanel:
    def test_filmstrip_builds_and_selects(self, tmp_path):
        root, app = _make_app()
        a = str(tmp_path / "a.jpg")
        _img(tmp_path / "a.jpg", seed=1)
        b = str(tmp_path / "b.jpg")
        _img(tmp_path / "b.jpg", seed=2)
        app._append_files([a, b])
        root.update_idletasks()
        assert len(app._dev_strip_cells) == 2
        assert app._dev_selected  # auto-selected
        app._dev_select(b)
        assert app._dev_selected == b
        root.destroy()

    def test_render_pipeline_and_histogram(self, tmp_path):
        root, app = _make_app()
        a = str(tmp_path / "a.jpg")
        _img(tmp_path / "a.jpg", seed=3)
        app._append_files([a])
        app._show_module("develop")
        root.update_idletasks()
        ok = _pump(root, lambda: (
            app._dev_render_state["after_photo"] is not None
            and app._dev_render_state["rendered"] is not None))
        assert ok, "develop render must complete (debounce + pipeline)"
        st = app._dev_render_state
        assert st["before_photo"] is not None
        # histogram + readouts populated from the processed output
        assert len(app._dev_hist.find_all()) > 0
        assert app._dev_expo_lbl.cget("text")
        assert app._dev_kelvin_lbl.cget("text")
        # status label cleared after success
        assert not app._dev_status_lbl.cget("text")
        app._on_main_close()

    def test_before_after_toggle(self, tmp_path):
        root, app = _make_app()
        a = str(tmp_path / "a.jpg")
        _img(tmp_path / "a.jpg", seed=4)
        app._append_files([a])
        app._show_module("develop")
        root.update_idletasks()
        assert _pump(root, lambda: (
            app._dev_render_state["after_photo"] is not None))
        st = app._dev_render_state
        after = app._dev_image_lbl.image
        assert after is st["after_photo"]
        app._dev_toggle_view()
        assert app._dev_show_before.get() is True
        assert app._dev_image_lbl.image is st["before_photo"]
        app._dev_toggle_view()
        assert app._dev_image_lbl.image is st["after_photo"]
        app._on_main_close()

    def test_no_files_placeholder(self):
        root, app = _make_app()
        app._show_module("develop")
        root.update_idletasks()
        assert app._dev_image_lbl.cget("text")  # no-selection hint visible
        root.destroy()


class TestToolsPanel:
    def test_one_card_per_workflow(self):
        root, app = _make_app()
        app._show_module("tools")
        root.update_idletasks()
        assert len(app.TOOLS_CARDS) == 12
        grid = app._module_frames["tools"].winfo_children()[0]\
            .winfo_children()[0]
        cards = [w for w in grid.winfo_children()]
        assert len(cards) == 12
        root.destroy()

class TestSettingsSplit:
    """v2.0 IA: edit tools live in Develop (beside the preview), output
    settings live in Export — one shared set of tk.Variables behind."""

    def test_adjust_controls_in_develop(self):
        import tkinter as tk
        from tkinter import ttk
        root, app = _make_app()
        dev = app._module_frames["develop"]
        exp = app._module_frames["export"]
        widgets_dev = list(app._walk_widgets(dev))
        widgets_exp = list(app._walk_widgets(exp))
        # grading sliders (brightness/contrast/…/clarity) → Develop
        sliders = [w for w in widgets_dev if isinstance(w, ttk.Scale)]
        assert len(sliders) >= 5, "adjust sliders must live in Develop"
        # output format combo → Export
        assert app.format_combo in widgets_exp, \
            "output controls must live in Export"
        assert app.format_combo not in widgets_dev
        root.destroy()

    def test_shared_variables_drive_both(self):
        root, app = _make_app()
        # the same variable backs the Develop slider and the pipeline:
        # moving it changes _build_options output
        app.brightness.set(1.5)
        opts = app._build_options()
        assert abs(opts.brightness - 1.5) < 1e-9
        root.destroy()


class TestExportQueue:
    def test_queue_lists_checked_files(self, tmp_path):
        import tkinter as tk
        root, app = _make_app()
        a = str(tmp_path / "a.jpg")
        _img(tmp_path / "a.jpg", seed=7)
        b = str(tmp_path / "b.jpg")
        _img(tmp_path / "b.jpg", seed=8)
        app._append_files([a, b])
        app._show_module("export")
        root.update_idletasks()
        rows = [w for w in app._export_queue_inner.winfo_children()
                if isinstance(w, tk.Frame)]
        assert len(rows) == 3, "2 photo rows + total footer"
        app._toggle_check(a)               # uncheck one
        app._refresh_export_queue()
        rows = [w for w in app._export_queue_inner.winfo_children()
                if isinstance(w, tk.Frame)]
        assert len(rows) == 2, "1 photo row + footer after uncheck"
        app._toggle_check(b)
        app._refresh_export_queue()
        labels = [w for w in app._export_queue_inner.winfo_children()
                  if isinstance(w, tk.Label)]
        assert any(app._t("export_queue_empty") in w.cget("text")
                   for w in labels), "empty state shown when none checked"
        root.destroy()
