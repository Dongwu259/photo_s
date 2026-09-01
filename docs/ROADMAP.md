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
| v1.7.0 | 局部调整 + 镜头矫正 + 感知反馈 | **已发布 2026-08-21**：`photo_s/mask.py` 命名蒙版（linear/radial/color 相对坐标 0-1，紧凑字符串 `masks`/`mask_adjust`，v1.8 AI/笔刷语法预留）+ 蒙版内 11 项标量局部调整；`point_color` 点颜色（取样色中心软掩码）；`photo_s/lens.py` 手动镜头矫正（畸变 k1/去暗角/消 CA，纯 numpy 双线性）；`analyze` 感知反馈（直方图/通道统计/色温估计/曝光/模糊，CLI+REST+MCP 19 工具）——`analyze → 调参 → process → analyze` 的 LLM 闭环；GUI 镜头/点颜色/蒙版编辑器（红色叠加预览）|
| v1.7.1 | AI 修图基础设施（阶段 1+2 全落地） | **已发布 2026-08-21**：`photo_s/lrxmp.py` LR 数据桥接（XMP/catalog 明文快照解析 → ProcessOptions + 覆盖分类）+ `lr-scan`（自动发现 .lrcat/.xmp → 覆盖报告 + `--export-dir` 训练 JSONL + `--render-dir` rawpy before 图，一条命令产出完整训练包）+ `lr-train`/`lr-predict`（岭回归自动基调，纯 numpy；**lr-predict 自动识别 CLIP+MLP npz**）+ `lr-recipes`（KMeans 配方库）+ `lr-similar`（内容特征 kNN）+ `lr-eval`（教师评测集，PhotoS 自渲染 after）+ `diff`/`audit`/`preview`（版本对比/质量闸门/视觉快照）+ `analyze --grid` 区域反馈 + MCP `batch_start/status/cancel` 异步任务（19→25 工具）+ `batch --trace` 轨迹日志 |
| v1.8.0 | AI 识别蒙版 + 笔刷 + 组合算子 + LR 数据管线 | **发布就绪未发版（2026-08-21）**：`photo_s/segmask.py`（U2Netp subject / PP-HumanSeg person / YOLOv8n-seg object:label，cv2.dnn + modelstore 权重下载校验，OpenCV 5 引擎自动回退）+ 笔刷蒙版 `brush:x,y,r|x,y,r`（GUI 画布绘制）+ 组合算子 `combo:A&B`/`combo:A-B` + 复杂字符串参数局部化（curves/hsl/color_grading/vignette/grain 进 mask_adjust，`{}` 包裹）+ GUI LR 式画布蒙版工作流（拖拽移动/图层排序/A/B 加减/羽化/undo/翻页/per-photo 注入）+ 调色对话框实时预览。另含 `lr-merge` 多机数据包合并 + `lr-scan --sanitize` 脱敏导出 + TRAINING.md/tools 训练管线。**1075 测试全绿**（发布前扫描修复 2 Critical + 10 Major + 33 Minor） |
| v2.0.0 | GUI v2.0：拆包 + 活切换 + 工作区 | **发布准备（2026-08-25）**：`gui.py`（10k 行）拆为 `gui/` 包（app/theme/strings/widgets/workflows/state/bus）；语言/主题**活切换**（反向映射遍历器，不再销毁重建）；UiBus 事件总线（12 处内联 drain 统一）；Library/Develop/Export/Tools **工作区**（Develop=胶片条+真实管线防抖预览+常驻直方图+旁侧调整工具，Export=导出队列+输出设置，两页共享 tk.Variable）；缩略图 ThumbCache LRU；Linux 深色检测 + Windows DPI PMv2；GUI 测试 HOME 隔离不变量；`docs/GUI_UPGRADE_PLAN.md` 全案 |
| v2.1.0 | 抠图 / 背景移除 | **已发布 2026-08-25**：`--cutout` 紧凑 spec 四模式（`subject`/`person`/`object:label` AI 分割复用 v1.8 segmask 权重零新增下载 + `color:R,G,B[,tol][,feather][,invert]` 硬键控解白底文字/logo）→ alpha → PNG/WebP/TIFF/AVIF/HEIC 透明输出，JPEG 按文件报错不静默拍平；`ProcessOptions.cutout` 字段使 preset/REST/MCP 零胶水继承；GUI Export 选项 Tab 抠图区块。真图冒烟通过（2026-08-27：权重真实下载路径 + sha256 校验、cv2 5.0 推理、实拍柯基主体完整抠出、白底文字键控干净、JPEG 报错路径） |
| v2.1.1 | patch：慢网络下载加固 + CI 转正 | modelstore 断点续传（HTTP Range 收养死进程 `.part`，完整未改名 part 离线采纳）+ 3 次重试 + 读超时 30→60s + 成功后清扫全部 `.part` 残片（v2.1.0 真图冒烟实证的慢网络首用失败）；CI Linux xvfb GUI job 去掉 `continue-on-error` 转正 + actions checkout@v5/setup-python@v6（Node 20 弃用警告） |
| v2.3.0 | Agent 自动化闭环收口 | **已发布 2026-08-28**：`photo-s suggest` 规则型参数推荐（analyze→保守参数+理由，`--scale` 调幅，CLI/MCP/REST 三面，零模型）；**auto-tone 插件三线接线修复**（engine `auto_tone` 槽位 + MCP/REST 启动注册钩子，装后 MCP 25→30 工具）+ 修复 v1.7.1 潜伏的 `_job_worker` 锁重入死锁（batch_status 永久挂死）；batch 任务内建 audit（`audit:true` 附 pass_rate）；cull `--score` 加权评分 + `--burst` 连拍留最佳。SKILL.md/全仓文档同步；1277 测试绿 |
| v2.2.0 | GUI 编辑效率 | **已发布 2026-08-27**：LR 式**复制/粘贴设置**（`_DEV_FIELDS` 42 字段快照，Develop 按钮 + Export 队列「粘贴到勾选」+「已调」徽标；per-photo 覆盖层 `_photo_adjust` 经 `_per_file_overlay` 与蒙版合并注入批处理）；**逐照片撤销/重做**（上限 50、首次编辑记基线、沉降入栈、切照片 flush/加载、Cmd+Z 在 Develop 优先逐照片历史）；**导出配方**（22 输出字段规范值快照，gui_state 持久化，套用/存/删）。agent 面零改动；新增 `test_gui_v22.py` 15 测，全量 1256 绿 |
| auto-tone-v2.1.0 | 插件：风格化 + 场景自适应（训练侧 v2.1 同步） | **已发布 2026-08-28**：`auto_tone_with_style`（SigLIP 视觉分析 16 风格 top-K + Qwen3-VL 自然语言→9 字段偏置解析，Qwen 缺席回退 8 手工预设）与 `analyze_visual_style` MCP 工具（插件 4→6，装后 MCP 26→32）；Python API `auto_tone_with_scene`（552 张 LR 目录统计的 7 场景数据驱动偏置，包内 scene_biases.json）；SigLIP 主模型 `auto_tone_siglip_h192_d03.pt`（PSNR 32.21，+2.93 dB vs v7_clean，独立 release tag auto-tone-v2.1.0）；predictor 修复 LayerNorm→GELU→Dropout 重建（v7/siglip 双 checkpoint 验证，修复推理双 GELU bug）+ SigLIP sig_dim 推断；batch_auto_tone 加 style_desc；重存权重兼容 weights_only=True。1286 测试绿 + 真实权重 e2e |

