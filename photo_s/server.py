"""
PhotoS - REST API Server (stdlib only)

Serves a small JSON HTTP API so external tools / AI agents can drive
PhotoS over the network. Defaults to binding 127.0.0.1 (local only).

Endpoints:
  GET  /health         → {"status": "ok", "version": ...}
  GET  /info           → supported formats, writable formats, installed plugins
  POST /process        → {"paths": [...], "options": {...}} → batch result JSON
                         {"async": true} → 202 {"task_id", ...} background task
                         {"dry_run": true} → paths/options without processing
  GET  /tasks          → list of running/finished task summaries
  GET  /tasks/<id>     → task progress {status, current, total, current_path, result?}
  POST /tasks/<id>/cancel → request cancellation (in-flight images finish)
  POST /dedup          → {"paths": [...], "threshold": 5}    → duplicate groups
  POST /rename         → {"paths": [...], "pattern": ..., "output_dir"?,
                           "overwrite"?, "dry_run"?}         → rename results
  POST /contact-sheet  → {"paths": [...], "output": ..., "cols"?, "thumb_width"?,
                           "thumb_height"?, "captions"?, "bg"?} → output path
  POST /check          → {"paths": [...]}                    → integrity report

Security: POST /process reads and writes arbitrary paths on this machine.
Only expose it on a trusted local network; use --token for Bearer auth.
"""

import json
import os
import secrets
import threading
import time
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import List, Optional

from . import __version__
from .engine import (
    ProcessOptions,
    batch_process,
    scan_directory,
    _canonical_format,
    SUPPORTED_FORMATS,
    PIL_WRITABLE,
    ALL_INPUT_EXTENSIONS,
)

VERSION = __version__


def _scalar_groups():
    """Derive int/float/str/bool field groups from ProcessOptions annotations.

    Any new scalar field on ProcessOptions is automatically exposed via the
    JSON API — no hand-maintained whitelist to keep in sync (the old hardcoded
    tuples drifted and silently dropped fields like output_sizes / pad).
    Non-scalar fields (list, e.g. output_sizes) are handled explicitly below.
    """
    from dataclasses import fields as _fields
    from typing import get_args, get_origin
    ints, floats, strs, bools = set(), set(), set(), set()
    for f in _fields(ProcessOptions):
        origin = get_origin(f.type)
        if origin is None:
            base = getattr(f.type, "__name__", None) or str(f.type)
        else:
            # Optional[X] → origin is Union; the underlying scalar is args[0]
            args = get_args(f.type)
            base = (getattr(args[0], "__name__", None) or str(args[0])) if args else ""
        if base == "int":
            ints.add(f.name)
        elif base == "float":
            floats.add(f.name)
        elif base == "str":
            strs.add(f.name)
        elif base == "bool":
            bools.add(f.name)
    return (sorted(ints), sorted(floats), sorted(strs), sorted(bools))


_INT_FIELDS, _FLOAT_FIELDS, _STR_FIELDS, _BOOL_FIELDS = _scalar_groups()


