# PhotoS GUI 全面升级方案（v2.0 系列）

> **状态（2026-08-25）**：§3 全部 + §4 第一批已落地并合入 **v2.0.0** 发布
>（按用户决定，原 v2.1 内容并入 v2.0.0，不另立版本）。剩余 §4 后续批与 §5/§6
> 见各节进展块。变更明细：`docs/GUI_CHANGES.md` §13。

> 2026-08-25 起，主题：**GUI 架构现代化 + Lightroom 式工作流**。
> 定位不变："CLI for AI agents, GUI for humans" —— 本方案只动 human 面，
> agent 面（CLI / REST / MCP / JSON 契约）零改动。

---

## 0. 目标与红线

### 目标

1. **可维护性**：`gui.py` 9950 行单文件（`PhotoSApp` 一个类约 100 个方法）拆成
   按职责划分的包；消灭 CLAUDE.md 里记录的脆弱约定（"设置面板行号从 24 起"、
   "新 tk.Variable 必须放 `__init__`"）。
2. **工作流**：从"左列表 + 右滚动设置 + 10 个模态弹窗"升级为
   Library / Develop / Export 三模块工作区，浏览类工作流全部非模态化。
3. **观感**：主题 token 化、HiDPI 完善、深色模式三平台检测 + 实时跟随。
4. **规模化**：几千张照片的图库网格虚拟化，缩略图 LRU 缓存。

### 红线（每阶段验收必须全绿）

| 红线 | 说明 |
|---|---|
| **零新硬依赖** | `dependencies` 依旧只有 Pillow/rawpy；`gui` extra 依旧只有 tkinterdnd2。不引入任何 GUI/主题框架库 |
| **三平台矩阵** | macOS 10.15+（aqua）/ Windows 10+（vista）/ Linux X11 + Wayland(XWayland)；Python 3.9–3.12 |
| **lite 包可裁剪** | `photo-s-lite` 无 GUI 必须继续成立（CI 已断言 `gui` 子命令 exit 1） |
| **测试全绿** | 现有 1164 个测试（含 5 个 GUI 测试文件）每阶段保持通过；`gui.PhotoSApp` / `gui.run_gui` 公开 seam 不变 |
| **i18n parity** | zh/en STRINGS key 集合一致（parity 测试强制），语言切换不丢状态 |
| **打包体积增量 0** | 无新依赖，PyInstaller 产物大小不涨 |

### 为什么不换 GUI 框架（已评估，明确否决）

| 候选 | 否决理由 |
|---|---|
| PySide6/Qt | +150–200MB 打包体积；10k 行全重写；现有 GUI 测试全部作废；违背零依赖哲学 |
| Web/Electron | 需起本地服务，与桌面工具定位冲突；agent 的 serve 已占 HTTP 通道心智 |
| ttkbootstrap 等 | 新依赖；平台渲染不一致（macOS aqua 原生主题会被强行覆盖，回归 v1.6 之前的"black boxes"类问题） |
| **留在 Tkinter** ✅ | 三平台官方发行版自带；自绘控件（FlatButton/CurveEditor/ColorWheel/HSLPanel）已证明 Canvas 能力足够；lite 裁剪逻辑现成 |

---

## 1. 现状诊断（痛点 → 代码位置）

| # | 痛点 | 位置 |
|---|---|---|
| P1 | 单文件 9950 行 / 单类 ~100 方法，改一处怕动全身 | `gui.py` 全文 |
| P2 | 语言/主题切换 = 销毁重建全部控件，逼出"tk.Variable 必须放 `__init__`"的 footgun | `_set_language` / `_toggle_theme`；CLAUDE.md 不变量 #4 |
| P3 | 60+ 控件挤在 400px 单列滚动面板，靠手工行号排布 | `_build_settings_panel`（行号从 24 起的约定） |
| P4 | 10+ 工作流全是模态 Toplevel（审查/去重/对比/重命名/蒙版/监视/联系表/cull/hash/HDR/预设） | `_show_*` 系列 |
| P5 | 主窗口无 before/after 对比（对比能力锁在弹窗里）、无直方图常驻 | `_show_compare` / `_show_comparison` |
| P6 | 深色检测缺 Linux（回落浅色）；系统主题切换不实时跟随；手动 toggle 靠全量重建 | `_system_dark_mode` |
| P7 | 缩略图缓存是无上限 dict，大图库内存失控；列表全量重建行 | `_thumb_cache`（1831）/ `_refresh_file_list` |
| P8 | Windows 打包 console=True，GUI 启动带控制台黑窗；无 macOS .app | `photo-s.spec` / `packaging/` |
| P9 | Linux CI 只有 xvfb 冒烟，GUI 测试实际只在 Windows 真跑 | `.github/workflows/ci.yml` |
| P10 | 设置不可搜索、调整不可复制粘贴到多选（LR 的 sync）、无快捷键帮助 | — |

