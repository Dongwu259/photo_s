"""Tests for photo_s/contract.py — the additive schema_version JSON contract.

Verifies that every JSON output surface (CLI --json, REST, MCP tools) carries
the additive ``schema_version`` marker, and that the server security
hardening (ready-file perms, DNS-rebinding Host check, body size cap) works.
"""

import json
import os
import sys
import urllib.request

# Ensure src package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from PIL import Image

from photo_s.contract import SCHEMA_VERSION, versioned
from photo_s.server import (write_ready_file, create_server,
                            _PhotoSHandler, MAX_BODY_BYTES)


# ── versioned() unit ────────────────────────────────────────────────────────

class TestVersioned:
    def test_additive(self):
        out = versioned({"a": 1, "b": [2]})
        assert out["a"] == 1 and out["b"] == [2]
        assert out["schema_version"] == SCHEMA_VERSION

    def test_marker_is_first_key(self):
        out = versioned({"a": 1})
        assert list(out)[0] == "schema_version"

    def test_version_is_one(self):
        assert SCHEMA_VERSION == 1


# ── CLI --json outputs ──────────────────────────────────────────────────────

from photo_s.cli import run_cli


class TestCliContract:
    def test_info_json(self, capsys):
        rc = run_cli(["info", "--json", "--language", "en"])
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert d["schema_version"] == SCHEMA_VERSION
        assert "formats" in d  # original keys preserved

    def test_batch_json(self, tmp_path, capsys):
        img = tmp_path / "in.png"
        Image.new("RGB", (8, 8), (255, 0, 0)).save(img)
        rc = run_cli(["convert", str(img), "-f", "JPEG", "--json",
                      "-o", str(tmp_path / "out")])
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert d["schema_version"] == SCHEMA_VERSION
        assert "summary" in d and "results" in d

    def test_dedup_json(self, tmp_path, capsys):
        img = tmp_path / "in.png"
        Image.new("RGB", (8, 8), (255, 0, 0)).save(img)
        rc = run_cli(["dedup", str(img), "--json", "--language", "en"])
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert d["schema_version"] == SCHEMA_VERSION
        assert "groups" in d


# ── REST outputs ────────────────────────────────────────────────────────────

class ServerFixture:
    def __init__(self, tmp_path, token=None):
        self.server = create_server("127.0.0.1", 0, token=token)
        self.port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        import threading
        threading.Thread(target=self.server.serve_forever,
                         daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def request(self, method, path, body=None, auth=False):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(f"{self.base}{path}", data=data,
                                     method=method)
        if body is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))


@pytest.fixture()
def srv(tmp_path):
    s = ServerFixture(tmp_path)
    yield s
    s.close()


class TestRestContract:
    def test_health_carries_schema_version(self, srv):
        status, payload = srv.request("GET", "/health")
        assert status == 200
        assert payload["schema_version"] == SCHEMA_VERSION
        assert payload["status"] == "ok"

    def test_error_response_carries_schema_version(self, srv):
        # 404 (unknown path) also gets the marker — consistent, harmless
        status, payload = srv.request("GET", "/nope")
        assert status == 404
        assert payload["schema_version"] == SCHEMA_VERSION


# ── MCP tools ───────────────────────────────────────────────────────────────

from photo_s import mcp_server as mcp


class TestMcpContract:
    def test_info_tool_carries_schema_version(self):
        out = mcp.info_tool()
        assert out["schema_version"] == SCHEMA_VERSION
        assert "version" in out

    def test_process_tool_error_carries_schema_version(self):
        out = mcp.process_tool(paths=["/nonexistent/*.jpg"])
        assert out["schema_version"] == SCHEMA_VERSION
        assert out["ok"] is False


# ── Server security hardening ───────────────────────────────────────────────

class TestReadyFilePerms:
    def test_mode_is_0600(self, tmp_path):
        p = tmp_path / "ready.json"
        write_ready_file(str(p), 1234, "secret")
        mode = os.stat(p).st_mode & 0o777
        assert mode == 0o600
        content = json.loads(p.read_text(encoding="utf-8"))
        assert content["token"] == "secret"


class TestHostAllowlist:
    def _handler(self, host):
        h = _PhotoSHandler.__new__(_PhotoSHandler)
        h.server = type("S", (), {"server_address": ("127.0.0.1", 8787)})()
        h.headers = {"Host": host}
        return h

    def test_loopback_allowed(self):
        assert self._handler("localhost")._host_allowed() is True
        assert self._handler("127.0.0.1:9999")._host_allowed() is True
        assert self._handler("[::1]:80")._host_allowed() is True

    def test_rebinding_blocked(self):
        # attacker.com resolving to 127.0.0.1 must be rejected
        assert self._handler("attacker.com")._host_allowed() is False

    def test_other_host_blocked(self):
        assert self._handler("10.0.0.5")._host_allowed() is False


class TestReadJsonCap:
    def test_oversize_returns_none_and_413(self, srv, tmp_path):
        # build a body larger than the cap and confirm it's rejected
        big = {"paths": ["/tmp/x"], "pad": "x" * (MAX_BODY_BYTES + 10)}
        status, payload = srv.request("POST", "/process", body=big)
        assert status == 413
        assert payload["schema_version"] == SCHEMA_VERSION
        assert "too large" in payload["error"]
