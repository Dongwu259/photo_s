"""Tests for photo_s.watcher — the folder-watch daemon.

The GUI drives start_watching in a thread with a stop_event; these tests
prove the loop actually exits and the observer is cleaned up on the event.
"""

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

pytest.importorskip("watchdog")

from PIL import Image

from photo_s.engine import ProcessOptions


class TestStartWatching:
    def test_start_watching_stops_on_event(self, tmp_path):
        from photo_s.watcher import start_watching

        watch_dir = tmp_path / "in"
        watch_dir.mkdir()
        out_dir = tmp_path / "out"
        options = ProcessOptions(quality=70, output_format="JPEG",
                                 output_dir=str(out_dir), suffix="")
        processed = []
        done = threading.Event()

        evt = threading.Event()
        t = threading.Thread(
            target=lambda: (start_watching(
                str(watch_dir), options,
                on_process=lambda r: (processed.append(r), done.set()),
                stop_event=evt)),
            daemon=True)
        t.start()

        # give the watchdog Observer time to start — a file created before
        # the observer is ready is never reported (race, flaky under load)
        time.sleep(1.5)
        src = watch_dir / "shot.png"
        Image.new("RGB", (20, 20), (50, 120, 200)).save(src)
        assert done.wait(timeout=15), "watcher never processed the file"
        assert processed and processed[0].success
        assert (out_dir / "shot.jpg").exists()

        # stopping must make the loop exit (≤1s granularity) and join
        evt.set()
        t.join(timeout=10)
        assert not t.is_alive(), "start_watching did not exit on stop_event"

    def test_stop_before_start(self, tmp_path):
        from photo_s.watcher import start_watching
        watch_dir = tmp_path / "in"
        watch_dir.mkdir()
        evt = threading.Event()
        evt.set()
        t = threading.Thread(
            target=start_watching,
            args=(str(watch_dir), ProcessOptions(quality=70,
                                                 output_format="JPEG")),
            kwargs={"stop_event": evt},
            daemon=True)
        t.start()
        t.join(timeout=10)
        assert not t.is_alive(), "start_watching should exit immediately"


class TestDebounceRetry:
    """Regression: an unstable (still-copying) file must stay pending for
    the next tick — not be silently marked processed and dropped forever."""

    def _handler(self, tmp_path, **opt_kw):
        from photo_s.watcher import _DebouncedHandler
        out = tmp_path / "out"
        options = ProcessOptions(quality=70, output_format="JPEG",
                                 output_dir=str(out), suffix="", **opt_kw)
        return _DebouncedHandler(options), out

    @staticmethod
    def _grow_during_sleep(monkeypatch, path, times):
        """Fake a slow copy: the file grows during the next ``times``
        stability-check sleeps, so the two getsize() calls disagree."""
        import photo_s.watcher as watcher_mod
        state = {"left": times}

        def fake_sleep(_seconds):
            if state["left"] > 0:
                state["left"] -= 1
                with open(path, "ab") as fh:
                    fh.write(b"x" * 64)

        monkeypatch.setattr(watcher_mod.time, "sleep", fake_sleep)

    def test_unstable_file_retried_then_processed(self, tmp_path, monkeypatch):
        handler, out = self._handler(tmp_path)
        src = tmp_path / "big.jpg"
        Image.new("RGB", (20, 20), (1, 2, 3)).save(src)
        path = str(src)
        handler._pending[path] = time.time() - 5  # past the debounce window
        self._grow_during_sleep(monkeypatch, path, times=1)

        # size still changing → not processed, but crucially NOT dropped
        assert handler.tick() == []
        assert path in handler._pending
        assert path not in handler._processed

        # copy finished (size stable) → processed on the next tick
        results = handler.tick()
        assert len(results) == 1 and results[0].success
        assert path not in handler._pending
        assert path in handler._processed
        assert (out / "big.jpg").exists()

    def test_never_stable_file_gives_up_then_redrop_works(self, tmp_path,
                                                          monkeypatch, capsys):
        handler, _ = self._handler(tmp_path)
        handler._MAX_STABILIZE_ATTEMPTS = 2
        src = tmp_path / "growing.jpg"
        Image.new("RGB", (20, 20), (4, 5, 6)).save(src)
        path = str(src)
        handler._pending[path] = time.time() - 5
        self._grow_during_sleep(monkeypatch, path, times=99)

        assert handler.tick() == []  # attempt 1
        assert handler.tick() == []  # attempt 2 → cap hit, abandon + warn
        assert path not in handler._pending
        # not marked processed — a later re-drop of the same name may retry
        assert path not in handler._processed
        assert "never stabilized" in capsys.readouterr().out

        # deleting + re-dropping the same name is processed normally
        # (the old bug skipped it forever via _processed)
        monkeypatch.undo()  # real sleep back; file no longer grows
        handler._pending[path] = time.time() - 5
        results = handler.tick()
        assert len(results) == 1 and results[0].success


class TestOwnOutputFilter:
    """Regression: watch without -o writes outputs into the watched dir;
    suffixed outputs must be ignored or a.jpg spawns a_compressed.jpg →
    a_compressed_compressed.jpg → … forever."""

    class _Evt:
        is_directory = False

        def __init__(self, path):
            self.src_path = str(path)

    def test_on_created_ignores_own_output(self, tmp_path):
        from photo_s.watcher import _DebouncedHandler
        handler = _DebouncedHandler(ProcessOptions(suffix="_compressed"))
        own = tmp_path / "a_compressed.jpg"
        Image.new("RGB", (16, 16)).save(own)
        handler.on_created(self._Evt(own))
        assert handler._pending == {}

        fresh = tmp_path / "a.jpg"
        Image.new("RGB", (16, 16)).save(fresh)
        handler.on_created(self._Evt(fresh))
        assert str(fresh) in handler._pending

    def test_tick_drops_suffixed_pending(self, tmp_path):
        """A suffixed file already in pending is dropped, never processed."""
        from photo_s.watcher import _DebouncedHandler
        handler = _DebouncedHandler(ProcessOptions(suffix="_compressed"))
        own = tmp_path / "b_compressed.png"
        Image.new("RGB", (16, 16)).save(own)
        handler._pending[str(own)] = time.time() - 5
        assert handler.tick() == []
        assert str(own) not in handler._pending

    def test_no_self_trigger_loop(self, tmp_path):
        """Handler-level end-to-end: default options (no -o) process a.jpg →
        a_compressed.jpg lands next to it; the watcher must not queue it."""
        from photo_s.watcher import _DebouncedHandler
        handler = _DebouncedHandler(ProcessOptions(quality=70,
                                                   output_format="JPEG"))
        src = tmp_path / "a.jpg"
        Image.new("RGB", (20, 20), (9, 9, 9)).save(src)
        handler._pending[str(src)] = time.time() - 5
        results = handler.tick()
        assert len(results) == 1 and results[0].success
        output = tmp_path / "a_compressed.jpg"
        assert output.exists()

        handler.on_created(self._Evt(output))  # watchdog reports the output…
        assert handler._pending == {}          # …and it is ignored
        assert handler.tick() == []
        assert not (tmp_path / "a_compressed_compressed.jpg").exists()