def _options_from_dict(data: dict, base: Optional[ProcessOptions] = None) -> ProcessOptions:
    """Build ProcessOptions from a JSON options dict (unknown keys ignored).

    Starts from ``base`` (server defaults) if given, then applies overrides.
    """
    opts = replace(base) if base is not None else ProcessOptions()
    for key in _INT_FIELDS:
        if key in data and data[key] is not None:
            try:
                setattr(opts, key, int(data[key]))
            except (TypeError, ValueError):
                pass
    for key in _FLOAT_FIELDS:
        if key in data and data[key] is not None:
            try:
                setattr(opts, key, float(data[key]))
            except (TypeError, ValueError):
                pass
    for key in _STR_FIELDS:
        if key in data and data[key] is not None:
            setattr(opts, key, str(data[key]))
    for key in _BOOL_FIELDS:
        if key in data and data[key] is not None:
            setattr(opts, key, bool(data[key]))
    # case-insensitive format ("png" / "WEBP" → canonical "PNG" / "WebP")
    opts.output_format = _canonical_format(opts.output_format)
    if data.get("target_size"):
        from .config import _parse_size
        size = _parse_size(data["target_size"])
        if size is not None:
            opts.target_size_bytes = size
    # config-style alias: "pad" → pad_ratio (same key the CLI/config use)
    if data.get("pad"):
        opts.pad_ratio = str(data["pad"])
    # multi-size: accept list of [label, w, h] tuples or dicts
    # e.g. [["thumb", 480, None], {"label": "screen", "width": 1920}]
    sizes = data.get("output_sizes")
    if sizes is not None:
        parsed_sizes = []
        for entry in sizes:
            if isinstance(entry, dict):
                label = str(entry.get("label", "") or "")
                mw = entry.get("width") or entry.get("max_width")
                mh = entry.get("height") or entry.get("max_height")
            else:
                parts = list(entry)
                label = str(parts[0]) if parts else ""
                mw = parts[1] if len(parts) > 1 else None
                mh = parts[2] if len(parts) > 2 else None
            try:
                mw = int(mw) if mw else None
            except (TypeError, ValueError):
                mw = None
            try:
                mh = int(mh) if mh else None
            except (TypeError, ValueError):
                mh = None
            if label:
                parsed_sizes.append((label, mw, mh))
        if parsed_sizes:
            opts.output_sizes = parsed_sizes
    return opts


def _resolve_paths(paths: List[str], recursive: bool = False) -> List[str]:
    """Expand a list of file/dir paths into supported image files.

    Directories are scanned shallowly by default; pass ``recursive=True``
    (the request's "recursive" field) to include subdirectories.
    """
    result = set()
    for p in paths:
        if os.path.isdir(p):
            result.update(scan_directory(p, recursive=recursive))
        elif os.path.isfile(p) and Path(p).suffix.lower() in ALL_INPUT_EXTENSIONS:
            result.add(os.path.abspath(p))
    return sorted(result)


# ── Async task store (POST /process with "async": true) ─────────────────
# Agents start a batch and poll GET /tasks/<id> for progress/result instead
# of holding a single HTTP request open for a long batch. Cancel is honored
# via the engine's cancel_checker (in-flight images finish; pending ones
# are drained as "Cancelled").

_TASKS_LOCK = threading.Lock()
_TASKS = {}          # task_id → {"state": dict, "cancel": threading.Event}
_MAX_TASKS = 100
_TERMINAL = ("done", "error", "cancelled")


def _prune_tasks() -> None:
    """Drop finished tasks beyond the cap (oldest finished first)."""
    if len(_TASKS) <= _MAX_TASKS:
        return
    finished = sorted(
        (t for t in _TASKS.values() if t["state"]["status"] in _TERMINAL),
        key=lambda t: t["state"].get("finished_at", 0),
    )
    for t in finished[: len(_TASKS) - _MAX_TASKS]:
        _TASKS.pop(t["state"]["task_id"], None)


def start_task(paths: List[str], options: ProcessOptions,
               dry_run: bool = False) -> str:
    """Start a /process batch in the background; return the task_id.

    The agent polls GET /tasks/<id> for progress and result, and may
    cancel via POST /tasks/<id>/cancel.
    """
    task_id = secrets.token_urlsafe(12)
    cancel = threading.Event()
    state = {
        "task_id": task_id,
        "status": "running",
        "current": 0,
        "total": len(paths),
        "current_path": "",
        "result": None,
    }

    def progress(current, total, path, *extra):
        state["current"] = current
        state["total"] = total
        state["current_path"] = path or ""

    def run():
        try:
            if dry_run:
                state["result"] = {"dry_run": True, "count": len(paths)}
            else:
                result = batch_process(
                    paths, options,
                    progress_callback=progress,
                    cancel_checker=lambda: cancel.is_set(),
                )
                state["result"] = result.to_dict()
            state["status"] = "cancelled" if cancel.is_set() else "done"
        except Exception as e:  # noqa: BLE001 — report to the polling agent
            state["result"] = {"error": str(e)}
            state["status"] = "error"
        finally:
            state["finished_at"] = time.time()

    with _TASKS_LOCK:
        _prune_tasks()
        _TASKS[task_id] = {"state": state, "cancel": cancel}
    threading.Thread(target=run, daemon=True).start()
    return task_id


