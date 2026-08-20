"""Tests for the stdlib REST API server in photo_s.server."""

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error

# Ensure src package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from PIL import Image

from photo_s.server import create_server, generate_token, write_ready_file
from photo_s.engine import ProcessOptions


class ServerFixture:
    def __init__(self, tmp_path, token=None, options=None):
        self.server = create_server("127.0.0.1", 0,
                                    options=options, token=token)
        self.port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self.token = token
        thread = threading.Thread(target=self.server.serve_forever,
                                  daemon=True)
        thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def request(self, method, path, body=None, auth=True):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(f"{self.base}{path}", data=data,
                                     method=method)
        if body is not None:
            req.add_header("Content-Type", "application/json")
        if self.token and auth:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))


@pytest.fixture()
def server(tmp_path):
    img = tmp_path / "a.png"
    Image.new("RGB", (32, 32), (200, 100, 50)).save(img)
    s = ServerFixture(tmp_path)
    yield s, str(img)
    s.close()


def test_health(server):
    s, _ = server
    status, payload = s.request("GET", "/health")
    assert status == 200
    assert payload["status"] == "ok"
    assert "version" in payload


def test_info(server):
    s, _ = server
    status, payload = s.request("GET", "/info")
    assert status == 200
    assert "formats" in payload
    assert "JPEG" in payload["formats"]
    assert "plugins" in payload


def test_process_single_image(server):
    s, img = server
    status, payload = s.request("POST", "/process",
                                {"paths": [img], "options": {"quality": 70}})
    assert status == 200
    assert payload["summary"]["success"] == 1
    assert payload["summary"]["failed"] == 0
    assert payload["results"][0]["quality"] == 70


def test_process_includes_ssim_field(server):
    s, img = server
    status, payload = s.request("POST", "/process",
                                {"paths": [img],
                                 "options": {"evaluate": True}})
    assert status == 200
    assert "ssim" in payload["results"][0]


def test_process_unknown_path_400(server):
    s, _ = server
    status, payload = s.request("POST", "/process", {"paths": ["/nope.jpg"]})
    assert status == 400


def test_dedup(server, tmp_path):
    s, img = server
    # two identical files at different paths (a set-deduped duplicate path would
    # collapse into one file and never register as a duplicate)
    dup = tmp_path / "copy.png"
    import shutil
    shutil.copyfile(img, dup)
    status, payload = s.request("POST", "/dedup",
                                {"paths": [img, str(dup)], "threshold": 5})
    assert status == 200
    assert payload["count"] == 1
    assert len(payload["groups"][0]["paths"]) == 2


def test_process_transform_options(server):
    s, img = server
    status, payload = s.request("POST", "/process",
                                {"paths": [img],
                                 "options": {"brightness": 1.5,
                                             "scrub": True,
                                             "date_shift": "+1h",
                                             "rotate_degrees": 90}})
    assert status == 200
    assert payload["summary"]["success"] == 1
    r = payload["results"][0]
    # 32x32 rotated 90° → 32x32; dims unchanged
    assert r["output_dims"] == r["input_dims"]


def test_process_float_roundtrip(server):
    s, img = server
    from photo_s.server import _options_from_dict
    opts = _options_from_dict({"brightness": 1.5, "gamma": 2.0,
                               "bogus_float": "x"})
    assert opts.brightness == 1.5
    assert opts.gamma == 2.0
    # unknown keys / bad casts silently ignored
    assert opts.quality == 85


def test_rename_dry_run(server):
    s, img = server
    status, payload = s.request("POST", "/rename",
                                {"paths": [img], "pattern": "Trip_{seq}",
                                 "dry_run": True})
    assert status == 200
    assert payload["ok"] == 1
    assert payload["results"][0]["output"].endswith("Trip_001.png")
    # dry run: original untouched
    assert os.path.exists(img)


def test_rename_missing_pattern_400(server):
    s, img = server
    status, _ = s.request("POST", "/rename", {"paths": [img]})
    assert status == 400


