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

- `engine.py` — `ProcessOptions` dataclass + `process_image` + `batch_process`（核心，含 `per_file_options(path, opts)` 钩子——GUI per-photo 蒙版经此逐文件注入，在输出路径预分配前调用）
- `cli.py` — argparse，子命令：compress/convert/batch/exif/preset/watch/dedup/info/rename/config/serve/mcp/check/contact-sheet/cull/select/hdr/blurfaces/hash/gallery/bench/plugin（含 plugin scaffold）/analyze/lr-scan/lr-train/lr-predict/lr-recipes/lr-similar/lr-eval/lr-merge/diff/audit/preview；`--language {en,zh,auto}` 全局 flag（`_pre_parse_language` 两段式解析：先 resolve 语言再建 parser，argparse 构造时定死 help 文本）
- `contract.py` — JSON 输出契约：`SCHEMA_VERSION = 1` + `versioned(payload)`（加性顶层键 `schema_version`，非信封）；CLI `--json`/REST `_send_json`/MCP 工具三处复用，零项目 import
- `i18n.py` — 国际化共享模块：`detect_system_language()`（三平台：env LANG/LC_ALL → macOS `defaults read -g AppleLanguages` → Windows `GetUserDefaultUILanguage` LCID → `locale.getlocale()`，每级 try/except 永不崩，`_system_language()` 记忆化）；`resolve_language()` 优先级 **flag > `PHOTO_S_LANG` env > config `language` > persisted(GUI) > 系统检测 > "en"**；`CURRENT_LANG` 模块变量 + `_t(key, lang, **kwargs)`（.format 只允许命名占位符）；CLI `STRINGS` 表（zh/en parity 测试强制）；GUI 持久化 `~/.photos/language`。**注意：检测层绝不调 `locale.setlocale`**（进程级副作用会污染后续 `open()` 默认编码）
- `gui.py` — Tkinter，双语（STRINGS zh/en），启动语言 `resolve_language(use_persisted=True)`（持久化 > env > 系统），`_on_language_selected` 持久化用户选择；设置面板可滚动 canvas；工作流对话框：审查打分灯箱（`_review_scan`/`_review_save` 同步 helper，EXIF 部分更新，评审后可按评分一键移动精选/淘汰：`_select_move` seam + 对话框 select 行）、去重查看器（`_dedup_scan`/`_dedup_move_to_trash` 同步 helper，移入 `_duplicates_trash` 不删除）、画廊导出（`_gallery_build`）、可滚动摘要对话框、「更多工具」菜单（`_show_watch` 目录监视 / `_show_contact_sheet` / `_show_cull` / `_show_hash` / `_show_hdr` HDR 合并 / `_show_presets`，Tk-free seam：`_cull_scan`/`_contact_sheet_build`/`_hash_generate`/`_hash_verify`/`_hdr_merge`/`_select_move`/`_apply_options_to_ui`）、**视觉预览**（`_preview`：真实管线渲染到临时目录，`_preview_options` 强制 `remove_original=False`，签名防抖自动刷新，root-drain 清理 tempdir）。**线程约定**：worker 只 `queue.put`，UI 更新走主线程 after-drain 循环（跨线程 `win.after` 会在非主循环下炸）
- 其他模块：adjust（调色/构图/白平衡/曝光/自动色阶）、**grade（v1.6.0 LR 方向调色：点曲线 PCHIP/手动色阶/自然饱和度/三向颜色分级/WB tint/HSL 分色/清晰度·纹理/去雾/暗角/颗粒，纯 numpy+PIL 零依赖，紧凑字符串建模 → REST/preset 零胶水）**、**mask（v1.8.0 命名蒙版：linear/radial/color 相对坐标 0-1 + AI 分割（subject/person/object:label → segmask，cv2.dnn 惰性）+ 笔刷（brush:x,y,r|x,y,r 点间胶囊并集）+ 组合算子（combo:A&B / combo:A-B，引用已命名蒙版并替换，render_mask 需传 refs）+ mask_adjust 蒙版内调整（11 项标量 + curves/hsl/color_grading/vignette/grain 复杂字符串 `{}` 包裹复用 grade.py），MaskError 清晰报错）、segmask（v1.8.0：U2Netp 4.6MB subject / PP-HumanSeg 6.2MB person / YOLOv8n-seg fp16 7MB object:label COCO 80 类，ONNX 经 modelstore 下载+sha256 校验，纯 numpy YOLO mask 解码+NMS，OpenCV 5.x 新引擎 forward 失败自动回退经典引擎，缺 cv2/权重抛清晰 RuntimeError 不静默；发布时三个 onnx 上传 GitHub release v1.8.0 附件）、lens（v1.7.0 手动镜头矫正：畸变 k1/去暗角/消 CA，纯 numpy 双线性重映射，LensError）**、**lrxmp（v1.9.0 阶段 1/2 LR 数据桥接：parse_xmp_sidecar / parse_develop_blob（`s = { key = value }` 明文快照）/ scan_catalog（只读 lrcat，关联链 settings→Adobe_images→AgLibraryFile→folder→root 已验证）/ crs_to_options（→ ProcessOptions）+ coverage（映射分类）/ render_before_images（rawpy 默认显影训练图）/ train_auto_tone·predict_auto_tone（岭回归 9 项全局参数纯 numpy，predict 自动识别 CLIP+MLP npz 分支——torch/open_clip 惰性导入、新旧权重转置兼容、缺依赖清晰 LrError）/ cluster_recipes（KMeans 配方库）/ similar_photos（84 维内容特征 kNN）/ prep_eval_set（教师评测集，PhotoS 自渲染 after），纯 stdlib）**、audit（出片质量闸门：pass/fail + 原因，agent 终止条件，复用 metrics）、logcurve（LOG 还原 1D LUT，纯 math）、denoise（NLM，可选 opencv）、straighten（扶正，可选 opencv）、hdr（包围曝光合并：opencv MergeMertens 曝光融合，`align` 用 AlignMTB，可选 opencv）、faceblur（人脸检测 + 模糊/马赛克，opencv Haar cascade，可选 opencv，cascade 缺失抛清晰 RuntimeError 不静默）、metrics（SSIM/PSNR/blur/曝光统计 + v1.7 analyze_image 感知分析：直方图/通道统计/色温估计 + v1.7.1 grid 区域反馈/天空肤色启发式/过曝区域框 + compare_images(diff) + snapshot_image(preview base64)，CLI/REST/MCP 三处共享）、bench（基准：输出写临时目录自动清理、_StageTimer 分段计时、--evaluate PSNR/SSIM）、rename、dedup（含 keep-sharpest）、**select（选片工作流：rating≥keep_min 移精选目录、≤reject_max 移淘汰目录、其余原地；双阈值 + move/copy + dry_run 零写入 + basename 平铺防穿越，CLI/GUI/MCP 共享）**、watcher（`start_watching` 支持 `stop_event`，GUI 可停止）、**cull（曝光/清晰度筛选，CLI/GUI/REST 共享）**、presets、plugin（插件发现 + find_provider）、plugincmd（`plugin` 子命令：install/list/info/fetch，shell 到 pip）、registry（官方插件目录）、modelstore（权重下载/校验/缓存，仅 stdlib）、hooks（PhotoSPlugin 接口：过滤器钩子 + operation provider）、config（TOML）、server（stdlib HTTP）、contact（联系表）、check（完整性/校验和清单 + collect_files）、gallery（HTML 画廊）、lut（.cube 3D/1D LUT 解析 + numpy 三线性，`LutError`）、envinfo（环境探测，info/MCP/GUI 三处共享）、mcp_server（MCP server，25 工具：process/info/exif/dedup/cull/select/hdr/blurfaces/hash/plugin/contact_sheet/gallery/watermark/preset/bench/watch/watch_status/watch_stop/analyze/batch_start/batch_status/batch_cancel/diff/audit/preview；**模块级零 mcp import**——mcp SDK 要求 py3.10+，惰性导入 + CLI 版本检查双防护）
- **rawpy 是核心依赖**（RAW 解码对照片工具是刚需，三平台有 wheel）；其余可选：`enhance = opencv-python-headless`（denoise + straighten + HDR 合并 + 人脸模糊，可选）。这些模块**懒加载** cv2，缺失时抛 "pip install 'photo-s-tools[enhance]'" 的 RuntimeError → process_image 记为 per-file 错误。
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
2. **管线顺序**（process_image）：open → 插件 pre_process → auto_rotate → **镜头矫正(lens_distort/lens_ca/lens_vignette, v1.7 几何先行) → auto_straighten(扶正, 可选opencv) → log_curve(LOG还原)** → 色彩管理 → 影调(brightness/contrast/saturation/gamma/sharpen/grayscale/sepia) → **LUT(lut_file: plugin provider 优先，否则 photo_s.lut 三线性) → 白平衡(wb_temp/wb_reference/wb_tint) → 曝光(ev/auto_exposure) → LR 调色块(levels → curves → clarity → texture → dehaze → vibrance → hsl → point_color(点颜色, v1.7 取样色中心) → color_grading，photo_s.grade 纯 numpy，紧凑字符串字段) → 局部调整(masks/mask_adjust, v1.7 mask.py 蒙版内标量)** → denoise(SCUNet provider 优先，否则可选opencv NLM) → 自动色阶(auto_levels) → **暗角/颗粒(vignette/grain)** → crop/rotate/flip → resize → pad → **打印尺寸(print_size)** → `output_dims` 捕获 → watermark → **人脸模糊(blur_faces, 可选opencv)** → EXIF 提取/保存（blur 只改像素、.info 复制，不影响 EXIF 保留）→ save
   - provider 槽位（denoise/lut）：`find_provider("denoise")` 命中 → `provider.denoise(img, strength, ctx)`（ctx 在管线内已有）；否则 `photo_s.denoise.apply_denoise`。`lut` 同理（`provider.lut(img, lut_path, ctx)` / `photo_s.lut.apply_lut`）。测试必须**对插件环境 hermetic**（monkeypatch `photo_s.plugin.discover_plugins` 隔离开发机已装插件）。