---

## 2. 版本切分（对齐"一个 minor 一个主题"的节奏）

| 版本 | 主题 | 工程量预估 |
|---|---|---|
| **v2.0.0** | 架构基建：拆包 + i18n 活绑定 + 主题 token + 平台检测补全 | 2–3 周 |
| **v2.1.0** | 工作区重构：Library / Develop / Export 三模块 + 非模态化 | 4–6 周（最大块） |
| **v2.2.0** | 交互效率：设置搜索 / 预设预览 / 复制粘贴调整 / 快捷键体系 | 2–3 周 |
| **v2.3.0** | 平台收尾：macOS .app+dmg / Windows 无控制台入口 / CI 三平台 GUI 矩阵 | 1–2 周 |

每阶段独立可发布、测试全绿、行为对用户只增不变（v2.1 的布局变化在发布说明里单列）。

---

## 3. v2.0.0 — 架构基建

> **进展（2026-08-25，第一批已落地，1179 测试全绿）**：
> - [x] 3.1 拆包：`photo_s/gui/` = app.py + theme.py + strings.py + widgets/
>   (flatbutton/editors/util/zoompan) + workflows.py + state.py；
>   `gui_widgets.py` 改 shim，`gui/__init__.py` 重导出全部旧名（测试零改动，
>   仅 test_gui_audit_fixes 的源码审计改为扫整个包）。**命名偏差**：STRINGS 放
>   `strings.py` 而非计划中的 `gui/i18n.py`——包内 `from . import i18n`
>   （photo_s.i18n）会产生相对导入歧义。`bus.py` 未建（queue+after-drain
>   约定继续生效，待 live-binding 一起做）。
> - [x] 3.3（部分）：theme token 化 + SPACING/RADIUS + Linux 深色检测
>   （gsettings → kdeglobals）；**实时跟随未做**（与 3.2 live-binding 同批）。
> - [x] 3.4：Windows DPI per-monitor v2 逐级回落（theme.apply_dpi_awareness）；
>   macOS Retina / tk scaling 验证待 CI 实跑。
> - [x] 3.5：ThumbCache 字节上限 LRU（256MB，线程安全，tests/test_theme.py）；
>   CI 新增 `test-linux-gui`（xvfb 跑 GUI 套件，`continue-on-error` 实验 job，
>   稳定后并入主矩阵）；lite spec excludes 显式列出 gui 子模块。
> **进展（2026-08-25，第二批已落地，1190 测试全绿）——v2.0.0 §3 全部完成**：
> - [x] 3.2 i18n 活绑定：**方案迭代**——500 个文本站点逐点注册不现实，改为
>   `_translation_remap` 反向映射遍历器（旧语言文本→新语言文本，同文多键多数
>   表决、平票丢弃保安全）；`_set_language` 不再销毁重建，滚动位置/折叠区状态
>   保留；`_toggle_theme` 同理走调色板值重映射遍历器。CLAUDE.md 不变量 #4 已
>   从硬约束降为约定。
> - [x] bus.py：UiBus 替换 13 处内联 drain（12 统一；preview 防抖混合轮询保留
>   为文档化例外，用 `drain_pending()`）。
> - [x] 3.3 实时跟随：FocusIn + 30s 轮询 `_recheck_system_theme`，手动 toggle
>   钉住（`_theme_user_override`）直至重启。
> - 新增 tests/test_gui_live.py（11 个：身份保留/无残留旧语言文本/重着色/
>   跟随与钉住/UiBus 语义）。


### 3.1 拆包：`photo_s/gui.py` → `photo_s/gui/` 包