def test_contact_sheet_endpoint(server):
    s, img = server
    import shutil
    dup = img.replace(".png", "_2.png")
    shutil.copyfile(img, dup)
    out = os.path.join(os.path.dirname(img), "sheet.png")
    status, payload = s.request("POST", "/contact-sheet",
                                {"paths": [img, dup], "output": out,
                                 "cols": 2})
    assert status == 200
    assert payload["count"] == 2
    assert os.path.exists(payload["output"])


def test_contact_sheet_missing_output_400(server):
    s, img = server
    status, _ = s.request("POST", "/contact-sheet", {"paths": [img]})
    assert status == 400


def test_check_endpoint(server):
    s, img = server
    status, payload = s.request("POST", "/check", {"paths": [img]})
    assert status == 200
    assert payload["checked"] == 1
    assert payload["ok"] == 1
    assert payload["corrupt"] == []


def test_not_found(server):
    s, _ = server
    status, _ = s.request("GET", "/bogus")
    assert status == 404


class TestAutomationHandshake:
    """--token auto + --ready-file: the host-agent integration contract."""

    def test_generate_token_is_urlsafe(self):
        t = generate_token()
        assert len(t) >= 20
        assert all(c.isalnum() or c in "-_" for c in t)

    def test_generate_token_unique(self):
        assert generate_token() != generate_token()

    def test_write_ready_file_atomic(self, tmp_path):
        path = str(tmp_path / "ready.json")
        write_ready_file(path, 43210, "tok123")
        data = json.loads(open(path).read())
        assert data["port"] == 43210
        assert data["token"] == "tok123"
        assert data["pid"] == os.getpid()

    def test_serve_end_to_end_via_subprocess(self, tmp_path):
        """Full agent flow: spawn serve --token auto --ready-file, poll the
        handshake file, then talk to /health with the handshake token."""
        import photo_s.cli as cli_mod
        ready = str(tmp_path / "ready.json")
        proc = subprocess.Popen(
            [sys.executable, "-m", "photo_s.cli", "serve",
             "--port", "0", "--token", "auto", "--ready-file", ready],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={**os.environ, "PYTHONPATH": os.path.dirname(
                os.path.dirname(os.path.abspath(cli_mod.__file__)))},
        )
        try:
            # poll for the handshake file (timeout 15s)
            deadline = time.time() + 15
            while time.time() < deadline and not os.path.exists(ready):
                time.sleep(0.1)
            assert os.path.exists(ready), "ready file never appeared"

            info = json.loads(open(ready).read())
            base = f"http://127.0.0.1:{info['port']}"

            # health without token → 401
            req = urllib.request.Request(f"{base}/health")
            try:
                urllib.request.urlopen(req, timeout=5)
                assert False, "expected 401"
            except urllib.error.HTTPError as e:
                assert e.code == 401

            # health with handshake token → 200
            req = urllib.request.Request(f"{base}/health")
            req.add_header("Authorization", f"Bearer {info['token']}")
            with urllib.request.urlopen(req, timeout=5) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            assert payload["status"] == "ok"
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


class TestTokenAuth:
    def test_missing_token_401(self, tmp_path):
        s = ServerFixture(tmp_path, token="secret123")
        try:
            status, _ = s.request("GET", "/health", auth=False)
            assert status == 401
        finally:
            s.close()

    def test_wrong_token_401(self, tmp_path):
        s = ServerFixture(tmp_path, token="secret123")
        try:
            req = urllib.request.Request(f"{s.base}/health")
            req.add_header("Authorization", "Bearer wrong")
            try:
                urllib.request.urlopen(req, timeout=5)
                assert False, "expected 401"
            except urllib.error.HTTPError as e:
                assert e.code == 401
        finally:
            s.close()

    def test_correct_token_200(self, tmp_path):
        s = ServerFixture(tmp_path, token="secret123")
        try:
            status, payload = s.request("GET", "/health")
            assert status == 200
            assert payload["status"] == "ok"
        finally:
            s.close()


