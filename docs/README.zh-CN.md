# 📷 PhotoS — 批量图片压缩与格式转换工具

[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Windows%20%7C%20Linux-lightgrey)](https://github.com)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-521%20passed-brightgreen)]()
[![PyPI](https://img.shields.io/badge/pypi-photo--s--tools-orange)](https://pypi.org/project/photo-s-tools/)

**PhotoS** 是一款跨平台批量图片处理工具，同时提供 **GUI 和 CLI**。为需要按指定尺寸交付图片的摄影师，
以及需要可靠图片处理管线的 AI agent 而设计。

> 🖥 **GUI** 给人用 — ⌨️ **CLI** 给 AI agent 用 — `pip install photo-s-tools`

> ✍️ **核心开发者：** deepseek-v4-flash · GLM-5.2

[English](../README.md) · **中文**

---

## ✨ 功能特性

| 功能 | GUI | CLI | 说明 |
|---|---|---|---|
| 批量压缩 | ✅ | ✅ | JPEG/WebP/HEIC/AVIF 质量调优 |
| 目标体积模式 | ✅ | ✅ | 自动调优质量以控制在目标文件体积以内 |
| 格式转换 | ✅ | ✅ | JPEG / PNG / WebP / TIFF / BMP / HEIC / AVIF |
| RAW 解码 | ✅ | ✅ | 22+ 种相机 RAW 格式，内置支持（rawpy/libraw） |
| 缩放 / 比例 | ✅ | ✅ | 最大尺寸、百分比或最长边上限 |
| 视觉预览 | ✅ | — | 原图↔处理后实时并排预览（经真实管线渲染） |
| 影调与色彩 | ✅ | ✅ | 亮度/对比度/饱和度/伽马/锐化，黑白、复古 |
| 白平衡 | ✅ | ✅ | `--wb 5600` 色温，或 `--wb-from ref.jpg` 采样灰卡 |
| 曝光 | ✅ | ✅ | `--ev +1` 档，或 `--auto-exposure 0.45` 归一化到目标 |
| 自动色阶 | ✅ | ✅ | `--auto-levels` 2% 裁切直方图拉伸 |
| LOG 还原 | ✅ | ✅ | `--log-curve SLOG3/CLOG3/LOGC3/DLOG/VLOG/HLG`（1D LUT，零依赖） |
| LUT 调色 | ✅ | ✅ | `--lut film.cube` 或预设名（内置三线性；`photo-s-plugin-lut` 加四面体 + 5 电影预设） |
| 降噪 | ✅ | ✅¹ | `--denoise 10` NLM（`[enhance]` 可选依赖） |
| 自动扶正 | ✅ | ✅¹ | `--auto-straighten` 校正地平线，置信度门控（`[enhance]` 可选依赖） |
| 裁剪 / 旋转 / 翻转 / 留边 | ✅ | ✅ | `--crop 800x600+0+0`、`--rotate 90`、`--flip h`、`--pad 16:9` |
| 打印尺寸 | ✅ | ✅ | `--print-size 8x10@300dpi` 中心裁剪 + 精确打印像素 |
| 智能重命名 | ✅ | ✅ | `{date}_{camera}_{seq}` 模板 |
| 自动整理归档 | ✅ | ✅ | `--organize date-camera` 子文件夹归类 |
| 水印 | ✅ | ✅ | 文字 + 图片水印，7 个位置 |
| 多尺寸输出 | ✅ | ✅ | `--sizes thumb:480x,screen:1920x` |
| 元数据打标 | ✅ | ✅ | `exif --rating` / `--keywords` / `--caption` 批量打标（UserComment） |
| 元数据筛选 | ✅ | ✅ | `exif --show --rating-min 3 --keywords beach` 筛出已打标照片 |
| 元数据导入 | — | ✅ | `exif --from-csv meta.csv` 从表格批量写入 |
| 选片 | ✅ | ✅ | `photo-s cull` 曝光/清晰度筛选（GUI 仅保留符合项，可撤销） |
| 连拍选图 | ✅ | ✅ | `dedup --action keep-sharpest` 每组保留最清晰 |
| 校验和清单 | ✅ | ✅ | `photo-s hash` SHA-256 归档完整性 + `--verify` |
| HTML 画廊 | ✅ | ✅ | `photo-s gallery` 自包含 index.html + 缩略图 |
| 预设 | ✅ | ✅ | 保存/加载命名配置 |
| 多配置批量 | — | ✅ | `--profiles web,thumb` 一份输入、N 份输出 |
| 并行处理 | ✅ | ✅ | `-j 8` 多线程 |
| JSON 输出 | — | ✅ | `--json` 供 AI agent 消费 |
| 配置文件 | — | ✅ | `photo-s.toml` 默认值（`config init/show`） |
| EXIF 编辑 | — | ✅ | `photo-s exif *.jpg --artist "Me"` |
| EXIF 日期偏移 | — | ✅ | `--date-shift "-5h30m"` 时区/相机时钟修正 |
| 隐私清理 | — | ✅ | `--scrub` 移除 EXIF+ICC+GPS |
| 同步日期 | — | ✅ | `--sync-date` 输出 mtime ← EXIF 拍摄时间 |
| 文件夹监视 | ✅ | ✅ | `photo-s watch ~/incoming/` 自动处理（`[watch]` 可选依赖） |
| 自动旋转 | ✅ | ✅ | 基于 EXIF Orientation |
| 图片去重 | ✅ | ✅ | 感知哈希重复检测 |
| 质量指标 | ✅ | ✅ | `--evaluate` SSIM + `--blur-score` |
| CSV 报告 | — | ✅ | `--report out.csv` 逐文件统计 |
| 完整性检查 | — | ✅ | `photo-s check` 损坏文件扫描 |
| 联系表 | ✅ | ✅ | `photo-s contact-sheet *.jpg -o sheet.png` |
| 色彩管理 | — | ✅ | `--srgb` / `--flatten-cmyk` |
| REST API | — | ✅ | `photo-s serve` 供 AI agent 使用 |
| 插件系统 | — | ✅ | 第三方插件支持 |
| 官方插件管理 | — | ✅ | `photo-s plugin list/install/info/fetch` + `pip install photo-s-plugin-scunet` |
| MCP server | — | ✅ | `photo-s mcp` 向 MCP 客户端（Claude Desktop）暴露 11 个工具 |
| 批量基准 | — | ✅ | `photo-s bench --dir ~/shoot -j 1,2,4,8` 实测并发扩展 |

> ¹ 降噪 / 自动扶正需要可选依赖：`pip install photo-s-tools[enhance]`（opencv-python-headless）。
> 未安装时这两个功能会给出明确的安装提示，不影响其余功能。

---

## 📦 安装

### pip 安装（推荐）

```bash
pip install photo-s-tools

# 带可选特性
pip install photo-s-tools[all]       # 全部
pip install photo-s-tools[heic]      # HEIC 支持
pip install photo-s-tools[avif]      # AVIF 支持
pip install photo-s-tools[watch]     # 文件夹监视
pip install photo-s-tools[exif]      # EXIF 编辑
pip install photo-s-tools[enhance]   # NLM 降噪 + 自动扶正（opencv）
pip install photo-s-tools[mcp]       # MCP server（需要 Python 3.10+）
```

### 源码安装

```bash
git clone https://github.com/Dongwu259/photo_s.git
cd photo_s
pip install -e .
```

---

## ⌨️ CLI 用法

```bash
photo-s --help                  # 显示全部命令
photo-s compress *.jpg -q 80    # 批量压缩
photo-s convert *.png -f webp   # 格式转换
photo-s batch ~/photos/ -r      # 递归批量处理
photo-s exif *.jpg --artist "Me" # 编辑 EXIF
photo-s preset save web -q 70   # 保存预设
photo-s preset list             # 列出预设
photo-s watch ~/incoming/       # 自动处理新文件
photo-s dedup ~/photos/         # 查找重复
photo-s info                    # 支持的格式
photo-s --version               # 显示版本号
```

### 摄影师工作流示例

```bash
# 选片：找出过曝/欠曝的照片
photo-s cull ~/shoot/ -r --overexposed-max 2% --underexposed-max 2% --list

# 打标 + 按打标筛选（核心工作流）
photo-s exif ~/shoot/ -r --rating 4 --keywords "keep,beach"   # 批量打标
photo-s exif ~/shoot/ -r --show --rating-min 4 --list         # 筛出 ≥4 星路径
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

### 常见示例

```bash
# 压缩到 ~5MB 自动调优，8 线程，JSON 输出（AI agent）
photo-s compress *.jpg --target-size 5MB -j 8 --json

# 并行转换为 AVIF
photo-s convert *.jpg -f AVIF -q 60 -j 4

# 按日期+相机归档并加水印
photo-s batch ~/photos/ --organize date-camera --watermark-text "© Me" -j 4

# 用 EXIF 元数据智能重命名
photo-s compress *.jpg --rename "{date}_{camera}_{seq}"

# 查找重复图片
photo-s dedup ~/photos/ --action report
```

### JSON 输出（供 AI agent）

`--json` 输出纯净 JSON 到 stdout（进度/诊断走 stderr）。所有面向 agent 的子命令都支持：
`compress`/`batch`/`convert`（批处理结果）、`check`/`dedup`（检查报告）、`rename`、
`contact-sheet`、`info`，以及 `--dry-run`（配置预览）。

```json
{
  "summary": {"total": 5, "success": 5, "failed": 0, "saved_bytes": 27262976, "saved_percent": 52.0},
  "results": [{"input": "photo.jpg", "output": "photo_compressed.jpg", "input_size": 10485760, "output_size": 5242880, "format": "JPEG", "dimensions": [6000, 4000], "quality": 78, "status": "ok"}]
}
```

配合任何 AI agent 使用：`photo-s compress *.jpg --json --target-size 5MB | your-agent`

> 退出码约定：批处理/重命名/检查失败 → `1`；`dedup` **发现重复 → `1`**（无重复 → `0`），
> agent 可据此分支。`--json` 模式下 `--remove-original` / `dedup --action move|delete`
> 跳过交互确认（agent 显式请求即视为确认）。

---

## 🖥 GUI 用法

```bash
photo-s          # 启动 GUI（无参数 = GUI）
photo-s gui      # 显式 GUI 模式
```

GUI 特性：中英文切换、拖放（需要 `pip install photo-s-tools[gui]`）、可取消的批量处理、
前后对比、全局快捷键（⌘/Ctrl+O 添加、⌘/Ctrl+R 开始、Esc 取消、⌘/Ctrl+E 审查、⌘/Ctrl+D 去重、⌘/Ctrl+G 画廊、⌘/Ctrl+Z 撤销）、**勾选式文件列表**（每行一个与设置面板同款的勾选框；处理/审查/去重/画廊全部作用于
勾选文件；添加文件夹自动递归扫描子文件夹；工具栏「全选/全不选」批量切换）、
**视觉预览**（⌘/Ctrl+P：原图↔处理后并排实时渲染，设置变化自动刷新）、
**审查打分灯箱**（←/→ 导航、0-5 星、关键词/标题、按评分与关键词过滤——直接写 EXIF）、
**去重查看器**（分组并排对比 + 清晰度评分，勾选保留，移入回收子文件夹而非删除）、
**HTML 画廊导出**、工具栏「更多工具」菜单（**目录监视** / **联系表** / **曝光筛选** / **校验和清单** / **预设管理**）。
打标后的照片可在 CLI 中按标签筛选（`photo-s exif --rating-min 4 --list`）
或交给 AI agent 使用。

> GUI 变更与接口契约：见 [`docs/GUI_CHANGES.md`](GUI_CHANGES.md)

### 截图

<!-- TODO: 补充截图 -->
- 主窗口：文件列表 + 设置面板
- 处理进度条与汇总对话框
- 前后对比视图

---

## 🎯 目标体积模式

独特功能：设定目标文件体积，PhotoS 通过二分搜索自动调优 JPEG/WebP/AVIF 质量。

```bash
photo-s compress *.jpg --target-size 5MB
# 自动在质量 ∈ [5, 85] 内二分，使每个输出 ≤ 5MB
```

---

## 🔌 插件系统

第三方插件通过 Python `entry_points` 扩展 PhotoS。

```bash
pip install photo-s-plugin-s3    # 示例：自动上传到 S3
photo-s compress *.jpg           # 插件自动生效
```

### 官方可选插件

官方插件是独立的 PyPI 发行版 `photo-s-plugin-<name>`，安装双通道（插件管理器或 pip）。
首个官方插件是 **SCUNet 强降噪**——比内置 NLM 更强的高 ISO 降噪。安装后
`--denoise N` 自动优先使用它（否则回退 NLM）：

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

> 模型权重**不进 wheel**：首次使用时从网络下载到 `~/.cache/photo-s/models/`
> （`$PHOTOS_CACHE_DIR` 可覆盖），带 sha256 校验。
> 所有官方插件遵循"独立发行版 + 权重外置"模式。

### 编写插件

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

完整 API 见 [docs/PLUGINS.md](PLUGINS.md)，包括 operation provider（如 `denoise` 槽位提供者）
与模型权重处理。

---

## 📋 支持的格式

| 格式 | 读 | 写 | 说明 |
|---|---|---|---|
| JPEG | ✅ | ✅ | 质量、渐进式、EXIF |
| PNG | ✅ | ✅ | 优化 |
| WebP | ✅ | ✅ | 质量 |
| AVIF | ✅ | ✅ | 质量（需要 `pillow-avif-plugin`） |
| HEIC | ✅ | ✅ | 需要 `pillow-heif` |
| TIFF | ✅ | ✅ | LZW 压缩 |
| BMP | ✅ | ✅ | |
| ICO | ✅ | ✅ | |
| RAW（22+ 格式） | ✅ | — | 内置支持（`rawpy`/libraw） |

---

## ✏️ 命名约定

| 上下文 | 写法 | 说明 |
|---|---|---|
| Python 包 / import | `photo_s` | 语法强制：`import photo-s` 非法 |
| CLI 命令 | `photo-s` | shell 惯例：`photo-s compress *.jpg` |
| PyPI 发行名 | `photo-s-tools` | `pip install photo-s-tools`（原名 `photo-s` 被 PyPI 拦截：与已有 `photos` 包太相似） |
| UI 标题 / 品牌 / 文档标题 | `PhotoS` | 人类可读品牌名 |

同一上下文内禁止混用（例如代码示例写 `photo_s compress`、UI 文案写 `photo-s` 都是错的）。
这是 Python 生态标准模式（scikit-learn→sklearn、Pillow→PIL 同理），请勿"统一"。

---

## 🤖 Agent / 应用集成

> 完整对接契约（CLI JSON shape、退出码、serve 端点、异步任务、配置文件优先级）见
> [`docs/AGENT_API.md`](AGENT_API.md) —— agent 对接只看这一份。

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
- Windows 无 Python 环境：用 PyInstaller 打包成 `photo-s.exe`（见下），
  宿主用绝对路径拉起，不依赖 PATH。
- 进程生命周期由宿主管理（退出时 terminate 子进程）。

### 3. CLI 子进程（一次性脚本 / CI）

`photo-s compress a.jpg -q 80 --json` → stdout JSON。每次调用有 Python
解释器启动开销（~200-300ms），高频批量场景不推荐。

### 4. MCP server（Claude Desktop 与 MCP 客户端）

[Model Context Protocol](https://modelcontextprotocol.io) 服务器——让 Claude
Desktop / 任意 MCP 客户端直接调用 PhotoS 工具（需要 Python 3.10+ 与可选依赖）：

```bash
pip install "photo-s-tools[mcp]"
photo-s mcp --list-tools        # 查看 7 个工具及参数 schema（JSON）
photo-s mcp                     # 启动 stdio MCP server
```

工具：`process`（批量质量/格式/缩放/影调/降噪）、`info`（环境探测）、
`exif`（元数据读写/筛选）、`dedup`（感知哈希分组、keep-sharpest）、
`cull`（曝光/清晰度筛选）、`hash`（SHA-256 清单）、`plugin`（官方插件管理）。
输出结构与 CLI `--json` 契约一致。

Claude Desktop 配置（`claude_desktop_config.json`）：

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

> 破坏性安全：`dedup` 的 `keep-sharpest` 默认 `dry_run=True`（删除需显式
> `dry_run=False`）；`process` 不覆盖输入文件。

### Windows 打包（无 Python/PATH 环境）

```bash
pip install pyinstaller piexif pillow-heif   # 可选特性一起打包
python packaging/build.py                    # → dist/photo-s/photo-s.exe
```

宿主用**绝对路径**拉起，不依赖任何环境变量（见上面的 spawn 模式）。
CI 已配置 `windows-latest` 构建产物（`.github/workflows/ci.yml`）。

---

## 🧪 开发

```bash
pip install -e ".[dev]"
python -m pytest tests/ -v
```

---

## 📄 许可证

MIT
