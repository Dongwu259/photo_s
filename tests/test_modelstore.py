"""Tests for the model weight store (photo_s.modelstore).

Covers cache-dir resolution, file:// downloads, sha256 verify, atomic rename,
mismatch cleanup, cache hits, and one http:// path via a stdlib server.
"""

import hashlib
import json
import os
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from photo_s import modelstore


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _spec(name="m.onnx", url="", sha="", size=0):
    return modelstore.WeightSpec(name=name, url=url, sha256=sha, size=size)


class TestCacheDir:
    def test_photos_cache_dir(self, monkeypatch):
        from pathlib import Path
        monkeypatch.setenv("PHOTOS_CACHE_DIR", "/tmp/photos-cache")
        monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
        # Path equality normalizes separators on both sides (Windows CI
        # keeps the env value verbatim and joins with backslashes)
        assert Path(modelstore.cache_dir()) == Path("/tmp/photos-cache") \
            / "models"

    def test_xdg(self, monkeypatch, tmp_path):
        monkeypatch.delenv("PHOTOS_CACHE_DIR", raising=False)
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        assert modelstore.cache_dir() == str(tmp_path / "photo-s" / "models")

    def test_default(self, monkeypatch):
        monkeypatch.delenv("PHOTOS_CACHE_DIR", raising=False)
        monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
        assert modelstore.cache_dir().endswith(
            os.path.join(".cache", "photo-s", "models"))


class TestVerify:
    def test_verify_true_false(self, tmp_path):
        p = tmp_path / "f.bin"
        p.write_bytes(b"hello")
        assert modelstore.verify(str(p), _digest(b"hello")) is True
        assert modelstore.verify(str(p), _digest(b"nope")) is False
        assert modelstore.verify(str(tmp_path / "missing"), "0" * 64) is False