3. **CLI 可配置参数用 `default=argparse.SUPPRESS`**：config 层靠 `hasattr(parsed, attr)` 判断"显式传参"（默认值比较会误判 `-q 85` 这类情况）。共享 options 构建块用 `getattr(parsed, attr, 默认)` 接线。
4. **GUI 新 tk.Variable 必须放 `__init__`**（`_set_language` 销毁重建控件，状态只存活在变量里）。设置面板新区块：`_add_section_label(row=N)` + 内容帧 `row=N+2`，行号从 24 起。
5. **STRINGS zh/en key 集合必须完全一致**（`_t` 缺 key 静默回退，会造成"看起来能用"的漏译）。**CLI 的 `i18n.STRINGS` 与 GUI 的 `STRINGS` 都受此约束**（parity 测试：test_i18n.py + test_gui_settings.py）。新增 CLI 字符串必须同时写 zh/en 两表。`--json` 输出键永远英文，人读文本走 `jout`（`--json` 时 stderr）。
   **JSON 输出契约（v1.6.0）**：所有 `--json`/REST/MCP 输出必须经 `contract.versioned()` 带顶层 `schema_version`（加性键，非信封）。新增输出键是 additive——**禁止重命名/删除已有键**（breaking 才递增 `SCHEMA_VERSION`）。测试 `tests/test_contract.py` 强制。
