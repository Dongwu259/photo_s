# 📷 PhotoS — Batch Image Compression & Format Conversion

<!-- mcp-name: io.github.Dongwu259/photo-s -->

[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Windows%20%7C%20Linux-lightgrey)](https://github.com)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-521%20passed-brightgreen)]()
[![PyPI](https://img.shields.io/badge/pypi-photo--s--tools-orange)](https://pypi.org/project/photo-s-tools/)

**PhotoS** is a cross-platform batch image processing tool with **both GUI and CLI**. Built for photographers who need to deliver images at specific sizes, and for AI agents that need reliable image processing pipelines.

> 🖥 **GUI** for humans — ⌨️ **CLI** for AI agents — `pip install photo-s-tools`

> ✍️ **Core developers:** deepseek-v4-flash · GLM-5.2 · Kimi K3

**English** · [中文](docs/README.zh-CN.md)

---

## ✨ Features

| Feature | GUI | CLI | Description |
|---|---|---|---|
| Batch compress | ✅ | ✅ | JPEG/WebP/HEIC/AVIF quality tuning |
| Target size mode | ✅ | ✅ | Auto-tune quality to fit under a target file size |
| Format convert | ✅ | ✅ | JPEG / PNG / WebP / TIFF / BMP / HEIC / AVIF |
| RAW decode | ✅ | ✅ | 22+ camera RAW formats, built-in (rawpy/libraw) |
| Resize / Scale | ✅ | ✅ | Max dimensions, percentage, or longest-side cap |
| Visual preview | ✅ | — | Live original↔processed preview rendered through the real pipeline |
| Tone & color | ✅ | ✅ | Brightness/contrast/saturation/gamma/sharpen, B&W, sepia |
| White balance | ✅ | ✅ | `--wb 5600` Kelvin, or `--wb-from ref.jpg` sample a gray card |
| Exposure | ✅ | ✅ | `--ev +1` stops, or `--auto-exposure 0.45` normalize to target |
| Auto levels | ✅ | ✅ | `--auto-levels` 2% clip histogram stretch |
| LOG recovery | ✅ | ✅ | `--log-curve SLOG3/CLOG3/LOGC3/DLOG/VLOG/HLG` (1D LUT, no deps) |
| LUT grading | ✅ | ✅ | `--lut film.cube` or preset names (built-in trilinear; `photo-s-plugin-lut` adds tetrahedral + 5 film presets) |
| Denoise | ✅ | ✅¹ | `--denoise 10` NLM (`[enhance]` extra) |
| Auto-straighten | ✅ | ✅¹ | `--auto-straighten` level the horizon, confidence-gated (`[enhance]` extra) |
| Crop / Rotate / Flip / Pad | ✅ | ✅ | `--crop 800x600+0+0`, `--rotate 90`, `--flip h`, `--pad 16:9` |
| Print size | ✅ | ✅ | `--print-size 8x10@300dpi` center-crop + exact print pixels |
| Smart rename | ✅ | ✅ | `{date}_{camera}_{seq}` templates |
| Auto folder organize | ✅ | ✅ | `--organize date-camera` subfolder creation |
| Watermark | ✅ | ✅ | Text + image overlay, 7 positions |
| Multi-size output | ✅ | ✅ | `--sizes thumb:480x,screen:1920x` |
| Metadata tagging | ✅ | ✅ | `exif --rating` / `--keywords` / `--caption` batch tag (UserComment) |
| Metadata filter | ✅ | ✅ | `exif --show --rating-min 3 --keywords beach` find tagged photos |
| Metadata import | — | ✅ | `exif --from-csv meta.csv` batch write from spreadsheet |
| Culling | ✅ | ✅ | `photo-s cull` exposure/sharpness filter (GUI keeps only matches, undoable) |
| Burst keep-sharpest | ✅ | ✅ | `dedup --action keep-sharpest` pick the sharpest of a burst |
| Checksum manifest | ✅ | ✅ | `photo-s hash` SHA-256 archive integrity + `--verify` |
| HTML gallery | ✅ | ✅ | `photo-s gallery` self-contained index.html + thumbs |
| Presets | ✅ | ✅ | Save/load named configs |
| Multi-profile batch | — | ✅ | `--profiles web,thumb` one input set, N outputs |
| Parallel processing | ✅ | ✅ | `-j 8` multi-threaded |
| JSON output | — | ✅ | `--json` for AI agent consumption |
| Config file | — | ✅ | `photo-s.toml` defaults (`config init/show`) |
| EXIF edit | — | ✅ | `photo-s exif *.jpg --artist "Me"` |
| EXIF date shift | — | ✅ | `--date-shift "-5h30m"` timezone/camera clock fixes |
| Privacy scrub | — | ✅ | `--scrub` strips EXIF+ICC+GPS |
| Sync date | — | ✅ | `--sync-date` output mtime ← EXIF datetime |
| Folder watch | ✅ | ✅ | `photo-s watch ~/incoming/` auto-process (`[watch]` extra) |
| Auto-rotate | ✅ | ✅ | EXIF Orientation-based |
| Image dedup | ✅ | ✅ | Perceptual hash duplicate detection |
| Quality metrics | ✅ | ✅ | `--evaluate` SSIM + `--blur-score` |
| CSV report | — | ✅ | `--report out.csv` per-file stats |
| Integrity check | — | ✅ | `photo-s check` corrupt file scan |
| Contact sheet | ✅ | ✅ | `photo-s contact-sheet *.jpg -o sheet.png` |
| Color management | — | ✅ | `--srgb` / `--flatten-cmyk` |
| REST API | — | ✅ | `photo-s serve` for AI agents |
| Plugin system | — | ✅ | Third-party plugin support |
| Official plugin manager | — | ✅ | `photo-s plugin list/install/info/fetch` + `pip install photo-s-plugin-scunet` |
| MCP server | — | ✅ | `photo-s mcp` expose 15 tools to MCP clients (Claude Desktop) |
| Batch benchmark | — | ✅ | `photo-s bench --dir ~/shoot -j 1,2,4,8` measure worker scaling |

> ¹ Denoise / auto-straighten need an optional dependency: `pip install photo-s-tools[enhance]` (opencv-python-headless).
> When missing, these features give a clear install hint and the rest keeps working.

---

## 📦 Installation

### pip install (recommended)

```bash
pip install photo-s-tools

# With optional features
pip install photo-s-tools[all]       # everything
pip install photo-s-tools[heic]      # HEIC support
pip install photo-s-tools[avif]      # AVIF support
pip install photo-s-tools[watch]     # folder watching
pip install photo-s-tools[exif]      # EXIF editing
pip install photo-s-tools[enhance]   # NLM denoise + auto-straighten (opencv)
pip install photo-s-tools[mcp]       # MCP server (Python 3.10+)
```

### From source

```bash
git clone https://github.com/Dongwu259/photo_s.git
cd photo_s
pip install -e .
```

### Zero-install (uvx)

Run without installing into your environment — uvx resolves the PyPI
dependencies on first run:

```bash
uvx --from photo-s-tools photo-s --help          # CLI
uvx --from "photo-s-tools[mcp]" photo-s mcp      # MCP server (Python 3.10+)
```

### Windows pre-built executables (no Python needed)

GitHub Releases ships two PyInstaller bundles (built by CI):
- `photo-s-windows` — full: GUI + CLI + MCP
- `photo-s-lite-windows` — CLI + MCP only, no Tk

Download the zip from the [Releases](https://github.com/Dongwu259/photo_s/releases)
page and run the `.exe` directly.

### Official plugins (separate PyPI distributions)

```bash
photo-s plugin install scunet          # SCUNet strong denoising
photo-s plugin install lut             # LUT film grading

# or directly via pip
pip install photo-s-plugin-scunet
pip install photo-s-plugin-lut
```

> `photo-s` itself is blocked on PyPI (too similar to the existing `photos`
> package), so the distribution name is **`photo-s-tools`**. Core requires
> Python ≥ 3.9; the `mcp` extra needs ≥ 3.10.

---

## ⌨️ CLI Usage

```bash
photo-s --help                  # Show all commands
photo-s --language en --help    # Help in English (zh / auto follow the system)
photo-s compress *.jpg -q 80    # Batch compress
photo-s convert *.png -f webp   # Convert format
photo-s batch ~/photos/ -r      # Recursive batch
photo-s exif *.jpg --artist "Me" # Edit EXIF
photo-s preset save web -q 70   # Save preset
photo-s preset list             # List presets
photo-s watch ~/incoming/       # Auto-process new files
photo-s dedup ~/photos/         # Find duplicates
photo-s info                    # Supported formats
photo-s --version               # Show version
```

### Photographer workflows

```bash
# Cull: find over/under-exposed shots
photo-s cull ~/shoot/ -r --overexposed-max 2% --underexposed-max 2% --list

# Tag + filter by tags (core workflow)
photo-s exif ~/shoot/ -r --rating 4 --keywords "keep,beach"   # batch tag
photo-s exif ~/shoot/ -r --show --rating-min 4 --list         # pick >=4-star paths
photo-s exif ~/shoot/ -r --show --keywords beach --json        # filter by keyword
photo-s exif --from-csv meta.csv                               # batch write from CSV
photo-s batch $(photo-s exif ~/shoot/ -r --show --rating-min 4 --list) -o /deliver/

# Archive: generate + verify a SHA-256 manifest
photo-s hash ~/archive/ -r -o manifest.csv
photo-s hash --verify manifest.csv

# Burst selection: keep the sharpest of each group
photo-s dedup ~/burst/ --action keep-sharpest --dry-run

# Delivery: HTML gallery / print size / white balance
photo-s gallery ~/shoot/ -o gallery/ --title "2026 Sichuan"
photo-s batch ~/shoot/ --print-size 8x10@300dpi
photo-s batch ~/shoot/ --wb 5600 --auto-levels

# Global correction: exposure / LOG recovery / denoise / straighten
photo-s batch ~/shoot/ --ev +0.5 --auto-exposure 0.45
photo-s batch ~/log/    --log-curve SLOG3 --wb 5600        # LOG footage recovery
photo-s batch ~/highiso/ --denoise 12 --ev -0.3            # high-ISO denoise
photo-s batch ~/tilted/ --auto-straighten --max-straighten-angle 8
```

### Common examples

```bash
# Compress to ~5MB with auto-tune, 8 threads, JSON output (AI agent)
photo-s compress *.jpg --target-size 5MB -j 8 --json

# Convert to AVIF with parallel workers
photo-s convert *.jpg -f AVIF -q 60 -j 4

# Organize by date+camera, add a watermark
photo-s batch ~/photos/ --organize date-camera --watermark-text "© Me" -j 4

# Smart rename with EXIF metadata
photo-s compress *.jpg --rename "{date}_{camera}_{seq}"

# Find duplicate images
photo-s dedup ~/photos/ --action report
```

### JSON output (for AI agents)

`--json` prints pure JSON to stdout (progress/diagnostics go to stderr). All agent-facing subcommands support it:
`compress`/`batch`/`convert` (batch results), `check`/`dedup` (reports), `rename`, `contact-sheet`,
`info`, and `--dry-run` (config preview).

```json
{
  "summary": {"total": 5, "success": 5, "failed": 0, "saved_bytes": 27262976, "saved_percent": 52.0},
  "results": [{"input": "photo.jpg", "output": "photo_compressed.jpg", "input_size": 10485760, "output_size": 5242880, "format": "JPEG", "dimensions": [6000, 4000], "quality": 78, "status": "ok"}]
}
```

Use with any AI agent: `photo-s compress *.jpg --json --target-size 5MB | your-agent`

> Exit-code convention: failures in batch/rename/check → `1`; `dedup` returns `1` **when duplicates are
> found** (0 otherwise), so agents can branch on it. Under `--json`, `--remove-original` /
> `dedup --action move|delete` skip interactive confirmation (an explicit agent request is taken as consent).

---

## 🖥 GUI Usage

```bash
photo-s          # Launch GUI (no args = GUI)
photo-s gui      # Explicit GUI mode
```

GUI features: auto-detected Chinese/English language (system locale on first launch; manual choice is remembered across restarts), drag-and-drop (needs `pip install photo-s-tools[gui]`),
cancellable batch processing, before/after comparison, global shortcuts
(⌘/Ctrl+O add, ⌘/Ctrl+R start, Esc cancel, ⌘/Ctrl+E review, ⌘/Ctrl+D dedup, ⌘/Ctrl+G gallery, ⌘/Ctrl+Z undo),
a **checkbox file list** (every row has a
real checkbox; all actions — process, review, dedup, gallery — run on the checked files;
adding a folder scans subfolders), a **review & rate lightbox**
(←/→ navigation, 0-5 stars, keywords/title, rating & keyword filters — writes EXIF),
a **duplicate viewer** (side-by-side groups with sharpness scores, keep-checkboxes,
move-to-trash instead of delete), and **HTML gallery export**. Tagged photos can then be
filtered in the CLI (`photo-s exif --rating-min 4 --list`) or used by AI agents.

> GUI changes & interface contract: [`docs/GUI_CHANGES.md`](docs/GUI_CHANGES.md)

### Screenshots

<!-- TODO: Add screenshots -->
- Main window with file list + settings panel
- Processing progress bar and summary dialog
- Before/after comparison view

---

## 🎯 Target Size Mode

Unique feature: set a target file size and PhotoS auto-tunes JPEG/WebP/AVIF quality via binary search.

```bash
photo-s compress *.jpg --target-size 5MB
# Auto-tunes quality ∈ [5, 85] to make each output ≤ 5MB
```

---

## 🔌 Plugin System

Third-party plugins extend PhotoS via Python `entry_points`.

```bash
pip install photo-s-plugin-s3    # Example: auto-upload to S3
photo-s compress *.jpg           # plugins auto-apply
```

### Official plugins

Official plugins are separate PyPI distributions `photo-s-plugin-<name>`. Install via either the
plugin manager or pip. The first official plugin is **SCUNet strong denoise** — stronger high-ISO
denoising than the built-in NLM. Once installed, `--denoise N` prefers it automatically
(and falls back to NLM otherwise):

```bash
# Channel 1: plugin manager (agent-friendly, --json)
photo-s plugin list
photo-s plugin install scunet --json
photo-s plugin fetch scunet          # pre-download the ONNX weights (~10-40MB, sha256-verified)
photo-s plugin info scunet

# Channel 2: plain pip
pip install photo-s-plugin-scunet

# Usage (auto uses SCUNet when installed, else NLM)
photo-s batch ~/highiso/ --denoise 12
```

> Model weights are **not shipped in the wheel**: downloaded on first use to
> `~/.cache/photo-s/models/` (override with `$PHOTOS_CACHE_DIR`), sha256-verified.
> All official plugins follow the "separate distribution + external weights" model.

### Writing a plugin

```python
# setup.py / pyproject.toml
[project.entry-points."photo_s.plugins"]
my-plugin = "my_package:MyPlugin"

# my_package.py
from photo_s.hooks import PhotoSPlugin

class MyPlugin(PhotoSPlugin):
    name = "my-plugin"

    def on_post_process(self, result, ctx):
        print(f"Processed: {result.output_path}")
```

See [docs/PLUGINS.md](docs/PLUGINS.md) for the full API, including operation providers
(e.g. a `denoise` slot provider) and model-weight handling.

---

## 📋 Supported Formats

| Format | Read | Write | Notes |
|---|---|---|---|
| JPEG | ✅ | ✅ | quality, progressive, EXIF |
| PNG | ✅ | ✅ | optimize |
| WebP | ✅ | ✅ | quality |
| AVIF | ✅ | ✅ | quality (requires `pillow-avif-plugin`) |
| HEIC | ✅ | ✅ | requires `pillow-heif` |
| TIFF | ✅ | ✅ | LZW compression |
| BMP | ✅ | ✅ | |
| ICO | ✅ | ✅ | |
| RAW (22+ formats) | ✅ | — | built-in via `rawpy` (libraw) |

---

## ✏️ Naming Convention

| Context | Form | Notes |
|---|---|---|
| Python package / import | `photo_s` | syntax-enforced: `import photo-s` is invalid |
| CLI command | `photo-s` | shell convention: `photo-s compress *.jpg` |
| PyPI distribution | `photo-s-tools` | `pip install photo-s-tools` (the obvious `photo-s` is blocked by PyPI — too similar to the existing `photos` package) |
| UI title / brand / doc headings | `PhotoS` | human-readable brand name |

Don't mix forms within the same context (e.g. `photo_s compress` in code examples, or `photo-s` in
UI copy, are both wrong). This is the standard Python-ecosystem pattern
(scikit-learn→sklearn, Pillow→PIL); please don't "unify" them.

---

## 🤖 Agent / Application Integration

> The complete integration contract (CLI JSON shapes, exit codes, `serve` endpoints, async tasks,
> config precedence) lives in [`docs/AGENT_API.md`](docs/AGENT_API.md) — agents only need that one doc.

PhotoS offers three integration paths, by recommendation:

### 1. Python library (recommended when the host is Python)

```python
from photo_s.engine import ProcessOptions, batch_process

options = ProcessOptions(
    output_dir="compressed/",
    quality=70,
    max_pixels=8000,
    strip_gps=True,          # privacy
    evaluate=True,           # SSIM
)
result = batch_process(["/path/a.jpg", "/path/b.jpg"], options, jobs=4)
for r in result.results:
    print(r.output_path, r.ssim)
```

No IPC overhead; just vendor the `photo_s` package into your app.

### 2. REST API (`photo-s serve` — non-Python host / cross-process)

```bash
photo-s serve --port 0 --token auto --ready-file ./photo-s.ready.json
```

- `--port 0` = random free port; `--token auto` = random token;
  `--ready-file` atomically writes `{"port", "token", "pid"}` after listening starts —
  the host agent polls that file (more reliable than parsing stdout, also on Windows), then:
  `GET /health` readiness probe → `POST /process` `{"paths": [...], "options": {...}}`
  → get BatchResult JSON (with ssim / blur_score).

**Long batches / progress / cancel** (`POST /process` with `"async": true`):

```bash
# 1. Submit an async task
curl -X POST .../process -H "Authorization: Bearer $TOKEN" \
     -d '{"paths": ["/photos/*.jpg"], "async": true}'
# → 202 {"task_id": "...", "poll": "/tasks/<id>", ...}

# 2. Poll progress
curl .../tasks/<id>
# → {"status": "running|done|cancelled|error", "current": N, "total": M,
#     "current_path": "...", "result": {BatchResult JSON when done}}

# 3. Cancel (queued files stop after the in-flight one finishes)
curl -X POST .../tasks/<id>/cancel
```

`POST /process` also supports `"dry_run": true` (returns the paths/options that would be processed,
no work done) and `options.output_sizes` (multi-size, `[["thumb",480,None], ...]`) and
`options.pad` (= `pad_ratio`).
- On Windows without a Python env: use PyInstaller to bundle `photo-s.exe`
  (see below), spawn it by absolute path — no PATH dependency.
- The host manages the process lifecycle (terminate the child on exit).

### 3. CLI subprocess (one-off scripts / CI)

`photo-s compress a.jpg -q 80 --json` → stdout JSON. Each call has a Python
interpreter startup cost (~200-300ms); not recommended for high-frequency batch.

### 4. MCP server (Claude Desktop & MCP clients)

[Model Context Protocol](https://modelcontextprotocol.io) server — lets Claude
Desktop / any MCP client call PhotoS tools directly (needs Python 3.10+ and
the optional extra):

```bash
pip install "photo-s-tools[mcp]"
photo-s mcp --list-tools        # inspect the 15 tools + schemas (JSON)
photo-s mcp                     # start the stdio MCP server
```

Tools: `process` (batch quality/format/resize/tone/denoise), `info` (environment
probe), `exif` (read/filter/write metadata), `dedup` (perceptual-hash groups,
keep-sharpest), `cull` (exposure/sharpness filter), `hash` (SHA-256 manifests),
`contact_sheet` (grid montage), `gallery` (HTML gallery), `watermark` (text/image
overlay), `preset` (list/save/load/delete), `plugin` (official plugin
management). Output shapes mirror the CLI `--json` contracts.

Claude Desktop config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "photo-s": {
      "command": "photo-s",
      "args": ["mcp"]
    }
  }
}
```

Zero-install variant (uvx resolves PyPI deps on first run — the same invocation
published on the [official MCP Registry](https://registry.modelcontextprotocol.io)
as `io.github.Dongwu259/photo-s`):

```json
{
  "mcpServers": {
    "photo-s": {
      "command": "uvx",
      "args": ["--from", "photo-s-tools[mcp]", "photo-s", "mcp"]
    }
  }
}
```

> Destructive safety: `dedup` `keep-sharpest` defaults to `dry_run=True`
> (deletion requires an explicit `dry_run=False`). `process` never overwrites
> inputs.

### Windows packaging (no Python/PATH env)

```bash
pip install pyinstaller piexif pillow-heif   # optional features too
python packaging/build.py                    # full: dist/photo-s/photo-s.exe (GUI+CLI+MCP)
python packaging/build.py --lite             # lite: dist/photo-s-lite/photo-s-lite.exe (CLI+MCP, no GUI)
```

Two editions: the **full** bundle ships the GUI; the **lite** bundle excludes
`photo_s.gui` + tkinter at build level (smaller, display-free) — ideal for
agent-spawned `serve`/`mcp` processes. In the lite build `photo-s-lite` with
no args prints help, `gui` exits 1 with a hint, and `--version` shows
`(lite)`.

The host launches by **absolute path**, no environment variables needed (see the spawn mode above).
CI builds both `windows-latest` artifacts (`.github/workflows/ci.yml`).

---

## 🧪 Development

```bash
pip install -e ".[dev]"
python -m pytest tests/ -v
```

---

## 📄 License

MIT
