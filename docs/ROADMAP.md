# PhotoS 版本路线 — Roadmap

> 节奏（2026-08-14 定）：**patch 随时发**（bug 修复 / 依赖升级 / 小优化 → vX.Y.Z+1，
> 不必凑轮）；**主题大轮攒 1-2 月发 minor**。每个 minor 一个清晰主题。

## 已发布

| 版本 | 主题 | 内容 |
|---|---|---|
| v1.0.0 | 首发 | CLI + 引擎核心 |
| v1.2.0 | GUI 补全 | 6 工作流入口（预览/监视/联系表/cull/hash/预设）+ 安全修复 |
| v1.3.0 | Agent 集成 + LUT + 性能工具 | MCP 7→11 工具、SSE 进度、LUT 调色 + 插件、auto-jobs、`bench`、`plugin scaffold`、Pillow14 兼容 |
| v1.4.0 | GUI 深化 + 降噪大图适配 | EXIF 编辑器扩展（镜头/ISO/快门等 7 字段）、重命名实时预览、多图并排对比（同步缩放勾选）、SCUNet 分块推理（24MP 不再 OOM）+ padding 修复、性能实测定案（8 线程 5.83x，不做多进程）、bench 三件套（SSIM/分段计时/临时目录）、双版本 exe（完整版 + lite）、v1.3.2 遗留低危清扫 6 项 |
| v1.5.0 | i18n + Agent 契约 + 摄影师工作流 | 全量 CLI/GUI 国际化（--language 三平台检测）、JSON 契约 schema_version 版本化 + server 加固（0600/DNS-rebinding/1MB 上限）、MCP 15→18 工具（select/hdr/blurfaces/bench/watch×3）、选片双阈值分拣、HDR 曝光融合（--align）、人脸模糊/马赛克、--preset 一键套用、批量 EXIF GPS、crop-ratio 回归 |
| v1.5.1 | Agent 接入便利化 | 现成 SKILL.md skill 包（cp -r 即用，仅核心包）、AGENT_API.md 补 Claude Code `claude mcp add` 连接（用户/项目/uvx 变体）、README 工具数 15→18 修正 + 新工具列表补全 |
| v1.6.0 | LR 方向调色 | `photo_s/grade.py` 11 算法（点曲线 PCHIP/手动色阶/自然饱和度/三向颜色分级/WB tint/HSL 分色/清晰度·纹理/去雾/暗角/颗粒，纯 numpy+PIL 零依赖）+ 3 个 LUT/MCP bug 修复 + 四层接线（CLI 11 flag/REST 自动/MCP 33 参数/GUI 11 控件）+ 紧凑字符串建模（REST/preset 零胶水）|
| v1.6.1 | GUI 大增强 | Lightroom 式调色编辑器（可拖拽曲线 RGB+R/G/B/复位、3 色轮+亮度条、HSL 编辑器）+ 设置面板分类 Tab（输出/调整/效果/元数据/选项）+ 区块折叠 + 工具栏分组瘦身 + 缩略图（异步懒加载）/布局记忆/过滤框/进度 ETA/重做；color_grading 支持每区亮度 |

## 规划中

### v1.6.0（LR 方向调色增强 —— 主题：专业调色）

> 需求来源：商业软件 LensPilot 以 photo_s 为底层图像管线，功能摸底（2026-08-18）指出
> 向 Lightroom 方向增强调色能力。定位约束不变：**批量/交付导向管线，不做交互式局部修图**。
> 全部 P0/P1 为**单图全局调整算法，纯 numpy/PIL 可实现，零新依赖**（打包环境已有 numpy/cv2/onnxruntime）。
> **实施（2026-08-18，已 push 未发版）**：P0+P1 全部落地进 `photo_s/grade.py`（11 函数）+ 3 个 bug 修复 + 四层接线（CLI 11 flag / REST 自动 / MCP 33 参数 / GUI 11 控件），899 测试全绿。
> **关键设计决策**：ROADMAP 原议 `curves/color_grading/hsl` 用 dict 字段——实施时改**紧凑字符串**（如 `curves="r:0,0;128,140;255,255"`、`color_grading="shadows:120,0.3"`），
> 与现有 `crop/pad/print_size` 同形态：REST `_scalar_groups` / preset `asdict` **零手工接线**（已验证）。

