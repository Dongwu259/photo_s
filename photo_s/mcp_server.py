"""
PhotoS - MCP (Model Context Protocol) server.

Exposes PhotoS tools (process/info/exif/dedup/cull/hash/plugin) to MCP
clients (Claude Desktop, AI agents) over stdio. Tools call photo_s module
functions directly (no CLI subprocess) and return JSON-serializable dicts
whose shapes mirror the `--json` CLI contract.

Requires the optional `mcp` extra: `pip install 'photo-s-tools[mcp]'`
(mcp>=1.20,<2 — the SDK requires Python >= 3.10).

IMPORTANT: this module must never import mcp at module level. photo-s
supports Python 3.9 while the mcp SDK needs 3.10+; the lazy import keeps 3.9
runs harmless and produces a clear install/version hint instead of an
ImportError. Also: MCP stdio owns stdout (JSON-RPC), so every tool here is
print-free — diagnostics go to stderr only.
"""

import asyncio
import json
import os
import sys
from typing import List, Optional

from . import __version__
from .engine import (ProcessOptions, batch_process, apply_exif_tags,
                     read_exif_metadata)

# Config-file base (set by create_server from --config); tool args win.
_base_options: ProcessOptions = ProcessOptions()


def _mcp():
    """Lazily import FastMCP (mirrors denoise._cv2's pattern)."""
    try:
        from mcp.server.fastmcp import FastMCP
        return FastMCP("photo-s",
                       instructions="PhotoS MCP server - batch image "
                                    "processing. Returns JSON-only results.")
    except ImportError:
        raise RuntimeError(
            "MCP server requires the optional dependency: "
            "pip install 'photo-s-tools[mcp]' (mcp>=1.20,<2)")


# ── Tool implementations (module-level, individually testable) ──────────────


def process_tool(
    paths: list,
    recursive: bool = False,
    quality: Optional[int] = None,
    output_format: Optional[str] = None,
    output_dir: Optional[str] = None,
    resize: Optional[str] = None,
    scale: Optional[int] = None,
    suffix: Optional[str] = None,
    target_size: Optional[str] = None,
    strip_gps: Optional[bool] = None,
    denoise: Optional[float] = None,
    ev: Optional[float] = None,
    log_curve: Optional[str] = None,
    wb_temp: Optional[int] = None,
    auto_straighten: Optional[bool] = None,
    jobs: Optional[int] = None,
    dry_run: bool = False,
) -> dict:
    """Batch process images: quality/format/resize/tone/exposure/denoise.

    ``paths`` accepts files, directories or globs (e.g. ["/shoot/*.jpg"]).
    Returns a BatchResult JSON with per-file status (same shape as
    ``photo-s batch --json``), plus ``ok``.
    """
    from .server import _options_from_dict
    from .cli import _collect_files, _parse_dimensions

    data = {
        "quality": quality, "output_format": output_format,
        "output_dir": output_dir, "scale_percent": scale,
        "suffix": suffix, "target_size": target_size,
        "strip_gps": strip_gps, "denoise": denoise, "ev": ev,
        "log_curve": log_curve, "wb_temp": wb_temp,
        "auto_straighten": auto_straighten, "jobs": jobs,
    }
    data = {k: v for k, v in data.items() if v is not None}
    if resize:
        w, h = _parse_dimensions(resize)
        data["max_width"], data["max_height"] = w, h

    files = _collect_files(list(paths), recursive=recursive)
    if not files:
        return {"ok": False,
                "error": "no supported image files found",
                "paths": list(paths)}

    if dry_run:
        return {
            "dry_run": True, "count": len(files), "files": files,
            "settings": {
                "output_format": data.get("output_format"),
                "quality": data.get("quality"),
                "target_size": data.get("target_size"),
                "output_dir": data.get("output_dir"),
                "max_width": data.get("max_width"),
                "max_height": data.get("max_height"),
                "scale_percent": data.get("scale_percent"),
                "suffix": data.get("suffix"),
                "jobs": data.get("jobs"),
            },
        }

    opts = _options_from_dict(data, base=_base_options)
    result = batch_process(files, opts)
    payload = result.to_dict()
    payload["ok"] = result.fail_count == 0
    return payload