def get_task(task_id: str) -> Optional[dict]:
    """Return a task's state dict (without the internal cancel event)."""
    with _TASKS_LOCK:
        task = _TASKS.get(task_id)
        return task["state"] if task else None


class _PhotoSHandler(BaseHTTPRequestHandler):
    """HTTP handler. options/token are class attrs set by create_server."""

    options = ProcessOptions()
    token: Optional[str] = None

    def log_message(self, fmt, *args):  # silence default request logging
        pass

    # ── helpers ──────────────────────────────────────────────────────────
    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self) -> bool:
        if self.token:
            return self.headers.get("Authorization", "") == f"Bearer {self.token}"
        # No token configured: still block browser cross-origin requests
        # (localhost CSRF drive-by). A malicious page can send a CORS
        # "simple request" (text/plain JSON, no preflight) to 127.0.0.1 and
        # it would otherwise be fully processed. Browsers always reveal their
        # origin on fetch/XHR; CLI/curl/agent clients send no Origin header
        # and are unaffected.
        origin = self.headers.get("Origin")
        if origin:
            return origin == f"http://{self.headers.get('Host', '')}"
        return True

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            return {}
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    # ── routes ───────────────────────────────────────────────────────────
    def do_GET(self):
        if not self._authed():
            self._send_json(401, {"error": "unauthorized"})
            return
        if self.path == "/health":
            self._send_json(200, {"status": "ok", "version": VERSION})
        elif self.path == "/info":
            from .plugin import discover_plugins
            self._send_json(200, {
                "version": VERSION,
                "formats": sorted(SUPPORTED_FORMATS),
                "writable": sorted(PIL_WRITABLE),
                "input_extensions": sorted(ALL_INPUT_EXTENSIONS),
                "plugins": [p.name for p in discover_plugins()],
            })
        elif self.path == "/plugins":
            from .registry import OFFICIAL_PLUGINS, to_dict
            from .plugin import discover_plugins
            from .plugincmd import _installed_version
            installed_objs = {}
            for p in discover_plugins():
                installed_objs[p.name] = p
            installed = []
            for name, p in installed_objs.items():
                installed.append({
                    "name": name,
                    "provides": list(getattr(p, "provides", ())),
                    "version": _installed_version("photo-s-plugin-" + name),
                })
            available = []
            for name, official in OFFICIAL_PLUGINS.items():
                entry = to_dict(official)
                entry["installed"] = name in installed_objs
                available.append(entry)
            self._send_json(200, {"installed": installed,
                                  "available": available})
        elif self.path == "/tasks":
            with _TASKS_LOCK:
                tasks = [{
                    "task_id": t["state"]["task_id"],
                    "status": t["state"]["status"],
                    "current": t["state"]["current"],
                    "total": t["state"]["total"],
                } for t in _TASKS.values()]
            self._send_json(200, {"tasks": tasks})
        elif self.path.startswith("/tasks/"):
            state = get_task(self.path[len("/tasks/"):])
            if state is None:
                self._send_json(404, {"error": "task not found"})
                return
            self._send_json(200, state)
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if not self._authed():
            self._send_json(401, {"error": "unauthorized"})
            return
        data = self._read_json()
        if self.path == "/process":
            paths = _resolve_paths(data.get("paths", []),
                                   bool(data.get("recursive", False)))
            if not paths:
                self._send_json(400, {"error": "no supported image files found"})
                return
            opts = _options_from_dict(data.get("options", {}), self.options)
            if data.get("async"):
                # Long-running batch → background task; agent polls /tasks/<id>.
                task_id = start_task(paths, opts,
                                     dry_run=bool(data.get("dry_run")))
                self._send_json(202, {
                    "task_id": task_id,
                    "status": "running",
                    "total": len(paths),
                    "poll": f"/tasks/{task_id}",
                })
                return
            if data.get("dry_run"):
                self._send_json(200, {
                    "dry_run": True,
                    "count": len(paths),
                    "paths": paths,
                    "options": data.get("options", {}),
                })
                return
            result = batch_process(paths, opts)
            self._send_json(200, result.to_dict())
        elif self.path == "/dedup":
            from .dedup import find_duplicates
            paths = _resolve_paths(data.get("paths", []),
                                   bool(data.get("recursive", False)))
            try:
                threshold = int(data.get("threshold", 5))
            except (TypeError, ValueError):
                threshold = 5
            dup = find_duplicates(paths, threshold=threshold)
            self._send_json(200, {
                "count": len(dup),
                "groups": [{"hash": h, "paths": ps} for h, ps in dup.items()],
            })
        elif self.path == "/rename":
            from .rename import rename_files
            paths = _resolve_paths(data.get("paths", []),
                                   bool(data.get("recursive", False)))
            pattern = data.get("pattern") or ""
            if not paths or not pattern:
                self._send_json(400, {"error": "paths and pattern are required"})
                return
            results = rename_files(
                paths, pattern,
                output_dir=data.get("output_dir"),
                overwrite=bool(data.get("overwrite", False)),
                dry_run=bool(data.get("dry_run", False)),
            )
            ok = sum(1 for r in results if r["status"] == "ok")
            self._send_json(200, {"total": len(results), "ok": ok,
                                  "results": results})
        elif self.path == "/contact-sheet":
            from .contact import build_contact_sheet
            from .adjust import hex_to_rgb
            paths = _resolve_paths(data.get("paths", []),
                                   bool(data.get("recursive", False)))
            output = data.get("output") or ""
            if not paths or not output:
                self._send_json(400, {"error": "paths and output are required"})
                return
            try:
                cols = int(data.get("cols", 4))
            except (TypeError, ValueError):
                cols = 4
            try:
                tw = int(data.get("thumb_width", 240))
                th = int(data.get("thumb_height", 240))
            except (TypeError, ValueError):
                tw = th = 240
            try:
                bg = hex_to_rgb(data.get("bg", "#000000"))
            except ValueError:
                bg = (0, 0, 0)
            out = build_contact_sheet(
                paths, output, cols=cols, thumb_size=(tw, th),
                captions=bool(data.get("captions", False)), bg=bg)
            self._send_json(200, {"output": out, "count": len(paths)})
        elif self.path == "/check":
            from .check import verify_images
            paths = _resolve_paths(data.get("paths", []),
                                   bool(data.get("recursive", False)))
            if not paths:
                self._send_json(400, {"error": "no supported image files found"})
                return
            results = verify_images(paths)
            corrupt = [r for r in results if not r["ok"]]
            self._send_json(200, {
                "checked": len(results),
                "ok": len(results) - len(corrupt),
                "corrupt": [{"path": r["path"], "error": r["error"]}
                            for r in corrupt],
            })
        elif self.path.startswith("/tasks/") and self.path.endswith("/cancel"):
            task_id = self.path[len("/tasks/"):-len("/cancel")]
            with _TASKS_LOCK:
                task = _TASKS.get(task_id)
            if task is None:
                self._send_json(404, {"error": "task not found"})
                return
            task["cancel"].set()
            self._send_json(200, {"task_id": task_id, "cancelled": True})
        elif self.path == "/plugins":
            # Remote plugin management: {"action": "install|uninstall|fetch",
            # "name": "scunet", "dry_run": bool?}
            from .registry import get_official
            from .plugincmd import _pip_run
            action = data.get("action")
            name = data.get("name")
            if action not in ("install", "uninstall", "fetch"):
                self._send_json(400, {"error": "action must be one of "
                                                "install|uninstall|fetch"})
                return
            official = get_official(name) if name else None
            if action in ("install", "uninstall") and official is None:
                self._send_json(400, {"error": "unknown plugin: {}".format(name)})
                return
            if action == "fetch":
                from .plugin import discover_plugins
                plugin = next((p for p in discover_plugins()
                               if p.name == name), None)
                if plugin is None:
                    self._send_json(400, {"error": "plugin not installed: {}"
                                          .format(name)})
                    return
                try:
                    from .modelstore import ensure
                    weights = [ensure(s) for s in plugin.weight_specs()]
                except RuntimeError as e:
                    self._send_json(500, {"ok": False, "error": str(e)})
                    return
                self._send_json(200, {"ok": True, "name": name,
                                      "weights": [{"path": w} for w in weights]})
                return

            dist = official.pypi_distribution
            if data.get("dry_run"):
                argv = ["install", "--quiet", dist] if action == "install" \
                    else ["uninstall", "-y", dist]
                self._send_json(200, {"ok": True, "name": name,
                                      "dry_run": True, "pip_argv": argv})
                return
            try:
                proc = _pip_run(["install", "--quiet", dist] if action == "install"
                                else ["uninstall", "-y", dist])
            except FileNotFoundError:
                self._send_json(500, {"ok": False,
                                      "error": "pip not available"})
                return
            if proc.returncode != 0:
                self._send_json(500, {"ok": False,
                                      "error": "pip {} failed: {}".format(
                                          action, (proc.stderr or "").strip()[-300:])})
                return
            self._send_json(200, {"ok": True, "name": name,
                                  "action": action, "distribution": dist})
        else:
            self._send_json(404, {"error": "not found"})


