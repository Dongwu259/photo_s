"""Tests for the MCP server (photo_s.mcp_server) via in-process call_tool.

FastMCP is testable WITHOUT stdio: ``await server.call_tool(name, args)``.
Skips cleanly when the optional `mcp` extra is not installed.
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

pytest.importorskip("mcp")

from PIL import Image

from photo_s.cli import run_cli
from photo_s.mcp_server import create_server, _call_tool_json
from photo_s import plugin as plugin_mod


def _call(name, args):
    return _call_tool_json(name, args)


def _img(path, color=(120, 100, 80), size=(32, 32)):
    Image.new("RGB", size, color).save(str(path), quality=95)
    return str(path)


class TestTools:
    def test_registered_tools(self):
        names = {t.name for t in asyncio.run(create_server().list_tools())}
        assert names == {"process", "info", "exif", "dedup", "cull",
                         "hash", "plugin"}


class TestProcessTool:
    def test_end_to_end_webp(self, tmp_path):
        a = _img(tmp_path / "a.jpg")
        b = _img(tmp_path / "b.jpg")
        out = tmp_path / "out"
        r = _call("process", {"paths": [a, b], "output_format": "WebP",
                              "output_dir": str(out), "quality": 80})
        assert r["ok"] is True
        assert r["summary"]["success"] == 2
        assert r["results"][0]["output"].endswith(".webp")
        assert os.path.isfile(r["results"][0]["output"])

    def test_resize(self, tmp_path):
        a = _img(tmp_path / "a.jpg", size=(64, 64))
        out = tmp_path / "out"
        r = _call("process", {"paths": [a], "resize": "4x4",
                              "output_dir": str(out)})
        assert r["results"][0]["output_dims"] == [4, 4]

    def test_dry_run_no_output(self, tmp_path):
        a = _img(tmp_path / "a.jpg")
        out = tmp_path / "out"
        r = _call("process", {"paths": [a], "output_dir": str(out),
                              "dry_run": True})
        assert r["dry_run"] is True
        assert r["count"] == 1
        assert not os.path.isdir(str(out))

    def test_no_files(self, tmp_path):
        r = _call("process", {"paths": [str(tmp_path / "nope*.jpg")]})
        assert r["ok"] is False
        assert "no supported image files" in r["error"]

    def test_hermetic_no_plugins(self, tmp_path, monkeypatch):
        """Must not depend on dev-machine installed plugins (e.g. scunet)."""
        monkeypatch.setattr(plugin_mod, "discover_plugins", lambda: [])
        a = _img(tmp_path / "a.jpg")
        out = tmp_path / "out"
        r = _call("process", {"paths": [a], "output_dir": str(out),
                              "denoise": 5})
        assert r["ok"] is True


class TestInfoTool:
    def test_shape(self):
        r = _call("info", {})
        assert "version" in r
        assert "formats" in r and "JPEG" in r["formats"]
        assert "writable" in r
        assert "optional_features" in r and "mcp" in r["optional_features"]
        assert "plugins" in r


class TestExifTool:
    def test_write_read_roundtrip(self, tmp_path):
        pytest.importorskip("piexif")
        a = _img(tmp_path / "a.jpg")
        w = _call("exif", {"action": "write",
                           "tags": {a: {"rating": 4, "keywords": "keep,beach"}}})
        assert w["written"] == 1
        s = _call("exif", {"action": "show", "paths": [a]})
        assert s["count"] == 1
        assert s["results"][0]["rating"] == 4
        assert "keep" in s["results"][0]["keywords"]

    def test_filter_rating_min(self, tmp_path):
        pytest.importorskip("piexif")
        a = _img(tmp_path / "a.jpg")
        b = _img(tmp_path / "b.jpg")
        _call("exif", {"action": "write", "tags": {a: {"rating": 4}}})
        _call("exif", {"action": "write", "tags": {b: {"rating": 2}}})
        s = _call("exif", {"action": "show", "paths": [str(tmp_path)],
                           "recursive": False, "rating_min": 3})
        assert s["count"] == 1
        assert s["results"][0]["path"] == a


class TestDedupTool:
    def test_report(self, tmp_path):
        import shutil
        a = _img(tmp_path / "a.jpg", color=(10, 20, 30))
        shutil.copyfile(a, tmp_path / "b.jpg")
        r = _call("dedup", {"paths": [a, str(tmp_path / "b.jpg")]})
        assert r["duplicate_count"] == 1
        assert len(r["groups"]) >= 1
        assert len(r["groups"][0]["paths"]) == 2

    def test_keep_sharpest_dry_run_safe(self, tmp_path):
        import shutil
        a = _img(tmp_path / "a.jpg", color=(10, 20, 30))
        shutil.copyfile(a, tmp_path / "b.jpg")
        r = _call("dedup", {"paths": [a, str(tmp_path / "b.jpg")],
                            "action": "keep-sharpest"})
        assert r["dry_run"] is True
        assert r["removed"] >= 1
        assert os.path.isfile(a) and os.path.isfile(str(tmp_path / "b.jpg"))


class TestCullTool:
    def test_overexposed_filtered(self, tmp_path):
        white = _img(tmp_path / "white.jpg", color=(255, 255, 255))
        normal = _img(tmp_path / "normal.jpg", color=(128, 128, 128))
        r = _call("cull", {"paths": [white, normal],
                           "overexposed_max": 1.0})
        assert r["kept"] == 1
        kept_paths = [x["path"] for x in r["results"] if x["kept"]]
        assert normal in kept_paths
        assert white not in kept_paths


class TestHashTool:
    def test_generate_and_verify(self, tmp_path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"hello archive")
        manifest = tmp_path / "manifest.csv"
        r = _call("hash", {"paths": [str(f)], "output": str(manifest)})
        assert r["count"] == 1
        assert r["entries"][0]["path"].endswith("data.bin")
        assert os.path.isfile(str(manifest))
        v = _call("hash", {"verify": str(manifest)})
        assert v["ok"] is True


class TestPluginTool:
    def test_list_hermetic(self, monkeypatch):
        # plugin_tool imports discover_plugins from photo_s.plugin directly
        # (bound at module import); patch THAT + clear the module cache so
        # a dev-machine editable install (e.g. scunet) can't leak in.
        plugin_mod.clear_cache()
        monkeypatch.setattr(plugin_mod, "discover_plugins", lambda: [])
        r = _call("plugin", {"action": "list"})
        assert r["installed"] == []
        names = [a["name"] for a in r["available"]]
        assert "scunet" in names
        assert r["available"][0]["installed"] is False

    def test_install_dry_run(self):
        r = _call("plugin", {"action": "install", "name": "scunet",
                             "dry_run": True})
        assert r["ok"] is True
        assert r["dry_run"] is True
        assert r["pip_argv"][-1] == "photo-s-plugin-scunet"

    def test_install_unknown(self):
        r = _call("plugin", {"action": "install", "name": "nope"})
        assert r["ok"] is False
        assert "registry" in r["error"]


class TestCliListTools:
    def test_list_tools_json(self, capsys):
        rc = run_cli(["mcp", "--list-tools"])
        out = capsys.readouterr().out
        assert rc == 0
        data = json.loads(out)
        assert len(data["tools"]) == 7
        for t in data["tools"]:
            assert "input_schema" in t
            assert "properties" in t["input_schema"]


class TestStdioEndToEnd:
    """Real MCP client (official SDK stdio_client) against `photo-s mcp`."""

    def test_handshake_and_process(self, tmp_path):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        import asyncio

        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        img = _img(tmp_path / "a.jpg")
        out = tmp_path / "out"

        async def run():
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "photo_s.cli", "mcp"],
                cwd=repo)
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    names = {t.name for t in tools.tools}
                    assert names == {"process", "info", "exif", "dedup",
                                     "cull", "hash", "plugin"}
                    result = await session.call_tool(
                        "process",
                        {"paths": [img], "output_dir": str(out),
                         "output_format": "PNG"})
                    data = json.loads(result.content[0].text)
                    assert data["ok"] is True
                    assert data["summary"]["success"] == 1
                    assert os.path.isfile(data["results"][0]["output"])

        asyncio.run(run())
