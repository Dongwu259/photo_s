# 更新日志 — Changelog

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)，
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

> - **核心包**：tag `vX.Y.Z` → PyPI `photo-s-tools`
> - **官方插件**：tag `<name>-vX.Y.Z` → PyPI `photo-s-plugin-<name>`（独立版本号）
> - 版本主题与路线图见 [`docs/ROADMAP.md`](docs/ROADMAP.md)
> - `schema_version` 是**契约版本**（当前 1），与发布版本号无关；只有
>   重命名/删除/改语义 JSON 键时才递增

---

## [Unreleased]

v2.6.0 P1/P2 批次：把 v2.5 的 agent 能力补进 GUI（Library 语义搜索/过滤、
智能建议、导出 audit、颜色标签）+ 结构项首批（panels/ 拆分、Tools 面板化
首批、分栏可拖）。

### Added
- **Develop「智能建议」按钮**：`photo-s suggest`（规则型、零依赖离线）参数
  一键应用进逐照片覆盖层——可撤销/可编辑/进预览与导出管线，兼作 AI 调色
  缺插件时的兜底；中性图（无可修项）明确提示
- **Library 语义搜索 + facet 过滤**：语义框查本地 `.photo-s-index.npz`
  （`photo-s index` 构建；内置 hist84 无文本编码器时给出安装指引而非报错）；
  评级 ≥N★ / 仅已调·未调 / 格式 / 颜色标签（含无标签）四组下拉过滤，
  选择按下标存储（语言切换安全）
- **导出后质量检查（audit）**：Export 选项新增勾选（默认开）——批处理完成
  后对输出跑 agent 同款 `audit_image`，状态栏与摘要窗显示通过率，未过项逐
  文件列原因，附「打开输出目录」按钮
- **颜色标签（LR 五色）**：EXIF UserComment 协议新增 `label` 字段
  （rating/keywords/title 同款写出与撤销语义）；键盘 6-9/0 设置与清除、
  审查灯箱标签按钮行、Library 行彩色圆点徽标、标签筛选联动；写回 XMP 时
  作为 `xmp:Label` 带给 Lightroom
- **分栏可拖 + 持久化（结构项）**：Develop 主行与 Export 主行改
  `ttk.PanedWindow`，sash 位置经 gui_state 跨重启恢复；蒙版编辑器收起
  侧栏改 pane forget/add（sash 记忆还原）
- **Tools 面板化首批（结构项）**：watch（autopilot 驾驶舱）内嵌为 Tools
  模块常驻面板——卡片点开/再点关闭，面板关闭经 close_hook 停表防泄漏

### Changed
- **panels/ 拆分启动（结构项）**：`gui/panels/` 建包——审查灯箱簇、九个
  工具对话框、watch 对话框以 mixin 平移出 app.py（约 2535 行，方法体
  逐字节保留）；`PhotoSApp` 多继承组合，app.py 11337 → 约 8850 行；
  worker→UI 封送契约审计（`lambda err=str(e)`）扫描范围同步覆盖 panels/

### Docs
- 快捷键表（? 键）补 6-9/0 标签键

## [v2.5.2] — 2026-09-16

上游问题清单修复（photo-s 渲染桥实测反馈，PS-1 ~ PS-5）。

### Fixed
- `grade.apply_hsl` 色带掩码补饱和度门控——HSV 中性像素 hue 无定义（兜底
  0° = 红色中心），大片白/近灰区域此前全权重吃红色带调整（高光塌陷、灰粉
  污染）；sat ≥ 0.1 的有效彩色像素行为不变
- `grade.apply_vibrance` 正向改乘性公式（`sat + sat·(1-sat)·amount`）——
  旧加性公式在低饱和区近似 `sat + amount`，把不可见 ~1% 色偏放大 ~9 倍成
  可见色块；中性像素严格不变（不再依赖 1e-3 兜底）
- `lrxmp.options_to_xmp` dict 路径兼容 `exposure` 键——`crs_to_options`
  读侧键是 `exposure`（LR 命名空间）而字段名是 `ev`，此前往返静默丢曝光
