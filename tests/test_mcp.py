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
        assert names == {"process", "info", "exif", "dedup", "cull", "select", "hdr", "blurfaces", "hash",
                         "plugin", "contact_sheet", "gallery",
                         "watermark", "preset", "bench",
                         "watch", "watch_status", "watch_stop"}

    def test_server_info_version(self):
        # serverInfo must report the PhotoS version, not the mcp SDK's
        # (FastMCP has no version kwarg in mcp>=1.20, so _mcp() sets it
        # on the low-level server directly).
        from photo_s import __version__
        assert create_server()._mcp_server.version == __version__


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

    def test_tone_and_lut_params(self, tmp_path):
        # Regression: process_tool's hand-maintained param list was missing
        # lut_file/brightness/contrast/saturation, so agents couldn't grade
        # via natural language (v1.6.0 bug fix).
        a = _img(tmp_path / "a.jpg")
        out = tmp_path / "out"
        cube = tmp_path / "id.cube"
        cube.write_text(
            "LUT_3D_SIZE 2\n"
            "0 0 0\n0 0 0\n0 0 0\n0 0 0\n"
            "0 0 0\n0 0 0\n0 0 0\n1 1 1\n")
        r = _call("process", {"paths": [a], "output_dir": str(out),
                              "brightness": 1.2, "contrast": 1.1,
                              "saturation": 1.3, "lut_file": str(cube)})
        assert r["ok"] is True
        assert r["summary"]["success"] == 1
        assert os.path.isfile(r["results"][0]["output"])

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

    def test_evaluate_ssim_present(self, tmp_path):
        a = _img(tmp_path / "a.jpg")
        b = _img(tmp_path / "b.jpg", color=(1, 2, 3))
        out = tmp_path / "out"
        r = _call("process", {"paths": [a, b], "output_dir": str(out),
                              "evaluate": True})
        assert r["ok"] is True
        for res in r["results"]:
            assert res.get("ssim") is not None, "evaluate=True must add ssim"

    def test_evaluate_off_by_default(self, tmp_path):
        a = _img(tmp_path / "a.jpg")
        out = tmp_path / "out"
        r = _call("process", {"paths": [a], "output_dir": str(out)})
        assert r["results"][0].get("ssim") is None


class TestBenchTool:
    def test_smoke(self, tmp_path):
        _img(tmp_path / "a.jpg")
        _img(tmp_path / "b.jpg", color=(2, 3, 4))
        r = _call("bench", {"dir": str(tmp_path), "jobs": [1, 2]})
        assert r["ok"] is True
        assert r["files"] == 2
        assert [run["jobs"] for run in r["runs"]] == [1, 2]
        assert "seconds" in r["runs"][0] and "speedup" in r["runs"][0]
        assert r["evaluate"] is None

    def test_evaluate(self, tmp_path):
        _img(tmp_path / "a.jpg")
        r = _call("bench", {"dir": str(tmp_path), "jobs": [1],
                            "evaluate": True})
        assert r["ok"] is True
        assert r["evaluate"] is not None
        assert "ssim" in r["evaluate"] and "psnr_db" in r["evaluate"]

    def test_rejects_bad_jobs(self, tmp_path):
        _img(tmp_path / "a.jpg")
        r = _call("bench", {"dir": str(tmp_path), "jobs": [0, -1]})
        assert r["ok"] is False

    def test_missing_dir(self, tmp_path):
        r = _call("bench", {"dir": str(tmp_path / "nope")})
        assert r["ok"] is False
        assert "not a directory" in r["error"]


class TestWatchTool:
    def test_start_status_stop(self, tmp_path):
        pytest.importorskip("watchdog")
        out = tmp_path / "out"
        r = _call("watch", {"dir": str(tmp_path), "output_dir": str(out),
                            "output_format": "JPEG"})
        assert r["started"] is True and r["id"]
        wid = r["id"]
        try:
            # watchdog's on_created can race the observer startup, so drop
            # one file immediately and another after a beat to guarantee at
            # least one processed event is observed.
            _img(tmp_path / "a.jpg")
            import time
            time.sleep(0.5)
            _img(tmp_path / "b.jpg", color=(2, 3, 4))
            deadline = time.time() + 12
            st = None
            while time.time() < deadline:
                st = _call("watch_status", {"id": wid})
                if st["processed_count"] >= 1:
                    break
                time.sleep(0.5)
            assert st is not None and st["processed_count"] >= 1
            assert os.path.isfile(st["results"][0]["output"])
        finally:
            _call("watch_stop", {"id": wid})
        # the watcher polls its stop_event on a ~1s tick, so wait for the
        # daemon thread to actually exit (status then reports running=False)
        import time
        deadline = time.time() + 5
        st = None
        while time.time() < deadline:
            st = _call("watch_status", {"id": wid})
            if not st["running"]:
                break
            time.sleep(0.2)
        assert st is not None and st["running"] is False
        assert st["stopped"] is True

    def test_missing_dir(self, tmp_path):
        r = _call("watch", {"dir": str(tmp_path / "nope")})
        assert r["started"] is False

    def test_status_unknown_id(self):
        r = _call("watch_status", {"id": "nope"})
        assert r["ok"] is False


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

    def test_batch_gps_write(self, tmp_path):
        pytest.importorskip("piexif")
        import piexif
        a = _img(tmp_path / "a.jpg")
        b = _img(tmp_path / "b.jpg")
        r = _call("exif", {"action": "write", "paths": [a, b],
                           "gps": "30,120"})
        assert r["written"] == 2
        for p in (a, b):
            gps = piexif.load(p).get("GPS", {})
            assert gps.get(piexif.GPSIFD.GPSLatitude) == ((30, 1), (0, 1), (0, 100))


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


