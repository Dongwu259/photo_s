"""Tests for photo_s/i18n.py — language detection, resolution, STRINGS table.

Covers: cross-platform detection (macOS/Windows/Linux), the precedence chain
(flag > env > config > persisted > system > en), CLI help rendering purity
(en has no CJK / zh has CJK), JSON output purity, config ``language`` key,
and GUI persistence.
"""

import re
import sys

import pytest

from photo_s import i18n


# ── helpers ─────────────────────────────────────────────────────────────────

CJK = re.compile(r"[一-鿿　-〿＀-￯]")


@pytest.fixture(autouse=True)
def _reset_detect():
    """Each test gets a fresh detection cache."""
    i18n._detect_cache = None
    yield
    i18n._detect_cache = None


# ── detect_system_language ──────────────────────────────────────────────────

class TestDetectSystemLanguage:
    def test_linux_env_zh(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.delenv("LANG", raising=False)
        monkeypatch.setenv("LANG", "zh_CN.UTF-8")
        assert i18n.detect_system_language() == "zh"

    def test_linux_env_en(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.delenv("LANG", raising=False)
        monkeypatch.setenv("LC_ALL", "en_US.UTF-8")
        assert i18n.detect_system_language() == "en"

    def test_lc_all_beats_lang(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setenv("LC_ALL", "en_US.UTF-8")
        monkeypatch.setenv("LANG", "zh_CN.UTF-8")
        assert i18n.detect_system_language() == "en"  # LC_ALL wins

    def test_macos_apple_languages_zh(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.delenv("LANG", raising=False)

        class _Proc:
            stdout = '(\n    "zh-Hans-CN"\n)'
        monkeypatch.setattr(i18n.subprocess, "run", lambda *a, **k: _Proc())
        assert i18n.detect_system_language() == "zh"

    def test_macos_apple_languages_en(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.delenv("LANG", raising=False)

        class _Proc:
            stdout = '(\n    "en"\n)'
        monkeypatch.setattr(i18n.subprocess, "run", lambda *a, **k: _Proc())
        assert i18n.detect_system_language() == "en"

    def test_macos_subprocess_failure_falls_through(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.delenv("LANG", raising=False)

        def _boom(*a, **k):
            raise OSError("defaults not found")
        monkeypatch.setattr(i18n.subprocess, "run", _boom)
        # falls through to locale fallback / "en" — never crashes
        assert i18n.detect_system_language() in ("en", "zh")

    def test_windows_lcid_zh(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.delenv("LANG", raising=False)

        class _Kernel32:
            def GetUserDefaultUILanguage(self):
                return 0x0804  # zh-CN
        class _Ctypes:
            windll = type("W", (), {"kernel32": _Kernel32()})()
        monkeypatch.setitem(sys.modules, "ctypes", _Ctypes())
        assert i18n.detect_system_language() == "zh"

    def test_windows_lcid_en_falls_through(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.delenv("LANG", raising=False)

        class _Kernel32:
            def GetUserDefaultUILanguage(self):
                return 0x0409  # en-US
        class _Ctypes:
            windll = type("W", (), {"kernel32": _Kernel32()})()
        monkeypatch.setitem(sys.modules, "ctypes", _Ctypes())
        monkeypatch.setattr(i18n, "_locale_module_language", lambda: None)
        # en-US LCID is not zh → falls through to locale (mocked empty) / "en"
        assert i18n.detect_system_language() == "en"

    def test_windows_windll_never_on_posix(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.delenv("LANG", raising=False)

        def _boom(*a, **k):
            raise AssertionError("windll must not be touched on POSIX")
        monkeypatch.setattr(i18n, "_windows_ui_language", _boom)
        # should not call the windows branch at all on linux
        i18n.detect_system_language()

    def test_empty_env_falls_back_en(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        for var in ("LANG", "LC_ALL", "LC_MESSAGES"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setattr(i18n, "_locale_module_language", lambda: None)
        assert i18n.detect_system_language() == "en"

    def test_never_raises(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")

        def _boom(*a, **k):
            raise RuntimeError("anything")
        monkeypatch.setattr(i18n, "_env_language", _boom)
        monkeypatch.setattr(i18n, "_locale_module_language", _boom)
        assert i18n.detect_system_language() == "en"


# ── resolve_language precedence chain ───────────────────────────────────────

class TestResolveLanguage:
    def test_explicit_beats_everything(self, monkeypatch):
        monkeypatch.setenv("PHOTO_S_LANG", "en")
        monkeypatch.setattr(i18n, "_system_language", lambda: "zh")
        assert i18n.resolve_language("zh") == "zh"

    def test_env_second(self, monkeypatch):
        monkeypatch.setenv("PHOTO_S_LANG", "en")
        monkeypatch.setattr(i18n, "_system_language", lambda: "zh")
        assert i18n.resolve_language(None) == "en"

    def test_auto_falls_through(self, monkeypatch):
        monkeypatch.delenv("PHOTO_S_LANG", raising=False)
        monkeypatch.setattr(i18n, "_system_language", lambda: "zh")
        assert i18n.resolve_language("auto") == "zh"

    def test_invalid_falls_through(self, monkeypatch):
        monkeypatch.delenv("PHOTO_S_LANG", raising=False)
        monkeypatch.setattr(i18n, "_system_language", lambda: "zh")
        assert i18n.resolve_language("fr") == "zh"

    def test_config_key_zh(self, monkeypatch, tmp_path, capsys):
        monkeypatch.delenv("PHOTO_S_LANG", raising=False)
        cfg = tmp_path / "photo-s.toml"
        cfg.write_text("[options]\nlanguage = \"zh\"\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        assert i18n.resolve_language(None) == "zh"

    def test_config_key_ignored_when_disabled(self, monkeypatch, tmp_path):
        monkeypatch.delenv("PHOTO_S_LANG", raising=False)
        monkeypatch.setattr(i18n, "_system_language", lambda: "en")
        cfg = tmp_path / "photo-s.toml"
        cfg.write_text("[options]\nlanguage = \"zh\"\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        assert i18n.resolve_language(None, use_config=False) == "en"

    def test_persisted_beats_detect(self, monkeypatch):
        monkeypatch.delenv("PHOTO_S_LANG", raising=False)
        monkeypatch.setattr(i18n, "_system_language", lambda: "zh")
        monkeypatch.setattr(i18n, "load_persisted_language", lambda: "en")
        assert i18n.resolve_language(None, use_persisted=True) == "en"

    def test_persisted_only_when_gated(self, monkeypatch):
        monkeypatch.delenv("PHOTO_S_LANG", raising=False)
        monkeypatch.setattr(i18n, "_system_language", lambda: "zh")
        monkeypatch.setattr(i18n, "load_persisted_language", lambda: "en")
        assert i18n.resolve_language(None, use_persisted=False) == "zh"

    def test_final_fallback_en(self, monkeypatch):
        monkeypatch.delenv("PHOTO_S_LANG", raising=False)
        monkeypatch.setattr(i18n, "_system_language", lambda: "en")
        monkeypatch.setattr(i18n, "load_persisted_language", lambda: None)
        assert i18n.resolve_language(None, use_persisted=True) == "en"


# ── STRINGS table ───────────────────────────────────────────────────────────

class TestStrings:
    def test_zh_en_key_sets_identical(self):
        assert set(i18n.STRINGS["zh"]) == set(i18n.STRINGS["en"])

    def test_no_positional_placeholders(self):
        # _t uses .format(**kwargs); bare {} would crash on any kwargs call
        for lang in ("zh", "en"):
            for key, text in i18n.STRINGS[lang].items():
                assert "{}" not in text, f"{key} has positional placeholder"

    def test_en_has_no_cjk(self):
        for key, text in i18n.STRINGS["en"].items():
            assert not CJK.search(text), f"{key} leaks CJK into en: {text!r}"

    def test_zh_has_cjk_for_help_keys(self):
        # spot check: a few known bilingual keys must be Chinese in zh
        assert i18n.STRINGS["zh"]["help___quality"] == "输出质量 1-100（默认 85）"
        assert i18n.STRINGS["en"]["help___quality"] == "Output quality 1-100 (default: 85)"

    def test_t_fallback_missing_key(self):
        assert i18n._t("no_such_key", lang="en") == "no_such_key"

    def test_t_kwargs_format(self):
        assert i18n._t("msg_files_found", lang="en", n=3) == "📁 Found 3 image file(s):"

    def test_t_uses_current_lang(self, monkeypatch):
        i18n.CURRENT_LANG = "en"
        assert i18n._t("help___version").startswith("Show version")
        i18n.CURRENT_LANG = "zh"
        assert i18n._t("help___version").startswith("显示版本号")


# ── CLI rendering purity (via run_cli) ──────────────────────────────────────

from photo_s.cli import run_cli


class TestCliRendering:
    def test_en_help_has_no_cjk(self, capsys):
        with pytest.raises(SystemExit):
            run_cli(["--language", "en", "--help"])
        out = capsys.readouterr().out
        assert not CJK.search(out)

    def test_zh_help_has_cjk(self, capsys):
        with pytest.raises(SystemExit):
            run_cli(["--language", "zh", "--help"])
        out = capsys.readouterr().out
        assert CJK.search(out)

    def test_all_subcommands_en_help_no_cjk(self, capsys):
        for cmd in ("compress", "convert", "batch", "exif", "preset", "plugin",
                    "watch", "dedup", "info", "rename", "check", "contact-sheet",
                    "cull", "select", "hdr", "blurfaces", "hash", "gallery",
                    "analyze", "lr-scan", "lr-train", "lr-predict",
                    "lr-recipes", "lr-similar", "lr-eval", "lr-merge",
                    "diff", "audit", "preview",
                    "bench", "config", "serve", "mcp"):
            capsys.readouterr()  # drain
            with pytest.raises(SystemExit):
                run_cli([cmd, "--language", "en", "--help"])
            out = capsys.readouterr().out
            assert not CJK.search(out), f"{cmd} help leaks CJK in en"

    def test_lang_alias_and_after_subcommand(self, capsys):
        with pytest.raises(SystemExit):
            run_cli(["compress", "--lang", "en", "--help"])
        out = capsys.readouterr().out
        assert not CJK.search(out)

    def test_json_output_stays_english_with_zh(self, tmp_path, capsys):
        # a JSON command in zh mode must still emit parseable JSON with
        # English keys (existing JSON tests cover the default path).
        import json as _json
        img = tmp_path / "x.png"
        from PIL import Image
        Image.new("RGB", (8, 8), (255, 0, 0)).save(img)
        rc = run_cli(["info", "--json", "--language", "zh"])
        assert rc == 0
        data = _json.loads(capsys.readouterr().out)
        assert "formats" in data  # English key


# ── config language key ─────────────────────────────────────────────────────

from photo_s.config import config_language


class TestConfigLanguage:
    def test_absent_returns_none(self):
        assert config_language({}) is None
        assert config_language({"options": {}}) is None

    def test_valid(self):
        assert config_language({"options": {"language": "zh"}}) == "zh"
        assert config_language({"options": {"language": "en"}}) == "en"

    def test_case_insensitive(self):
        assert config_language({"options": {"language": "ZH"}}) == "zh"

    def test_auto_and_invalid_return_none(self):
        assert config_language({"options": {"language": "auto"}}) is None
        assert config_language({"options": {"language": "fr"}}) is None


# ── GUI persistence ─────────────────────────────────────────────────────────

class TestPersistence:
    def test_round_trip(self, tmp_path, monkeypatch):
        from pathlib import Path
        monkeypatch.setattr(i18n, "STATE_DIR", tmp_path)
        monkeypatch.setattr(i18n, "LANGUAGE_FILE", tmp_path / "language")
        assert i18n.load_persisted_language() is None
        i18n.save_language("en")
        assert i18n.load_persisted_language() == "en"

    def test_invalid_ignored(self, tmp_path, monkeypatch):
        from pathlib import Path
        monkeypatch.setattr(i18n, "STATE_DIR", tmp_path)
        monkeypatch.setattr(i18n, "LANGUAGE_FILE", tmp_path / "language")
        i18n.save_language("fr")  # ignored, no file
        assert i18n.load_persisted_language() is None

    def test_never_raises_on_bad_dir(self, monkeypatch):
        # a read-only / unwritable path must not crash the GUI
        from pathlib import Path
        monkeypatch.setattr(i18n, "STATE_DIR", Path("/dev/null/not/a/dir"))
        monkeypatch.setattr(i18n, "LANGUAGE_FILE", Path("/dev/null/not/a/dir/lang"))
        i18n.save_language("en")  # must not raise