- **局部调整统一 delta 口径**：`lrxmp._local_adjust` 读侧 / `_LOCAL_XMP_MAP`
  写侧不再写 `1 + v`——mask_adjust 的 brightness/contrast/saturation/
  sharpen 本就是 delta（`mask.apply_local` 内部 `1.0 + v`），旧换算被二次
  +1（LR UI +45 渲染成 2.45 倍对比度）
- `mask.parse_masks` 容忍退化径向蒙版——rx=0（LR 线条/塌缩形状经 lrxmp
  往返为 `0.0000`）此前抛 `MaskError` 中止整图所有蒙版，现 clamp 到最小
  半径（≈1000px 图上 1px 细线）；负半径仍报错

### Docs
- `adjust.apply_white_balance` 注明 kelvin 校正方向与 LR Temp 滑块相反；
  `adjust.apply_exposure` 注明乘法发生在 sRGB gamma 空间（大 |EV| 偏差）

## [v2.5.1] — 2026-09-10

XMP 内嵌与 Lightroom 逐值实测对齐（patch）。

### Fixed
- `xmp-export --embed` 内嵌 JPEG APP1 段的包形态改为 LR 实测同形
  （PI 后不再有 xml 声明 + 尾部填充 + EXIF 段序对齐）
- 补 `crs:AlreadyApplied=False`——LR 对 JPEG 保守忽略该开发设置的开关
- 蒙版组改写为 LR 18.2.2 实测结构（Seq + 嵌套 Description + Mask/Gradient
  Zero-Full + 径向 Midpoint/Roundness/Flipped/Version 属性集 + 全键集局部参数
  + 小写布尔）；旧属性组合会被 LR 静默丢弃
- 局部参数改为 0-1 标度——修正 v1.9 起 blob/XMP 双侧隐性偏低两个量级的问题
- XMP 嵌套 `CorrectionMasks` 不再被重复收集为独立修正组

### Verified
- LR 实测全通：全局调色 / 线性蒙版 / 径向蒙版（含反选）/ 评分关键词逐值一致

## [v2.5.0] — 2026-09-02

数据闭环 + LR 双向互通 + 语义搜索。

### Added
- **XMP 写出**：`xmp-export` 与 `batch --write-xmp`——crs 字段逐项逆映射 +
  radial/linear 蒙版 + 评分/关键词，LR 可直接续修；补全读侧 XMP 曲线/蒙版解析
  的既有缺口；`autotone.resolve_auto_tone_options` 让 XMP 记录真实参数
- **autopilot 无人值守管线**：监视 → suggest/auto-tone → audit → passed/review
  分流 + JSONL 轨迹；watcher 新增 `on_modified` / `on_file` 钩子；
  CLI / MCP×3 / REST `/v1/autopilot` 四面接线
- **语义搜索**：`index` 建嵌入索引（插件 SigLIP 文本+图像 / 内置 84 维直方图），
  `find` 支持中英文文本查询与以图搜图；`--tags` 自动打标（EXIF + 可选 XMP
  `dc:subject`）；MCP 31 核心工具
- `diff` 前后对比与 `preview` base64 视觉快照

### Changed
- 蒙版画布升格进 Develop；审查灯箱并入 Library（v2.4 推迟的结构归位）
- 平台打包（A 原案）**取消**：无签名证书下 Gatekeeper/SmartScreen 会拒跑
  unsigned 应用，pip 为前期唯一入口，打包移至远期

### Fixed
- 字符串型局部调整的序列化 `float()` 必崩问题（v1.8 遗留）

## [v2.4.0] — 2026-09-02

所见即所得 + AI 调色 GUI + 全自动闭环批①。

### Added
- **AI 调色 GUI**：auto-tone 插件预测的 9 项参数写入逐照片覆盖层，可微调/可撤销
- **局部调整词汇表**：`local: [{region, params}]`，引擎经真实管线应用全部 9 个
  字段（修复旧接线只落 3/9 的缺口）
- **美学 verifier**：SigLIP 回归头 + Qwen VLM 终审，`audit --aesthetic 1-10`
  四面接线；训练工具 `tools/train_verifier.py`
- **ModelScope 国内下载链**：视觉塔 / tokenizer / 插件权重三源
- Library VirtualGrid 虚拟列表（5k 首绘 20.9ms、翻页 0.3ms）、键盘评级
  1-5/P/?、before/after 可拖分割线、设置搜索、预设悬停预览、首跑引导卡

