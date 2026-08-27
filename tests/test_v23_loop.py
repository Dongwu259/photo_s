"""v2.3 agent-loop tests: suggest / plugin wiring / batch audit / cull v2.

* suggest: dark→ev+, bright→ev-, neutral→empty, scale softens, unreadable,
  and the full ROADMAP loop analyze → suggest → process → audit
* plugin wiring: MCP + REST registration hooks fire for overriding plugins
  (and skip base-class no-ops), engine auto_tone slot errors clearly when
  the plugin is missing and delegates when present
* batch audit: start_task(audit=True) and batch_start_tool(audit=True)
  attach per-file {passed, reason} + a pass-rate summary
* cull v2: weighted scores rank (never reject), EXIF/mtime burst grouping,
  best-of-burst marking
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest
from PIL import Image


def _img(path, fill=(128, 128, 128), noise=20, size=(160, 160), seed=1):
    rng = np.random.default_rng(seed)
    arr = np.full((size[1], size[0], 3), fill, np.int16)
    arr += rng.integers(-noise, noise + 1, arr.shape)
    Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB").save(path)
    return str(path)


@pytest.fixture()
def photos(tmp_path):
    dark = _img(tmp_path / "dark.jpg", fill=(45, 42, 40), seed=1)
    bright = _img(tmp_path / "bright.jpg", fill=(240, 238, 235), seed=2)
    mid = _img(tmp_path / "mid.jpg", fill=(128, 126, 124), noise=40, seed=3)
    return {"dark": dark, "bright": bright, "mid": mid}


# ── suggest ──────────────────────────────────────────────────────────────────


class TestSuggest:
    def test_dark_image_gets_positive_ev(self, photos):
        from photo_s.suggest import suggest_file
        r = suggest_file(photos["dark"])
        assert r["ok"] and not r["neutral"]
        assert r["suggested"]["ev"] > 0
        assert any(x["field"] == "ev" for x in r["reasons"])

    def test_bright_image_gets_negative_ev(self, photos):
        from photo_s.suggest import suggest_file
        r = suggest_file(photos["bright"])
        assert r["suggested"]["ev"] < 0

    def test_neutral_analysis_yields_nothing(self):
        from photo_s.suggest import suggest_params
        # a balanced, contrasty, saturated frame: nothing objectively off
        neutral = {
            "stats": {"contrast": 0.22, "saturation_mean": 0.35},
            "exposure": {"luminance": 0.5, "overexposed_pct": 0.2,
                         "underexposed_pct": 0.2},
            "white_balance": {"kelvin_estimate": 6600, "tint_gm": 1.0},
            "blur_score": 0.5,
            "histogram": {"luma": [100] + [800] * 26 + [100, 0, 0, 0, 0]},
        }
        out = suggest_params(neutral)
        assert out["suggested"] == {}
        assert out["neutral"] is True
        assert out["reasons"] == []

    def test_scale_softens(self, photos):
        from photo_s.suggest import suggest_file
        full = suggest_file(photos["dark"])
        half = suggest_file(photos["dark"], scale=0.5)
        if "ev" in full["suggested"] and "ev" in half["suggested"]:
            assert abs(half["suggested"]["ev"]) <= abs(full["suggested"]["ev"])

    def test_unreadable(self, tmp_path):
        from photo_s.suggest import suggest_file
        r = suggest_file(str(tmp_path / "missing.jpg"))
        assert r["ok"] is False and r["suggested"] == {}

    def test_full_loop_analyze_suggest_process_audit(self, tmp_path, photos):
        """The ROADMAP contract: analyze → suggest → process → audit."""
        from photo_s.suggest import suggest_file
        from photo_s.engine import batch_process, ProcessOptions
        from photo_s.audit import audit_image

        sug = suggest_file(photos["dark"])
        opts = ProcessOptions(
            output_dir=str(tmp_path / "out"),
            output_format="JPEG", quality=90,
            **{k: v for k, v in sug["suggested"].items()
               if k in ProcessOptions.__dataclass_fields__})
        result = batch_process([photos["dark"]], opts)
        assert result.success_count == 1
        out = result.results[0].output_path
        a = audit_image(out)
        # fixing a very dark frame must land inside the audit gates
        assert a["passed"], a["reason"]

    def test_rest_suggest(self, tmp_path, photos):
        from tests.test_server import ServerFixture
        s = ServerFixture(tmp_path)
        try:
            status, payload = s.request(
                "POST", "/v1/suggest",
                {"paths": [photos["dark"], photos["mid"]]})
            assert status == 200
            assert payload["count"] == 2
            dark = next(r for r in payload["results"]
                        if r["path"].endswith("dark.jpg"))
            assert dark["suggested"].get("ev", 0) > 0
        finally:
            s.close()

    def test_mcp_suggest_tool(self, photos):
        from photo_s.mcp_server import suggest_tool
        out = suggest_tool(paths=[photos["dark"]])
        assert out["ok"] and out["count"] == 1
        assert out["results"][0]["suggested"].get("ev", 0) > 0


# ── plugin wiring ────────────────────────────────────────────────────────────


class _FakePlugin:
    name = "fake"

    def __init__(self):
        self.called = None


class TestPluginWiring:
    def test_mcp_hook_registers_overriding_plugin(self, monkeypatch):
        import photo_s.plugin as plugin_mod
        from photo_s.mcp_server import create_server

        fake = _FakePlugin()

        def register(mcp):
            fake.called = mcp

        fake.register_mcp_tools = register  # instance-level override
        monkeypatch.setattr(plugin_mod, "discover_plugins",
                            lambda: [fake])
        mcp = create_server()
        assert fake.called is mcp

    def test_mcp_hook_skips_base_noop(self, monkeypatch):
        import photo_s.plugin as plugin_mod
        from photo_s.hooks import PhotoSPlugin
        from photo_s.mcp_server import create_server, list_tools_json

        # a plugin that does NOT override register_mcp_tools (e.g. scunet)
        # must not register phantoms — compare within the patched world so
        # the assertion holds whatever plugins are really installed
        monkeypatch.setattr(plugin_mod, "discover_plugins",
                            lambda: [PhotoSPlugin()])
        core = len(list_tools_json())
        create_server()  # must not raise
        assert len(list_tools_json()) == core

    def test_rest_hook_registers_once(self, monkeypatch):
        import photo_s.plugin as plugin_mod
        import photo_s.server as server_mod

        calls = []

        class Fake:
            name = "fake"

            def register_rest(self, handler_class):
                calls.append(handler_class)

        monkeypatch.setattr(plugin_mod, "discover_plugins", lambda: [Fake()])
        # strip any earlier once-flag so the test is hermetic
        if hasattr(server_mod._PhotoSHandler, "_plugin_routes_registered"):
            del server_mod._PhotoSHandler._plugin_routes_registered
        server_mod.create_server(port=0).server_close()
        server_mod.create_server(port=0).server_close()
        assert len(calls) == 1  # class-level patching must not stack

    def test_engine_auto_tone_missing_plugin_errors(self, monkeypatch,
                                                    tmp_path, photos):
        import photo_s.plugin as plugin_mod
        from photo_s.engine import process_image, ProcessOptions
        from dataclasses import replace

        monkeypatch.setattr(plugin_mod, "find_provider", lambda op: None)
        opts = replace(ProcessOptions(), auto_tone=0.8,
                       output_dir=str(tmp_path / "o1"))
        res = process_image(photos["mid"], opts)
        assert res.success is False
        assert "auto-tone plugin" in res.error

    def test_engine_auto_tone_delegates_to_provider(self, monkeypatch,
                                                    tmp_path, photos):
        import photo_s.plugin as plugin_mod
        from photo_s.engine import process_image, ProcessOptions
        from dataclasses import replace
        from PIL import ImageEnhance

        seen = {}

        class Provider:
            name = "fake"

            def auto_tone(self, img, strength, ctx):
                seen["strength"] = strength
                seen["input_path"] = ctx.input_path
                return ImageEnhance.Brightness(img).enhance(1.0)

        monkeypatch.setattr(plugin_mod, "find_provider",
                            lambda op: Provider() if op == "auto_tone"
                            else None)
        opts = replace(ProcessOptions(), auto_tone=0.6,
                       output_dir=str(tmp_path / "o2"))
        res = process_image(photos["mid"], opts)
        assert res.success is True, res.error
        assert seen["strength"] == 0.6
        assert seen["input_path"] == photos["mid"]


# ── batch audit ──────────────────────────────────────────────────────────────


def _wait(predicate, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


class TestBatchAudit:
    def test_start_task_attaches_audit(self, tmp_path, photos):
        from photo_s.server import start_task, get_task
        from photo_s.engine import ProcessOptions

        tid = start_task([photos["mid"], photos["dark"]], ProcessOptions(
            output_dir=str(tmp_path / "out"), output_format="JPEG"),
            audit=True)
        assert _wait(lambda: get_task(tid)["status"] in
                     ("done", "error", "cancelled"))
        state = get_task(tid)
        assert state["status"] == "done", state["result"]
        res = state["result"]
        assert res["audit_summary"]["audited"] == 2
        assert 0.0 <= res["audit_summary"]["pass_rate"] <= 1.0
        audited_rows = [r for r in res["results"] if "audit" in r]
        assert len(audited_rows) == 2
        assert all("passed" in r["audit"] for r in audited_rows)

    def test_start_task_without_audit_has_no_summary(self, tmp_path, photos):
        from photo_s.server import start_task, get_task
        from photo_s.engine import ProcessOptions

        tid = start_task([photos["mid"]], ProcessOptions(
            output_dir=str(tmp_path / "out2"), output_format="JPEG"))
        assert _wait(lambda: get_task(tid)["status"] in
                     ("done", "error", "cancelled"))
        res = get_task(tid)["result"]
        assert "audit_summary" not in res

    def test_mcp_batch_start_audit(self, tmp_path, photos):
        pytest.importorskip("mcp")
        from photo_s.mcp_server import (batch_start_tool, batch_status_tool,
                                        _JOBS, _JOBS_LOCK)
        out = batch_start_tool(paths=[photos["mid"]], audit=True,
                               options={"output_dir": str(tmp_path / "o3"),
                                        "output_format": "JPEG"})
        assert out["ok"], out
        jid = out["job_id"]

        def done():
            with _JOBS_LOCK:
                return _JOBS.get(jid, {}).get("phase") in (
                    "done", "error", "cancelled")

        assert _wait(done)
        state = batch_status_tool(jid)
        assert state["phase"] == "done"
        assert state["audit_summary"]["audited"] == 1


# ── cull v2 ──────────────────────────────────────────────────────────────────


class TestCullScore:
    def test_scores_rank_not_reject(self, photos):
        from photo_s.cull import score_files
        rows = score_files([photos["bright"], photos["mid"]])
        assert all("score" in r for r in rows)
        assert rows[0]["score"] >= rows[1]["score"]  # sorted best-first
        assert rows[0]["path"].endswith("mid.jpg")    # mid beats clipped

    def test_unreadable_scores_zero_last(self, tmp_path, photos):
        from photo_s.cull import score_files
        rows = score_files([photos["mid"],
                            str(tmp_path / "nope.jpg")])
        assert rows[-1]["score"] == 0 and rows[-1]["ok"] is False


class TestCullBurst:
    @staticmethod
    def _set_exif_time(path, dt):
        import piexif
        exif = piexif.load(path)
        exif["Exif"][piexif.ExifIFD.DateTimeOriginal] = \
            dt.strftime("%Y:%m:%d %H:%M:%S")
        piexif.insert(piexif.dump(exif), path)

    def test_burst_grouping_by_exif(self, tmp_path):
        from datetime import datetime, timedelta
        from photo_s.cull import group_bursts
        t0 = datetime(2026, 8, 27, 10, 0, 0)
        burst = [_img(tmp_path / f"b{i}.jpg", seed=10 + i) for i in range(3)]
        later = _img(tmp_path / "solo.jpg", seed=99)
        for i, p in enumerate(burst):
            self._set_exif_time(p, t0 + timedelta(seconds=i))
        self._set_exif_time(later, t0 + timedelta(minutes=10))
        groups = group_bursts(burst + [later], gap_seconds=2.0)
        assert len(groups) == 2
        sizes = sorted(g["count"] for g in groups)
        assert sizes == [1, 3]
        big = max(groups, key=lambda g: g["count"])
        assert big["span_seconds"] == 2.0

    def test_mtime_fallback_groups(self, tmp_path):
        from photo_s.cull import group_bursts
        a = _img(tmp_path / "a.jpg", seed=1)
        b = _img(tmp_path / "b.jpg", seed=2)
        c = _img(tmp_path / "c.jpg", seed=3)
        now = time.time()
        os.utime(a, (now, now))
        os.utime(b, (now + 1, now + 1))
        os.utime(c, (now + 600, now + 600))
        groups = group_bursts([a, b, c])
        assert sorted(g["count"] for g in groups) == [1, 2]

    def test_best_of_bursts_marks_sharpest(self, tmp_path):
        from photo_s.cull import best_of_bursts
        # sharp = high-variance noise (high Laplacian score),
        # flat = smooth gradient (low score); same mtime-second group
        sharp = _img(tmp_path / "sharp.jpg", fill=(128, 128, 128),
                     noise=90, seed=5)
        flat = _img(tmp_path / "flat.jpg", fill=(128, 128, 128),
                    noise=0, seed=6)
        now = time.time()
        os.utime(sharp, (now, now))
        os.utime(flat, (now + 0.5, now + 0.5))
        rows = best_of_bursts([flat, sharp])
        by_path = {r["path"]: r for r in rows}
        assert by_path[sharp]["burst_best"] is True
        assert by_path[flat]["burst_best"] is False
        assert by_path[sharp]["burst_size"] == 2