def info_tool() -> dict:
    """Environment probe: version, supported formats, writable formats,
    optional-feature status and installed plugins (same shape as
    ``photo-s info --json``)."""
    from .engine import ALL_INPUT_EXTENSIONS, SUPPORTED_FORMATS, PIL_WRITABLE
    from .envinfo import optional_features, plugins
    return {
        "version": __version__,
        "input_extensions": sorted(ALL_INPUT_EXTENSIONS),
        "formats": sorted(SUPPORTED_FORMATS),
        "writable": sorted(PIL_WRITABLE),
        "optional_features": optional_features(),
        "plugins": plugins(),
    }


def exif_tool(
    action: str = "show",
    paths: Optional[list] = None,
    recursive: bool = False,
    rating_min: Optional[int] = None,
    rating: Optional[int] = None,
    keywords: Optional[str] = None,
    camera: Optional[str] = None,
    tags: Optional[dict] = None,
) -> dict:
    """Read/filter or write EXIF metadata.

    ``action="show"`` scans ``paths`` and returns per-file metadata, filtered
    by rating/keywords/camera. ``action="write"`` takes ``tags`` as a
    {"<path>": {"rating": 4, "keywords": "keep", ...}} map.
    """
    from .cli import _collect_files

    if action == "write":
        written, errors = 0, []
        for path, tagdict in (tags or {}).items():
            try:
                apply_exif_tags(path, tagdict)
                written += 1
            except Exception as e:  # per-file errors, don't abort the batch
                errors.append({"path": path, "error": str(e)})
        return {"action": "write", "written": written, "errors": errors}

    # show / filter (mirrors `photo-s exif --show`)
    files = _collect_files(list(paths or []), recursive=recursive)
    results = []
    for p in files:
        try:
            m = read_exif_metadata(p)
        except Exception:
            continue
        if rating_min is not None and (m.get("rating") or 0) < rating_min:
            continue
        if rating is not None and m.get("rating") != rating:
            continue
        if keywords:
            kws = m.get("keywords") or []
            if not any(k in kws for k in
                       [k.strip() for k in keywords.split(",") if k.strip()]):
                continue
        if camera and (camera.lower() not in (m.get("camera") or "").lower()):
            continue
        results.append({"path": p, **m})
    return {"action": "show", "count": len(results), "results": results}


def dedup_tool(
    paths: list,
    recursive: bool = False,
    threshold: int = 5,
    action: str = "report",
    dry_run: bool = True,
) -> dict:
    """Find duplicate images by perceptual hash.

    ``action="report"`` lists duplicate groups. ``action="keep-sharpest"``
    keeps the sharpest of each burst and removes the rest — SAFETY: deletion
    requires ``dry_run=False`` explicitly (default True).
    """
    from .cli import _collect_files
    from .dedup import find_duplicates, handle_duplicates

    files = _collect_files(list(paths), recursive=recursive)
    groups = find_duplicates(files, threshold=threshold)

    if action == "keep-sharpest":
        kept, removed = handle_duplicates(groups, action="keep-sharpest",
                                          dry_run=dry_run)
        return {"action": "keep-sharpest", "kept": kept, "removed": removed,
                "dry_run": dry_run}

    savings = 0
    group_list = []
    for h, paths_in_group in groups.items():
        for extra in paths_in_group[1:]:
            try:
                savings += os.path.getsize(extra)
            except OSError:
                pass
        group_list.append({"hash": h, "paths": list(paths_in_group)})
    return {"count": len(group_list),
            "duplicate_count": sum(len(g["paths"]) - 1 for g in group_list),
            "savings_bytes": savings, "groups": group_list}