## 规划中

### v2.3.0（已发布 2026-08-28 —— 保留立项研究结论；速览见下方「已发布」表）

> **立项研究结论（2026-08-27 全面盘点）**，四项不足按优先级：
>
> 1. **auto-tone 插件三线未接线（最严重）**：插件功能面完整（9 字段参数 + 置信度 +
>    RAG + 批量 + Qwen advisor，权重仅 4.6MB），但 engine 只有 lut/denoise 两个
>    provider 槽位（`auto_tone` provider 是死代码）；插件自带的 MCP 4 工具注册
>    （`register_mcp_tools`）与 REST 4 路由注册从未被主仓调用（唯一调用方是测试）；
>    `docs/PLUGINS.md` 的 `--preset auto-tone` 示例指向不存在的内置预设。
>    **用户安装了插件，agent 却完全看不到它。**
> 2. **analyze → 参数映射代码为零**：`AGENT_API.md` 的「判读速查表」只给 LLM 读；
>    代码里仅有 auto_exposure/auto_levels 两个单点。无网络/无插件时 agent 拿到
>    统计数据仍要自己猜参数。
> 3. **batch 异步任务无 audit 钩子**：REST/MCP `batch_start` 的 result 只有
>    BatchResult；验收要另调 `/audit`——闭环的 stop 条件不在任务里。
> 4. **挑片维度割裂**：cull 是 5 阈值二分类（无综合质量分、无连拍分组）；
>    keep-sharpest 藏在 dedup 里。摄影师挑片要跨三个工具拼。

