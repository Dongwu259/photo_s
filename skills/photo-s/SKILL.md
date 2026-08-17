---
name: photo-s
description: Batch photo processing toolbox (PhotoS). Use when the user asks to compress/convert/resize RAW or JPEG photos in batch, edit EXIF metadata (rating, keywords, camera, GPS), deduplicate similar photos, cull by exposure/sharpness, rank and move keepers by rating, merge bracketed HDR shots, blur or pixelate faces for privacy, build contact sheets or HTML galleries, generate SHA-256 manifests, rename files in batch, watch a folder and auto-process new files, or benchmark processing speed. 批量照片处理工具箱：压缩/转码/缩放/EXIF 编辑/去重/选片/HDR 合并/人脸模糊/联系表/画廊/校验清单。
---

# PhotoS — Batch Photo Toolbox

> Positioning: **CLI for AI agents, GUI for humans**. All heavy lifting is exposed
> as stable CLI commands with machine-readable JSON output. Full contract:
> `docs/AGENT_API.md` (in this repo).

## Install

```bash
pip install photo-s-tools            # core: Pillow + rawpy (RAW decode)
pip install "photo-s-tools[enhance]" # + opencv: denoise / straighten / HDR / face blur
pip install "photo-s-tools[mcp]"     # + MCP server (Python 3.10+)
```

- Binary: `photo-s` · Python package: `photo_s` (importable in-process) · PyPI name:
  `photo-s-tools` · brand: PhotoS.
- Works on macOS / Linux / Windows. Python 3.9+.

## Golden rules (read first)

1. **Always pass `--json` for automation.** Every command returns one JSON document
   on stdout with a top-level `schema_version` key (currently `1`); human-readable
   text goes to stderr when `--json` is set. JSON keys are always English.
2. **Never delete or overwrite inputs implicitly.** `batch`/`compress` write outputs
   beside inputs (or into `-o DIR`). Deletion-style commands (`dedup keep-sharpest`,
   `--remove-original`) require explicit flags.
3. **Prefer `--dry-run` first** for anything that moves or deletes files
   (`select`, `dedup`) — zero writes, same JSON shape with `would_*` actions.
4. **Pin language when text matters**: `--language en|zh|auto` (default `auto` =
   system detection). Use `en` for scripted/CI use.
5. **Exit codes**: `0` = success, `1` = failure (bad args, missing deps). Per-file
   errors are reported in `results[].status`/`error`, not by aborting the batch.
6. **Optional opencv features** (`denoise`, `auto_straighten`, `hdr`, `blurfaces`)
   fail per-file with a clear "install photo-s-tools[enhance]" message when opencv
   is missing. Check `photo-s info --json` → `optional_features` first.

## Subcommand → task map

