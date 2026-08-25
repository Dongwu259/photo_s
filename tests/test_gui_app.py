"""GUI app-level regression tests (real Tk when a display is available).

Covers bugs found in the full gui.py audit: after-callbacks touching
destroyed widgets, the FlatButton API contract, _build_options mapping,
and the file-list dimensions cache.
"""

import os
import sys

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


class TestCopyText:
    def test_dialog_closed_before_flash_restore(self):
        """Closing the dialog within the 1.2s copy-flash window must not
        raise (regression: TclError 'invalid command name' when the after
        callback touched the destroyed button)."""
        import time
        import tkinter as tk
        from photo_s.gui import FlatButton
        root, app = _make_app()
        win = tk.Toplevel(root)
        btn = FlatButton(win, text="Copy", command=lambda: None, bg="#111111")
        btn.pack()
        root.update()
        app._copy_text(win, "hello", btn)
        win.destroy()
        time.sleep(1.3)   # let the 1.2s after callback come due
        root.update()     # deliver it (must not raise)
        root.destroy()


class TestFlatButton:
    def test_state_roundtrip_and_forwarding(self):
        from photo_s.gui import FlatButton
        root, app = _make_app()
        hits = []
        btn = FlatButton(root, text="Go", command=lambda: hits.append(1),
                         bg="#111111", fg="#eeeeee")
        btn.pack()
        root.update()
        assert btn.cget("text") == "Go"
        btn.configure(text="Wait", state="disabled")
        assert btn.cget("state") == "disabled"
        btn._on_click(None)
        assert hits == [], "disabled button must block clicks"
        btn._on_enter(None)
        assert btn.cget("bg") == "#111111", "no hover while disabled"
        btn.configure(state="normal")
        btn._on_click(None)
        assert hits == [1]
        # hover swaps the rendered fill
        btn.configure(hover_bg="#555555")
        btn._on_enter(None)
        assert btn.cget("bg") == "#555555"
        btn._on_leave(None)
        assert btn.cget("bg") == "#111111"
        root.destroy()

    def test_pill_drawn(self):
        """The canvas must hold a rounded shape + text, sized to the label."""
        from photo_s.gui import FlatButton
        root, app = _make_app()
        btn = FlatButton(root, text="Abc", command=lambda: None,
                         bg="#111111", border_color="#ff0000")
        btn.pack()
        root.update()
        # height floor is low: the default 11pt font can render a short
        # canvas on Windows (observed 8px) — the canvas still must have size.
        # Requested size, not winfo_width(): a bare Xvfb (no window manager)
        # never maps the toplevel, so the mapped size stays 1 — the request
        # is what _measure_and_redraw actually sized.
        assert btn.winfo_reqwidth() > 10 and btn.winfo_reqheight() >= 6
        assert len(btn.find_all()) == 2, "one rounded rect + one text item"
        btn.configure(text="A much longer label")
        root.update()
        assert btn.winfo_reqwidth() > 60, "canvas must resize with the text"
        root.destroy()