```
photo_s/gui/            # 已落地（2026-08-25）
  __init__.py      # 兼容 shim：重导出全部旧名（测试/插件零改动）
  app.py           # PhotoSApp：窗口骨架、面板、全部工作流对话框、全局快捷键
  theme.py         # 调色板/字体/间距/圆角 token + 三平台深色检测 + DPI 链
  strings.py       # STRINGS（zh/en）——不叫 i18n.py，避开包内相对导入歧义
  state.py         # gui_state.json 持久化 + ThumbCache（字节上限 LRU）
  widgets/         # FlatButton / editors(曲线·色轮·HSL) / util / zoompan
  workflows.py     # 13 个 Tk-free seam 函数（app 薄委托，签名不变）
  bus.py           # UiBus：worker→UI 事件总线（12 处内联 drain 已统一）
  （待 v2.1）panels/     # library.py / develop.py / export.py / tools.py
```

迁移映射（现有方法 → 新家）：

| 现有块（gui.py 行号区间） | 去处 |
|---|---|
| 74–175 调色板/字体/深色检测 | `theme.py` |
| 177–1430 STRINGS 表 | `gui/i18n.py` |
| 1431–1674 FlatButton/canvas 工具/ZoomPan | `widgets/` |
| 1676–2100 `__init__`/状态持久化/快捷键 | `app.py` + `state.py` |
| 2191–3260 文件面板 + 设置面板 | `panels/`（v2.1 重组） |
| 3397–3830 曲线/色轮/HSL/点颜色对话框 | `dialogs/` + `widgets/` |
| 3831–5160 蒙版工作流 | `panels/develop.py` 素材（v2.1 升格） |
| 5799–6560 Tk-free seam 群 | `workflows/` |
| 6558–7110 审查灯箱 | `panels/library.py` 素材 |
| 7463–7660 列表刷新/缩略图 | `state.py` + `widgets/virtualgrid.py` |
| 8019–8178 `_build_options` | `panels/export.py` 素材 |
| 9294–9520 处理线程/进度 | `app.py` + `bus.py` |

拆包原则：**纯搬迁不改逻辑**，一个 PR 一个模块，每次全量测试绿。

### 3.2 i18n 活绑定（根治 P2）——已落地，实现为反向映射遍历器而非 bind_text 注册表（500 个文本站点逐点登记不现实；遍历器对新控件零约定，见上方进展块）

现状：`_set_language` 销毁重建所有控件 → 状态只能存活在 tk.Variable → CLAUDE.md 被迫写成不变量。

方案：注册表模式。构建控件时登记 `(widget, attr, key, kwargs)`：

```python
bind_text(label, "title")            # label.configure(text=_t("title"))
bind_text(btn, "start", fmt=...)     # 语言切换 → 只 configure(text=...)
```

语言切换 = 遍历注册表改 text，**不重建任何控件**。主题切换同理：token 化后
遍历登记的 `(widget, option, token)` 改颜色。CLAUDE.md 不变量 #4 随之废除，
替换为"新控件必须经 `bind_text`/`bind_color` 登记"。

### 3.3 主题 token 化 + 平台检测补全（P6）

- `theme.py` 单一来源：`COLORS`（现有两套 palette 平移）+ 新增
  `SPACING`（4/8/12/16/22）、`RADIUS`、字号（现有 FONT_* 平移）。
- light/dark key 集合 parity 测试（新增 `test_theme.py`）。
- **Linux 深色检测**：`gsettings get org.gnome.desktop.interface color-scheme`
  → `prefer-dark`；失败回落 xsettings/环境变量，最终回落浅色（保持现有
  try/except 永不崩风格）。
- **实时跟随**：窗口 `<FocusIn>` + 30s 轮询重检系统外观，变化时走 3.2 的
  token 重着色（不重建）。macOS `defaults read -g` / Windows 注册表已有。

### 3.4 HiDPI

- Windows：现有 `SetProcessDpiAwareness(1)` 升级为 per-monitor v2
  （`SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)`，
  失败逐级回落），并按 DPI 设置 `root.tk.call('tk', 'scaling')`。
- macOS：Tk 8.6 自动 Retina，验证缩略图/预览按 2x 渲染不糊（`winfo_fpixels('1i')` 探测）。
- Linux：尊重 `GDK_SCALE`，探测 Xft.dpi。

### 3.5 测试与 CI 基建（P9）

- Linux CI 的 test job 增加 `xvfb-run python -m pytest tests/ -q`（现在 GUI
  测试在 headless Linux 跳过、只在 Windows 真跑）→ GUI 测试三平台中两个平台
  常驻执行，Windows 继续作为真窗口会话验证。
- 缩略图缓存换 LRU（上限按字节计，默认 ~256MB，P7 的治标部分）。

---

## 4. v2.1.0 — 工作区重构（三模块）

