"""Tests for plugin discovery (photo_s.plugin.discover_plugins).

Hermetic: importlib.metadata.entry_points is monkeypatched so the dev
machine's installed plugins never leak in, and the _PLUGINS cache is reset
around every test.
"""

import importlib.metadata
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from photo_s import plugin as plugin_mod
from photo_s.hooks import PhotoSPlugin


class _FakePlugin(PhotoSPlugin):
    pass


class _FakeEP:
    name = "fake"

    def load(self):
        return _FakePlugin


class _BrokenEP:
    name = "broken"

    def load(self):
        raise ImportError("boom")


class _EPS(list):
    """Entry-point list that also satisfies the py3.9 `.get(group)` branch."""

    def get(self, key, default=None):
        return self


@pytest.fixture(autouse=True)
def _reset_cache():
    plugin_mod.clear_cache()
    yield
    plugin_mod.clear_cache()


class TestDiscoverPlugins:
    def test_discovers_and_caches(self, monkeypatch):
        calls = []

        def _fake_entry_points(group=None):
            calls.append(group)
            return _EPS([_FakeEP()])

        monkeypatch.setattr(importlib.metadata, "entry_points",
                            _fake_entry_points)
        first = plugin_mod.discover_plugins()
        second = plugin_mod.discover_plugins()
        assert len(first) == 1
        assert isinstance(first[0], _FakePlugin)
        assert first[0].name == "fake"
        assert second is first  # cached list object
        assert len(calls) == 1  # entry_points scanned only once

    def test_broken_plugin_skipped(self, monkeypatch):
        monkeypatch.setattr(importlib.metadata, "entry_points",
                            lambda group=None: _EPS([_BrokenEP(), _FakeEP()]))
        plugins = plugin_mod.discover_plugins()
        assert [p.name for p in plugins] == ["fake"]

    def test_concurrent_first_call_race(self, monkeypatch):
        """Regression: parallel workers calling discover_plugins() for the
        first time must never observe the half-built (empty) cache.

        Old code published ``_PLUGINS = []`` before the slow entry_points()
        scan, so every concurrent first caller except the scanner got an
        empty list and silently fell back to built-in NLM / trilinear LUT.
        """
        scanning = threading.Event()

        def _slow_entry_points(group=None):
            scanning.set()
            time.sleep(0.3)
            return _EPS([_FakeEP()])

        monkeypatch.setattr(importlib.metadata, "entry_points",
                            _slow_entry_points)

        results = []

        def _call():
            # snapshot at call time — the old code published the cache list
            # up front and filled it in place, so checking after join() would
            # miss the race; consumers (find_provider) iterate it immediately
            results.append(len(plugin_mod.discover_plugins()))

        scanner = threading.Thread(target=_call)
        scanner.start()
        scanning.wait(timeout=5)  # scanner is inside the slow scan now
        workers = [threading.Thread(target=_call) for _ in range(8)]
        for t in workers:
            t.start()
        scanner.join(timeout=10)
        for t in workers:
            t.join(timeout=10)

        assert len(results) == 9
        # no caller may see the empty half-built list
        assert all(n == 1 for n in results)