class TestBuildOptions:
    def test_mapping_smoke(self):
        """Key tk.Variables must map onto ProcessOptions fields."""
        root, app = _make_app()
        app.max_width.set("640")
        app.max_height.set("480")
        app.quality.set(72)
        app.denoise.set("12")
        app.strip_gps.set(True)
        app.date_shift.set("-5h")
        app.wb_temp.set("5600")
        app.log_curve.set("SLOG3")
        opts = app._build_options()
        assert opts.max_width == 640 and opts.max_height == 480
        assert opts.quality == 72
        assert opts.denoise == 12.0
        assert opts.strip_gps is True
        assert opts.date_shift == "-5h"
        assert opts.wb_temp == 5600.0
        assert opts.log_curve == "SLOG3"
        # blank fields stay off
        assert opts.crop is None and opts.crop_ratio is None
        assert opts.auto_exposure is None and opts.gpx_trace is None
        root.destroy()

    def test_grading_fields_roundtrip(self):
        """v1.6.0 LR-grading tk.Variables map to ProcessOptions and back."""
        root, app = _make_app()
        app.wb_tint.set("15")
        app.levels.set("80,200,1.1")
        app.curves.set("0,0;128,140;255,255")
        app.vibrance.set("0.4")
        app.color_grading.set("shadows:120,0.3")
        app.hsl.set("green:10,0.2,0.1")
        app.clarity.set("0.3")
        app.texture.set("0.2")
        app.dehaze.set("0.5")
        app.vignette.set("0.4,0.4,0.4")
        app.grain.set("0.1,1.5")
        opts = app._build_options()
        assert opts.wb_tint == 15.0
        assert opts.levels == "80,200,1.1"
        assert opts.curves == "0,0;128,140;255,255"
        assert opts.vibrance == 0.4
        assert opts.color_grading == "shadows:120,0.3"
        assert opts.hsl == "green:10,0.2,0.1"
        assert opts.clarity == 0.3 and opts.texture == 0.2
        assert opts.dehaze == 0.5
        assert opts.vignette == "0.4,0.4,0.4"
        assert opts.grain == "0.1,1.5"
        # a fresh app keeps the new fields off by default
        app2 = _make_app()[1]
        assert app2._build_options().wb_tint == 0.0
        assert app2._build_options().levels == ""
        # options → UI (preset load path)
        app2._apply_options_to_ui(opts)
        assert app2.curves.get() == "0,0;128,140;255,255"
        assert app2.vibrance.get() == "0.4"
        assert app2.color_grading.get() == "shadows:120,0.3"
        root.destroy()

    def test_v17_fields_roundtrip(self):
        """v1.7.0 local-adjustment / lens fields map both directions."""
        root, app = _make_app()
        app.point_color.set("200,120,80:30,0.2,-0.1,0.2")
        app.masks.set("sky:linear:0.5,0,0.5,1,feather=0.3")
        app.mask_adjust.set("sky:exposure=-0.7")
        app.lens_distort.set("0.15")
        app.lens_vignette.set("0.3,0.4")
        app.lens_ca.set("0.999,1.001")
        opts = app._build_options()
        assert opts.point_color == "200,120,80:30,0.2,-0.1,0.2"
        assert opts.masks == "sky:linear:0.5,0,0.5,1,feather=0.3"
        assert opts.mask_adjust == "sky:exposure=-0.7"
        assert opts.lens_distort == 0.15
        assert opts.lens_vignette == "0.3,0.4"
        assert opts.lens_ca == "0.999,1.001"
        # fresh app: all off
        app2 = _make_app()[1]
        o2 = app2._build_options()
        assert o2.point_color == "" and o2.masks == ""
        assert o2.lens_distort == 0.0 and o2.lens_ca == ""
        # options -> UI
        app2._apply_options_to_ui(opts)
        assert app2.point_color.get() == "200,120,80:30,0.2,-0.1,0.2"
        assert app2.masks.get() == "sky:linear:0.5,0,0.5,1,feather=0.3"
        assert app2.lens_distort.get() == "0.15"
        root.destroy()

    def test_point_color_ok_writes_spec(self):
        """_point_color_ok serializes targets back to the compact spec."""
        root, app = _make_app()
        app._point_color_ok(None, [(200, 120, 80, 30.0, 0.2, -0.1, 0.2),
                                   (10, 10, 240, -20.0, 0.0, 0.1, 0.1)])
        assert app.point_color.get() == (
            "200,120,80:30,0.2,-0.1,0.2;10,10,240:-20,0,0.1,0.1")
        root.destroy()

    def test_masks_ok_writes_specs(self):
        """_masks_ok serializes masks + adjustments back to compact specs."""
        root, app = _make_app()
        specs = [("sky", "linear", [0.5, 0.0, 0.5, 1.0], 0.3, False),
                 ("spot", "radial", [0.5, 0.5, 0.3, 0.4], 0.0, True)]
        adjusts = {"sky": {"exposure": -0.7, "saturation": 0.2},
                   "gone": {"brightness": 1.0}}  # stale name is dropped
        app._masks_ok(None, specs, adjusts)
        assert app.masks.get() == (
            "sky:linear:0.5,0,0.5,1,feather=0.3;"
            "spot:radial:0.5,0.5,0.3,0.4,invert")
        assert app.mask_adjust.get() == "sky:exposure=-0.7,saturation=0.2"
        root.destroy()

    def test_masks_ok_v18_specs_roundtrip(self):
        """v1.8 kinds (combo/object/subject/negative brush) must serialize
        without crashing and round-trip through the engine parser."""
        from photo_s.mask import parse_masks
        root, app = _make_app()
        specs = [("c1", "combo", ["sky", "&", "face"], 0.3, False),
                 ("car", "object", ["car"], 0.0, False),
                 ("sub", "subject", [], 0.2, True),
                 ("br", "brush", [(0.5, 0.5, 0.05), (0.6, 0.6, -0.04)],
                  0.0, False)]
        app._masks_ok(None, specs, {})
        parsed = parse_masks(app.masks.get())
        by_name = {s.name: s for s in parsed}
        assert by_name["c1"].kind == "combo"
        assert by_name["c1"].params == ("sky", "&", "face")
        assert by_name["c1"].feather == pytest.approx(0.3)
        assert by_name["car"].params == ("car",)
        assert by_name["sub"].invert is True
        assert by_name["br"].params == ((0.5, 0.5, 0.05), (0.6, 0.6, -0.04))
        root.destroy()