class TestEnsure:
    def test_download_file_url_and_cache_hit(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PHOTOS_CACHE_DIR", str(tmp_path / "cache"))
        src = tmp_path / "src.onnx"
        data = b"\x00\x01model-bytes"
        src.write_bytes(data)
        spec = _spec(name="m.onnx",
                     url=src.as_uri(), sha=_digest(data), size=len(data))

        path = modelstore.ensure(spec)
        assert os.path.isfile(path)
        assert path == os.path.join(modelstore.cache_dir(), "m.onnx")
        assert open(path, "rb").read() == data

        # second call is a cache hit — no redownload (remove source to prove it)
        src.unlink()
        path2 = modelstore.ensure(spec)
        assert path2 == path

    def test_sha256_mismatch_raises_and_cleans_part(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PHOTOS_CACHE_DIR", str(tmp_path / "cache"))
        src = tmp_path / "src.onnx"
        data = b"model-bytes"
        src.write_bytes(data)
        spec = _spec(name="m.onnx", url=src.as_uri(), sha="f" * 64)

        with pytest.raises(RuntimeError, match="sha256 mismatch"):
            modelstore.ensure(spec)
        # no .part leftover, no final file
        cache = tmp_path / "cache" / "models"
        assert not list(cache.glob("*.part"))
        assert not (cache / "m.onnx").exists()

    def test_missing_file_url_raises(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PHOTOS_CACHE_DIR", str(tmp_path / "cache"))
        monkeypatch.setattr(modelstore, "_RETRY_SLEEP", 0.0)
        spec = _spec(name="m.onnx",
                     url=(tmp_path / "missing.onnx").as_uri(), sha="0" * 64)
        with pytest.raises(RuntimeError, match="download failed"):
            modelstore.ensure(spec)

    def test_cached_path_none_when_not_verified(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PHOTOS_CACHE_DIR", str(tmp_path / "cache"))
        spec = _spec(name="m.onnx", url="file:///none", sha="0" * 64)
        assert modelstore.cached_path(spec) is None


class TestHttpDownload:
    """One http:// path via a stdlib ThreadingHTTPServer (mirrors test_server)."""

    def test_http_download(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PHOTOS_CACHE_DIR", str(tmp_path / "cache"))
        data = b"http-model-bytes" * 10

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            spec = _spec(name="m.onnx",
                         url=f"http://127.0.0.1:{port}/m.onnx",
                         sha=_digest(data), size=len(data))
            path = modelstore.ensure(spec)
            assert open(path, "rb").read() == data
        finally:
            server.shutdown()
            server.server_close()


class TestStatus:
    def test_status_shape(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PHOTOS_CACHE_DIR", str(tmp_path / "cache"))
        spec = _spec(name="m.onnx", url="file:///none", sha="0" * 64, size=42)
        s = modelstore.status(spec)
        assert s["name"] == "m.onnx"
        assert s["cached"] is False
        assert s["path"] is None
        assert s["size"] == 42


class TestPartFileThreadUnique:
    """Regression: ensure() used pid-only .part — collided across threads."""

    def test_part_name_contains_thread_id(self):
        import photo_s.modelstore as ms
        src = open(ms.__file__).read()
        assert "threading.get_ident()" in src


class TestSlowNetwork:
    """v2.1.1 hardening: retries, HTTP Range resume, stale-part adoption/sweep.

    Each test stands up a stdlib HTTP server (mirrors TestHttpDownload) and,
    where relevant, plants a partial left by a *dead* process — the exact
    real-world failure: a first-use download that stalls on a slow link.
    """

    @staticmethod
    def _stale_part(spec_name, data, age=300.0, tag="99999.8888"):
        """Plant a dead process's partial in the cache (old mtime)."""
        import time as _time
        os.makedirs(modelstore.cache_dir(), exist_ok=True)
        p = os.path.join(modelstore.cache_dir(),
                         "{}.{}.part".format(spec_name, tag))
        with open(p, "wb") as f:
            f.write(data)
        t = _time.time() - age
        os.utime(p, (t, t))
        return p

    @staticmethod
    def _serve(handler_cls):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, "http://127.0.0.1:{}".format(server.server_address[1])

    def test_stale_part_resumed_via_range(self, tmp_path, monkeypatch):
        """The core fix: a stalled first download resumes instead of
        restarting — the server sees Range: bytes=<offset>- and serves only
        the remainder."""
        monkeypatch.setenv("PHOTOS_CACHE_DIR", str(tmp_path / "cache"))
        data = bytes(range(256)) * 400                      # 100 KiB
        half = len(data) // 2
        self._stale_part("m.onnx", data[:half])
        seen = {}

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                seen["range"] = self.headers.get("Range")
                self.send_response(206)
                self.send_header("Content-Length",
                                 str(len(data) - half))
                self.end_headers()
                self.wfile.write(data[half:])

            def log_message(self, *a):
                pass

        server, base = self._serve(H)
        try:
            spec = _spec(name="m.onnx", url=base + "/m.onnx",
                         sha=_digest(data), size=len(data))
            path = modelstore.ensure(spec)
            assert open(path, "rb").read() == data
            assert seen["range"] == "bytes={}-".format(half)
            # no .part leftovers — the adopted one renamed, nothing else
            assert not list((tmp_path / "cache" / "models").glob("*.part"))
        finally:
            server.shutdown()
            server.server_close()

    def test_complete_stale_part_adopted_offline(self, tmp_path, monkeypatch):
        """A partial holding the whole verified file (download finished, the
        process died before the rename) is accepted with zero network use."""
        monkeypatch.setenv("PHOTOS_CACHE_DIR", str(tmp_path / "cache"))
        data = b"whole-file-but-unrenamed"
        self._stale_part("m.onnx", data)
        spec = _spec(name="m.onnx", url="file:///definitely/missing.onnx",
                     sha=_digest(data), size=len(data))
        path = modelstore.ensure(spec)
        assert open(path, "rb").read() == data
        assert not list((tmp_path / "cache" / "models").glob("*.part"))

    def test_retry_after_server_error(self, tmp_path, monkeypatch):
        """Transient 500 → retried, second attempt succeeds."""
        monkeypatch.setenv("PHOTOS_CACHE_DIR", str(tmp_path / "cache"))
        monkeypatch.setattr(modelstore, "_RETRY_SLEEP", 0.0)
        data = b"retry-model-bytes" * 8
        hits = {"n": 0}

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                hits["n"] += 1
                if hits["n"] == 1:
                    self.send_response(500)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        server, base = self._serve(H)
        try:
            spec = _spec(name="m.onnx", url=base + "/m.onnx",
                         sha=_digest(data), size=len(data))
            assert open(modelstore.ensure(spec), "rb").read() == data
            assert hits["n"] == 2
        finally:
            server.shutdown()
            server.server_close()

    def test_range_ignored_falls_back_to_full(self, tmp_path, monkeypatch):
        """file://-style servers that ignore Range (200 + full body) must not
        corrupt the file by appending a second copy of the prefix."""
        monkeypatch.setenv("PHOTOS_CACHE_DIR", str(tmp_path / "cache"))
        data = b"mirror-server-full-body" * 16
        self._stale_part("m.onnx", data[:40])
        seen = {}

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                seen["range"] = self.headers.get("Range")
                self.send_response(200)          # Range deliberately ignored
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        server, base = self._serve(H)
        try:
            spec = _spec(name="m.onnx", url=base + "/m.onnx",
                         sha=_digest(data), size=len(data))
            assert open(modelstore.ensure(spec), "rb").read() == data
            assert seen["range"] is not None      # resume was attempted
        finally:
            server.shutdown()
            server.server_close()

    def test_416_falls_back_to_full(self, tmp_path, monkeypatch):
        """Server refusing the range (416) → clean restart inside the call."""
        monkeypatch.setenv("PHOTOS_CACHE_DIR", str(tmp_path / "cache"))
        data = b"range-unsatisfiable" * 32
        # 32 < len(data): a partial larger than the declared file size would be
        # (correctly) rejected as corrupt before any request is made
        self._stale_part("m.onnx", b"\xff" * 32)
        hits = {"n": 0}

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                hits["n"] += 1
                if self.headers.get("Range"):
                    self.send_response(416)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        server, base = self._serve(H)
        try:
            spec = _spec(name="m.onnx", url=base + "/m.onnx",
                         sha=_digest(data), size=len(data))
            assert open(modelstore.ensure(spec), "rb").read() == data
            assert hits["n"] == 2
        finally:
            server.shutdown()
            server.server_close()

    def test_stale_parts_swept_after_success(self, tmp_path, monkeypatch):
        """Once the final file verifies, every other .part is garbage."""
        monkeypatch.setenv("PHOTOS_CACHE_DIR", str(tmp_path / "cache"))
        data = b"sweep-me"
        # empty partials: skipped by adoption (size 0) but matched by the sweep
        self._stale_part("m.onnx", b"", tag="99999.8888")
        self._stale_part("m.onnx", b"", age=600.0, tag="77777.6666")
        src = tmp_path / "src.onnx"
        src.write_bytes(data)
        spec = _spec(name="m.onnx", url=src.as_uri(),
                     sha=_digest(data), size=len(data))
        modelstore.ensure(spec)
        assert not list((tmp_path / "cache" / "models").glob("*.part"))

    def test_fresh_foreign_part_not_stolen(self, tmp_path, monkeypatch):
        """A partial touched < _STALE_PART_SECONDS ago belongs to a live
        writer — never adopted, left exactly as found on failure."""
        monkeypatch.setenv("PHOTOS_CACHE_DIR", str(tmp_path / "cache"))
        monkeypatch.setattr(modelstore, "_RETRY_SLEEP", 0.0)

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(503)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *a):
                pass

        server, base = self._serve(H)
        try:
            os.makedirs(modelstore.cache_dir(), exist_ok=True)
            fresh = os.path.join(modelstore.cache_dir(),
                                 "m.onnx.111.222.part")
            with open(fresh, "wb") as f:
                f.write(b"live-writer-partial")
            spec = _spec(name="m.onnx", url=base + "/m.onnx", sha="0" * 64)
            with pytest.raises(RuntimeError, match="download failed"):
                modelstore.ensure(spec)
            assert open(fresh, "rb").read() == b"live-writer-partial"
        finally:
            server.shutdown()
            server.server_close()
