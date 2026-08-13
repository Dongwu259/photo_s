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
        # pathlib comparison — separator-agnostic (Windows CI uses \\)
        assert modelstore.cache_dir() == str(Path("/tmp/photos-cache")
                                             / "models")

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