> **进展（2026-08-25，第一批已落地，1199 测试全绿；发布时并入 v2.0.0，不另立版本号）**：
> - [x] 模块外壳：模块栏 + Library/Develop/Export/Tools 四帧，`_show_module`
>   纯 pack 切换（不销毁控件），活动模块持久化，`Cmd/Ctrl+1..4` 快捷键。
> - [x] Library：现有文件面板迁入，全宽（网格虚拟化 VirtualGrid 留后续）。
> - [x] Develop（新建）：胶片条（files 签名去重 + LRU 缩略图）+ 大图预览
>   （160ms 防抖、真管线渲染、stale 丢弃）+ before/after 切换 + 常驻直方图
>   与曝光/色温读数（`analyze_image`）。
> - [x] Export：导出队列（勾选照片 + 体积合计 + 空态）+ 输出设置 Notebook。
> - [x] **IA 修正（用户反馈）**：调整 Tab（影调/调色/矫正/局部）移入 Develop 右栏
>   （直方图下方、预览旁），Export 只留输出/水印/元数据/选项 + 照片队列——
>   两页共用同一组 tk.Variable。GUI 测试全面 HOME 隔离（gui_state.json 污染
>   曾引发跨文件级联失败）。
> - [x] Tools：12 张工作流启动卡片（仍打开既有对话框）。
> - [ ] 后续批：审查灯箱吸收进 Library、蒙版画布从弹窗升格进 Develop、
>   逐工具非模态面板化、VirtualGrid 网格、`ttk.PanedWindow` 分栏持久化。
> - 源头文案统一（消歧义票）：`more_hdr`/`more_watch` en 与标题键一致、
>   `mask_tool` zh 改"蒙版工具"。

### 4.1 信息架构

```
┌────────────────────────────────────────────────────────────┐
│  PhotoS    [Library] [Develop] [Export] [Tools]   ⚙ 🌐 ☀ 👤 │
├──────────────┬─────────────────────────────┬───────────────┤
│              │                             │               │
│  Library:    │  Develop:                   │  Export:      │
│  网格/列表    │  大图预览 + before/after     │  输出配置     │
│  过滤/评级    │  + 胶片条 + 直方图常驻       │  队列+进度    │
│  元数据面板   │  + 蒙版画布（升格自弹窗）     │  结果/报告    │
│              │  + 右侧折叠调色面板树         │               │
├──────────────┴─────────────────────────────┴───────────────┤
│  状态栏：选中数 / 体积 / 处理进度 ETA（现有底部栏平移）        │
└────────────────────────────────────────────────────────────┘
```

- 分栏用 `ttk.PanedWindow`，宽度可拖，记忆到 `~/.photos/gui_state.json`
  （现有 `_load_gui_state` 扩展）。
- **Library**：吸收现有文件列表 + 审查灯箱（`_show_review` 的评级/关键词/
  精选分拣）。网格用新的 `widgets/VirtualGrid`（Canvas 只渲染可视区 +
  固定行高 + 现有 after-drain 缩略图管线），评级★/旗标/色标直接标在缩略图上。
- **Develop**：主预览复用现有 `_preview` 真管线渲染（tempdir 机制不变）；
  before/after 三模式（并排 / 拆分线拖动 / 按住看 before）——把 `_show_compare`
  的同步缩放能力上移；直方图常驻（`metrics.analyze_image` 已有，加 PIL 绘制）；
  **蒙版工作流从模态对话框升格为模块内画布**（`_open_mask_workflow` 的
  拖拽/羽化/图层/A-B/笔刷/翻页逻辑整体平移）。
- **Export**：吸收 `_build_settings_panel` 的输出类区块 + 处理队列/进度/摘要。
- **Tools**：dedup / cull / hash / 联系表 / HDR / 监视 / 画廊导出集中为
  非模态面板（各自现有 seam 函数是 Tk-free 的，直接接新面板）。

### 4.2 非模态化原则

浏览/比对类一律面板化；Toplevel 只保留三类：**确认对话、文件路径选择、
阻塞式输入（重命名模板）**。语言/主题/处理期间的行为锁沿用现有
`processing` 门控。

### 4.3 设置面板重组（P3）

60+ 控件从"单列滚动 + 手工行号"改为 Develop 右侧**折叠面板树**：
基本（曝光/白平衡/色调）→ 曲线 → 色彩（HSL/色轮/点颜色）→ 效果
（纹理/清晰度/去雾/暗角/颗粒）→ 细节（锐化/降噪）→ 镜头 → 构图（裁剪/
旋转/打印尺寸）→ 元数据 → 水印。每个折叠区即现有 CollapsibleSection 的
增强版（记忆展开状态）。手工行号约定废除。