class TestCsrf:
    """No-token mode must reject browser cross-origin requests (CSRF)."""

    def _status_with_origin(self, tmp_path, origin, path="/health",
                            method="GET", body=None):
        s = ServerFixture(tmp_path, token=None)
        try:
            data = json.dumps(body).encode() if body is not None else None
            req = urllib.request.Request(f"{s.base}{path}", data=data,
                                         method=method)
            if body is not None:
                req.add_header("Content-Type", "application/json")
            if origin is not None:
                req.add_header("Origin", origin)
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    return resp.status
            except urllib.error.HTTPError as e:
                return e.code
        finally:
            s.close()

    def test_no_origin_allowed(self, tmp_path):
        # CLI/curl/agent clients send no Origin header → unaffected
        assert self._status_with_origin(tmp_path, None) == 200

    def test_same_origin_allowed(self, tmp_path):
        s = ServerFixture(tmp_path, token=None)
        try:
            req = urllib.request.Request(f"{s.base}/health")
            req.add_header("Origin", f"http://127.0.0.1:{s.port}")
            with urllib.request.urlopen(req, timeout=5) as resp:
                assert resp.status == 200
        finally:
            s.close()

    def test_cross_origin_rejected(self, tmp_path):
        assert self._status_with_origin(tmp_path, "http://evil.example.com") == 401

    def test_null_origin_rejected(self, tmp_path):
        # sandboxed iframes / file:// pages send Origin: null
        assert self._status_with_origin(tmp_path, "null") == 401

    def test_cross_origin_process_post_blocked(self, tmp_path):
        # The destructive /process endpoint must not accept cross-origin posts
        img = tmp_path / "a.png"
        Image.new("RGB", (8, 8)).save(img)
        body = {"paths": [str(img)], "dry_run": True}
        status = self._status_with_origin(
            tmp_path, "http://evil.example.com",
            path="/process", method="POST", body=body)
        assert status == 401


def test_process_dry_run(server):
    s, img = server
    out = os.path.join(os.path.dirname(img), "out")
    status, payload = s.request("POST", "/process",
                                {"paths": [img], "dry_run": True,
                                 "options": {"output_dir": out, "quality": 70}})
    assert status == 200
    assert payload["dry_run"] is True
    assert payload["count"] == 1
    assert payload["paths"] == [os.path.abspath(img)]
    assert not os.path.exists(out)  # no processing side effects


def test_process_multi_size_via_options(server):
    s, img = server
    status, payload = s.request(
        "POST", "/process",
        {"paths": [img], "options": {"output_sizes": [["thumb", 16, None]]}})
    assert status == 200
    r = payload["results"][0]
    assert r["status"] == "ok"
    from pathlib import Path
    main = Path(r["output"])
    thumb = main.with_name(main.stem + "_thumb" + main.suffix)
    assert thumb.exists(), "multi-size output not written"


def test_options_from_dict_output_sizes_and_pad():
    from photo_s.server import _options_from_dict
    opts = _options_from_dict({
        "output_sizes": [["thumb", 16, None],
                         {"label": "screen", "width": 800}],
        "pad": "16:9",
    })
    assert opts.output_sizes == [("thumb", 16, None), ("screen", 800, None)]
    assert opts.pad_ratio == "16:9"


def test_options_from_dict_format_case_insensitive():
    from photo_s.server import _options_from_dict
    opts = _options_from_dict({"output_format": "png"})
    assert opts.output_format == "PNG"
    opts = _options_from_dict({"output_format": "webp"})
    assert opts.output_format == "WebP"


def test_scalar_groups_cover_all_fields():
    """Every ProcessOptions field is reachable via the JSON API — either in a
    derived scalar group or explicitly special-cased. Guards against the
    historical whitelist drift that silently dropped output_sizes / pad."""
    from photo_s.server import (
        _INT_FIELDS, _FLOAT_FIELDS, _STR_FIELDS, _BOOL_FIELDS)
    covered = (set(_INT_FIELDS) | set(_FLOAT_FIELDS)
               | set(_STR_FIELDS) | set(_BOOL_FIELDS))
    all_fields = set(ProcessOptions.__dataclass_fields__)
    assert all_fields - covered <= {"output_sizes"}  # list, handled specially