### Fixed
- v2.1 风格化底座错配（误用 v7 CLIP 底座，tokenizer 可达机器必崩 64↔77）

## [v2.3.0] — 2026-08-28

Agent 自动化闭环收口。

### Added
- `suggest` 规则型参数推荐：`analyze` → 保守参数 + 理由，零模型零依赖，
  CLI / MCP / REST 三面（agent 闭环 `analyze → suggest → process → audit`）
- `cull --score` 加权质量评分排序 + `--burst` 连拍组留最佳
- batch 任务内建 audit（`audit:true` 附 `pass_rate`）

### Fixed
- auto-tone 插件三线接线：engine `auto_tone` 槽位 + MCP/REST 启动注册钩子
  （装后 MCP 25→30+ 工具）
- v1.7.1 潜伏的 `_job_worker` 锁重入死锁（`batch_status` 永久挂住）

## [v2.2.0] — 2026-08-27

GUI 编辑效率。

### Added
- LR 式**复制/粘贴设置**（42 字段快照；Develop 按钮 + Export 队列「粘贴到勾选」
  +「已调」徽标）
- **逐照片撤销/重做**（上限 50，切照片时 flush/加载，`Cmd+Z` 在 Develop 优先
  逐照片历史）
- **导出配方**（22 个输出字段规范值快照，`gui_state` 持久化，套用/存/删）

## [v2.1.1] — 2026-08-27

慢网络下载加固 + CI 转正。

### Fixed
- modelstore 断点续传（HTTP Range 收养死进程的 `.part`，完整未改名 part
  离线采纳）+ 3 次重试 + 读超时 30→60s + 成功后清扫全部 `.part` 残片
- CI Linux xvfb GUI job 去掉 `continue-on-error`；actions 升到
  checkout@v5 / setup-python@v6

## [v2.1.0] — 2026-08-25

抠图 / 背景移除。

### Added
- `--cutout` 紧凑 spec 四模式：`subject` / `person` / `object:label`
  （复用 v1.8 segmask 权重，零新增下载）+ `color:R,G,B[,tol][,feather][,invert]`
  硬键控（解白底文字/logo）→ alpha → PNG/WebP/TIFF/AVIF/HEIC 透明输出
- `ProcessOptions.cutout` 字段使 preset / REST / MCP 零胶水继承
- GUI Export 选项 Tab 抠图区块

### Notes
- JPEG + cutout **按文件报错，绝不静默拍平白底**

## [v2.0.0] — 2026-08-25

GUI v2.0：拆包 + 活切换 + 工作区。

### Changed
- `gui.py`（10k 行单文件）拆为 `gui/` 包：
  `app` / `theme` / `strings` / `widgets/` / `workflows` / `state` / `bus`
- 调用方兼容面保留：`photo_s/gui_widgets.py` 为 shim，`gui/__init__.py`
  重导出全部旧名

### Added
- **语言/主题活切换**（反向映射遍历器 + 调色板值重映射，不再销毁重建控件）
- **UiBus** 事件总线（worker → UI，固化 queue + after-drain 约定）
- **Library / Develop / Export / Tools 四工作区**（`Cmd/Ctrl+1..4`）
- Develop：胶片条 + 真实管线防抖预览 + 常驻直方图 + 旁侧调整（两页共享
  `tk.Variable`）
- Export：导出队列（勾选照片 + 体积合计）+ 输出设置 Notebook
- ThumbCache LRU 缩略图缓存；Linux 深色检测；Windows DPI PMv2 感知
- GUI 测试 HOME 隔离不变量

## [v1.9.0] — 2026-08-23

RAW → JPEG 输出质量全线升级。

### Added
- 色度子采样（`--jpeg-subsampling 444/422/420`）、去马赛克算法
  （`--raw-demosaic auto/ahd/vng/ppg/dcb/dht/amaze`）、RAW 色彩空间
  （sRGB/AdobeRGB/ProPhotoRGB）、16-bit RAW → TIFF（`[tiff16]`）
