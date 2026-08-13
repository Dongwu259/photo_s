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
