# PhotoS 功能清单 — Feature Inventory

> 以代码实际为准（v1.2.0），覆盖 CLI / 引擎 / GUI / REST / MCP / 插件 六层。
> 定位 "CLI for AI agents, GUI for humans"。

## 1. CLI 命令（18 个）

| 命令 | 作用 |
|---|---|
| `compress` | 压缩体积：`-q` 质量、`--target-size` 自动调优、RAW→JPEG、`--raw-half-size` |
| `convert` | 格式转换（`-f`），8 种输出格式 |
| `batch` | 批量处理：压缩+转换+缩放+全部引擎能力，`-r` 递归、`--organize` 子文件夹 |
| `exif` | 批量读写元数据 / 打标（rating/keywords/title）/ 按评分筛选 |
| `rename` | 智能模板重命名 `{date}/{make}/{camera}/{seq}/…`，`-o` 复制改名 |
| `dedup` | 查重 + `keep-sharpest`（保留最锐） |
| `cull` | 曝光/清晰度筛选（过曝/欠曝/亮暗范围/模糊分） |
| `check` | 图片完整性检查 |
| `hash` | 校验和清单生成/校验（SHA-256 manifest） |
| `contact-sheet` | 联系表（网格拼图） |
| `gallery` | HTML 画廊 |
| `watch` | 目录监视自动处理 |
| `preset` | 预设配置管理 |
| `config` | TOML 配置文件管理 |
| `info` | 格式/环境探测（`--json`） |
| `serve` | REST API（AI agent 集成） |
| `mcp` | MCP server（stdio，7 工具，py3.10+） |
| `plugin` | 插件管理 install/list/info/fetch |

全局：`--json`（agent 友好输出）、`--version`。

## 2. 引擎处理能力（ProcessOptions 61 字段）

**管线顺序**：open → 插件 pre_process → auto_rotate → auto_straighten → log_curve → 色彩管理 → 影调 → 白平衡 → 曝光 → denoise → 自动色阶 → crop/rotate/flip → resize → pad → 打印尺寸 → watermark → save

| 类别 | 能力 |
|---|---|
| 压缩 | 质量调优、target-size 自动调优、optimize、progressive |
| 格式 | JPEG/PNG/WebP/TIFF/HEIC/AVIF/BMP/ICO |
| 缩放 | max_width/height、max_pixels、scale_percent |
| 影调 | brightness/contrast/saturation/gamma/sharpen/grayscale/sepia |
| 白平衡 | wb_temp（色温 K）、wb_reference（灰卡采样） |
| 曝光 | ev（2^EV）、auto_exposure |
| 降噪 | denoise 0-20（SCUNet provider 优先，否则 NLM） |
| 校正 | auto_levels（自动色阶）、log_curve（LOG 还原）、auto_straighten（扶正） |
| 构图 | crop、crop_ratio、rotate、flip、pad |
| 多尺寸 | output_sizes（`label:WxH,…`） |
| 元数据 | preserve_exif、strip_gps、scrub、date_shift、sync_date、gpx_trace、PhotoS: 打标 |
| 命名/组织 | prefix/suffix、rename_pattern、folder_pattern（date/date-camera/自定义） |
| 输出 | output_dir、overwrite、remove_original、keep_mtime、resume、print_size、watermark |
| RAW | rawpy 核心：37 种扩展原生读写、raw_half_size、raw_auto_bright |

**RAW 输入**：.arw .cr2 .cr3 .crw .dng .erf .kdc .mef .mos .mrw .nef .nrw .orf .pef .raf .raw .rw2 .rwl .sr2 .srf .srw .x3f .3fr …（共 37 种）

## 3. GUI（Tkinter，双语 zh/en，明暗主题）

**文件区**：添加文件/文件夹（不支持自动跳过+提醒）、勾选式二次选定（全选/全不选）、移除、分析
**处理**：批量处理+进度、Esc 取消、队列追加续跑、双击对比、RAW 原生预览
**工作流**：
- 审查打分灯箱（0-5 评分/关键词/标题、过滤、翻页、灯箱内撤销）
- 去重查看器（缩略图+清晰度+★最锐预选、移入回收不删除、撤销回移）
- 画廊导出（HTML + 浏览器打开）
- 摘要对话框、全局撤销（栈 10 项）
**设置面板**：格式（8 种）、压缩模式（质量/target-size）、缩放、输出、命名、子文件夹、选项、水印、多尺寸、影调、构图、校正（白平衡/曝光/自动色阶/LOG/降噪/扶正）、元数据
**全局快捷键**：⌘O 加文件 · ⌘⇧O 加文件夹 · ⌘R 处理 · ⌘P 预览 · ⌘E 审查 · ⌘D 去重 · ⌘G 画廊 · ⌘Z 撤销 · Esc 取消
**其它**：设置对话框（MCP 状态/依赖安装/插件管理）、插件管理器、拖放（可选）、RAW 预览

## 4. REST API（`photo-s serve`）

`/health` `/info` `/plugins` `/tasks`(+id) `/process` `/dedup` `/rename` `/contact-sheet` `/check` `/plugins`(POST)
- Bearer token 认证（`--token auto` 随机生成）+ ready-file 握手
- 无 token 时 CSRF Origin 防护（拒绝跨域浏览器请求）

## 5. MCP server（7 工具）

`process` `info` `exif` `dedup` `cull` `hash` `plugin` — dedup 默认 dry_run 安全；模块级零 mcp import

## 6. 插件系统

- 官方插件 **scunet**（SCUNet 强降噪，ONNX）：强度感知混合（0-20）、权重 modelstore 下载 + sha256 校验
- 协议：`provides` operation provider + pre/post 过滤钩子

## 7. 其它模块

`watcher` 目录监视 · `config` TOML 预设 · `check` 完整性 · `hash` 校验和 · `gpx` 轨迹 · `modelstore` 权重缓存 · `registry` 官方插件目录

## 8. 可选依赖（extras）

`raw`(no-op，rawpy 已核心) · `exif`(piexif) · `watch`(watchdog) · `gui`(tkinterdnd2) · `heic` · `avif` · `enhance`(opencv: NLM 降噪+扶正) · `mcp`

## 9. 平台 / 验证

- macOS / Linux / Windows（CI 7 jobs：py3.9-3.12 全量 + Windows 真实 Tk + SCUNet 真推理 + exe 打包）
- 测试 453 个全绿
