"""Tests for packaging/build.py (PyInstaller bundle script).

Hermetic: pyinstaller discovery and subprocess.run are monkeypatched, so no
real build runs. Regression coverage for the removed --onefile flag, which
PyInstaller rejects when a .spec file is given ('option(s) not allowed:
--onedir/--onefile makespec options not valid when a .spec file is given').
"""

import importlib.util
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_build():
    spec = importlib.util.spec_from_file_location(
        "photos_packaging_build", os.path.join(_ROOT, "packaging", "build.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestBuildCommand:
    def test_command_uses_spec_without_onefile(self, monkeypatch, capsys):
        build = _load_build()
        monkeypatch.setattr(build.shutil, "which",
                            lambda name: "/usr/bin/pyinstaller")
        captured = {}

        class _Result:
            returncode = 0

        def _run(cmd, cwd):
            captured["cmd"] = cmd
            return _Result()

        monkeypatch.setattr(build.subprocess, "run", _run)
        monkeypatch.setattr(sys, "argv", ["build.py"])
        rc = build.main()
        assert rc == 0
        assert "--onefile" not in captured["cmd"]
        assert captured["cmd"][-1].endswith("photo-s.spec")
        # reported artifact is the one-dir layout dist/photo-s/photo-s
        out = capsys.readouterr().out
        assert os.path.join("dist", "photo-s", "photo-s") in out

    def test_onefile_flag_rejected(self, monkeypatch, capsys):
        """--onefile no longer exists: argparse must reject it (exit 2)."""
        build = _load_build()
        monkeypatch.setattr(sys, "argv", ["build.py", "--onefile"])
        with pytest.raises(SystemExit) as exc:
            build.main()
        assert exc.value.code != 0
        capsys.readouterr()


class TestLiteBuild:
    def test_lite_flag_selects_lite_spec(self, monkeypatch, capsys):
        build = _load_build()
        monkeypatch.setattr(build.shutil, "which",
                            lambda name: "/usr/bin/pyinstaller")
        captured = {}

        class _Result:
            returncode = 0

        def _run(cmd, cwd):
            captured["cmd"] = cmd
            return _Result()

        monkeypatch.setattr(build.subprocess, "run", _run)
        monkeypatch.setattr(sys, "argv", ["build.py", "--lite"])
        rc = build.main()
        assert rc == 0
        assert captured["cmd"][-1].endswith("photo-s-lite.spec")
        out = capsys.readouterr().out
        assert os.path.join("dist", "photo-s-lite", "photo-s-lite") in out

    def test_lite_spec_excludes_gui_and_tk(self):
        """The lite spec must shut out every GUI piece: the photo_s.gui
        module, both tkinter import names, and tkinterdnd2 (which CI
        installs via .[all] and would otherwise be bundled)."""
        spec_path = os.path.join(_ROOT, "photo-s-lite.spec")
        with open(spec_path, encoding="utf-8") as f:
            content = f.read()
        for mod in ('"photo_s.gui"', '"tkinter"', '"_tkinter"',
                    '"tkinterdnd2"'):
            assert mod in content, f"lite spec must exclude {mod}"
        assert '"photo-s-lite"' in content

    def test_full_spec_keeps_gui(self):
        """Guard the split: the full spec must NOT exclude the GUI."""
        with open(os.path.join(_ROOT, "photo-s.spec"),
                  encoding="utf-8") as f:
            content = f.read()
        assert "photo_s.gui" not in content
        assert "tkinterdnd2" in content  # bundled when installed
