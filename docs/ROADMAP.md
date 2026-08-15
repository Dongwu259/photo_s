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

## 规划中

### v1.5.0（i18n + Agent 契约 + 加固 + 审计遗留 + 摄影师批处理工作流，**开发完成待发布**）
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
- [ ] **待发布**：push → CI 全绿确认 → tag v1.5.0 → PyPI → Release（发布流程见 RELEASE.md / 交接文档 §2）

### v1.5.1+（patch 轨道，随时发）
- [ ] 依赖升级与平台坑修复（rawpy / Pillow 小版本、Windows/Linux 真机问题）
- [ ] 文档/示例补全

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