class TestSelectTool:
    def _rate(self, path, rating):
        _call("exif", {"action": "write", "tags": {path: {"rating": rating}}})

    def test_dry_run_classifies(self, tmp_path):
        pytest.importorskip("piexif")
        a = _img(tmp_path / "a.jpg")
        b = _img(tmp_path / "b.jpg")
        c = _img(tmp_path / "c.jpg")
        self._rate(a, 5)
        self._rate(b, 1)
        # c stays unrated → skip
        r = _call("select", {"paths": [a, b, c],
                             "selects_dir": str(tmp_path / "sel"),
                             "rejects_dir": str(tmp_path / "rej"),
                             "dry_run": True})
        assert r["ok"] is True and r["dry_run"] is True
        by_name = {os.path.basename(x["path"]): x for x in r["results"]}
        assert by_name["a.jpg"]["status"] == "keep"
        assert by_name["a.jpg"]["action"] == "would_move"
        assert by_name["b.jpg"]["status"] == "reject"
        assert by_name["c.jpg"]["status"] == "skip"
        # dry_run: nothing was created
        assert not os.path.exists(str(tmp_path / "sel"))

    def test_move_and_remove_sources(self, tmp_path):
        pytest.importorskip("piexif")
        a = _img(tmp_path / "a.jpg")
        b = _img(tmp_path / "b.jpg")
        self._rate(a, 5)
        self._rate(b, 1)
        sel, rej = tmp_path / "sel", tmp_path / "rej"
        r = _call("select", {"paths": [a, b], "selects_dir": str(sel),
                             "rejects_dir": str(rej)})
        assert r["kept"] == 1 and r["rejected"] == 1
        assert os.path.isfile(str(sel / "a.jpg"))
        assert os.path.isfile(str(rej / "b.jpg"))
        assert not os.path.exists(a) and not os.path.exists(b)

    def test_copy_preserves_originals(self, tmp_path):
        pytest.importorskip("piexif")
        a = _img(tmp_path / "a.jpg")
        self._rate(a, 5)
        r = _call("select", {"paths": [a], "selects_dir": str(tmp_path / "sel"),
                             "mode": "copy"})
        assert r["kept"] == 1
        assert os.path.isfile(a)  # original kept
        assert os.path.isfile(str(tmp_path / "sel" / "a.jpg"))


class TestHdrTool:
    def test_merge(self, tmp_path):
        pytest.importorskip("cv2")
        import numpy as np
        evs = []
        for i, v in enumerate((30, 128, 230)):
            arr = np.full((24, 32, 3), v, dtype="uint8")
            p = tmp_path / f"e{i}.jpg"
            Image.fromarray(arr).save(str(p))
            evs.append(str(p))
        out = str(tmp_path / "hdr.jpg")
        r = _call("hdr", {"paths": evs, "output": out})
        assert r["ok"] is True
        assert r["count"] == 3
        assert r["dims"] == [32, 24]
        assert os.path.isfile(out)

    def test_missing_cv2_clear_error(self, tmp_path, monkeypatch):
        import builtins
        from photo_s import hdr as hdr_mod
        monkeypatch.setattr(
            hdr_mod, "_cv2",
            lambda: (_ for _ in ()).throw(
                RuntimeError("hdr requires the optional dependency: "
                             "pip install 'photo-s-tools[enhance]'")))
        r = _call("hdr", {"paths": [str(tmp_path / "a.jpg")],
                          "output": str(tmp_path / "h.jpg")})
        assert r["ok"] is False
        assert "enhance" in r["error"]


