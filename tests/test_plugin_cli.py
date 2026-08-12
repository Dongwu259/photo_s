"""Tests for the `photo-s plugin` subcommand (photo_s.plugincmd).

Uses run_cli + capsys, monkeypatches _pip_run, and injects a fake installed
plugin into discover_plugins to exercise weight status paths.
"""

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PIL import Image

from photo_s.cli import run_cli
from photo_s import plugincmd
from photo_s.hooks import PhotoSPlugin
from photo_s.modelstore import WeightSpec


class _FakeProvider(PhotoSPlugin):
    name = "scunet"
    provides = ("denoise",)

    def __init__(self, weight=None):
        self._weight = weight

    def weight_specs(self):
        return [self._weight] if self._weight else []


@pytest.fixture(autouse=True)
def _clean_plugin_env(monkeypatch):
    """These tests are hermetic: they must not depend on whether a plugin
    (e.g. the editable-installed scunet) is present in the dev environment.
    Tests that need a fake plugin override this explicitly."""
    monkeypatch.setattr(plugincmd, "discover_plugins", lambda: [])
    yield


def _out(capsys):
    return capsys.readouterr().out


class TestPluginList:
    def test_list_json_shape(self, capsys):
        rc = run_cli(["plugin", "list", "--json"])
        assert rc == 0
        data = json.loads(_out(capsys))
        assert "installed" in data and "available" in data
        scunet = next(a for a in data["available"] if a["name"] == "scunet")
        assert scunet["pypi_distribution"] == "photo-s-plugin-scunet"
        assert "description" in scunet
        assert scunet["installed"] is False

    def test_list_json_stdout_pure(self, capsys):
        run_cli(["plugin", "list", "--json"])
        json.loads(_out(capsys))  # must parse as JSON with no trailing junk

    def test_list_human_mode(self, capsys):
        rc = run_cli(["plugin", "list"])
        assert rc == 0
        assert "scunet" in _out(capsys)


class TestPluginInstall:
    def test_install_unknown_rc1(self, capsys):
        rc = run_cli(["plugin", "install", "nope", "--json"])
        assert rc == 1
        data = json.loads(_out(capsys))
        assert data["ok"] is False
        assert "registry" in data["error"]

    def test_install_dry_run_no_pip(self, capsys, monkeypatch):
        monkeypatch.setattr(plugincmd, "_pip_run",
                            lambda argv: (_ for _ in ()).throw(AssertionError(
                                "pip must not run in dry-run")))
        rc = run_cli(["plugin", "install", "scunet", "--dry-run", "--json"])
        assert rc == 0
        data = json.loads(_out(capsys))
        assert data["dry_run"] is True
        assert data["pip_argv"][-1] == "photo-s-plugin-scunet"

    def test_install_success(self, capsys, monkeypatch):
        class _Proc:
            returncode = 0
            stdout = stderr = ""

        monkeypatch.setattr(plugincmd, "_pip_run", lambda argv: _Proc())
        rc = run_cli(["plugin", "install", "scunet", "--json"])
        assert rc == 0
        data = json.loads(_out(capsys))
        assert data["ok"] is True
        assert data["distribution"] == "photo-s-plugin-scunet"

    def test_install_pip_failure(self, capsys, monkeypatch):
        class _Proc:
            returncode = 1
            stdout = ""
            stderr = "ERROR: no matching distribution"

        monkeypatch.setattr(plugincmd, "_pip_run", lambda argv: _Proc())
        rc = run_cli(["plugin", "install", "scunet", "--json"])
        assert rc == 1
        data = json.loads(_out(capsys))
        assert data["ok"] is False
        assert data["error"] == "pip install failed"

    def test_install_already_installed(self, capsys, monkeypatch):
        monkeypatch.setattr(plugincmd, "discover_plugins",
                            lambda: [_FakeProvider()])
        rc = run_cli(["plugin", "install", "scunet", "--json"])
        assert rc == 0
        data = json.loads(_out(capsys))
        assert data["already_installed"] is True


class TestPluginUninstall:
    def test_uninstall_dry_run(self, capsys):
        rc = run_cli(["plugin", "uninstall", "scunet", "--dry-run", "--json"])
        assert rc == 0
        data = json.loads(_out(capsys))
        assert data["dry_run"] is True
        assert "uninstall" in data["pip_argv"]

    def test_uninstall_success(self, capsys, monkeypatch):
        class _Proc:
            returncode = 0
            stdout = stderr = ""

        monkeypatch.setattr(plugincmd, "_pip_run", lambda argv: _Proc())
        rc = run_cli(["plugin", "uninstall", "scunet", "--json"])
        assert rc == 0
        data = json.loads(_out(capsys))
        assert data["ok"] is True


class TestPluginInfo:
    def test_info_unknown(self, capsys):
        rc = run_cli(["plugin", "info", "nope", "--json"])
        assert rc == 1
        data = json.loads(_out(capsys))
        assert data["error"] == "unknown plugin"

    def test_info_registry_not_installed(self, capsys):
        rc = run_cli(["plugin", "info", "scunet", "--json"])
        assert rc == 0
        data = json.loads(_out(capsys))
        assert data["installed"] is False
        assert data["pypi_distribution"] == "photo-s-plugin-scunet"

    def test_info_with_weights(self, capsys, tmp_path, monkeypatch):
        monkeypatch.setenv("PHOTOS_CACHE_DIR", str(tmp_path / "cache"))
        cached = tmp_path / "cache" / "models" / "m.onnx"
        cached.parent.mkdir(parents=True)
        data = b"x" * 8
        cached.write_bytes(data)
        import hashlib
        spec = WeightSpec(name="m.onnx", url="file:///none",
                          sha256=hashlib.sha256(data).hexdigest(), size=8)
        monkeypatch.setattr(plugincmd, "discover_plugins",
                            lambda: [_FakeProvider(weight=spec)])
        rc = run_cli(["plugin", "info", "scunet", "--json"])
        assert rc == 0
        data = json.loads(_out(capsys))
        assert data["installed"] is True
        assert data["provides"] == ["denoise"]
        assert data["weights"][0]["cached"] is True


class TestPluginFetch:
    def test_fetch_not_installed(self, capsys):
        rc = run_cli(["plugin", "fetch", "scunet", "--json"])
        assert rc == 1
        data = json.loads(_out(capsys))
        assert data["ok"] is False
        assert "not installed" in data["error"]

    def test_fetch_downloads_weights(self, capsys, tmp_path, monkeypatch):
        import hashlib
        monkeypatch.setenv("PHOTOS_CACHE_DIR", str(tmp_path / "cache"))
        src = tmp_path / "m.onnx"
        data = b"model-bytes"
        src.write_bytes(data)
        spec = WeightSpec(name="m.onnx", url=src.as_uri(),
                          sha256=hashlib.sha256(data).hexdigest(), size=len(data))
        monkeypatch.setattr(plugincmd, "discover_plugins",
                            lambda: [_FakeProvider(weight=spec)])
        rc = run_cli(["plugin", "fetch", "scunet", "--json"])
        assert rc == 0
        data = json.loads(_out(capsys))
        assert data["ok"] is True
        assert data["weights"][0]["cached"] is True
        assert os.path.isfile(data["weights"][0]["path"])