class TestFileList:
    def test_dims_cached_across_refreshes(self):
        """Image dims must be cached per (path, size, mtime) — re-refreshing
        the list must not re-open every image (RAW open is slow)."""
        import tempfile
        from PIL import Image
        root, app = _make_app()
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "a.jpg")
            Image.new("RGB", (30, 20)).save(p)
            app.files = [p]
            app._refresh_file_list()
            assert app._dims_cache, "cache must be populated"
            first = dict(app._dims_cache)
            app._refresh_file_list()
            assert app._dims_cache == first, "re-refresh must hit the cache"
        root.destroy()


class TestMaskWorkflow:
    def test_workflow_opens_with_v18_specs_and_closes_safely(self, tmp_path):
        """打开工作流：combo/brush/字符串键调整解析 + 叠加渲染；
        快速关窗不崩（win.after 回调的 winfo_exists 防护）。"""
        import tkinter as tk
        from PIL import Image
        root, app = _make_app()
        p = os.path.join(str(tmp_path), "a.jpg")
        Image.new("RGB", (60, 40), (100, 120, 140)).save(p)
        app.files = [p]
        app._checked = {p}
        app._photo_masks = None
        app.masks.set("sky:linear:0,0,1,0,feather=0.3;"
                      "c:combo:sky&f;f:brush:0.5,0.5,0.05")
        app.mask_adjust.set("sky:brightness=0.5;"
                            "sky:curves={r:0,0;128,140;255,255}")
        app._open_mask_workflow()
        root.update()
        wins = [w for w in root.winfo_children()
                if isinstance(w, tk.Toplevel)]
        assert wins, "workflow window must open"
        wins[0].destroy()
        root.update()  # 触发 pending after 回调，winfo_exists 防护拦截
        root.destroy()

    def test_workflow_with_no_checked_files_is_noop(self, monkeypatch):
        """空勾选 → 警告提示而非崩溃（self._flash 不存在——回归）。"""
        import tkinter as tk
        from tkinter import messagebox
        warns = []
        monkeypatch.setattr(messagebox, "showwarning",
                            lambda *a, **k: warns.append(a) or None)
        root, app = _make_app()
        app.files = []
        app._checked = set()
        app._open_mask_workflow()
        root.update()
        assert warns, "must warn when no photos are checked"
        wins = [w for w in root.winfo_children()
                if isinstance(w, tk.Toplevel)]
        assert not wins, "no checked files must not open a window"
        root.destroy()
