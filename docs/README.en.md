# 📷 PhotoS

<!-- mcp-name: io.github.Dongwu259/photo-s -->

[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Windows%20%7C%20Linux-lightgrey)](https://github.com)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![PyPI](https://img.shields.io/badge/pypi-photo--s--tools-orange)](https://pypi.org/project/photo-s-tools/)

**CLI for AI agents, GUI for humans.** PhotoS is a cross-platform batch photo
toolbox: a full Tkinter GUI — v2.2 workspace with Library / Develop (live
pipeline preview + histogram + edit tools beside it, copy/paste settings
between photos, per-photo undo) / Export (photo queue + output settings +
named export recipes) / Tools modules — and a CLI / REST / MCP surface with
one versioned JSON contract for AI agents.

> 🖥 GUI for humans · ⌨️ CLI for AI agents · `pip install photo-s-tools`

**English** · [中文](../README.md)

---

## 🤖 Built for AI agents

PhotoS is an AI-agent-ready image pipeline: four integration paths, one versioned
JSON contract (`schema_version`, additive-only — upgrades never break a consumer).

| Path | Entry point |
|---|---|
| **MCP server** — 26 core tools + plugin tools auto-registered (process / suggest / select / hdr / blurfaces / dedup / …) | `claude mcp add photo-s -- photo-s mcp` |
| **Packaged SKILL.md** — skill-capable agents, zero extras | `cp -r skills/photo-s ~/.claude/skills/` |
| **REST API** — async tasks + SSE progress | `photo-s serve --port 0 --token auto --ready-file x.json` |
| **Python library** — no IPC overhead | `from photo_s.engine import batch_process` |

Every output carries `schema_version`; JSON keys are always English; per-file
errors never abort the batch; destructive actions require an explicit flag.
Full contract: [`docs/AGENT_API.md`](AGENT_API.md).

---

## ✨ Features

| Feature | GUI | CLI | Description |
|---|---|---|---|
| Batch compress | ✅ | ✅ | JPEG/WebP/HEIC/AVIF quality tuning, chroma subsampling (444/422/420) |
| Target size mode | ✅ | ✅ | Auto-tune quality to fit under a target file size |
| Format convert | ✅ | ✅ | JPEG / PNG / WebP / TIFF / BMP / HEIC / AVIF |
| RAW decode | ✅ | ✅ | 22+ camera RAW formats, built-in (rawpy/libraw); demosaic algorithm choice, color space (sRGB/AdobeRGB/ProPhotoRGB), 16-bit TIFF output, auto sRGB ICC tagging |
| Resize / Scale | ✅ | ✅ | Max dimensions, percentage, or longest-side cap |
| Visual preview | ✅ | — | Live original↔processed preview rendered through the real pipeline |
| Tone & color | ✅ | ✅ | Brightness/contrast/saturation/gamma/sharpen, B&W, sepia |
| Export sharpen | ✅ | ✅ | LR-style output-stage USM, radius scales with output resolution |
| White balance | ✅ | ✅ | Kelvin temperature or gray-card sampling |
| WB tint axis | ✅ | ✅ | Green(-)/magenta(+) G-M axis |
| Point curves / levels | ✅ | ✅ | PCHIP point curves, manual black/white/gamma |
| 3-way color grading | ✅ | ✅ | Shadows/midtones/highlights hue + sat zones |
| HSL split | ✅ | ✅ | 8 color domains, hue/sat/lum shifts |
| Point color | ✅ | ✅ | Targeted hue/sat/lum around a sampled color + range |
| Local masks | ✅ | ✅ | Named linear/radial/color-range masks + v1.8 AI segmentation (`subject`/`person`/`object:class`), brush strokes (subtract mode), combos (A&B / A-B); 11 scalar + 5 string local adjustments under each |
| Lens correction | ✅ | ✅ | Manual distortion k1, vignette fix, CA fix (pure numpy); named user-maintained lens profiles |
| Perceptual analysis | ✅ | ✅ | Histograms / channel stats / WB lean / exposure / blur (`analyze`) |
| Param suggestions | — | ✅ | Rule-based `suggest`: analyze stats → conservative fix params with reasons (zero models, offline) |
| Vibrance / clarity / texture | ✅ | ✅ | Natural saturation, local contrast |
| Dehaze / vignette / grain | ✅ | ✅ | Dark-channel dehaze, radial vignette, film grain |
| Exposure | ✅ | ✅ | Stops adjustment or normalize-to-target auto exposure |
| Auto levels | ✅ | ✅ | 2% clip histogram stretch |
| Highlight recovery | ✅ | ✅ | LR-style: compress flat clipped highlights back to visible gradient |
| LOG recovery | ✅ | ✅ | SLOG3/CLOG3/LOGC3/DLOG/VLOG/HLG (1D LUT, no deps) |
| LUT grading | ✅ | ✅ | .cube trilinear (plugin adds tetrahedral + 5 film presets) |
| AI auto-tone | — | ✅¹ | Plugin: CLIP+MLP predicts 9-field LR params + confidence, RAG boost, optional Qwen3-VL aesthetic score & advisor (`photo-s-plugin-auto-tone[model]`); v2.3 wired into the engine slot (`--auto-tone`), MCP tools and REST routes auto-register on install |
| Denoise | ✅ | ✅¹ | NLM (`[enhance]` extra) |
| Auto-straighten | ✅ | ✅¹ | Level the horizon, confidence-gated (`[enhance]` extra) |
| HDR merge | ✅ | ✅¹ | Exposure fusion, handheld alignment (`[enhance]` extra) |
| Face blur | ✅ | ✅¹ | Blur or pixelate faces, Haar cascade (`[enhance]` extra) |
| Cutout | ✅ | ✅ | Background removal → alpha: AI segmentation (`subject`/`person`/`object:class`) or color key (`color:R,G,B[tol,feather,invert]` — white-bg text/logo); PNG/WebP/TIFF/AVIF/HEIC (JPEG errors per file) |
| Crop / Rotate / Flip / Pad | ✅ | ✅ | Unified aspect crop + arbitrary geometry |
| Print size | ✅ | ✅ | Center-crop + exact print pixels at a DPI |
| Smart rename | ✅ | ✅ | Date/camera/sequence templates |
| Auto folder organize | ✅ | ✅ | Date/camera subfolder creation |
| Watermark | ✅ | ✅ | Text + image overlay, 7 positions |
| Multi-size output | ✅ | ✅ | One input set, N labeled outputs |
| Metadata tagging | ✅ | ✅ | Rating/keywords/caption batch tag (UserComment) |
| Metadata filter | ✅ | ✅ | Find photos by rating/keywords |
| Metadata import | — | ✅ | Batch write from spreadsheet |
| Culling | ✅ | ✅ | Exposure/sharpness filter (GUI keeps only matches, undoable); `--score` weighted quality ranking + `--burst` keep-best-per-burst |
| Select (keeper) | ✅ | ✅ | Sort by rating — keep/reject thresholds (≥4 keep, ≤2 reject) |
| Burst keep-sharpest | ✅ | ✅ | Keep the sharpest of a burst |
| Checksum manifest | ✅ | ✅ | SHA-256 archive integrity + verify |
| HTML gallery | ✅ | ✅ | Self-contained index.html + thumbnails |
| Presets | ✅ | ✅ | Save/load named configs + built-in `lr-look` (LR-style grade: S-curve, vibrance, export sharpen) |
| Multi-profile batch | — | ✅ | One input set, N output profiles |
| Parallel processing | ✅ | ✅ | Multi-threaded |
| JSON output | — | ✅ | Machine-readable output for AI agents |
| Config file | — | ✅ | TOML defaults |
| EXIF edit | — | ✅ | Batch copyright/author/GPS |
| Preset apply | — | ✅ | One-click apply a saved style |
| EXIF date shift | — | ✅ | Timezone/camera clock fixes |
| Privacy scrub | — | ✅ | Strip EXIF + ICC + GPS |
| Sync date | — | ✅ | Output mtime ← EXIF datetime |
| Folder watch | ✅ | ✅ | Auto-process new files (`[watch]` extra) |
| Auto-rotate | ✅ | ✅ | EXIF Orientation-based |
| Image dedup | ✅ | ✅ | Perceptual hash duplicate detection |
| Quality metrics | ✅ | ✅ | SSIM / blur score |
| CSV report | — | ✅ | Per-file stats |
| Integrity check | — | ✅ | Corrupt file scan |
| Contact sheet | ✅ | ✅ | Grid montage |
| Color management | — | ✅ | sRGB / CMYK flatten |
| REST API | — | ✅ | HTTP server for agents (async tasks + SSE progress) |
| Plugin system | — | ✅ | Third-party plugin support |
| Official plugin manager | — | ✅ | list/install/info/fetch + pip install |
| MCP server | — | ✅ | 26 core tools (+plugin tools auto-register) for MCP clients (Claude Desktop / Claude Code / any MCP client) |
| Batch benchmark | — | ✅ | Worker-scaling measurement |

> ¹ Denoise / auto-straighten / HDR / face blur need an optional dependency:
> `pip install photo-s-tools[enhance]` (opencv-python-headless). When missing,
> these features give a clear install hint and the rest keeps working.

---

## 📦 Install

```bash
pip install photo-s-tools            # core — RAW decode (rawpy) built in
pip install "photo-s-tools[enhance]" # + opencv: face blur / HDR / denoise / straighten
pip install "photo-s-tools[tiff16]"  # + tifffile: 16-bit RAW → TIFF output
pip install "photo-s-tools[mcp]"     # + MCP server (Python 3.10+)
```

Zero-install (uvx): `uvx --from photo-s-tools photo-s --help` ·
`uvx --from "photo-s-tools[mcp]" photo-s mcp`

## 🚀 Quick start

```bash
photo-s batch 'RAW/*.ARW' --format jpeg -o out/ -q 90   # batch RAW → JPEG
photo-s batch 'RAW/*.ARW' -o out/ -q 95 --jpeg-subsampling 444 \
  --raw-demosaic amaze                                # max quality RAW → JPEG
photo-s batch 'RAW/*.ARW' -o out/ --preset lr-look     # LR-style grade out of the box
photo-s compress *.jpg --target-size 5MB -j 8           # auto-tune to ≤5MB
photo-s select ~/shoot/ -r --selects-dir picks --rejects-dir bin --dry-run
photo-s hash ~/deliver/ -o manifest.csv --verify manifest.csv
```

`photo-s --help` lists all 35 commands. Language: `--language en|zh|auto`.

---

## 🧭 Documentation

| Doc | Contents |
|---|---|
| [`docs/FEATURES.md`](FEATURES.md) | Full inventory — 35 CLI commands, engine pipeline |
| [`docs/AGENT_API.md`](AGENT_API.md) | Agent contract: JSON shapes, exit codes, REST, MCP |
| [`docs/PLUGINS.md`](PLUGINS.md) | Plugin system: SCUNet denoise, LUT, write your own |
| [`docs/GUI_CHANGES.md`](GUI_CHANGES.md) | GUI behavior & interface contract |
| [`docs/ROADMAP.md`](ROADMAP.md) | Version roadmap (v1.6.0: Lightroom-direction grading) |

> Names: PyPI distribution **`photo-s-tools`** (the obvious `photo-s` is taken) ·
> CLI command `photo-s` · Python package `photo_s` · brand **PhotoS**.

---

## ⚠️ Limitations

PhotoS is a **batch / delivery pipeline**, not an interactive editor — no RAW-domain editing. Local editing is spec-driven: named masks (linear/radial/color/AI segmentation/brush strokes/combos) + local adjustments under masks, all as compact strings that serialize through CLI/REST/MCP/presets.

- **On-device inference, no cloud.** Denoise model weights (SCUNet) download to
  your machine on first use; nothing is uploaded.
- **Licensing.** Official code and most official model weights (incl. the SCUNet
  checkpoint) are **MIT** — free for commercial use. Exception: the auto-tone
  plugin's weights are **CC-BY-NC 4.0** (non-commercial, trained on personal
  Lightroom edits; see `plugins/auto-tone/LICENSE-WEIGHTS.txt`). Third-party
  plugins and models carry their own licenses; verify before redistribution.

## 📄 License

MIT