def test_process_recursive_scan(server, tmp_path):
    s, img = server
    sub = tmp_path / "sub"
    sub.mkdir()
    Image.new("RGB", (16, 16), (10, 200, 10)).save(sub / "nested.png")
    # output dir must sit OUTSIDE the scanned tree, or the recursive scan
    # picks up previous runs' outputs as new inputs
    out_dir = str(tmp_path.parent / f"{tmp_path.name}-out")
    # shallow: only the top-level file
    status, payload = s.request("POST", "/process",
                                {"paths": [str(tmp_path)],
                                 "options": {"output_dir": out_dir}})
    assert status == 200
    assert payload["summary"]["total"] == 1
    # recursive: includes the subdirectory file
    status, payload = s.request("POST", "/process",
                                {"paths": [str(tmp_path)], "recursive": True,
                                 "options": {"output_dir": out_dir}})
    assert status == 200
    names = {os.path.basename(r["input"]) for r in payload["results"]}
    assert "a.png" in names and "nested.png" in names
    assert payload["summary"]["total"] == 2


def test_process_async_roundtrip(server):
    s, img = server
    status, payload = s.request("POST", "/process",
                                {"paths": [img], "async": True})
    assert status == 202
    tid = payload["task_id"]
    assert payload["poll"] == f"/tasks/{tid}"

    deadline = time.time() + 5
    state = None
    while time.time() < deadline:
        st, state = s.request("GET", f"/tasks/{tid}")
        assert st == 200
        if state["status"] in ("done", "error", "cancelled"):
            break
        time.sleep(0.01)
    assert state["status"] == "done"
    assert state["result"]["summary"]["success"] == 1

    # task appears in the list endpoint
    _, tasks = s.request("GET", "/tasks")
    assert any(t["task_id"] == tid for t in tasks["tasks"])


def test_task_cancel_endpoint(server):
    s, img = server
    status, payload = s.request("POST", "/process",
                                {"paths": [img], "async": True})
    assert status == 202
    tid = payload["task_id"]
    status, resp = s.request("POST", f"/tasks/{tid}/cancel")
    assert status == 200
    assert resp["cancelled"] is True
    # unknown task → 404
    status, resp = s.request("POST", "/tasks/nope/cancel")
    assert status == 404


def test_start_task_cancel_honored(monkeypatch):
    """The async task honors cancel via the engine's cancel_checker."""
    from types import SimpleNamespace
    import photo_s.server as srv

    def fake_batch(paths, options, progress_callback=None, cancel_checker=None):
        for _ in range(20):
            if cancel_checker and cancel_checker():
                break
            time.sleep(0.001)
        return SimpleNamespace(to_dict=lambda: {"summary": {"cancelled": True}})

    monkeypatch.setattr(srv, "batch_process", fake_batch)
    tid = srv.start_task(["/tmp/a.jpg"], ProcessOptions())
    with srv._TASKS_LOCK:
        srv._TASKS[tid]["cancel"].set()

    deadline = time.time() + 5
    state = None
    while time.time() < deadline:
        state = srv.get_task(tid)
        if state["status"] in ("done", "error", "cancelled"):
            break
        time.sleep(0.001)
    assert state["status"] == "cancelled"