class TestBlurFacesTool:
    def test_missing_cv2_is_per_file_error(self, tmp_path, monkeypatch):
        # blurfaces_tool routes through the engine pipeline; when opencv is
        # missing the failure is recorded per file, not fatal to the batch
        import photo_s.faceblur as fb
        monkeypatch.setattr(
            fb, "_cv2",
            lambda: (_ for _ in ()).throw(
                RuntimeError("face blur requires the optional dependency: "
                             "pip install 'photo-s-tools[enhance]'")))
        a = _img(tmp_path / "a.jpg")
        out = tmp_path / "out"
        r = _call("blurfaces", {"paths": [a], "output_dir": str(out)})
        assert r["ok"] is False
        assert r["success"] == 0
        assert "enhance" in r["results"][0]["error"]


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

    def test_unknown_action_rejected(self):
        # regression: "remove"/"status" fell through to a pip uninstall argv;
        # with dry_run=False that really uninstalled the plugin
        r = _call("plugin", {"action": "remove", "name": "scunet"})
        assert r["ok"] is False
        assert "unknown action" in r["error"]
        assert "pip_argv" not in r


class TestCliListTools:
    def test_list_tools_json(self, capsys):
        rc = run_cli(["mcp", "--list-tools"])
        out = capsys.readouterr().out
        assert rc == 0
        data = json.loads(out)
        assert len(data["tools"]) == 18
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
                                     "cull", "select", "hdr", "blurfaces", "hash", "plugin",
                                     "contact_sheet", "gallery",
                                     "watermark", "preset", "bench",
                                     "watch", "watch_status", "watch_stop"}
                    result = await session.call_tool(
                        "process",
                        {"paths": [img], "output_dir": str(out),
                         "output_format": "PNG"})
                    data = json.loads(result.content[0].text)
                    assert data["ok"] is True
                    assert data["summary"]["success"] == 1
                    assert os.path.isfile(data["results"][0]["output"])

        asyncio.run(run())


class TestContactSheetTool:
    def test_builds_montage(self, tmp_path):
        a = _img(tmp_path / "a.jpg")
        b = _img(tmp_path / "b.jpg")
        out = str(tmp_path / "sheet.jpg")
        r = _call("contact_sheet", {"paths": [a, b], "output": out,
                                    "cols": 2})
        assert r["ok"] is True
        assert r["count"] == 2
        assert os.path.isfile(r["output"])

    def test_no_files(self, tmp_path):
        r = _call("contact_sheet", {"paths": [str(tmp_path / "nope.jpg")],
                                    "output": str(tmp_path / "x.jpg")})
        assert r["ok"] is False


class TestGalleryTool:
    def test_builds_html(self, tmp_path):
        a = _img(tmp_path / "a.jpg")
        out = str(tmp_path / "gal")
        r = _call("gallery", {"paths": [a], "out_dir": out})
        assert r["ok"] is True
        assert r["count"] == 1
        assert os.path.isfile(r["output"])  # output == index.html path
        assert r["output"].endswith("index.html")


class TestWatermarkTool:
    def test_text_watermark(self, tmp_path):
        a = _img(tmp_path / "a.jpg", size=(64, 64))
        out = str(tmp_path / "out")
        r = _call("watermark", {"paths": [a], "text": "PhotoS",
                                "output_dir": out})
        assert r["ok"] is True
        assert r["summary"]["success"] == 1

    def test_missing_path_returns_error(self, tmp_path):
        # regression: raw paths went straight to batch_process — a missing
        # file raised FileNotFoundError and killed the whole batch
        r = _call("watermark", {"paths": [str(tmp_path / "nope.jpg")],
                                "text": "PhotoS"})
        assert r["ok"] is False
        assert "no supported image files" in r["error"]

    def test_directory_expanded(self, tmp_path):
        # regression: directories were not expanded (fed raw to the engine)
        _img(tmp_path / "a.jpg", size=(64, 64))
        _img(tmp_path / "b.jpg", size=(64, 64))
        out = str(tmp_path / "out")
        r = _call("watermark", {"paths": [str(tmp_path)], "text": "PhotoS",
                                "output_dir": out})
        assert r["ok"] is True
        assert r["summary"]["success"] == 2


class TestPresetTool:
    def test_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PHOTOS_HOME", str(tmp_path / "home"))
        r = _call("preset", {"action": "save", "name": "p1",
                             "options": {"quality": 72, "grayscale": True}})
        assert r["ok"] is True
        loaded = _call("preset", {"action": "load", "name": "p1"})
        assert loaded["ok"] is True
        assert loaded["options"]["quality"] == 72
        assert loaded["options"]["grayscale"] is True
        lst = _call("preset", {"action": "list"})
        assert "p1" in lst["presets"]
        deleted = _call("preset", {"action": "delete", "name": "p1"})
        assert deleted["deleted"] is True