**P0 — 插件接线修复**：
- [x] engine 增 `auto_tone` provider 槽位（色彩管理后、手动调整前；`--auto-tone 0-1`；
      缺插件 per-file 清晰报错 + 指向 suggest 替代；preset/REST/MCP options 零胶水继承）
- [x] mcp_server / server 启动时发现已装插件的 `register_mcp_tools` / `register_rest`
      并调用（hooks 协议 + base 默认 no-op 不误计；REST 类级补丁进程内 once + 插件侧
      幂等守卫防 do_POST 层层包裹）；实测装插件后 MCP 25→30 工具、REST 自动挂
      /v1/auto_tone* 路由
- [x] PLUGINS.md 示例修正（`--preset auto-tone` → `--auto-tone` + MCP/REST 自动注册）
- [x] **顺带发现并修复既有死锁**：`_job_worker` 在 `_JOBS_LOCK` 内调
      `cancel_checker()`（非重入锁重入）→ batch job 永久持锁、所有 batch_status
      轮询挂死（v1.7.1 起潜伏，既有测试只查工具名从未跑完 job）

**P0 — `photo-s suggest`（规则型参数推荐，零模型零依赖）**：
- [x] 新 `photo_s/suggest.py`：analyze 统计 → 保守建议（ev 拉回 0.5 / 过曝→
      highlight_recovery / kelvin·tint 偏→wb_temp=估计值·wb_tint 反向 / 低对比→
      contrast 轻乘 / 直方图两端未用满无裁切→levels[宽度≥80 防爆] / 低饱和→
      vibrance 护肤色 / blur+低对比双信号→clarity 轻量），每条带理由+依据指标；
      中性图 `suggested={}` + `neutral=true`；`--scale 0-1` 全幅度缩放
- [x] CLI `suggest`（人读/`--json`/`--scale`）+ MCP `suggest` 工具 +
      REST `POST /v1/suggest`
- [x] 分工写入 AGENT_API.md §7.1（规则层 vs auto-tone 风格层，可叠加）
- [x] 回归测试：`analyze → suggest → process → audit` 全链路（暗图修复后过闸门）

**P1 — batch 任务 audit 内建**：
- [x] REST `POST /process {"async":true,"audit":true}` 与 MCP
      `batch_start(audit=True)`：完成后对**输出**逐图 audit，result 附
      `audit {passed, reason}` + `audit_summary {pass_rate}`

**P2 — 智能挑片 v2**：
- [x] cull `--score`：加权综合分（曝光贴近 0.5×0.35 + 对比×0.25 + 清晰度×0.25 +
      饱和×0.15 − 过曝/欠曝惩罚）0-100 排序，附各分量（可解释），只排序不淘汰
- [x] cull `--burst [--gap S]`：EXIF DateTimeOriginal 聚类（无 EXIF 回落 mtime），
      组内留最高分（`burst_best` 标记）；`--list` 输出保留候选供管道
- [x] GUI Tools 卡片文案同步（评分排序 + 连拍留最佳）

**测试**：`tests/test_v23_loop.py` 21 个（suggest 规则/中性/scale/不可读/全链路/REST/MCP、
接线钩子真伪/once 幂等/engine 槽位缺失与委托、batch audit REST+MCP、cull 评分/EXIF·mtime
分组/留最佳）；test_mcp 工具表改核心子集断言（兼容插件加工具）。
**待发布**（版本 bump + RELEASE 流程，用户确认后执行）。

### v2.4.0（实施中 2026-08-29 —— 主题：所见即所得，滚得动 + AI 调色 GUI）