class TestProcessStreamSSE:
    """POST /process/stream: per-file SSE frames + final done frame."""

    def _stream(self, port, token, body):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        conn.request("POST", "/process/stream", body=json.dumps(body),
                     headers=headers)
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
        status = resp.status
        ctype = resp.getheader("Content-Type", "")
        conn.close()
        return status, ctype, raw

    @staticmethod
    def _parse_frames(raw):
        frames = []
        for block in raw.split("\n\n"):
            block = block.strip()
            if block.startswith("data: "):
                frames.append(json.loads(block[len("data: "):]))
        return frames

    def test_streams_progress_and_done(self, tmp_path, server):
        s, img = server
        out = tmp_path / "out"
        status, ctype, raw = self._stream(
            s.port, s.token,
            {"paths": [img], "options": {"output_dir": str(out),
                                         "output_format": "PNG",
                                         "suffix": ""}})
        assert status == 200
        assert ctype.startswith("text/event-stream")
        frames = self._parse_frames(raw)
        progress = [f for f in frames if "current" in f]
        done = [f for f in frames if f.get("status") == "done"]
        assert progress, "expected at least one progress frame"
        assert progress[0]["total"] == 1
        assert progress[0]["current"] == 1
        assert done and done[-1]["result"]["summary"]["success"] == 1

    def test_unauthorized(self, tmp_path):
        s = ServerFixture(tmp_path, token="secret")
        try:
            status, ctype, raw = self._stream(s.port, "wrong", {"paths": []})
            assert status == 401
            assert "error" in json.loads(raw)
        finally:
            s.close()


class TestDoPostResilience:
    """Regression: do_POST must never die with an empty reply — validation
    errors → 400, unexpected errors → 500 JSON."""

    def test_process_unknown_output_format_400(self, server):
        s, img = server
        status, payload = s.request(
            "POST", "/process",
            {"paths": [img], "options": {"output_format": "BOGUS"}})
        assert status == 400
        assert payload["ok"] is False
        assert "unsupported output format" in payload["error"]

    def test_process_internal_error_500(self, server, monkeypatch):
        """Blanket guard: an unexpected engine failure → 500 JSON {"ok": False}
        instead of a dropped connection (the old crash path)."""
        import photo_s.server as srv

        def boom(paths, options, **kw):
            raise RuntimeError("engine exploded")

        monkeypatch.setattr(srv, "batch_process", boom)
        s, img = server
        status, payload = s.request("POST", "/process", {"paths": [img]})
        assert status == 500
        assert payload["ok"] is False
        assert "engine exploded" in payload["error"]

    def test_contact_sheet_zero_cols_and_thumb_clamped(self, server):
        """cols=0 used to crash the grid math with ZeroDivisionError."""
        s, img = server
        out = os.path.join(os.path.dirname(img), "sheet0.png")
        status, payload = s.request(
            "POST", "/contact-sheet",
            {"paths": [img], "output": out, "cols": 0, "thumb_width": 0})
        assert status == 200
        assert os.path.exists(payload["output"])

    def test_output_sizes_scalar_entry_ignored(self, server):
        """[42] used to raise TypeError inside _options_from_dict."""
        s, img = server
        status, payload = s.request(
            "POST", "/process",
            {"paths": [img],
             "options": {"output_sizes": [42, ["thumb", 16, None]]}})
        assert status == 200
        assert payload["results"][0]["status"] == "ok"
        from pathlib import Path
        main = Path(payload["results"][0]["output"])
        assert main.with_name(main.stem + "_thumb" + main.suffix).exists()


def test_options_from_dict_rejects_unknown_format():
    from photo_s.server import _options_from_dict
    with pytest.raises(ValueError, match="unsupported output format"):
        _options_from_dict({"output_format": "BOGUS"})


def test_options_from_dict_output_sizes_skips_scalars():
    from photo_s.server import _options_from_dict
    opts = _options_from_dict({"output_sizes": [42, ["thumb", 16, None]]})
    assert opts.output_sizes == [("thumb", 16, None)]


def test_analyze_route(server):
    s, img = server
    status, payload = s.request("POST", "/analyze", {"paths": [img]})
    assert status == 200
    assert payload["ok"] is True
    res = payload["results"][0]
    assert set(res["histogram"]) == {"r", "g", "b", "luma"}
    assert "kelvin_estimate" in res["white_balance"]
    assert payload["schema_version"] == 1


def test_analyze_route_no_files(server):
    s, _ = server
    status, payload = s.request("POST", "/analyze", {"paths": ["/nope.jpg"]})
    assert status == 400


def test_analyze_route_sample_size_clamped(server):
    s, img = server
    status, payload = s.request("POST", "/analyze",
                                {"paths": [img], "sample_size": "bogus"})
    assert status == 200  # falls back to default instead of 500
    assert payload["ok"] is True
