# 📷 PhotoS — Batch Image Compression & Format Conversion

[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Windows%20%7C%20Linux-lightgrey)](https://github.com)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-352%20passed-brightgreen)]()
[![PyPI](https://img.shields.io/badge/pypi-photo--s-orange)](https://pypi.org)

**PhotoS** is a cross-platform batch image processing tool with **both GUI and CLI**. Built for photographers who need to deliver images at specific sizes, and for AI agents that need reliable image processing pipelines.

> 🖥 **GUI** for humans — ⌨️ **CLI** for AI agents — `pip install photo-s`

---

## ✨ Features

| Feature | GUI | CLI | Description |
|---|---|---|---|
| Batch compress | ✅ | ✅ | JPEG/WebP/HEIC/AVIF quality tuning |
| Target size mode | ✅ | ✅ | Auto-tune quality to fit under a target file size |
| Format convert | ✅ | ✅ | JPEG / PNG / WebP / TIFF / BMP / HEIC / AVIF |
| RAW decode | ✅ | ✅ | 22+ camera RAW formats via rawpy |
| Resize / Scale | ✅ | ✅ | Max dimensions, percentage, or longest-side cap |
| Tone & color | ✅ | ✅ | Brightness/contrast/saturation/gamma/sharpen, B&W, sepia |
| White balance | — | ✅ | `--wb 5600` Kelvin, or `--wb-from ref.jpg` sample a gray card |
| Exposure | — | ✅ | `--ev +1` stops, or `--auto-exposure 0.45` normalize to target |
| Auto levels | — | ✅ | `--auto-levels` 2% clip histogram stretch |
| LOG recovery | — | ✅ | `--log-curve SLOG3/CLOG3/LOGC3/DLOG/VLOG/HLG` (1D LUT, no deps) |
| Denoise | — | ✅¹ | `--denoise 10` NLM (`[enhance]` extra) |
| Auto-straighten | — | ✅¹ | `--auto-straighten` level the horizon, confidence-gated (`[enhance]` extra) |
| Crop / Rotate / Flip / Pad | ✅ | ✅ | `--crop 800x600+0+0`, `--rotate 90`, `--flip h`, `--pad 16:9` |
| Print size | — | ✅ | `--print-size 8x10@300dpi` center-crop + exact print pixels |
| Smart rename | ✅ | ✅ | `{date}_{camera}_{seq}` templates |
| Auto folder organize | ✅ | ✅ | `--organize date-camera` subfolder creation |
| Watermark | ✅ | ✅ | Text + image overlay, 7 positions |
| Multi-size output | ✅ | ✅ | `--sizes thumb:480x,screen:1920x` |
| Metadata tagging | — | ✅ | `exif --rating` / `--keywords` / `--caption` batch tag (UserComment) |
| Metadata filter | — | ✅ | `exif --show --rating-min 3 --keywords beach` find tagged photos |
| Metadata import | — | ✅ | `exif --from-csv meta.csv` batch write from spreadsheet |
| Culling | — | ✅ | `photo-s cull` exposure/sharpness filter |
| Burst keep-sharpest | — | ✅ | `dedup --action keep-sharpest` pick the sharpest of a burst |
| Checksum manifest | — | ✅ | `photo-s hash` SHA-256 archive integrity + `--verify` |
| HTML gallery | — | ✅ | `photo-s gallery` self-contained index.html + thumbs |
| Presets | ✅ | ✅ | Save/load named configs |
| Multi-profile batch | — | ✅ | `--profiles web,thumb` one input set, N outputs |
| Parallel processing | ✅ | ✅ | `-j 8` multi-threaded |
| JSON output | — | ✅ | `--json` for AI agent consumption |
| Config file | — | ✅ | `photo-s.toml` defaults (`config init/show`) |
| EXIF edit | — | ✅ | `photo-s exif *.jpg --artist "Me"` |
| EXIF date shift | — | ✅ | `--date-shift "-5h30m"` timezone/camera clock fixes |
| Privacy scrub | — | ✅ | `--scrub` strips EXIF+ICC+GPS |
| Sync date | — | ✅ | `--sync-date` output mtime ← EXIF datetime |
| Folder watch | — | ✅ | `photo-s watch ~/incoming/` auto-process |
| Auto-rotate | ✅ | ✅ | EXIF Orientation-based |
| Image dedup | ✅ | ✅ | Perceptual hash duplicate detection |
| Quality metrics | ✅ | ✅ | `--evaluate` SSIM + `--blur-score` |
| CSV report | — | ✅ | `--report out.csv` per-file stats |
| Integrity check | — | ✅ | `photo-s check` corrupt file scan |
| Contact sheet | — | ✅ | `photo-s contact-sheet *.jpg -o sheet.png` |
| Color management | — | ✅ | `--srgb` / `--flatten-cmyk` |
| REST API | — | ✅ | `photo-s serve` for AI agents |
| Plugin system | — | ✅ | Third-party plugin support |
| Official plugin manager | — | ✅ | `photo-s plugin list/install/info/fetch` + `pip install photo-s-plugin-scunet` |

> ¹ 降噪 / 自动扶正需要可选依赖：`pip install photo-s[enhance]`（opencv-python-headless）。
> 未安装时这两个功能会给出明确的安装提示，不影响其余功能。

---

## 📦 Installation

### pip install (recommended)

```bash
pip install photo-s

# With optional features
pip install photo-s[all]       # everything
pip install photo-s[heic]      # HEIC support
pip install photo-s[avif]      # AVIF support
pip install photo-s[raw]       # RAW processing
pip install photo-s[watch]     # folder watching
pip install photo-s[exif]      # EXIF editing
pip install photo-s[enhance]   # NLM denoise + auto-straighten (opencv)
```

### From source

```bash
git clone https://github.com/yourname/photo-s.git
cd photo-s
pip install -e .
```

---

## ⌨️ CLI Usage

```bash
photo-s --help                  # Show all commands
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

### 摄影师工作流示例

```bash
# 筛选：找出过曝/欠曝的照片
photo-s cull ~/shoot/ -r --overexposed-max 2% --underexposed-max 2% --list

# 打标 + 按打标筛选（核心工作流）
photo-s exif ~/shoot/ -r --rating 4 --keywords "keep,beach"   # 批量打标
photo-s exif ~/shoot/ -r --show --rating-min 4 --list         # 筛出 ≥4 星
photo-s exif ~/shoot/ -r --show --keywords beach --json        # 关键词筛选
photo-s exif --from-csv meta.csv                               # 从表格批量写元数据
photo-s batch $(photo-s exif ~/shoot/ -r --show --rating-min 4 --list) -o /deliver/

# 归档：生成 + 校验 SHA-256 清单
photo-s hash ~/archive/ -r -o manifest.csv
photo-s hash --verify manifest.csv

# 连拍选图：每组保留最清晰
photo-s dedup ~/burst/ --action keep-sharpest --dry-run

# 交付：HTML 画廊 / 打印尺寸 / 白平衡
photo-s gallery ~/shoot/ -o gallery/ --title "2026 川西"
photo-s batch ~/shoot/ --print-size 8x10@300dpi
photo-s batch ~/shoot/ --wb 5600 --auto-levels

# 全局校正：曝光 / LOG 还原 / 降噪 / 扶正
photo-s batch ~/shoot/ --ev +0.5 --auto-exposure 0.45
photo-s batch ~/log/    --log-curve SLOG3 --wb 5600        # LOG 片还原
photo-s batch ~/highiso/ --denoise 12 --ev -0.3            # 高ISO降噪
photo-s batch ~/tilted/ --auto-straighten --max-straighten-angle 8
```

### Common Examples

```bash
# Compress to ~5MB with auto-tune, 8 threads, JSON output (AI agent)
photo-s compress *.jpg --target-size 5MB -j 8 --json

# Convert to AVIF with parallel workers
photo-s convert *.jpg -f AVIF -q 60 -j 4

# Organize by date+camera, add watermark
photo-s batch ~/photos/ --organize date-camera --watermark-text "© Me" -j 4

# Smart rename with EXIF metadata
photo-s compress *.jpg --rename "{date}_{camera}_{seq}"

# Find duplicate images
photo-s dedup ~/photos/ --action report
```

### JSON Output (for AI agents)

`--json` 输出纯净 JSON 到 stdout（进度/诊断走 stderr），所有面向 agent 的子命令都支持：
`compress`/`batch`/`convert`（批处理结果）、`check`/`dedup`（检查报告）、
`rename`（重命名结果）、`contact-sheet`、`info`（格式清单）、`--dry-run`（预览配置）。

```json
{
  "summary": {"total": 5, "success": 5, "failed": 0, "saved_bytes": 27262976, "saved_percent": 52.0},
  "results": [{"input": "photo.jpg", "output": "photo_compressed.jpg", "input_size": 10485760, "output_size": 5242880, "format": "JPEG", "dimensions": [6000, 4000], "quality": 78, "status": "ok"}]
}
```

Use with any AI agent: `photo-s compress *.jpg --json --target-size 5MB | your-agent`

> 退出码约定：批处理/重命名/检查失败 → `1`；`dedup` **发现重复 → `1`**（无重复 → `0`），
> agent 可据此分支。`--json` 模式下 `--remove-original` / `dedup --action move|delete`
> 跳过交互确认（agent 显式请求即视为确认），不会因无 stdin 而挂起。

---

## 🖥 GUI Usage

```bash
photo-s          # Launch GUI (no args = GUI)
photo-s gui      # Explicit GUI mode
```

GUI features: Chinese/English language switch, drag-and-drop (needs `pip install photo-s[gui]`),
cancellable batch processing, before/after comparison, and an About dialog.

> 面向开发/Agent 的 GUI 变更与接口文档：[`docs/GUI_CHANGES.md`](docs/GUI_CHANGES.md)

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
photo-s compress *.jpg           # 插件自动生效 plugins auto-apply
```

### Official plugins (官方可选插件)

PhotoS 维护的官方插件是独立 PyPI 发行版 `photo-s-plugin-<name>`，安装双通道
（插件管理器或 pip）。首个官方插件是 **SCUNet 强降噪**——比内置 NLM 更强的高 ISO
降噪，安装后 `--denoise N` 自动优先使用它（否则回退 NLM）：

```bash
# 通道一：插件管理器（agent 友好，--json）
photo-s plugin list
photo-s plugin install scunet --json
photo-s plugin fetch scunet          # 预下载 ONNX 权重（~10-40MB，sha256 校验）
photo-s plugin info scunet

# 通道二：传统 pip
pip install photo-s-plugin-scunet

# 使用（有 scunet 插件时自动走 SCUNet，否则 NLM）
photo-s batch ~/highiso/ --denoise 12
```

> 模型权重**不进 wheel**：首次使用时从 GitHub Releases 下载到
> `~/.cache/photo-s/models/`（`$PHOTOS_CACHE_DIR` 可覆盖），带 sha256 校验。
> 其他官方插件同样遵循"独立发行版 + 权重外置"模式。

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

See [docs/PLUGINS.md](docs/PLUGINS.md) for full API documentation.

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
| RAW (22+ formats) | ✅ | — | via `rawpy` (libraw) |

---

## ✏️ 命名约定 Naming Convention

| 上下文 | 写法 | 说明 |
|---|---|---|
| Python 包 / import | `photo_s` | 语法强制：`import photo-s` 非法，包名用下划线 |
| CLI 命令 / PyPI 发行名 | `photo-s` | shell 惯例：`pip install photo-s`、`photo-s compress ...` |
| UI 标题 / 品牌 / 文档标题 | `PhotoS` | 人类可读品牌名 |

同上下文内禁止混用（例如代码示例写 `photo_s compress`、UI 文案写 `photo-s` 都是错的）。
这是 Python 生态标准模式（scikit-learn→sklearn、Pillow→PIL 同理），请勿"统一"。

---

## 🤖 Agent / 应用集成（供其他软件调用）

> 完整对接契约（CLI JSON shape、退出码、serve 端点、异步任务、配置文件优先级）见
> [`docs/AGENT_API.md`](docs/AGENT_API.md) —— agent 对接只看这一份。

PhotoS 提供三种集成方式，按推荐程度排序：

### 1. Python 库直调（推荐 — 宿主是 Python）

```python
from photo_s.engine import ProcessOptions, batch_process

options = ProcessOptions(
    output_dir="compressed/",
    quality=70,
    max_pixels=8000,
    strip_gps=True,          # 隐私
    evaluate=True,           # SSIM
)
result = batch_process(["/path/a.jpg", "/path/b.jpg"], options, jobs=4)
for r in result.results:
    print(r.output_path, r.ssim)
```

无 IPC 开销；打包时把 `photo_s` 包放进应用即可。

### 2. REST API（`photo-s serve` — 非 Python 宿主 / 跨进程）

```bash
photo-s serve --port 0 --token auto --ready-file ./photo-s.ready.json
```

- `--port 0` = 随机空闲端口；`--token auto` = 自动生成随机 token；
  `--ready-file` 在监听成功后原子写入 `{"port", "token", "pid"}` ——
  **宿主 agent 轮询该文件**（而非解析 stdout，Windows 下更稳），然后：
  `GET /health` 就绪探测 → `POST /process` `{"paths": [...], "options": {...}}`
  → 拿 BatchResult JSON（含 ssim / blur_score）。

**长批处理 / 进度 / 取消**（`POST /process` 带 `"async": true`）：

```bash
# 1. 提交异步任务
curl -X POST .../process -H "Authorization: Bearer $TOKEN" \
     -d '{"paths": ["/photos/*.jpg"], "async": true}'
# → 202 {"task_id": "...", "poll": "/tasks/<id>", ...}

# 2. 轮询进度/结果
curl .../tasks/<id>
# → {"status": "running|done|cancelled|error", "current": N, "total": M,
#     "current_path": "...", "result": {BatchResult JSON when done}}

# 3. 取消（进行中的图片完成后停止排队的）
curl -X POST .../tasks/<id>/cancel
```

`POST /process` 另支持 `"dry_run": true`（返回将处理的 paths/options，不处理）与
`options.output_sizes`（多尺寸，`[["thumb",480,None], ...]`）和 `options.pad`（= `pad_ratio`）。
- Windows 无环境变量：用 PyInstaller 把 photo-s 打成 `photo-s.exe`，
  宿主用绝对路径拉起子进程，不依赖 PATH。
- 进程生命周期由宿主管理（退出时 terminate 子进程）。

### 3. CLI 子进程（一次性脚本 / CI）

`photo-s compress a.jpg -q 80 --json` → stdout JSON。每次调用有 Python
解释器启动开销（~200-300ms），高频批量场景不推荐。

### Windows 打包（无 Python/PATH 环境）

```bash
pip install pyinstaller piexif pillow-heif   # 可选特性一起打包
python packaging/build.py                    # → dist/photo-s/photo-s.exe
python packaging/build.py --onefile          # 或单个 exe（启动稍慢）
```

宿主用**绝对路径**拉起，不依赖任何环境变量（见上面的 spawn 模式）。
CI 已配置 `windows-latest` 构建产物（.github/workflows/ci.yml）。

---

## 🧪 Development

```bash
pip install -e ".[dev]"
python -m pytest tests/ -v
```

---

## 📄 License

MIT