def cull_tool(
    paths: list,
    recursive: bool = False,
    overexposed_max: Optional[float] = None,
    underexposed_max: Optional[float] = None,
    luminance_min: Optional[float] = None,
    luminance_max: Optional[float] = None,
    sharpness_min: Optional[float] = None,
) -> dict:
    """Filter images by exposure and sharpness thresholds.

    Returns per-file stats plus a ``kept`` flag (mirrors ``photo-s cull``).
    """
    from .cli import _collect_files
    from .metrics import compute_exposure_stats, compute_blur_score

    files = _collect_files(list(paths), recursive=recursive)
    results, kept = [], 0
    for p in files:
        try:
            s = compute_exposure_stats(p)
        except Exception:
            continue
        if not s.get("ok"):
            continue
        blur = None
        if sharpness_min is not None:
            blur = round(compute_blur_score(p), 1)
        ok = True
        if overexposed_max is not None and s["overexposed_pct"] > overexposed_max:
            ok = False
        if underexposed_max is not None and s["underexposed_pct"] > underexposed_max:
            ok = False
        if luminance_min is not None and s["luminance"] < luminance_min:
            ok = False
        if luminance_max is not None and s["luminance"] > luminance_max:
            ok = False
        if sharpness_min is not None and (blur or 0) < sharpness_min:
            ok = False
        results.append({
            "path": p,
            "luminance": s["luminance"],
            "overexposed_pct": s["overexposed_pct"],
            "underexposed_pct": s["underexposed_pct"],
            "blur_score": blur,
            "kept": ok,
        })
        if ok:
            kept += 1
    return {"count": len(results), "kept": kept, "results": results}


def hash_tool(
    paths: Optional[list] = None,
    recursive: bool = False,
    output: Optional[str] = None,
    verify: Optional[str] = None,
) -> dict:
    """Generate or verify a SHA-256 checksum manifest (any file type).

    Generate: ``paths`` + optional ``output`` (default "manifest.csv");
    returns the entries inline so agents needn't read the CSV.
    Verify: pass ``verify`` = manifest path.
    """
    from .check import (collect_files, compute_checksums, write_manifest,
                        verify_manifest)

    if verify:
        report = verify_manifest(verify)
        report["ok"] = not report.get("missing") and \
            not report.get("mismatched")
        return report

    files = collect_files(list(paths or []), recursive=recursive)
    entries = compute_checksums(files)
    out = os.path.abspath(output or "manifest.csv")
    write_manifest(out, entries)
    return {"output": out, "count": len(files), "entries": entries}


def plugin_tool(
    action: str = "list",
    name: Optional[str] = None,
    dry_run: bool = False,
) -> dict:
    """Manage official plugins: ``list`` installed/available, ``install`` or
    ``uninstall`` by name (shells to pip; ``dry_run`` prints the pip argv)."""
    from .registry import OFFICIAL_PLUGINS, get_official, to_dict
    from .plugin import discover_plugins
    from .plugincmd import _pip_run, _installed_version

    if action == "list":
        installed_objs = {}
        for p in discover_plugins():
            installed_objs[p.name] = p
        installed = []
        for n, p in installed_objs.items():
            installed.append({
                "name": n,
                "provides": list(getattr(p, "provides", ())),
                "version": _installed_version("photo-s-plugin-" + n),
            })
        available = []
        for n, official in OFFICIAL_PLUGINS.items():
            entry = to_dict(official)
            entry["installed"] = n in installed_objs
            available.append(entry)
        return {"installed": installed, "available": available}

    if action not in ("install", "uninstall"):
        return {"ok": False, "name": name,
                "error": f"unknown action: {action}",
                "actions": ["list", "install", "uninstall"]}

    official = get_official(name) if name else None
    if official is None:
        return {"ok": False, "name": name,
                "error": "not in official registry"}

    dist = official.pypi_distribution
    argv = (["install", "--quiet", dist] if action == "install"
            else ["uninstall", "-y", dist])
    if dry_run:
        return {"ok": True, "name": name, "dry_run": True,
                "pip_argv": [sys.executable, "-m", "pip", *argv]}
    try:
        proc = _pip_run(argv)
    except FileNotFoundError:
        return {"ok": False, "name": name, "error": "pip not available"}
    if proc.returncode != 0:
        return {"ok": False, "name": name,
                "error": "pip {} failed".format(action),
                "detail": (proc.stderr or "").strip()[-400:]}
    payload = {"ok": True, "name": name, "action": action,
               "distribution": dist}
    ver = _installed_version(dist)
    if ver:
        payload["version"] = ver
    return payload


