"""Graceful-degradation tests for the MCP feature — these run EVEN when the
optional `mcp` extra is not installed.

Covers: missing-mcp hint, py3.9 version guard, no-traceback CLI errors.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from photo_s.cli import run_cli


class TestMissingMcp:
    def test_mcp_hint(self, monkeypatch):
        """_mcp() must raise a clear RuntimeError when mcp is not importable."""
        monkeypatch.setitem(sys.modules, "mcp", None)
        monkeypatch.setitem(sys.modules, "mcp.server", None)
        monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", None)
        from photo_s import mcp_server
        with pytest.raises(RuntimeError, match=r"photo-s\[mcp\]"):
            mcp_server._mcp()

    def test_cli_list_tools_missing_mcp(self, capsys, monkeypatch):
        monkeypatch.setitem(sys.modules, "mcp", None)
        monkeypatch.setitem(sys.modules, "mcp.server", None)
        monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", None)
        rc = run_cli(["mcp", "--list-tools"])
        err = capsys.readouterr().err
        assert rc == 1
        assert "photo-s[mcp]" in err
        assert "Traceback" not in err


class TestPy39Guard:
    def test_py39_clear_error(self, capsys, monkeypatch):
        """photo-s mcp on py3.9 → clear "requires Python 3.10+" message."""
        monkeypatch.setattr(sys, "version_info", (3, 9, 18))
        rc = run_cli(["mcp"])
        err = capsys.readouterr().err
        assert rc == 1
        assert "3.10" in err
        assert "Traceback" not in err
