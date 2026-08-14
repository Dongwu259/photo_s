# PhotoS 功能清单 — Feature Inventory

> 以代码实际为准（v1.4.0），覆盖 CLI / 引擎 / GUI / REST / MCP / 插件 六层。
> 定位 "CLI for AI agents, GUI for humans"。

## 1. CLI 命令（19 个）

| 命令 | 作用 |
|---|---|
| `compress` | 压缩体积：`-q` 质量、`--target-size` 自动调优、RAW→JPEG、`--raw-half-size` |
| `convert` | 格式转换（`-f`），8 种输出格式 |
| `batch` | 批量处理：压缩+转换+缩放+全部引擎能力，`-r` 递归、`--organize` 子文件夹 |
| `exif` | 批量读写元数据（make/model/lens/iso/shutter/aperture/focal/date）/ 打标（rating/keywords/title）/ 按评分筛选 |
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
| `serve` | REST API（AI agent 集成，含 `/process/stream` SSE 进度） |
| `mcp` | MCP server（stdio，11 工具，py3.10+） |
| `plugin` | 插件管理 install/list/info/fetch/**scaffold** |
| `bench` | 批量基准：`--dir -j 1,2,4,8 --denoise` 实测各并发耗时/加速比；每阶段计时（load/process/save）；`--evaluate` 输出质量（PSNR/SSIM 对比源图）；输出写临时目录跑完自动清理，不污染源目录 |

全局：`--json`（agent 友好输出）、`--version`。`-j/--jobs` 默认 **auto**（min(CPU核数,8)）。

**并发调优（v1.4.0 实测定案）**：真实交付集（29 张 24MP）`-j 1,2,4,8` 实测 2.62s→0.45s，8 线程 **5.83x**，线程远未饱和——重活（解码/缩放/编码/降噪推理）都在 Pillow/numpy/onnxruntime 里释放 GIL，纯 Python 段占比小，**多进程是负优化**（降噪场景内存翻倍）。调优旋钮：`-j` 提并发；SCUNet 降噪时可用 `OMP_NUM_THREADS` / onnxruntime intra-op 控制单算子线程数，避免与外层 `-j` 超额订阅。机器不同结论可能不同，用 `bench` 实测。

## 2. 引擎处理能力（ProcessOptions 61 字段）

**管线顺序**：open → 插件 pre_process → auto_rotate → auto_straighten → log_curve → 色彩管理 → 影调 → **LUT 调色（`--lut` .cube/预设，plugin provider 优先否则内置三线性）** → 白平衡 → 曝光 → denoise → 自动色阶 → crop/rotate/flip → resize → pad → 打印尺寸 → watermark → save

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
**处理**：批量处理+进度、Esc 取消、队列追加续跑、双击对比、RAW 原生预览、**视觉预览**（⌘P：真实管线渲染原图↔处理后并排，设置变化防抖自动刷新，只写临时目录绝不删源）
**工作流**（工具栏「更多工具」菜单）：
- 审查打分灯箱（0-5 评分/关键词/标题 + 拍摄信息编辑：品牌/型号/镜头/ISO/快门/光圈/日期、过滤、翻页、灯箱内撤销）
- 批量重命名（模板实时预览、批内撞名检测、就地/复制两模式，预览=真实执行结果）
- 多图并排对比（2-4 张，滚轮缩放/拖拽平移/双击复位，共享视口状态天然同步）
- 去重查看器（缩略图+清晰度+★最锐预选、移入回收不删除、撤销回移）
- 画廊导出（HTML + 浏览器打开）
- 目录监视（watchdog，后台自动处理新图，关闭对话框即停）
- 联系表（网格拼图）
- 曝光/清晰度筛选（cull，仅保留符合项可撤销）
- 校验和清单（生成/校验 manifest）
- 预设管理（保存当前设置/加载/删除，加载映射回全部 UI 变量）
- 摘要对话框、全局撤销（栈 10 项）
**设置面板**：格式（8 种）、压缩模式（质量/target-size）、缩放、输出、命名、子文件夹、选项、水印、多尺寸、影调、构图、校正（白平衡/曝光/自动色阶/LOG/降噪/LUT 调色/扶正）、元数据
**全局快捷键**：⌘O 加文件 · ⌘⇧O 加文件夹 · ⌘R 处理 · ⌘P 预览 · ⌘E 审查 · ⌘D 去重 · ⌘G 画廊 · ⌘Z 撤销 · Esc 取消
**其它**：设置对话框（MCP 状态/依赖安装/插件管理）、插件管理器、拖放（可选）、RAW 预览

## 4. REST API（`photo-s serve`）

`/health` `/info` `/plugins` `/tasks`(+id) `/process` `/process/stream`(SSE) `/dedup` `/rename` `/contact-sheet` `/check` `/plugins`(POST)
- Bearer token 认证（`--token auto` 随机生成）+ ready-file 握手
- 无 token 时 CSRF Origin 防护（拒绝跨域浏览器请求）
- **`POST /process/stream`**：text/event-stream 实时进度（每文件一条 `data:` 帧 + 结束 `done` 帧），agent 免轮询

## 5. MCP server（11 工具）

`process` `info` `exif` `dedup` `cull` `hash` `plugin` `contact_sheet` `gallery` `watermark` `preset` — dedup 默认 dry_run 安全；模块级零 mcp import

## 6. 插件系统

- 官方插件 **scunet**（SCUNet 强降噪，ONNX）：强度感知混合（0-20）、分块推理（tile 512 + overlap 64 线性斜坡融合，大图不 OOM）、输入自动补齐到 64 倍数、权重 modelstore 下载 + sha256 校验
- 官方插件 **lut**（LUT 调色，纯 numpy 无权重）：四面体插值 override 内置三线性 + 5 个电影预设（filmic-v1/warm、cinema-cool、portrait-soft、punchy）
- 开发脚手架：`photo-s plugin scaffold <name>` 生成插件包骨架
- 协议：`provides` operation provider（denoise/lut）+ pre/post 过滤钩子

## 7. 其它模块

`watcher` 目录监视（`start_watching` 支持 `stop_event`，GUI 可停止）· `cull` 曝光/清晰度筛选（CLI/GUI/REST 共享）· `config` TOML 预设 · `check` 完整性 · `hash` 校验和 · `gpx` 轨迹 · `modelstore` 权重缓存 · `registry` 官方插件目录

## 8. 可选依赖（extras）

`raw`(no-op，rawpy 已核心) · `exif`(piexif) · `watch`(watchdog) · `gui`(tkinterdnd2) · `heic` · `avif` · `enhance`(opencv: NLM 降噪+扶正) · `mcp`

## 9. 平台 / 验证

- macOS / Linux / Windows（CI 7 jobs：py3.9-3.12 全量 + Windows 真实 Tk + SCUNet 真推理 + exe 打包双版本：完整版 + lite 无 GUI 精简版）
- 测试 690 个全绿