**P0 — LR 核心旋钮**（`photo_s/grade.py`，`ProcessOptions` 字段 + CLI flag + GUI 设置面板 + REST/MCP 自动继承）：

- [x] 点曲线 `apply_curves(img, channel_points)`：控制点 PCHIP 单调样条 → 256 项 LUT；`curves: str`；channel ∈ rgb/r/g/b
- [x] 手动色阶 `apply_levels(img, black, white, gamma)`：黑场/白场/中间调三点重映射；`levels: str`
- [x] 自然饱和度 `apply_vibrance(img, amount)`：HSV 空间按当前饱和度反向加权提升（保护肤色/已饱和区，与全局饱和度互补）；`vibrance: float`
- [x] 三向颜色分级 `apply_color_grading(img, shadows, midtones, highlights)`：各档 (hue_deg, saturation) + 亮度掩膜平滑过渡叠加着色；`color_grading: str`
- [x] WB tint 轴 `wb_tint`：`apply_white_balance` 扩 G/M 品红-绿轴（小矩阵）；`wb_tint: float`

**P1 — 风格化常用**：

- [x] HSL 分色 `apply_hsl(img, adjustments)`：8 色域（red/orange/yellow/green/aqua/blue/purple/magenta）×（hue/sat/lum 偏移），高斯软过渡；`hsl: str`
- [x] 清晰度/纹理 `apply_clarity(amount, radius=60)` / `apply_texture(amount, radius=4)`：亮度通道 USM 局部对比，clarity 大半径 / texture 小半径；`clarity` / `texture: float`
- [x] 去雾 `apply_dehaze(img, amount)`：暗通道先验 + 高斯模糊透射率估计（批量级，无 opencv 依赖）；`dehaze: float`
- [x] 暗角 `apply_vignette(img, amount, midpoint, feather)`：径向渐变掩膜乘法；`vignette: str`
- [x] 颗粒 `apply_grain(img, amount, size)`：亮度加权单色斑点噪声（胶片感）；`grain: str`

**Bug 修复（P0，摸底发现，必修）**：

- [x] **3D/1D LUT 后 EXIF 丢失**：`apply_lut` 出口统一 `out.info = img.info.copy()`（1D/3D 两条路径），端到端测试锁定
- [x] `apply_lut` 3D 路径 RGBA 丢 alpha：先拆 alpha 再重挂（1D 路径原本已处理）
- [x] MCP `process` 工具 schema 未暴露 `lut_file/brightness/contrast/saturation`：补参数（+v1.6.0 全部调色参数，共 33 个）

**管线顺序（实际实施，向后兼容——现有 tone/LUT 原位保留，新调色块插入）**：

```
auto_rotate → auto_straighten → log_curve → 色彩管理
→ tone(倍率，原位) → LUT → WB(temp+tint) → 曝光
→ levels → curves → clarity → texture → dehaze
→ vibrance → hsl → color_grading        ← 新调色块
→ denoise → auto_levels → vignette → grain
→ crop/rotate/flip → resize → pad → print → watermark → blur_faces → EXIF → save
```

**远期（不在 v1.6）**：渐变蒙版（线性/径向 + 羽化 + 全局调整子集，唯一适合批量的局部形态，参数可序列化进 ProcessOptions）；XMP `crs:` 编辑参数读写（LensPilot LR 桥接从「读回结果」升级为「双向 interchange」——我方调整可被 LR 直接打开续修，LR 修完的参数我方复现）。

**明确不做**：RAW 域编辑（画质追不上 LR 线性 RAW 管线，rawpy 解码后 sRGB 域调整即可，定位交付级）；笔刷蒙版/修复画笔/AI 主体选择（交互重，与批量交付定位相悖）；镜头校正（畸变/色差需 lensfun 级数据库，投入产出比低）。