def generate_token() -> str:
    """Generate a random Bearer token for --token auto."""
    return secrets.token_urlsafe(24)


def write_ready_file(path: str, port: int, token: Optional[str]) -> None:
    """Atomically write the server handshake file for host agents.

    JSON payload: {"port", "token", "pid"}. The agent polls for this file
    instead of parsing stdout (robust on Windows where stdout encoding and
    buffering are unreliable).
    """
    payload = {"port": port, "token": token, "pid": os.getpid()}
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp, path)  # atomic on Windows and POSIX


def create_server(host: str = "127.0.0.1", port: int = 0,
                  options: Optional[ProcessOptions] = None,
                  token: Optional[str] = None) -> ThreadingHTTPServer:
    """Create (but do not start) a PhotoS API server. Used by run_server and tests."""
    _PhotoSHandler.options = options or ProcessOptions()
    _PhotoSHandler.token = token
    return ThreadingHTTPServer((host, port), _PhotoSHandler)


def run_server(host: str = "127.0.0.1", port: int = 8787,
               options: Optional[ProcessOptions] = None,
               token: Optional[str] = None,
               ready_file: Optional[str] = None) -> None:
    """Start the PhotoS API server, blocking until Ctrl+C.

    Args:
        ready_file: If set, write {"port", "token", "pid"} to this path once
                    the server is listening — the automation handshake for
                    host agents (paired with --token auto).
    """
    server = create_server(host, port, options=options, token=token)
    actual_port = server.server_address[1]
    scheme = "https" if os.environ.get("PHOTO_S_TLS") else "http"
    print(f"🚀 PhotoS API 服务已启动 Server started: {scheme}://{host}:{actual_port}")
    print(f"   端点 Endpoints: GET /health, GET /info, "
          f"POST /process /dedup /rename /contact-sheet /check")
    if token:
        print(f"   🔐 已启用 Bearer token 认证 Bearer auth enabled")
        if ready_file:
            print(f"   📄 握手文件 Ready file: {ready_file}")
    else:
        print("   ⚠️  无认证 No auth — 仅限本机信任环境 (trusted local use only)")
    print("   按 Ctrl+C 停止 Press Ctrl+C to stop")
    print()

    if ready_file:
        try:
            write_ready_file(ready_file, actual_port, token)
        except OSError as e:
            print(f"⚠️  握手文件写入失败 Ready file error: {e}", file=os.sys.stderr)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if ready_file:
            try:
                os.unlink(ready_file)
            except OSError:
                pass
