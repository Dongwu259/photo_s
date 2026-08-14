# PhotoS — 项目约定（Claude Code 工作指引）

批量照片处理工具箱：CLI + Tkinter GUI + REST API + 插件系统。定位 "CLI for AI agents, GUI for humans"。

## 命名约定（禁止"统一"）

| 上下文 | 写法 |
|---|---|
| Python 包 / import | `photo_s`（语法强制，import 不能有连字符） |
| CLI 命令 | `photo-s`（pyproject `[project.scripts]` 入口） |
| PyPI 发行名 | `photo-s-tools`（`photo-s` 被 PyPI 拦截：与已有 `photos` 包太相似） |
| UI / 品牌 / 文档标题 | `PhotoS` |

同一上下文内不得混用。README 有详细说明。

## 架构速览

- `engine.py` — `ProcessOptions` dataclass + `process_image` + `batch_process`（核心）
- `cli.py` — argparse，子命令：compress/convert/batch/exif/preset/watch/dedup/info/rename/config/serve/mcp/check/contact-sheet/cull/hash/gallery/bench/plugin（含 plugin scaffold）
- `gui.py` — Tkinter，双语（STRINGS zh/en），设置面板可滚动 canvas；工作流对话框：审查打分灯箱（`_review_scan`/`_review_save` 同步 helper，EXIF 部分更新）、去重查看器（`_dedup_scan`/`_dedup_move_to_trash` 同步 helper，移入 `_duplicates_trash` 不删除）、画廊导出（`_gallery_build`）、可滚动摘要对话框、「更多工具」菜单（`_show_watch` 目录监视 / `_show_contact_sheet` / `_show_cull` / `_show_hash` / `_show_presets`，Tk-free seam：`_cull_scan`/`_contact_sheet_build`/`_hash_generate`/`_hash_verify`/`_apply_options_to_ui`）、**视觉预览**（`_preview`：真实管线渲染到临时目录，`_preview_options` 强制 `remove_original=False`，签名防抖自动刷新，root-drain 清理 tempdir）。**线程约定**：worker 只 `queue.put`，UI 更新走主线程 after-drain 循环（跨线程 `win.after` 会在非主循环下炸）
- 其他模块：adjust（调色/构图/白平衡/曝光/自动色阶）、logcurve（LOG 还原 1D LUT，纯 math）、denoise（NLM，可选 opencv）、straighten（扶正，可选 opencv）、metrics（SSIM/blur/曝光统计）、rename、dedup（含 keep-sharpest）、watcher（`start_watching` 支持 `stop_event`，GUI 可停止）、**cull（曝光/清晰度筛选，CLI/GUI/REST 共享）**、presets、plugin（插件发现 + find_provider）、plugincmd（`plugin` 子命令：install/list/info/fetch，shell 到 pip）、registry（官方插件目录）、modelstore（权重下载/校验/缓存，仅 stdlib）、hooks（PhotoSPlugin 接口：过滤器钩子 + operation provider）、config（TOML）、server（stdlib HTTP）、contact（联系表）、check（完整性/校验和清单 + collect_files）、gallery（HTML 画廊）、lut（.cube 3D/1D LUT 解析 + numpy 三线性，`LutError`）、envinfo（环境探测，info/MCP/GUI 三处共享）、mcp_server（MCP server，11 工具：process/info/exif/dedup/cull/hash/plugin/contact_sheet/gallery/watermark/preset；**模块级零 mcp import**——mcp SDK 要求 py3.10+，惰性导入 + CLI 版本检查双防护）
- **rawpy 是核心依赖**（RAW 解码对照片工具是刚需，三平台有 wheel）；其余可选：`enhance = opencv-python-headless`（denoise + straighten，可选）。这些模块**懒加载** cv2，缺失时抛 "pip install 'photo-s-tools[enhance]'" 的 RuntimeError → process_image 记为 per-file 错误。
- 官方可选插件：独立 PyPI 发行版 `photo-s-plugin-<name>`（源码在 `plugins/<name>/`，不进核心 wheel）；模型权重外置（scunet 首次使用经 `modelstore.ensure` 下载到缓存 + sha256 校验；**lut 纯 numpy 无权重**）。安装双通道：`photo-s plugin install <name>` 或 `pip install photo-s-plugin-<name>`。开发脚手架：`photo-s plugin scaffold <name>`（生成 pyproject + PhotoSPlugin 桩）。
- **Operation provider**：`PhotoSPlugin.provides = ("denoise"|"lut",)` + 同名方法（如 `denoise(img, strength, ctx)` / `lut(img, lut_path, ctx)`）。`provides` 非空的插件**被排除**在通用 pre/post 钩子之外，只在管线槽位被调用（引擎 `find_provider` 查找；`--denoise` 有 provider 时优先否则回退 NLM；`--lut` 有 provider 时优先否则回退 `photo_s.lut` 三线性）。provider 异常按 per-file 错误传播，不静默吞。
- 元数据打标：`rating`/`keywords`/`title` 打包进 EXIF UserComment 的 `PhotoS:` 段（`apply_exif_tags`/`read_exif_metadata`），其余字段写标准 EXIF tag