### v1.5.0（i18n + Agent 契约 + 加固 + 审计遗留 + 摄影师批处理工作流）
**A. 国际化（i18n）**
- [x] 新 `photo_s/i18n.py`：CLI `STRINGS` 集中表（279 key × 2，parity 测试强制）、`_t(key, lang, **kwargs)`、三平台检测（macOS AppleLanguages / Windows LCID / Linux env）、`resolve_language` 优先级链（flag > env > config > persisted > 系统 > en）、GUI `~/.photos/language` 持久化、不用 `locale.setlocale`
- [x] CLI `--language {en,zh,auto}` 全局 flag + 两段式解析、257 条 help + ~190 条运行时消息单一语言、`--json` 键保持英文、config `language` key
- [x] GUI 启动自动检测 + 用户选择持久化

**B. Agent 契约版本化 + server 安全加固**
- [x] 新 `photo_s/contract.py`：`SCHEMA_VERSION = 1` + `versioned(payload)`（加性顶层键，非信封）；CLI 16 处 `json.dumps` + plugincmd `_json()` + REST `_send_json` 单点 + MCP 工具 `@_versioned` 装饰器，全部 JSON 输出带 `schema_version`
- [x] server 安全加固：ready-file 0600 权限、DNS rebinding Host 白名单 + Origin 对比实际绑定地址、`_read_json` 1MB 上限（413 + 排空连接）
- [x] AGENT_API.md 契约声明（additive、消费者忽略未知键、breaking 才递增）+ §3.2 安全边界说明

**C. v1.3.2 审计遗留 3 项**
- [x] `min_photo_s_version` 安装时接线（`plugin install` 拒绝核心过旧 + `plugin list` 暴露 `compatible` 键）、`PHOTO_S_TLS` 真 TLS（stdlib ssl 包 socket，缺证书报错不静默）、GUI 预览 drain `rendered` 守卫（同 options 不重渲，`stable` 归零只是延迟不是修复）

**D. 摄影师批处理工作流（原 v1.6.0，合并进 v1.5.0 一次发布）**
- [x] **选片工作流 `select`**：按 EXIF 评分双阈值分拣——rating ≥ keep_min(4) 移精选目录、≤ reject_max(2) 移淘汰目录、3 星/未评分原地；move/copy、dry_run 零写入、basename 平铺防穿越、原子 move（copy2→os.replace→删源）；CLI + MCP `select_tool` + GUI 评审灯箱「移动精选/淘汰」按钮
- [x] **批量 EXIF GPS + make/model**：`apply_exif_tags` 支持 `gps "lat,lon"`（GPS IFD + N/S/E/W refs，非法值静默跳过）；CLI `exif --gps/--make/--model` 批量写；MCP `exif_tool` `gps` 参数
- [x] **统一比例裁剪验证**：`--crop-ratio`（16:9/1:1 等）已端到端存在（engine→adjust→CLI→GUI），补方形 + 与 `--crop` 组合回归测试锁定
- [x] **风格预设一键套用**：CLI `preset save` 改经共享 builder 捕获全选项集（原只 4 字段）；`preset load` 真正可用；batch/compress/convert 新增 `--preset NAME`（优先级：显式 CLI > --preset > config > 默认；jobs/output_dir 不套用）
- [x] **包围曝光 HDR 合并**：新 `photo_s/hdr.py`（opencv MergeMertens 曝光融合，无需 EV；`--align` AlignMTB 手持对齐，坏 build 抛清晰错误不静默回退）；CLI `hdr` + MCP `hdr_tool` + GUI「更多工具」入口
- [x] **批量人脸模糊 `blurfaces`**：新 `photo_s/faceblur.py`（opencv Haar cascade 检测 + 高斯模糊/马赛克；cascade 缺失抛清晰 RuntimeError 不静默返原图）；`ProcessOptions.blur_faces/blur_faces_margin` 入管线（watermark 后 EXIF 前，只改像素 .info 保留）；CLI `--blur-faces`（batch）+ 独立 `blurfaces` 子命令 + MCP `blurfaces_tool` + GUI 设置面板
- [x] 净效果：MCP 工具 11→18、CLI 子命令 19→22、**834 测试全绿**（2026-08-16）

