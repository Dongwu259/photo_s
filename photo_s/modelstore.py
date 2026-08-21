"""
PhotoS - Model Weight Store (download / verify / cache)

Official optional plugins ship code on PyPI but keep large model weights out
of the wheel. Weights are downloaded on first use from a canonical URL (e.g. a
GitHub Release asset) into a per-user cache directory, verified against a
sha256 digest, and cached thereafter.

Cache directory resolution:
    $PHOTOS_CACHE_DIR          → <dir>/models
    $XDG_CACHE_HOME/photo-s    → <xdg>/photo-s/models
    default                    → ~/.cache/photo-s/models

Stdlib only (urllib.request) — matches the project's no-heavy-deps stance.
"""

import hashlib
import os
import sys
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import __version__

_CHUNK = 65536


@dataclass(frozen=True)
class WeightSpec:
    """A single downloadable model weight file.

    Plugins expose their weights via ``PhotoSPlugin.weight_specs()``; the
    engine / ``plugin fetch`` command turns each spec into a cached file via
    :func:`ensure`. ``url`` may be ``http(s)://`` or ``file://`` (the latter
    is used by tests).
    """
    name: str        # basename in the cache, e.g. "scunet.onnx"
    url: str         # http(s):// or file://
    sha256: str      # lowercase hex digest of the file
    size: int = 0    # bytes, informational only


def cache_dir() -> str:
    """Resolve the model cache directory (created lazily on demand)."""
    env = os.environ.get("PHOTOS_CACHE_DIR")
    if env:
        return os.path.join(env, "models")
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return os.path.join(xdg, "photo-s", "models")
    return str(Path.home() / ".cache" / "photo-s" / "models")


def _path_for(spec: WeightSpec) -> str:
    return os.path.join(cache_dir(), spec.name)


def verify(path: str, sha256: str) -> bool:
    """True iff the file at ``path`` hashes to ``sha256``."""
    if not os.path.isfile(path):
        return False
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(_CHUNK)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError:
        return False
    return digest.hexdigest().lower() == sha256.lower()


def cached_path(spec: WeightSpec) -> Optional[str]:
    """Absolute cached path if present AND verified, else None."""
    path = _path_for(spec)
    if verify(path, spec.sha256):
        return path
    return None


def status(spec: WeightSpec) -> dict:
    """Machine-readable weight state for ``plugin info`` / ``plugin fetch``."""
    path = cached_path(spec)
    return {
        "name": spec.name,
        "cached": path is not None,
        "path": path,
        "size": spec.size,
    }


def ensure(spec: WeightSpec, timeout: int = 30) -> str:
    """Return the absolute cached path for ``spec``, downloading if needed.

    - Cache hit (present + verified) → return immediately.
    - Otherwise stream-download to ``.{name}.{pid}.part`` while hashing.
    - On digest match → atomically ``os.replace`` to the final path.
    - On mismatch / network error → ``RuntimeError``, leftover ``.part`` removed.

    Safe for concurrent processes: unique ``.part`` per pid + atomic rename +
    verify-on-every-hit means the last successful verifier wins.
    """
    path = _path_for(spec)
    cached = cached_path(spec)
    if cached is not None:
        return cached

    os.makedirs(os.path.dirname(path), exist_ok=True)
    # pid alone collides when two threads (parallel batch workers) download the
    # same weight in one process — add the thread id so they write to distinct
    # .part files instead of truncating each other's stream.
    part = "{}.{}.{}.part".format(path, os.getpid(), threading.get_ident())
    try:
        _download(spec, part, timeout)
        if verify(part, spec.sha256):
            os.replace(part, path)
            return path
        raise RuntimeError(
            "sha256 mismatch for {}: expected {} got {}"
            .format(spec.name, spec.sha256,
                    _digest_hex(part) if os.path.exists(part) else "n/a")
        )
    finally:
        if os.path.exists(part):
            try:
                os.unlink(part)
            except OSError:
                pass


def _digest_hex(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest().lower()


def _download(spec: WeightSpec, dest: str, timeout: int) -> None:
    """Stream ``spec.url`` to ``dest`` while hashing (raises on failure)."""
    req = urllib.request.Request(
        spec.url, headers={"User-Agent": "photo-s/{}".format(__version__)})
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, \
                open(dest, "wb") as f:
            while True:
                chunk = resp.read(_CHUNK)
                if not chunk:
                    break
                digest.update(chunk)
                f.write(chunk)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        raise RuntimeError(
            "download failed for {}: {} (manual download: {})"
            .format(spec.name, e, spec.url))
    if digest.hexdigest().lower() != spec.sha256.lower():
        raise RuntimeError(
            "sha256 mismatch for {}: expected {} got {}"
            .format(spec.name, spec.sha256, digest.hexdigest().lower()))