6. GUI 禁用 `tk.Button`，用 `FlatButton`；输入/勾选类用 `ttk.*`。
7. **测试模式**：纯 assert + `tmp_path` + PIL 小图；engine 层用 `_process(src, out_dir, **kwargs)` 助手（tests/test_features.py）；可配置项测试参照 `_apply_config_defaults` 的 hasattr 语义。
8. **PIL 解压炸弹阈值**：`photo_s/__init__.py` 把 `Image.MAX_IMAGE_PIXELS` 设为有界值 `512_000_000`（警告 >512MP、硬报错 >1024MP）——合法大图（如 112MP）不再误报 DecompressionBombWarning，真炸弹仍被拦。只设一次不切换（线程安全），改阈值需同步 tests/test_pil_limit.py。

## 常用命令

```bash
python3 -m pytest tests/ -q      # 全量测试（当前 1072 个）
python3 -m photo_s.cli --help    # CLI 冒烟（无 PATH 依赖；--language en/zh 切换）
python3 -m photo_s.cli plugin list --json   # 官方插件目录 + 已装状态
python3 -m photo_s.cli mcp --list-tools     # MCP 工具 + schema（需 photo-s-tools[mcp]，py3.10+）
```

## 集成方式（用户 agent 产品）

- 宿主是 Python → 直接 `from photo_s.engine import batch_process`（推荐）
- 非 Python / 跨进程 → `photo-s serve --port 0 --token auto --ready-file x.json`，轮询握手文件拿 `{port, token}` 后走 HTTP
- 一次性脚本 → CLI + `--json`
- agent skill → 仓库 `skills/photo-s/SKILL.md`（现成 skill 包：`cp -r skills/photo-s ~/.claude/skills/`，零额外依赖）
- MCP 深度集成 → `pip install "photo-s-tools[mcp]"` + `claude mcp add photo-s -- photo-s mcp`（25 工具，契约见 docs/AGENT_API.md §6 + §7 感知反馈闭环）
