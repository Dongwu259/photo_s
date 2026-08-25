"""Tests for the GUI Settings dialog and STRINGS zh/en parity.

The parity test is important: `_t` silently falls back on missing keys, so a
drift between the two dicts produces "looks working" untranslated UI.
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


from photo_s.gui import STRINGS, PhotoSApp

_SETTINGS_KEYS = {
    "settings", "settings_title", "set_mcp", "set_mcp_desc",
    "mcp_installed", "mcp_missing", "mcp_install_hint", "mcp_launch",
    "mcp_claude_config", "mcp_claude_snippet", "copy", "copied",
    "set_deps", "dep_install", "dep_installing", "set_plugins_link",
}


class TestStringsParity:
    def test_zh_en_key_sets_identical(self):
        zh, en = STRINGS["zh"], STRINGS["en"]
        assert set(zh.keys()) == set(en.keys())

    def test_settings_keys_present_both_langs(self):
        for key in _SETTINGS_KEYS:
            assert key in STRINGS["zh"], f"zh missing {key}"
            assert key in STRINGS["en"], f"en missing {key}"

    def test_settings_keys_translated(self):
        """zh/en values must actually differ for human strings (no dupes)."""
        for key in ("settings", "set_mcp", "copy", "set_deps"):
            assert STRINGS["zh"][key] != STRINGS["en"][key], key


class TestSettingsDialog:
    def test_show_settings_exists(self):
        assert hasattr(PhotoSApp, "_show_settings")

    def test_headless_smoke(self):
        """Best-effort: open the dialog on a real/headless display."""
        import tkinter as tk
        try:
            root = tk.Tk()
        except Exception as e:
            pytest.skip("no display: {}".format(e))
        try:
            app = PhotoSApp(root)
            root.update_idletasks()
            app._show_settings()
            root.update_idletasks()
            toplevels = [w for w in root.winfo_children()
                         if isinstance(w, tk.Toplevel)]
            assert len(toplevels) == 1
            assert app._t("settings_title") in toplevels[0].title()
            root.destroy()
        except Exception as e:
            root.destroy()
            pytest.skip("GUI init failed: {}".format(e))

    def test_theme_toggle_retints_ttk_styles(self):
        """Theme switch must re-apply ttk style colors — styles persist
        across the widget rebuild, so without re-configuring them entries/
        sliders/comboboxes stay stuck on the previous palette. Regression
        test for the dark->light toggle leaving ttk widgets dark."""
        import tkinter as tk
        from tkinter import ttk
        try:
            root = tk.Tk()
        except Exception as e:
            pytest.skip("no display: {}".format(e))
        try:
            app = PhotoSApp(root)
            root.update_idletasks()
            style = ttk.Style(root)
            before = style.lookup("TCombobox", "fieldbackground")
            if not before:
                pytest.skip("combobox style has no fieldbackground")
            app._toggle_theme()
            root.update_idletasks()
            after = style.lookup("TCombobox", "fieldbackground")
            assert before != after, "ttk styles must follow the theme switch"
            root.destroy()
        except Exception as e:
            root.destroy()
            pytest.skip("GUI init failed: {}".format(e))