- 导出锐化（输出级 USM，半径随分辨率缩放）、高光恢复（LR 式硬切高光压缩）
- 内置 `lr-look` 预设；用户维护的命名镜头档案（`lens-profile`）
- RAW 解码输出自动打 sRGB ICC

### Fixed
- vibrance 灰染红；`--preset` 后缀覆盖；`brightness` 丢元数据
- AMAZE/不支持的去马赛克算法不再静默回退 sips——选项错误必须清晰报错

## [v1.8.0] — 2026-08-21

AI 识别蒙版 + 笔刷 + 组合算子 + LR 数据管线。

### Added
- `segmask`：U2Netp subject / PP-HumanSeg person / YOLOv8n-seg object:label
  （COCO 80 类），cv2.dnn 惰性加载 + modelstore 权重下载校验 + OpenCV 5
  引擎自动回退
- 笔刷蒙版 `brush:x,y,r|x,y,r`（GUI 画布绘制）+ 组合算子 `combo:A&B` /
  `combo:A-B`
- 复杂字符串参数局部化（curves / hsl / color_grading / vignette / grain 进
  `mask_adjust`，`{}` 包裹）
- GUI LR 式画布蒙版工作流（拖拽/图层排序/A-B 加减/羽化/undo/翻页/per-photo 注入）
- `lr-merge` 多机数据包合并；`lr-scan --sanitize` 脱敏导出

## [v1.7.1] — 2026-08-21

AI 修图基础设施（阶段 1+2 全落地）。

### Added
- `lrxmp` LR 数据桥接：XMP sidecar / catalog 明文快照解析 → `ProcessOptions`
  + 字段覆盖分类
- `lr-scan`（自动发现 `.lrcat`/`.xmp` → 覆盖报告 + 训练 JSONL + before 图渲染）
- `lr-train` / `lr-predict`（岭回归自动基调，纯 numpy；预测端自动识别
  CLIP+MLP npz）、`lr-recipes`（KMeans 配方库）、`lr-similar`（内容特征 kNN）、
  `lr-eval`（教师评测集）
- `diff` / `audit` / `preview`；`analyze --grid` 区域反馈
- MCP 异步任务 `batch_start/status/cancel`；`batch --trace` 轨迹日志

## [v1.7.0] — 2026-08-21

局部调整 + 镜头矫正 + 感知反馈闭环。

### Added
- `mask` 命名蒙版（linear / radial / color，相对坐标 0-1）+ 蒙版内 11 项
  局部调整；紧凑字符串 `masks` / `mask_adjust`
- `point_color` 点颜色（取样色中心软掩码）
- `lens` 手动镜头矫正（畸变 k1 / 去暗角 / 消色差，纯 numpy 双线性重映射）
- `analyze` 感知分析（直方图/通道统计/色温估计/曝光/模糊）——打通
  `analyze → 调参 → process → analyze` 的 LLM 闭环
- GUI 镜头 / 点颜色 / 蒙版编辑器（红色叠加预览）

## [v1.6.1] — 2026-08-19

GUI 大增强。

### Added
- Lightroom 式调色编辑器（可拖拽 RGB + R/G/B 曲线、3 色轮 + 亮度条、
  HSL 编辑器）
- 设置面板分类 Tab（输出/调整/效果/元数据/选项）+ 区块折叠 + 工具栏分组瘦身
- 异步懒加载缩略图、布局记忆、过滤框、进度 ETA、重做

### Fixed
- 曲线拖拽命中测试 + 颜色分级亮度条

## [v1.6.0] — 2026-08-18

LR 方向调色。

### Added
- `grade.py` 11 个算法：点曲线（PCHIP）/ 手动色阶 / 自然饱和度 / 三向颜色
  分级 / WB tint / HSL 分色 / 清晰度·纹理 / 去雾 / 暗角 / 颗粒
  （纯 numpy+PIL，零依赖），紧凑字符串建模 → REST/preset 零胶水
- 四层接线：CLI 11 flag / REST 自动 / MCP 33 参数 / GUI 11 控件

### Fixed
- LUT 处理后 EXIF 与 alpha 丢失；MCP 暴露 tone/LUT 参数

## [v1.5.1] — 2026-08-17

Agent 接入便利化。

