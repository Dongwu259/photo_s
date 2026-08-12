"""
PhotoS - Folder Watcher Daemon

Monitors a directory for new image files and auto-processes them.
Uses the watchdog library.
"""

import os
import time
import threading
from pathlib import Path
from typing import Callable, Optional

from .engine import (
    ProcessOptions,
    ProcessResult,
    process_image,
    format_size,
    ALL_INPUT_EXTENSIONS,
)


class _DebouncedHandler:
    """File-system event handler with debounce (wait for file to stabilize).

    Wraps watchdog's FileSystemEventHandler pattern.
    """

    def __init__(self, options: ProcessOptions,
                 on_process: Optional[Callable[[ProcessResult], None]] = None):
        self.options = options
        self.on_process = on_process
        self._pending = {}   # path → first seen time
        self._processed = set()  # paths already processed

    def on_created(self, event):
        """Called when a file is created."""
        if event.is_directory:
            return
        path = event.src_path
        ext = Path(path).suffix.lower()
        if ext not in ALL_INPUT_EXTENSIONS:
            return
        self._pending[path] = time.time()

    def tick(self):
        """Check pending files; process those that have stabilized."""
        now = time.time()
        to_process = []

        for path, first_seen in list(self._pending.items()):
            if now - first_seen >= 2.0:  # 2-second debounce
                if path not in self._processed:
                    # Also check file is still there and hasn't changed
                    try:
                        size = os.path.getsize(path)
                        time.sleep(0.3)
                        if os.path.getsize(path) == size:
                            to_process.append(path)
                    except OSError:
                        pass
                self._processed.add(path)
                del self._pending[path]

        results = []
        for path in to_process:
            try:
                result = process_image(path, self.options)
                results.append(result)
                if self.on_process:
                    self.on_process(result)
            except Exception as e:
                results.append(ProcessResult(
                    input_path=path, output_path="",
                    input_size=0, output_size=0,
                    input_format="", output_format="",
                    input_dims=(0, 0), output_dims=(0, 0),
                    success=False, error=str(e),
                ))

        return results


def start_watching(
    watch_dir: str,
    options: ProcessOptions,
    recursive: bool = False,
    on_process: Optional[Callable[[ProcessResult], None]] = None,
) -> None:
    """Watch a directory for new images and process them automatically.

    Blocks until Ctrl+C.

    Args:
        watch_dir: Directory to monitor.
        options: ProcessOptions for auto-processing.
        recursive: Watch subdirectories too.
        on_process: Callback when a file is processed.
    """
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        print("❌ watchdog not installed. Run: pip3 install watchdog")
        return

    handler = _DebouncedHandler(options, on_process)

    class Handler(FileSystemEventHandler):
        def on_created(self, event):
            handler.on_created(event)

    observer = Observer()
    observer.schedule(Handler(), watch_dir, recursive=recursive)
    observer.start()

    print(f"👁  正在监视 Watching: {watch_dir}")
    print(f"   设置: {options.output_format} q={options.quality}")
    if options.remove_original:
        print("   ⚠️  处理后删除原文件 Remove original is ON")
    print("   按 Ctrl+C 停止 Press Ctrl+C to stop")
    print()

    processed_count = 0

    try:
        while True:
            time.sleep(1)
            results = handler.tick()
            for r in results:
                processed_count += 1
                name = os.path.basename(r.input_path)
                if r.success:
                    savings = r.input_size - r.output_size
                    print(f"  ✅ #{processed_count} {name} → "
                          f"{format_size(r.output_size)} "
                          f"(-{format_size(savings)})")
                    if r.achieved_quality:
                        print(f"     质量 Quality: {r.achieved_quality}")
                else:
                    print(f"  ❌ #{processed_count} {name}: {r.error}")
    except KeyboardInterrupt:
        observer.stop()
        print(f"\n👁  已停止 Stopped. 共处理 {processed_count} 个文件.")
    observer.join()
