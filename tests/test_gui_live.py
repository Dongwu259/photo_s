"""v2.0 live-switch tests: language / theme without UI rebuild.

The pre-v2.0 switches destroyed and rebuilt every widget. Now the tree
is retranslated / recolored in place — these tests pin the new contract:

* widget identity survives a switch (same object, still usable)
* every static string remaps to the new language (no stale zh text)
* palette values remap to the new theme
* the system-appearance follower flips on change, a manual toggle pins
* UiBus (bus.py) semantics, headless
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


def _texts(app):
    """All text-option values in the main window tree."""
    import tkinter as tk
    out = []
    for w in app._walk_widgets(app.root):
        try:
            t = w.cget("text")
        except tk.TclError:
            continue
        if isinstance(t, str):
            out.append(t)
    return out


class TestLiveLanguageSwitch:
    def test_widgets_survive_and_retranslate(self):
        from photo_s.gui import STRINGS
        root, app = _make_app()
        app._set_language("zh")
        progress = app.progress_label
        count = app.file_count_label
        app._set_language("en")
        root.update_idletasks()
        # identity: same widget objects, never destroyed
        assert app.progress_label is progress
        assert app.file_count_label is count
        assert app.progress_label.winfo_exists()
        # every static zh string remapped (zh-only values must be gone)
        zh_only = set(STRINGS["zh"].values()) - set(STRINGS["en"].values())
        stale = [t for t in _texts(app) if t in zh_only]
        assert stale == [], "stale zh strings after live switch: %r" % stale
        # dynamic count label recomputed in the new language
        assert "file" in app.file_count_label.cget("text")
        # combobox selector synced
        assert app.lang_combo.get() == "English"
        root.destroy()

    def test_switch_back_and_forth_keeps_identity(self):
        root, app = _make_app()
        btn = app.theme_btn
        app._set_language("en")
        app._set_language("zh")
        app._set_language("en")
        assert app.theme_btn is btn and btn.winfo_exists()
        root.destroy()

    def test_translation_remap_majority_vote(self):
        from photo_s.gui.app import PhotoSApp
        remap = PhotoSApp._translation_remap("zh", "en")
        # a known key remaps
        assert remap[STRINGS_ZH_SUBTITLE] == STRINGS_EN_SUBTITLE
        # zh "亮度" backs three keys (Brightness ×2, HSL Lum ×1) — the
        # majority target wins, the text must not be dropped
        assert remap["亮度"] == "Brightness"

    def test_early_return_on_same_language(self):
        root, app = _make_app()
        before = app.progress_label
        app._set_language(app.lang)          # no-op
        assert app.progress_label is before
        root.destroy()


STRINGS_ZH_SUBTITLE = "批量图片压缩与格式转换工具"
STRINGS_EN_SUBTITLE = "Batch Image Compression & Conversion"


class TestLiveThemeSwitch:
    def test_palette_recolored_without_rebuild(self):
        from photo_s.gui import COLORS
        root, app = _make_app()
        progress = app.progress_label
        root_bg_before = root.cget("bg")
        app._toggle_theme()
        root.update_idletasks()
        # identity preserved
        assert app.progress_label is progress
        assert app.progress_label.winfo_exists()
        # root + widget tree follow the new palette
        assert root.cget("bg") == COLORS["bg"]
        assert root_bg_before != COLORS["bg"]
        # theme icon flipped
        assert app.theme_btn.cget("text") in ("☀️", "🌙")
        app._toggle_theme()   # restore for later tests
        root.destroy()

    def test_manual_toggle_pins_system_follower(self, monkeypatch):
        root, app = _make_app()
        app._toggle_theme()                     # manual → pin
        pinned = app.dark_mode
        monkeypatch.setattr(
            "photo_s.gui.app._system_dark_mode",
            lambda: not pinned)                 # system "flips"
        app._recheck_system_theme()
        assert app.dark_mode == pinned, "manual choice must win"
        root.destroy()

    def test_follower_flips_on_system_change(self, monkeypatch):
        from photo_s.gui import COLORS
        root, app = _make_app()
        assert app._theme_user_override is False
        want = not app.dark_mode
        monkeypatch.setattr(
            "photo_s.gui.app._system_dark_mode", lambda: want)
        app._recheck_system_theme()
        root.update_idletasks()
        assert app.dark_mode == want
        assert root.cget("bg") == COLORS["bg"]
        root.destroy()


class TestUiBus:
    """Headless UiBus semantics via a fake widget."""

    class _FakeWin:
        def __init__(self, alive=True):
            self.alive = alive
            self.after_calls = []

        def winfo_exists(self):
            return self.alive

        def after(self, ms, fn):
            self.after_calls.append((ms, fn))

    def test_schedule_then_manual_drain_runs_callbacks(self):
        from photo_s.gui.bus import UiBus
        win = self._FakeWin()
        bus = UiBus(win)
        ran = []
        bus.schedule(lambda: ran.append(1))
        bus._drain()
        assert ran == [1]

    def test_dead_widget_does_not_rearm(self):
        from photo_s.gui.bus import UiBus
        win = self._FakeWin(alive=False)
        bus = UiBus(win)
        ran = []
        bus.schedule(lambda: ran.append(1))
        bus._drain()
        assert ran == [], "callbacks must not run into a dead widget"
        assert bus._running is False
        assert win.after_calls == []

    def test_stop_halts_loop(self):
        from photo_s.gui.bus import UiBus
        win = self._FakeWin()
        bus = UiBus(win)
        bus.start()
        assert bus._running is True
        assert win.after_calls, "loop must re-arm while alive"
        bus.stop()
        bus._drain()
        assert bus._running is False

    def test_drain_pending_runs_once_without_rearm(self):
        from photo_s.gui.bus import UiBus
        win = self._FakeWin()
        bus = UiBus(win)
        ran = []
        bus.schedule(lambda: ran.append(1))
        bus.drain_pending()
        assert ran == [1]
        assert win.after_calls == []