### Added
- 现成 `skills/photo-s/SKILL.md` skill 包（`cp -r` 即用，零额外依赖）
- `AGENT_API.md` 补 Claude Code `claude mcp add` 连接方式（用户/项目/uvx 变体）

## [v1.5.0] — 2026-08-16

i18n + Agent 契约 + 摄影师批处理工作流。

### Added
- 全量 CLI/GUI 国际化（`--language en|zh|auto`，三平台语言检测）
- JSON 契约 `schema_version` 版本化 + server 加固（0600 权限 / DNS-rebinding
  防护 / 1MB 请求上限）
- 选片双阈值分拣 `select`、HDR 曝光融合（`--align`）、人脸模糊/马赛克
  `blurfaces`、`--preset` 一键套用、批量 EXIF GPS
- MCP 15→18 工具（select / hdr / blurfaces / bench / watch×3）

## [v1.4.2] — 2026-08-15

### Fixed
- MCP `serverInfo` 报告 PhotoS 版本而非 mcp SDK 版本
- `server.json` 描述裁到 ≤100 字符（registry 校验）

## [v1.4.1] — 2026-08-15

### Added
- MCP 分发元数据（`server.json` / `glama.json` / `smithery.yaml` + Dockerfile）

## [v1.4.0] — 2026-08-14

GUI 深化 + 降噪大图适配。

### Added
- EXIF 编辑器扩展（镜头/ISO/快门/光圈/焦距等 7 字段）、重命名实时预览、
  多图并排对比（同步缩放勾选）
- SCUNet 分块推理（24MP 不再 OOM）+ padding 修复
- `bench` 三件套（PSNR/SSIM 评估、分段计时、临时目录输出）
- 双版本 exe（完整版 + lite：CLI+MCP）

### Notes
- 性能实测定案：8 线程 5.83x —— **不做多进程**

## [v1.3.2] — 2026-08-14

### Fixed
- 全库审计修复 28 个高/中危问题（数据丢失、挂死、崩溃）
- CI：跨盘 gallery 测试在 Windows 上递归（`os.path` 即 `ntpath`）

## [v1.3.1] — 2026-08-14

### Fixed
- 审计发现的 8 个潜伏 bug（Pillow 兼容、库路径不对称）
- 自动色阶 RGB 崩溃 + 输出格式大小写不敏感

## [v1.3.0] — 2026-08-14

Agent 集成 + LUT + 性能工具。

### Added
- MCP 7→11 工具、SSE 进度、LUT 调色 + 插件系统
- `bench` 基准、`plugin scaffold`、auto-jobs
- Pillow 14 兼容

## [v1.2.0] — 2026-08-13

GUI 补全。

### Added
- 6 个工作流入口（预览 / 监视 / 联系表 / cull / hash / 预设）+ 安全修复

## [v1.0.0] — 2026-08-13

首发：CLI + 引擎核心。

---

## 官方插件

插件与核心**独立版本号**。权重不打进 wheel，随用随下（sha256 校验）。

### photo-s-plugin-auto-tone
| 版本 | 日期 | 内容 |
|---|---|---|
| [2.3.0] | 2026-09-02 | 风格化 + 场景自适应（训练侧 v2.1 同步）；SigLIP 主模型 PSNR 32.21 |
| [2.2.0] | 2026-09-02 | ModelScope 镜像权重；局部调整词汇表 + 美学 verifier |
| [2.1.0] | 2026-08-28 | `auto_tone_with_style` + `analyze_visual_style`；修推理双 GELU bug |
| [0.1.0] | 2026-08-24 | 首发：CLIP+MLP v7_clean（PSNR 29.10）+ RAG 检索增强 |

### photo-s-plugin-scunet
| 版本 | 日期 | 内容 |
|---|---|---|
| [0.3.0] | 2026-08-14 | 分块推理（大图不 OOM）+ padding 修复 |
| [0.2.0] | 2026-08-13 | 真实权重接入（外部数据格式双文件） |
| [0.1.0] | 2026-08-13 | 首发：ONNX 强降噪 |

### photo-s-plugin-lut
| 版本 | 日期 | 内容 |
|---|---|---|
| [0.1.0] | 2026-08-14 | 首发：四面体插值 .cube 调色 + 电影预设（纯 numpy） |