> 立项研究结论：v2.2 的 per-photo 覆盖层加深了「三处所见不一致」——Develop 预览
> 含覆盖层、⌘P 预览弹窗只走全局 options、review 灯箱/蒙版画布显示原图（三处同一个
> 照片长得不一样）。Library 每行 7 个 widget 全量重建（勾选一张也重建全部行），
> 几千张库可感知卡顿。§5 剩余四项（设置搜索/预设浏览器/快捷键表/首跑引导）全未做。
> **用户追加**：发布模型（auto-tone 插件）的 GUI 修图支持。

- [x] 三处所见统一：⌘P 预览经 `_per_file_overlay` 注入（staleness 键改有效
      options，覆盖层变化重渲）；review 灯箱异步管线渲染 + 「已调」徽标；
      蒙版画布底图走仅调色注入（不与画布蒙版双重应用）；共享
      `_render_adjusted_async`
- [x] Library VirtualGrid：固定行高 canvas 虚拟列表（数据模型 + 仅可视窗口物化，
      勾选/选中状态绘制时读取）——虚拟化涵盖并取代行级差量刷新；5k 基准
      首绘 20.9ms / 40 canvas 项（旧 ≈3.5 万 widget）、翻页 0.3ms；修
      yscrollcommand↔scrollregion 无限乒乓 + stat 失败 cache_key 隐患
- [x] Library 键盘评级 1–5 / P（EXIF 写入 + 行内星标）+ `?` 快捷键表；根级绑定
      + 模块/输入焦点双守卫；Enter 送修图、⌫ 移除
- [x] Develop before/after 并排 + 可拖分割线对比（overlay canvas，PIL 合成；
      旧 Label 缝不动）
- [x] 设置搜索（跨 4 Tab + Develop 面板，命中高亮 + 自动切换 + 滚动入视野）、
      预设侧栏浏览器（悬停=渲染 sig 替换的实时预览，不碰滑杆/撤销史；点击正式
      套用）、首跑引导卡（gui_state 持久化）
- [x] **AI 调色 GUI（用户追加）**：Develop「AI 调色」+ 强度下拉 → 插件预测 9
      参数写入逐照片覆盖层（可微调/可撤销/预览即时）；缺插件/失败清晰指引；
      真实权重 e2e（置信度 0.926，5.1s 含塔加载）
- [ ] 蒙版画布从弹窗升格进 Develop、审查灯箱吸收进 Library（§4 后续批）——
      **移至 v2.4.x/v2.5**：功能目标（WYSIWYG 统一）已达成，纯界面归位属
      布局重构，单独成批做回归面更可控

测试：`test_gui_v24.py` 32 项；全量 1308 通过。

### 全自动闭环批①：词汇表扩展 + 美学 verifier + ModelScope 塔源（实施 2026-09-02）

> 立项来源：v1.9 阶段 3 模型层差距分析的前两项（输出词汇表太窄、无 verifier
> 即无 stop 条件）。随 v2.4.0 一同发布或作 v2.4.1（发版时定）。