---

## 5. v2.2.0 — 交互效率包（P10）

| 功能 | 说明 |
|---|---|
| 设置搜索 | 设置树顶部搜索框，命中项高亮 + 自动展开所在折叠区 |
| 预设浏览器 | Export/Develop 侧栏列出内置 + 用户预设，键盘/悬停实时预览（复用 `_preview`，防抖） |
| 复制/粘贴调整 | LR 式 sync：Develop 里 ⌘C 复制当前参数 → 多选照片 ⌘V 批量粘贴（`replace(opts)` + `per_file_options` 已支持逐文件注入） |
| 调整历史 | 本会话参数快照栈（每次"应用"前压栈），一键回滚——与 preset 互补，不落盘 |
| 快捷键体系 | 现有 8 组全局快捷键扩展到三模块（网格评级 1–5、P 拒绝、D 开发、G 网格、\\ before/after），`?` 弹快捷键表 |
| 首跑引导 | 空窗口时显示三步引导卡（拖入照片 → Develop 调整 → Export 导出） |

---

## 6. v2.3.0 — 平台收尾（P8）

| 平台 | 内容 |
|---|---|
| macOS | PyInstaller windowed `.app` + dmg（`photo-s-mac.spec`：codesign ad-hoc、Tk 8.6 pin python.org 构建）；`tk::mac::ShowPreferences/About` 菜单集成 |
| Windows | 增加无控制台 GUI 入口 `photo-s-gui.exe`（spec 复制，`console=False`）；CLI 主 exe 保持 console=True 不变 |
| Linux | 可选 AppImage（`pkg2appimage`/appimagetool）；`.desktop` 文件随 sdist 分发；深色检测已在 v2.0 落地 |
| CI | bundle job 扩展三平台矩阵（win 完整+lite / mac dmg / linux AppImage 可选 allowed-to-fail）；GUI 冒烟三平台各跑一次 `PhotoSApp` 构建 + `_build_options` |

---

## 7. 多平台验收清单（每阶段通用）

- [ ] macOS 12+ / Windows 10 21H2+ / Ubuntu 22.04（X11 与 XWayland）手动过一遍冒烟
- [ ] 深色/浅色：三平台检测 + 切换 + PHOTOS_DARK 覆盖
- [ ] HiDPI：Windows 150%/200% 缩放、macOS Retina 截图对比
- [ ] zh/en：切换后无残留英文、无布局溢出（CJK 宽度）
- [ ] 拖放：tkinterdnd2 安装/未安装两态（未安装走按钮路径）
- [ ] 字体回落：Noto Sans 缺失的裸 Linux（容器）不崩
- [ ] `pip install photo-s-tools` 无 gui extra 时 CLI 全功能正常（GUI 可选性）
- [ ] lite bundle 断言继续通过

## 8. 风险与对策

| 风险 | 对策 |
|---|---|
| 拆包引入回归 | 纯搬迁 PR 化（一个模块一个 PR），每步 1164 测试绿；shim 保持 import 路径不变 |
| VirtualGrid 性能不达标 | 固定行高 + 可视区裁剪 + LRU 缩略图；先做 5k 张基准（bench 思路），不达标不上 |
| Tk 原生主题差异（aqua/vista/xpnative） | token 只作用于自绘/Canvas 控件；ttk 控件继续走系统主题（v1.6 "black boxes" 教训写进 theme.py 注释） |
| Wayland 原生不支持 tkinterdnd2 | 文档明确 XWayland 要求；拖放不可用时按钮路径兜底（现有） |
| macOS Tk 老旧（系统 Tcl/Tk 8.5） | README 已要求 python.org 构建；dmg 打包时冻结 Tk 版本 |
| 工程量超预期 | 版本切分已按可独立发布设计；v2.1 若超期可先发 Library+Develop，Tools/Export 面板化挪 v2.1.1 |

## 9. 成功指标

- 零新硬依赖；打包体积增量 0
- 冷启动 < 1.5s（main window 可交互）
- 5,000 张照片网格滚动无可感知卡顿（虚拟化 + LRU）
- 预览防抖刷新 < 300ms（沿用真管线渲染）
- 语言/主题切换 < 100ms 且不重建控件（活绑定）
- GUI 测试在 Linux(xvfb) + Windows 双平台常驻执行