def contact_sheet_tool(
    paths: list,
    output: str,
    recursive: bool = False,
    cols: int = 4,
    thumb: int = 240,
    captions: bool = True,
    bg: str = "#000000",
) -> dict:
    """Build a contact sheet (grid montage) from images.

    ``output`` is the destination image path. Returns ``{"output", "count"}``
    (same shape as ``photo-s contact-sheet --json``).
    """
    from .adjust import hex_to_rgb
    from .cli import _collect_files
    from .contact import build_contact_sheet

    files = _collect_files(list(paths), recursive=recursive)
    if not files:
        return {"ok": False, "error": "no supported image files found",
                "paths": list(paths)}
    try:
        bg_rgb = hex_to_rgb(bg)
    except ValueError:
        bg_rgb = (0, 0, 0)
    out = build_contact_sheet(files, output, cols=cols,
                              thumb_size=(thumb, thumb), captions=captions,
                              bg=bg_rgb)
    return {"ok": True, "output": out, "count": len(files)}


def gallery_tool(
    paths: list,
    out_dir: str,
    recursive: bool = False,
    title: str = "PhotoS Gallery",
    thumb: int = 360,
) -> dict:
    """Generate an HTML gallery from images.

    Returns ``{"output", "count"}`` (same shape as ``photo-s gallery --json``).
    """
    from .cli import _collect_files
    from .gallery import build_gallery

    files = _collect_files(list(paths), recursive=recursive)
    if not files:
        return {"ok": False, "error": "no supported image files found",
                "paths": list(paths)}
    res = build_gallery(files, out_dir, title=title, thumb_size=thumb)
    res["ok"] = True
    return res


def watermark_tool(
    paths: list,
    text: str = "",
    image: str = "",
    position: str = "BOTTOM_RIGHT",
    opacity: int = 50,
    output_format: Optional[str] = None,
    quality: Optional[int] = None,
    output_dir: Optional[str] = None,
) -> dict:
    """Overlay a text or image watermark on images via the batch pipeline.

    Returns a BatchResult JSON with per-file status, plus ``ok``.
    """
    from .server import _options_from_dict
    from .cli import _collect_files

    files = _collect_files(list(paths))
    if not files:
        return {"ok": False,
                "error": "no supported image files found",
                "paths": list(paths)}

    data = {
        "watermark_text": text, "watermark_image": image,
        "watermark_position": position, "watermark_opacity": opacity,
        "output_format": output_format, "quality": quality,
        "output_dir": output_dir,
    }
    data = {k: v for k, v in data.items() if v is not None}
    opts = _options_from_dict(data, base=_base_options)
    result = batch_process(files, opts)
    payload = result.to_dict()
    payload["ok"] = result.fail_count == 0
    return payload


def preset_tool(
    action: str,
    name: str = "",
    description: str = "",
    options: dict = {},
) -> dict:
    """Manage processing presets: list / save / load / delete.

    ``load`` returns the preset's ProcessOptions as a JSON dict that can be
    fed straight back into ``process``. ``save`` takes an ``options`` dict.
    """
    from .presets import (delete_preset, list_presets, load_preset,
                          save_preset)

    if action == "list":
        return {"ok": True, "presets": list_presets()}
    if not name:
        return {"ok": False, "error": "name is required for this action"}

    if action == "save":
        from .server import _options_from_dict
        opts = _options_from_dict(options or {}, base=_base_options)
        save_preset(name, opts, description=description)
        return {"ok": True, "name": name, "action": "save"}

    if action == "load":
        opts = load_preset(name)
        if opts is None:
            return {"ok": False, "name": name, "error": "preset not found"}
        return {"ok": True, "name": name, "options": opts.__dict__}

    if action == "delete":
        ok = delete_preset(name)
        return {"ok": ok, "name": name, "action": "delete",
                "deleted": ok}
    return {"ok": False, "error": f"unknown action: {action}",
            "actions": ["list", "save", "load", "delete"]}