- [x] **局部调整词汇表（#1）**：auto-tone 输出新增加性键 `local:
      [{region, params}]`（region = v1.8 AI 蒙版词汇表 subject/person/
      object:label，params = mask_adjust 标量子集）；引擎新 `photo_s/autotone.py`
      把 9 全局字段按引擎调色顺序 + 局部调整过蒙版管线应用——**顺带修复
      v2.3 潜伏缺口：旧像素协议经插件 numpy 简化渲染，9 个预测字段只落
      exposure/contrast/saturation 3 个**；GUI「AI 调色」局部预测写 per-photo
      蒙版（与手动蒙版同通道，编辑器可改可删）；predictor 支持局部头
      checkpoint（local_state_dict/local_regions/local_params/local_ranges）
- [x] **训练侧**：lr-scan 导出 rating（Adobe_images.rating 0-5 星 = 个人美学
      标注）；`tools/prep_local_labels.py`（LR 几何蒙版 × AI 分割 IoU → 语义
      region 局部标签）；TRAINING.md §5.1/§5.2 契约文档
- [x] **美学 verifier（#2）**：插件 `core/verifier.py`——SigLIP 嵌入 + MLP
      回归头（单次前向 1-10 分，循环 reward/候选排序级）+ Qwen VLM LoRA 终审
      组合（`verify_aesthetic(prefer=auto|head|qwen)`，两者皆缺显式不可用，
      不静默给分）；`tools/train_verifier.py`（星级×2 或显式 score 训练头）
- [x] **audit 美学闸门接线（四面）**：`audit_image(aesthetic, verifier)`
      （闸门请求但插件缺席 → RuntimeError；verifier 无分数 → 该项 fail +
      原因进 reason）；CLI `--aesthetic`；MCP `audit(aesthetic=)` +
      `batch_start(aesthetic=)`（无插件 → job error 态非挂死）；REST
      `/audit` + `/process {async, audit, aesthetic}`；新 MCP 工具
      `verify_aesthetic` + REST `/v1/aesthetic/verify`
- [x] **SigLIP/CLIP 塔下载源切 ModelScope（用户追加）**：塔注册表
      （repo → sha256/size/modelscope 镜像，SigLIP sha 为 2.61GB 真实下载
      实测）；`PHOTOS_AUTO_TONE_TOWER_SOURCE=auto|hf|modelscope` 来源链
      （auto = HF 失败回落 MS）；HF hub 缓存命中零重复下载；复用 modelstore
      断点续传/重试/校验，镜像与上游 sha 不一致即报错。实测 MS 下载
      2.61GB @ ~21MB/s + SigLIP 编码验证通过

测试：`test_vocab_verifier.py` 25 + `test_vocab_plugin.py` 29；全量回归见提交。

### v2.5.0 候选（平台收尾 —— GUI_UPGRADE_PLAN §6 原案）

- [ ] macOS：PyInstaller windowed `.app` + dmg（codesign ad-hoc、Tk 8.6 pin）；
      `tk::mac::ShowPreferences/About` 菜单集成
- [ ] Windows：无控制台 `photo-s-gui.exe`（console=False，主 exe 不变）
- [ ] Linux：AppImage（可 allowed-to-fail）+ `.desktop` 随 sdist
- [ ] CI bundle 三平台矩阵 + GUI 冒烟三平台各一次

### 远期（数据/生态，未排期）

- **XMP 写出**（LR 双向互通收口）：lrxmp 已能 LR→PhotoS；写 `.xmp` sidecar 让 LR
  直接打开 PhotoS 调整续修——「agent 用的 Lightroom」定位的最后一块
- **CLIP 语义搜索/自动打标**：`photo-s index` + `find "日落 海边"`（lr-similar
  84 维特征已留升级口，换 CLIP embedding 即得；控制权重 ≤50MB 蒸馏模型）
- **美学 verifier**（v1.9 阶段 3 首步）：CLIP/小 VLM + 回归头 → audit 的 reward 闸门
  （复用 auto-tone 的权重发行/推理基建）
- **AI 超分**（Real-ESRGAN 小模型）：复用 modelstore + SCUNet 分块推理基建，
  交付导向 2x；先评估权重体积与速度
- **watch 联动**：监视目录 → suggest/auto-tone 动态调参 → audit 自动验收的
  无人值守管线（P0 落地后自然长出）
- **分发渠道**：Homebrew tap / scoop / winget / Docker 镜像（REST/MCP server 容器化）

### v1.8.0（AI 识别蒙版 + 笔刷 -- 主题：智能局部调整，方向已定）

> **实施（2026-08-21，发布就绪未发版）**：四项 + GUI 工作流全部落地，**1075 测试全绿**。
> 发布前全面扫描修复 2 Critical + 10 Major（mask_adjust 字符串键、exposure→ev 别名、
> combo 循环、per-photo 泄漏、NaN 静默黑图等）+ 33 Minor。
> 权重已选定并算好 sha256：U2Netp 4.6MB + PP-HumanSeg 6.2MB + YOLOv8n-seg
> **fp16 7.0MB**（EdgeFirst fp32 13.9MB 超网络切断线，转 fp16 后安全；cv2.dnn
> 实测 fp16 可用，结果与 fp32 一致）。**发布时须上传三个 onnx 到 v1.8.0
> GitHub release 附件**（URL 已在 segmask.py WEIGHTS 写死为
> `photo_s/releases/download/v1.8.0/*.onnx`，sha256 已 pin）。

- [x] **AI 分割蒙版**：`subject:`（U2Netp 显著性）/ `person:`（PP-HumanSeg 人像）/ `object:label`（YOLOv8n-seg，COCO 80 类）三类；新 `photo_s/segmask.py`（cv2.dnn 惰性导入 + modelstore 下载/校验/缓存 + 纯 numpy YOLO mask 解码+NMS）；**OpenCV 5.x 新图引擎 forward 失败自动回退经典引擎**（Paddle 导出模型 residual bug）；缺 cv2/权重抛清晰错误不静默。
- [x] **笔刷蒙版**：`brush:x,y,r|x,y,r|...`（`|` 分隔点，避免与 masks 的 `;` 冲突）；渲染为点间胶囊并集（纯 numpy）；**负点**（`-x,y,r` = 从蒙版减去，A/B 模式）；**GUI LR 式画布蒙版工作流**（勾选照片大图 + 多蒙版叠加分色半透明 overlay + 笔刷/线性/径向/颜色/AI 工具画布绘制 + **拖拽蒙版内部 = 移动位置** + **图层上移/下移排序** + A/B 添加/减去模式 + ◀▶ 翻页 + per-photo 蒙版经 `batch_process(per_file_options=)` 逐文件注入，未编辑照片自动回落全局蒙版）。**其他调色对话框（曲线/色轮/HSL/点颜色）内嵌照片预览条 + 翻页（点颜色支持点击取色）**。
- [x] 蒙版组合算子：`combo:A&B`（交集）/ `combo:A-B`（差集），引用已命名蒙版并替换之；`render_mask` 加 `refs` 参数，engine/GUI 传入全部 spec。
- [x] 复杂字符串参数局部化：`mask_adjust` 值支持 `curves={...}`/`hsl={...}`/`color_grading={...}`/`vignette={...}`/`grain={...}`（`{}` 包裹避免分隔符冲突，复用 grade.py 函数，蒙版内与全局数值一致）。
- [x] **lr-merge**（多机数据包合并：去重 + 图集复制 + 溯源；v1.7.1 之后补入）
- [x] **lr-scan --sanitize**（脱敏导出数据包：剥 EXIF 相对路径，配 `--images` 可直接 lr-train；v1.7.1 之后补入）
- [x] **TRAINING.md + tools/ 训练管线**（train_tone_torch.py CLIP+MLP 训练脚本 + llama_factory_lora.yaml + 隐私边界文档；lr-predict 自动识别 npz 格式开箱即用）

### v1.9.0（AI 智能修图 —— 主题：个人修图数据驱动的全自动调色；已发布，后续演进见本节）

> **目标**："agent 使用的 Lightroom"，最终 agent 全自动修图。
> **路线图（2026-08-21 定，三阶段）**：工具层（无模型补感知/循环/验收）→ 数据层（个人 LR 修图数据
> 入 PhotoS 参数空间）→ 模型层（verifier / 小模型微调）。
> **数据资产**：用户本人是摄影师，有海量 Lightroom 修图记录（RAW + XMP `crs:` 参数）——
> before/after 与工具使用轨迹天然成对；PhotoS 紧凑字符串参数空间即轨迹记录格式。

**阶段 1 — 工具层（纯工具，无模型）——v1.7.1 已全部落地（2026-08-21）**：

- [x] `preview`/`snapshot` 工具：缩放图 base64 + 直方图 PNG 进 MCP 结果（agent 视觉感知——analyze 数字之外直接看图）
- [x] `analyze` 区域反馈：grid 4×4/8×8 亮度/色偏 + 过曝/欠曝区域检测 + 启发式分区（天空/肤色）
- [x] MCP 异步 batch job（目录级 process + poll/cancel：batch_start/status/cancel）
- [x] `diff` 版本对比（PSNR/SSIM/MAD）；参数快照回滚 = 既有 `preset save/load`
- [x] `audit`/`quality-gate`（pass/fail + 原因——agent 的终止条件，无 stop 条件即无全自动）
- [x] **XMP `crs:` 桥接**（`photo_s/lrxmp.py`：LR 参数 ↔ ProcessOptions 互转；渐变滤镜 ↔ linear mask、径向 ↔ radial mask 映射）——个人数据管线，从远期提级
- [x] **轨迹日志**：`batch --trace DIR` 记 before-analyze → params → after-analyze（即训练数据格式）

**阶段 2 — 数据层（个人 LR 数据）——v1.7.1 已全部落地（2026-08-21）**：

- [x] LR 目录勾选「自动写入 XMP」→ lrxmp 批量解析 → 参数向量库（lr-scan 自动发现 .lrcat+.xmp）
- [x] before 图生成：`lr-scan --render-dir` rawpy 默认渲染（幂等）——一条命令产出完整训练包
- [x] 编辑配方聚类：`lr-recipes` KMeans 参数空间 → 个人风格配方库，簇中心 = PhotoS options
- [x] 相似修图检索：`lr-similar` 84 维内容特征 kNN（CLIP embedding 为升级路径，换特征即得）
- [x] 自动基调回归：`lr-train`/`lr-predict` 岭回归（纯 numpy 零 torch，任何机器可训）9 项全局参数；CLIP+MLP/torch 为升级路径
- [x] 教师评测集：`lr-eval` 采样 → before/after 渲染对（PhotoS 自渲染 after）+ 打分模板（评估先行）

**阶段 3 — 模型层（数据到万级后）**：

- [ ] 美学 verifier：CLIP/小 VLM + 回归头，做 reward 与验收闸门
- [ ] LoRA 微调小模型（Qwen3-VL 3B / MiniCPM-V 4.6）：before 图 → PhotoS 紧凑字符串
- [ ] （远期）RL 自探索：参数空间为 action、verifier 分数为 reward

### v1.6.0（LR 方向调色增强 —— 主题：专业调色）

> 需求来源：商业软件 LensPilot 以 photo_s 为底层图像管线，功能摸底（2026-08-18）指出
> 向 Lightroom 方向增强调色能力。定位约束不变：**批量/交付导向管线，不做交互式局部修图**。
> 全部 P0/P1 为**单图全局调整算法，纯 numpy/PIL 可实现，零新依赖**（打包环境已有 numpy/cv2/onnxruntime）。
> **实施（2026-08-18，已发布 v1.6.0）**：P0+P1 全部落地进 `photo_s/grade.py`（11 函数）+ 3 个 bug 修复 + 四层接线（CLI 11 flag / REST 自动 / MCP 33 参数 / GUI 11 控件），899 测试全绿。
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

**远期（不在 v1.7）**：~~XMP `crs:` 编辑参数读写~~（**已提级：v1.9+ 阶段 1 数据管线，见上节**——个人 LR 修图数据即训练基座；LensPilot LR 桥接的「双向 interchange」目标不变：我方调整可被 LR 直接打开续修，LR 修完的参数我方复现）；专有调色模型训练（v1.7 的紧凑字符串参数空间即模型输出词汇表 + analyze 统计即数据基座，训练管线见上节 v1.9+ 阶段 2/3）。

**定位修订（v1.7.0，2026-08-20）**：旧「明确不做」三条改判两条--
- **笔刷蒙版/AI 主体选择**：原判"交互重、与批量相悖"。改判依据：紧凑字符串建模使蒙版**可序列化进 ProcessOptions**，批量语义成立（相对坐标/命名引用）；AI 分割权重小模型化（<10MB）后成本可控。-> 拆进 v1.8。
- **镜头矫正**：原判"需 lensfun 级数据库，投入产出比低"。改判依据：手动三参数（畸变/去暗角/消 CA）零依赖即可覆盖常见修正，lensfun 自动识别留作远期插件。-> v1.7 已落地。
- **RAW 域编辑**：维持不做（画质追不上 LR 线性 RAW 管线，rawpy 解码后 sRGB 域调整即可，定位交付级）。

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

## 候选（未排期，2026-08-27 清理）

> 原候选 C/D/E 中已落地或已并入上方版本段落的条目移除；保留仍然成立的观察。

- 插件生态扩展的成本结构未变：每个官方 operation 插件都要新 provider 槽位、动
  引擎，跨层成本高——v2.3.0 的接线修复优先让**已有**插件的入口面（MCP/REST）
  通用化，再考虑新官方插件
- `photo-s-plugin-lut`（纯 numpy 无权重）的"零依赖纯代码"插件类型可继续探索

## 原则

1. **数据先行**：性能类改动先 `bench` 再动手，不拍脑袋上多进程
2. **主题集中**：一个 minor 一个故事，Release notes 好写、用户/agent 好感知
3. **patch 轻快**：小修复不等大轮，随时 `v1.3.1` 发（流程见 RELEASE.md / 发布记忆）