| Task | Command | Notes |
|---|---|---|
| Full pipeline batch (compress/convert/resize/tone/crop/watermark/…) | `photo-s batch PATHS... [-o DIR] [-q 85] [--resize 1920x1080] [--crop-ratio 16:9] [--strip-gps] [--preset NAME] [--blur-faces MODE] [--denoise] [--ev -1]` | MODE = blur or pixelate; see `photo-s batch --help` |
| Single-file convert | `photo-s convert IN [-o OUT]` | |
| RAW → JPEG/TIFF batch | `photo-s batch 'RAW/*.ARW' --format jpeg` | rawpy built-in, no extra dep |
| EXIF read / write / filter | `photo-s exif PATHS... [--rating N] [--keywords ...] [--gps "lat,lon"] [--make --model] [--from-csv meta.csv]` | `--rating-min N` filters |
| Deduplicate | `photo-s dedup PATHS... [--action keep-sharpest] [--dry-run]` | perceptual hash; actions: report/move/delete/keep-sharpest |
| Cull by exposure/sharpness | `photo-s cull PATHS... [--overexposed-max ...] [--sharpness-min ...]` | |
| Rank & move by rating | `photo-s select PATHS... [--keep-min 4] [--reject-max 2] [--selects-dir DIR] [--rejects-dir DIR] [--copy] [--dry-run]` | reads EXIF rating |
| HDR merge (exposure brackets) | `photo-s hdr IMG1 IMG2 IMG3... -o out.jpg [--align]` | needs `[enhance]` |
| Face blur / pixelate | `photo-s blurfaces PATHS... [--mode pixelate] [--margin 20] [-o DIR]` | privacy; needs `[enhance]` |
| Contact sheet | `photo-s contact-sheet PATHS... -o sheet.jpg [--cols 4] [--caption]` | |
| HTML gallery | `photo-s gallery PATHS... -o OUTDIR [--title ...]` | |
| Batch rename | `photo-s rename PATHS... --pattern '{seq}'` | live preview; vars: {year} {month} {day} {date} {time} {camera} {make} {iso} {focal} {seq} |
| Corrupt-file scan | `photo-s check PATHS... [--json]` | integrity report |
| SHA-256 manifest | `photo-s hash PATHS... -o manifest.csv [--verify manifest.csv]` | generate / verify |
| Watch a folder | `photo-s watch DIR [-o DIR] [--recursive]` | auto-process new files |
| Presets | `photo-s preset save NAME --quality 80 ...` then `photo-s batch ... --preset NAME` | saves full option set |
| Speed benchmark | `photo-s bench --dir DIR -j 1,2,4,8 [--evaluate]` | temp output, source untouched |
| Environment probe | `photo-s info --json` | version, optional features, plugins |

## Typical workflows

### 1. Ingest → rank → keepers
```bash
photo-s batch "RAW/*.ARW" --format jpeg -o keepers/ -q 90
photo-s exif "RAW/*.ARW" --rating-min 4            # what the camera rated
photo-s select "RAW/*.ARW" --keep-min 4 --reject-max 2 \
    --selects-dir selects/ --rejects-dir rejects/ --dry-run
# inspect JSON, re-run without --dry-run to move
```

### 2. Share-ready with privacy (strip GPS + face blur)
```bash
photo-s batch "share/*.jpg" -o share/clean/ --strip-gps --scrub
photo-s blurfaces "share/clean/*.jpg" --mode pixelate
```

### 3. Client delivery
```bash
photo-s batch "picked/*.jpg" -o deliver/ --resize 2000x2000 -q 92 --watermark "© you"
photo-s contact-sheet "picked/*.jpg" -o sheet.jpg --caption
photo-s hash deliver/ -o deliver/manifest.csv --verify deliver/manifest.csv
```

### 4. Processing-speed check
```bash
photo-s bench --dir "RAW/" -j 1,2,4,8 --evaluate
```

## Errors & recovery

- Per-file failures do not abort the batch — check `results[].status == "error"`
  and `results[].error`, then retry only the failed paths.
- Missing optional dep → error message names the extra to install
  (`pip install "photo-s-tools[enhance]"`).
- `select` with `keep_min <= reject_max` → usage error (exit 1).
- `hdr` with fewer than 2 images → usage error (exit 1). `--align` unavailable on
  some opencv builds → clear error, retry without `--align`.
- `blurfaces` with a missing Haar cascade → error; **never** silently returns the
  unmasked image.

## Alternative integrations (when the skill isn't enough)

- **Python host**: `from photo_s.engine import ProcessOptions, batch_process` — no IPC overhead.
- **MCP (deep, tool-level)**: install `photo-s-tools[mcp]` (Python 3.10+), then
  `claude mcp add photo-s -- photo-s mcp` and call tools (`process`, `select`,
  `hdr`, `blurfaces`, `dedup`, …) directly. 18 tools, schemas via
  `photo-s mcp --list-tools`.
- **REST**: `photo-s serve --port 0 --token auto --ready-file x.json` — poll the
  file for `{port, token}`, then HTTP with bearer token.
- Full contract (JSON shapes, exit codes, `serve` endpoints, config precedence):
  `docs/AGENT_API.md`.