# ── Server assembly ─────────────────────────────────────────────────────────


def create_server(config_path: Optional[str] = None):
    """Build a fresh FastMCP server with all tools registered.

    ``config_path`` (from ``photo-s mcp --config``) supplies ProcessOptions
    defaults merged under tool arguments (explicit tool args win).
    Testable without stdio via ``await server.call_tool(...)``.
    """
    global _base_options
    _base_options = ProcessOptions()
    if config_path:
        from .config import load_config, apply_config
        _base_options = apply_config(load_config(config_path), _base_options)

    mcp = _mcp()
    mcp.add_tool(process_tool, name="process",
                 description="Batch process images: quality/format/resize/"
                             "tone/exposure/denoise. Accepts files, "
                             "directories or globs. Returns BatchResult JSON "
                             "with per-file status.")
    mcp.add_tool(info_tool, name="info",
                 description="Environment probe: version, supported formats, "
                             "optional-feature and plugin status.")
    mcp.add_tool(exif_tool, name="exif",
                 description="Read/filter or write EXIF metadata "
                             "(rating/keywords/camera/title/...). "
                             "action='show' filters files; action='write' "
                             "takes a per-path tag map.")
    mcp.add_tool(dedup_tool, name="dedup",
                 description="Find duplicate images by perceptual hash. "
                             "action='report' lists groups; "
                             "action='keep-sharpest' keeps the sharpest of a "
                             "burst (deletion requires dry_run=False).")
    mcp.add_tool(cull_tool, name="cull",
                 description="Filter images by exposure and sharpness "
                             "thresholds; returns per-file stats and a kept "
                             "list.")
    mcp.add_tool(hash_tool, name="hash",
                 description="Generate or verify a SHA-256 checksum manifest "
                             "(any file type).")
    mcp.add_tool(plugin_tool, name="plugin",
                 description="Manage official plugins: list installed/"
                             "available, install, uninstall (shells to pip).")
    mcp.add_tool(contact_sheet_tool, name="contact_sheet",
                 description="Build a contact sheet (grid montage) from "
                             "images; returns the output path and count.")
    mcp.add_tool(gallery_tool, name="gallery",
                 description="Generate an HTML gallery from images; returns "
                             "the output directory and count.")
    mcp.add_tool(watermark_tool, name="watermark",
                 description="Overlay a text or image watermark on images "
                             "via the batch pipeline.")
    mcp.add_tool(preset_tool, name="preset",
                 description="Manage processing presets: list / save / load "
                             "/ delete. 'load' returns options JSON for "
                             "'process'.")
    return mcp


def run_stdio(config_path: Optional[str] = None) -> None:
    """Blocking stdio entry point for ``photo-s mcp``."""
    asyncio.run(create_server(config_path=config_path).run_stdio_async())


def list_tools_json() -> List[dict]:
    """Tool names + JSON input schemas (for ``photo-s mcp --list-tools``)."""
    tools = asyncio.run(create_server().list_tools())
    return [{
        "name": t.name,
        "description": t.description,
        "input_schema": t.model_dump(by_alias=True)["inputSchema"],
    } for t in tools]


def _call_tool_json(name: str, args: dict) -> dict:
    """Call a tool in-process and normalize the result to a dict.

    ``call_tool`` returns ``list[TextContent]`` (or a raw dict on newer
    versions) — this helper handles both. Used by tests.
    """
    result = asyncio.run(create_server().call_tool(name, args))
    if isinstance(result, list) and result and hasattr(result[0], "text"):
        return json.loads(result[0].text)
    return result