**E. 发布状态**：v1.5.0 为合并版本（i18n + 契约 + 加固 + 审计遗留 + 摄影师工作流）
- [x] **已发布 2026-08-16**：CI 7 job 全绿 → tag v1.5.0 → PyPI（wheel + sdist）→ GitHub Release（wheel）→ 干净 venv 安装验证

### v1.5.1+（patch 轨道，随时发）
- [x] **v1.5.1 已发布 2026-08-17**：SKILL.md skill 包 + Claude Code MCP 文档 + README 修正（见已发布表）
- [ ] 依赖升级与平台坑修复（rawpy / Pillow 小版本、Windows/Linux 真机问题）

### v1.4.0 实施记录（2026-08-14，已全部落地）
**A. 性能实测收尾** —— 真实照片集（29 张交付图）`bench -j 1,2,4,8`：2.62s → 0.45s，
8 线程 5.83x，线程远未饱和、GIL 非瓶颈（重活全在 Pillow/numpy/onnxruntime 中释放）。
**结论：不做多进程**（ProcessPool 对降噪场景是负优化，内存翻倍），已文档化（FEATURES.md 并发调优段）。

**B. GUI for humans 深化**
- [x] EXIF 编辑器 UI：从 rating/keywords/title 扩到品牌/型号/镜头/ISO/快门/光圈/日期
      （引擎层同步扩展：`_EXIF_TYPED_TAGS` 支持 SHORT/RATIONAL 写入，CLI `exif`
      新增 `--lens/--iso/--shutter/--aperture/--focal`）
- [x] 批量重命名实时预览：模板改动 300ms 防抖重算、批内撞名检测标黄、
      预览与真实执行结果逐字节一致（parity 测试钉住）
- [x] 多图并排对比（2-4 张，滚轮缩放/拖拽平移/双击复位，「同步缩放」勾选框联动）

**C. 降噪大图适配**
- [x] SCUNet 分块推理（tile=512/overlap=64 线性斜坡融合）：24MP 图切 ~70 块，
      实测 8 并发 4 张 155s 跑完无 OOM（修复前直接 SIGKILL）；
      顺带修复边长非 64 倍数必挂的 padding bug

**D. 发布当日补攒（计划外）**
- [x] bench 三件套：`--evaluate`（PSNR/SSIM）、每阶段计时（load/process/save）、
      输出改临时目录跑完自清理（不污染源目录）；metrics 修 SSIM 偶数窗口 bug + 新增 PSNR
- [x] v1.3.2 遗留低危清扫 6 项：straighten/config 旧包名提示、CLI 进度 off-by-one、
      sized 输出纳入撞名预分配、scaffold 拒绝覆盖 + 数字类名清洗、GPX 秒进位 + NaN 坐标过滤
- [x] 双版本发行：完整版 exe（GUI+CLI）/ photo-s-lite exe（CLI+MCP，无 Tk，181MB vs 188MB）

## 候选（未排期）

- **C. Agent 集成再深一层**：JSON 输出契约版本化（`schema_version`）、更多 MCP 工具
  （bench / watch 状态）——边际收益递减，v1.3.0 已做主体
- **D. 插件生态扩展**：更多官方 operation 插件（每个都要新 provider 槽位、动引擎，
  跨层成本高）——差异化亮点但性价比低于 A/B
- **E. 独立发行版生态**：`photo-s-plugin-lut` 已是纯 numpy 无权重；可探索更多
  "零依赖纯代码"插件类型

## 原则

1. **数据先行**：性能类改动先 `bench` 再动手，不拍脑袋上多进程
2. **主题集中**：一个 minor 一个故事，Release notes 好写、用户/agent 好感知
3. **patch 轻快**：小修复不等大轮，随时 `v1.3.1` 发（流程见 RELEASE.md / 发布记忆）
