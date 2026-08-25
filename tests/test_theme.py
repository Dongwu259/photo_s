"""v2.0 GUI theme/state tests — headless (no Tk window needed).

* palette parity: light/dark tokens must expose identical key sets
  (a missing key reads as "works" but paints a stale color)
* dark-mode detection: PHOTOS_DARK override + the Linux paths
  (gsettings / kdeglobals) faked — real desktops vary on CI
* ThumbCache: byte-bounded LRU semantics the thumbnail drain relies on
* gui_state.json round-trip against an isolated HOME
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from photo_s.gui.state import ThumbCache, load_state, save_state, state_file
from photo_s.gui.theme import (
    COLORS, SPACING, RADIUS,
    _DARK_COLORS, _LIGHT_COLORS, _apply_palette, _linux_dark_mode,
    _system_dark_mode, apply_dpi_awareness,
)


class TestPaletteParity:
    def test_light_dark_key_sets_identical(self):
        assert set(_LIGHT_COLORS.keys()) == set(_DARK_COLORS.keys())

    def test_apply_palette_flips_colors_in_place(self):
        try:
            _apply_palette(True)
            assert COLORS["bg"] == _DARK_COLORS["bg"]
            assert set(COLORS.keys()) == set(_LIGHT_COLORS.keys())
            _apply_palette(False)
            assert COLORS["bg"] == _LIGHT_COLORS["bg"]
        finally:
            # restore whatever the system appearance implies
            _apply_palette(_system_dark_mode())

    def test_layout_tokens_present(self):
        assert set(SPACING) == {"xs", "s", "m", "l", "xl"}
        assert set(RADIUS) == {"pill", "card", "input"}


class TestDarkDetection:
    def test_photos_dark_env_override(self, monkeypatch):
        monkeypatch.setenv("PHOTOS_DARK", "1")
        assert _system_dark_mode() is True
        monkeypatch.setenv("PHOTOS_DARK", "0")
        assert _system_dark_mode() is False
        monkeypatch.setenv("PHOTOS_DARK", "nope")
        assert _system_dark_mode() is False

    def test_linux_gsettings_prefer_dark(self, monkeypatch):
        class _R:
            stdout = "'prefer-dark'\n"
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(
            "photo_s.gui.theme.subprocess.run", lambda *a, **k: _R())
        assert _system_dark_mode() is True

    def test_linux_gsettings_prefer_light(self, monkeypatch):
        class _R:
            stdout = "'prefer-light'\n"
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(
            "photo_s.gui.theme.subprocess.run", lambda *a, **k: _R())
        assert _system_dark_mode() is False

    def test_linux_falls_back_to_kdeglobals(self, monkeypatch, tmp_path):
        def _no_gsettings(*a, **k):
            raise FileNotFoundError("no gsettings")
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(
            "photo_s.gui.theme.subprocess.run", _no_gsettings)
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / ".config").mkdir()
        (tmp_path / ".config" / "kdeglobals").write_text(
            "[General]\nColorScheme=BreezeDark\n", encoding="utf-8")
        assert _linux_dark_mode() is True

    def test_linux_unknown_desktop_is_light(self, monkeypatch, tmp_path):
        def _no_gsettings(*a, **k):
            raise FileNotFoundError("no gsettings")
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(
            "photo_s.gui.theme.subprocess.run", _no_gsettings)
        monkeypatch.setenv("HOME", str(tmp_path))  # no kdeglobals either
        assert _linux_dark_mode() is False

    def test_dpi_awareness_never_raises_off_windows(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        apply_dpi_awareness()  # no-op
        monkeypatch.setattr(sys, "platform", "win32")
        apply_dpi_awareness()  # no windll on this host — must swallow


class TestThumbCache:
    @staticmethod
    def _img(w, h):
        from PIL import Image
        return Image.new("RGB", (w, h))

    def test_lru_evicts_oldest_first(self):
        c = ThumbCache(max_bytes=4 * 27)  # room for four 3x3 images
        for i in range(5):
            c[i] = self._img(3, 3)
        assert len(c) == 4
        assert 0 not in c and 1 in c and 4 in c

    def test_access_refreshes_recency(self):
        c = ThumbCache(max_bytes=4 * 27)
        for i in range(4):
            c[i] = self._img(3, 3)
        assert 0 in c                  # exactly full — no eviction yet
        c[4] = self._img(3, 3)         # 5th insert evicts the LRU (0)
        assert 0 not in c and 4 in c
        c[5] = self._img(3, 3)         # evicts 1
        c[6] = self._img(3, 3)         # evicts 2
        assert 1 not in c and 2 not in c and 3 in c

    def test_touch_before_evict_keeps_entry(self):
        c = ThumbCache(max_bytes=4 * 27)
        for i in range(4):
            c[i] = self._img(3, 3)
        assert c[0] is not None          # touch → most-recent
        c[9] = self._img(3, 3)          # evicts 1, not 0
        assert 0 in c and 1 not in c

    def test_false_marker_costs_nothing(self):
        c = ThumbCache(max_bytes=27)
        c["ok"] = self._img(3, 3)
        c["bad"] = False
        assert "bad" in c and c.get("bad") is False
        assert c.bytes == 27

    def test_overwrite_updates_footprint(self):
        c = ThumbCache(max_bytes=100 * 100 * 3)
        c["k"] = self._img(100, 100)
        assert c.bytes == 100 * 100 * 3
        c["k"] = self._img(10, 10)
        assert c.bytes == 10 * 10 * 3

    def test_clear_and_get_default(self):
        c = ThumbCache()
        c["k"] = self._img(2, 2)
        c.clear()
        assert len(c) == 0
        assert c.get("missing") is None
        assert c.get("missing", "d") == "d"


class TestGuiState:
    def test_roundtrip(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        save_state({"geometry": "1120x720+10+20", "thumb_size": 144})
        assert state_file() == tmp_path / ".photos" / "gui_state.json"
        assert load_state() == {"geometry": "1120x720+10+20",
                                "thumb_size": 144}

    def test_missing_file_returns_empty_dict(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        assert load_state() == {}

    def test_corrupt_file_returns_empty_dict(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        p = tmp_path / ".photos" / "gui_state.json"
        p.parent.mkdir(parents=True)
        p.write_text("{not json", encoding="utf-8")
        assert load_state() == {}
