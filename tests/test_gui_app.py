"""GUI app-level regression tests (real Tk when a display is available).

Covers bugs found in the full gui.py audit: after-callbacks touching
destroyed widgets, the FlatButton API contract, _build_options mapping,
and the file-list dimensions cache.
"""

import os
import sys

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
        # canvas on Windows (observed 8px) — the canvas still must have size
        assert btn.winfo_width() > 10 and btn.winfo_height() >= 6
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