## 关键不变量（改动必须遵守）

1. **`ProcessOptions` 拷贝统一走 `dataclasses.replace`**（engine.py 三处，新字段自动随 dataclass 定义传播，无需手动同步）：
   - Site A `batch_process` 每文件拷贝：`replace(options, jobs=1)` + 设 `_seq_counter`
   - Site B `save_options_base`（process_image 内）：`replace(options, quality=achieved_quality)` + 手设 `_gpx_pos`（`_save_image` 只读保存期字段：scrub/date_shift/strip_gps/gpx_pos 等）
   - Site C `_compress_to_temp` trial_opts：`replace(options, quality=quality, output_format=fmt)`（目标体积试存）
   - **注意**：`_gpx_pos` 是动态属性（非 dataclass 字段），`replace()` 不携带，需要时手动补。
   - server 侧 JSON options 字段组由 `_scalar_groups()` 从注解动态派生（非手写白名单）。
2. **管线顺序**（process_image）：open → 插件 pre_process → auto_rotate → **auto_straighten(扶正, 可选opencv) → log_curve(LOG还原)** → 色彩管理 → 影调(brightness/contrast/saturation/gamma/sharpen/grayscale/sepia) → **LUT(lut_file: plugin provider 优先，否则 photo_s.lut 三线性) → 白平衡(wb_temp/wb_reference) → 曝光(ev/auto_exposure) → denoise(SCUNet provider 优先，否则可选opencv NLM) → 自动色阶(auto_levels)** → crop/rotate/flip → resize → pad → **打印尺寸(print_size)** → `output_dims` 捕获 → watermark → save
   - provider 槽位（denoise/lut）：`find_provider("denoise")` 命中 → `provider.denoise(img, strength, ctx)`（ctx 在管线内已有）；否则 `photo_s.denoise.apply_denoise`。`lut` 同理（`provider.lut(img, lut_path, ctx)` / `photo_s.lut.apply_lut`）。测试必须**对插件环境 hermetic**（monkeypatch `photo_s.plugin.discover_plugins` 隔离开发机已装插件）。
3. **CLI 可配置参数用 `default=argparse.SUPPRESS`**：config 层靠 `hasattr(parsed, attr)` 判断"显式传参"（默认值比较会误判 `-q 85` 这类情况）。共享 options 构建块用 `getattr(parsed, attr, 默认)` 接线。
4. **GUI 新 tk.Variable 必须放 `__init__`**（`_set_language` 销毁重建控件，状态只存活在变量里）。设置面板新区块：`_add_section_label(row=N)` + 内容帧 `row=N+2`，行号从 24 起。
5. **STRINGS zh/en key 集合必须完全一致**（`_t` 缺 key 静默回退，会造成"看起来能用"的漏译）。
6. GUI 禁用 `tk.Button`，用 `FlatButton`；输入/勾选类用 `ttk.*`。
7. **测试模式**：纯 assert + `tmp_path` + PIL 小图；engine 层用 `_process(src, out_dir, **kwargs)` 助手（tests/test_features.py）；可配置项测试参照 `_apply_config_defaults` 的 hasattr 语义。
8. **PIL 解压炸弹阈值**：`photo_s/__init__.py` 把 `Image.MAX_IMAGE_PIXELS` 设为有界值 `512_000_000`（警告 >512MP、硬报错 >1024MP）——合法大图（如 112MP）不再误报 DecompressionBombWarning，真炸弹仍被拦。只设一次不切换（线程安全），改阈值需同步 tests/test_pil_limit.py。

## 常用命令

```bash
python3 -m pytest tests/ -q      # 全量测试（当前 645 个）
python3 -m photo_s.cli --help    # CLI 冒烟（无 PATH 依赖）
python3 -m photo_s.cli plugin list --json   # 官方插件目录 + 已装状态
python3 -m photo_s.cli mcp --list-tools     # MCP 工具 + schema（需 photo-s-tools[mcp]，py3.10+）
```

## 集成方式（用户 agent 产品）

- 宿主是 Python → 直接 `from photo_s.engine import batch_process`（推荐）
- 非 Python / 跨进程 → `photo-s serve --port 0 --token auto --ready-file x.json`，轮询握手文件拿 `{port, token}` 后走 HTTP
- 一次性脚本 → CLI + `--json`
