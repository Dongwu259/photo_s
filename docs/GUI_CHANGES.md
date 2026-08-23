# PhotoS GUI 变更文档（供其他 Agent 对接）

> 本文档记录 GUI 六轮改动的全部内容、接口契约和后续开发约定。
> 涉及文件：`photo_s/gui.py`（重写）、`photo_s/engine.py`（取消支持）、
> `pyproject.toml`（gui 可选依赖）、`tests/test_engine.py`（新增测试）。

---

## 1. 变更总览

| 轮次 | 主题 | 主要改动 |
|---|---|---|
| 第一轮 | Bug 修复 | grid 行冲突、拖放未接线、误删同名文件、getsize 崩溃、假取消、异常丢失等 11 项 |
| 第二轮 | UI 重做 | 修复右侧设置栏遮挡、去除全部 emoji、FlatButton、ttk 原生控件 |
| 第三轮 | 国际化 | 中/英语言切换、关于窗口、文案全部抽到 STRINGS 字典 |
| 第四轮 | 工具箱补全 | 4 个新区块（水印/多尺寸/影调/构图）、双击对比、处理队列追加 |
| 第五轮 | 界面现代化 | FlatButton 改 Canvas 药丸、卡片化布局、clam 主题（主题切换全量重染 ttk）、滚动抖动修复（卡片级绑定 + 边界吸附 + 去抖）、设置/MCP 对话框、插件管理器 |
| 第六轮 | 工作流补全 | 审查打分灯箱、去重查看器、画廊导出、摘要对话框可滚动（v1.2.0，见 §8） |
| 第七轮 | v1.4.0 深化 | EXIF 编辑器扩拍摄信息 7 字段、批量重命名实时预览、多图并排对比（首个 Canvas 缩放视口，见 §9） |
| 第八轮 | v1.6.0 工作流 | 评审灯箱加「移动精选/淘汰」（`_select_move` seam）、HDR 合并对话框（「更多工具」）、设置面板人脸模糊选项（见 §11） |
| 第九轮 | v1.8.0 蒙版工作流 | LR 式画布蒙版工作流（`_open_mask_workflow`）、调色对话框实时预览（见 §12） |

---

## 12. 第九轮：v1.8.0 蒙版工作流 + 实时预览

### 12.1 LR 式画布蒙版工作流（`_open_mask_workflow`）

- 入口：「更多工具」→ 蒙版；勾选照片打开 **1320x860** 大窗口（可缩到 1080x700）
- 画布：大图 + 多蒙版叠加（`_MASK_COLORS` 分色半透明 overlay）；笔刷/线性/径向/取色/AI 工具
- 蒙版类型全支持：linear/radial/color + AI（subject/person/object:label）+ brush + combo
- **拖拽蒙版内部 = 移动位置**；Alt 拖拽同样移动；图层列表上移/下移排序
- **A/B 加减模式**：选中笔刷蒙版后 A=加画、B=减画（负点 `-x,y,r` 编码，模式跨照片/撤销清零）
- 径向蒙版绘制时显示**虚线范围圈**；羽化滑杆 live（AI/笔刷蒙版同样生效，`,feather=` 序列化 round-trip）
- **undo**：50 层深快照栈，快照含 path（跨照片 undo 自动跳转）；apply-all 记全量快照
- ◀▶ 翻页（所有勾选照片），per-photo 蒙版经 `batch_process(per_file_options=)` 逐文件注入
  （engine 钩子保证无蒙版照片回落全局 options——见 §2.1 同款 seam）
- 序列化共享模块级 `_mask_spec_string`（workflow 与 v1.7 表单对话框共用，combo/负笔刷点编码统一）

### 12.2 调色对话框实时预览（v1.8.0）

- `_add_photo_reference(parent, on_pick, render_fn)`：内嵌照片预览条 + 翻页 + 点击取色；
  打开/翻页即渲染编辑器状态（不再停在原图）
- 四个对话框接线：曲线 `_curve_render` / 色轮 `_wheels_render` / HSL `_hsl_render` /
  点颜色 `_pc_render`——与引擎相同的 grade 函数与字符串构造，**所见即所得**
- 预览缩略图档位 48/96/144（移除 Label 字符单位 bug）

### 12.3 健壮性（发布前扫描修复，见 commit 历史）

- per-photo 蒙版跨文件泄漏（engine 钩子收 base options）
- combo/object/负笔刷点序列化崩溃与编码错误（共享 helper）
- AI 叠加层缺依赖一次性警告、坏蒙版段逐段容错（不再整串清空）
- 线性工具点击未拖动零长度防护、异类工具不覆写选中蒙版、切换蒙版先存滑杆编辑
- ai_cache 翻页/删除/撤销清理、50ms 关窗 after 回调防护、AI 分割 watch 光标

---

## 2. 对外接口契约（对接时依赖这些）

### 2.1 `engine.batch_process` 新增 `cancel_checker` 参数

```python
def batch_process(
    input_paths: List[str],
    options: ProcessOptions,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    cancel_checker: Optional[Callable[[], bool]] = None,   # 新增，默认 None
) -> BatchResult:
```

- `cancel_checker()` 返回 `True` 表示请求取消。不传时行为与旧版完全一致（向后兼容）。
- **串行模式（jobs=1）**：循环中断，未处理的图片**不出现在** `result.results` 中。
- **并行模式（jobs>1）**：进行中的任务正常完成；未开始的任务立即返回
  `success=False, error="已取消 Cancelled"` 的 `ProcessResult`（计入 `fail_count`）。
- 每个图片会调用 `cancel_checker` 两次（循环守卫 + `process_one` 入口），实现侧勿假设调用次数。
- **`BatchResult.fail_count` 语义微调**：现在是 `len(results) - success_count`，
  不再包含"因取消而未处理"的文件（旧版为 `total - success`）。

### 2.2 GUI 模块结构（`photo_s/gui.py`）

**入口**：`run_gui()`。有 `tkinterdnd2` 时用 `TkinterDnD.Tk()` 创建 root，否则 `tk.Tk()`。
`DND_AVAILABLE` 标志导出可检测。

**本地化**：

```python
STRINGS = {"zh": {...}, "en": {...}}   # 两个语言 dict 的 key 集合必须完全一致
DEFAULT_LANG = "zh"

class PhotoSApp:
    def _t(self, key, **kwargs) -> str   # 取当前语言文案，支持 {name} 格式化
    def _set_language(self, lang)        # 销毁并重建整个 UI
```

- `_set_language` 重建 UI 不丢状态：所有用户输入保存在 `tk.Variable` 和 `self.files`。
- 处理中语言下拉框被 `_toggle_settings` 禁用，重建不会打断批处理。
- **新增文案必须同时加到 zh 和 en**（冒烟测试断言两个字典 key 集合相等）。
- 文案中含字面花括号（如 `{date}` 变量说明）时，调用 `_t(key)` 不要传 kwargs，
  否则 `.format()` 会报错。

**FlatButton**（替代 `tk.Button`）：

```python
FlatButton(master, text, command, bg, fg="white", hover_bg=None,
           font=None, padx=16, pady=7, border_color=None)
```

- 基于 `tk.Label` 自绘。macOS Aqua 下 `tk.Button` 忽略 `bg/fg`（白字白底事故的根源），
  **GUI 内禁止再用 `tk.Button`**。
- 支持 `configure(state="disabled")`：文字变灰且点击被忽略。
- 悬停通过 `<Enter>/<Leave>` 切换 `hover_bg`。

**文件列表约定**：`ttk.Treeview` 的 **iid = 文件完整路径**。
`_remove_selected` 直接以 iid 删除，依赖此约定；改动 `_refresh_file_list` 时不得破坏。

**布局契约**：

- 右栏设置面板固定宽 `SETTINGS_WIDTH = 400`，**先 pack**（side=right），
  左栏文件列表后 pack 吃剩余空间。交换顺序会导致小窗口下设置栏被挤压（曾因此遮挡）。
- 设置面板滚动区：canvas 内嵌窗口宽度由 canvas 的 `<Configure>` 事件实时同步
  （`_on_canvas_configure`），不要写死宽度。
- grid 行号分配（`_add_section_label` 的 sep 占 row、label 占 row+1）：
  0 格式 / 2-4 压缩模式 / 5 质量 / 6 目标大小 / 7-10 缩放 / 11-13 输出 /
  14-16 命名 / 17-19 子文件夹 / 20-22 选项 / 23 spacer。新增区块需占用未用的连续三行。

**子文件夹预设**：`self._folder_preset_values = ["", "date", "camera", "date-camera", None]`
按 combobox **索引**映射（`None` = 自定义），不依赖显示文本（多语言安全）。

**线程模型**：处理在 daemon 线程跑，Tk 更新只通过 `root.after(100, _poll_progress)` 轮询
`_progress_lock` 保护的共享状态。工作线程禁止直接触碰 Tk 控件。

### 2.3 `pyproject.toml`

- 新增可选依赖：`gui = ["tkinterdnd2>=0.3.0"]`，并已并入 `all`。
- `pip install photo-s-tools[gui]` 启用拖放；未安装时 GUI 正常降级（隐藏拖放提示）。

---

## 3. 第一轮修复的 Bug 清单（回归参考）

1. 设置面板 grid 行冲突：row 6/8/11/13/15 多处控件互相重叠 → 全部重编号（见 §2.2 行号表）
2. 拖放从未接线：`tkinterdnd2` 只导入未使用 → 注册 drop target + `_on_drop`（支持文件和文件夹）
3. `_remove_selected` 按文件名匹配 → 改 iid=完整路径（同名不同目录文件不再误删）
4. `_update_stats`/`_preview` 裸调 `os.path.getsize` → `_total_size()` 容错（文件被移走不再崩）
5. 取消按钮无效 → engine `cancel_checker`（见 §2.1）
6. 批处理异常静默丢失 → `_batch_error` + `messagebox.showerror`
7. 对比窗口竖图溢出 + `input_size=0` 除零 → 限 400×320 + 保护
8. 处理完成后文件列表不刷新 → 完成后刷新并剔除已不存在的文件
9. `jobs` 解析：" 2 "/0/abc → strip + `max(1, int)`
10. 窗口居中负坐标 → `max(0, ...)` 钳制
11. 空文件夹无提示；死代码 `_settings_next_row` 删除

## 4. 第二轮 UI 重做要点

- 默认窗口 1040×680 → **1120×720**，最小 980×640，设置栏 380→400px
- 去除全部 emoji（macOS Tk 渲染为单色方块）；仅保留排版符号 `→` `·` `×` `—`
- 全部 `tk.Entry/Checkbutton/Radiobutton` → `ttk.*` 原生样式
- 字体 SF Pro（Tk 找不到）→ Helvetica Neue（darwin）
- Treeview：行高 26、斑马纹（tag `even`）、选中行 accent 色
- macOS 已知限制：ttk.Progressbar 颜色、tk 控件圆角不可定制，属正常

## 5. 第三轮国际化要点

- 单一语言显示（不再中英并排），设置栏内容宽度 374→342px
- 关于窗口 `_show_about()`：版本、功能、Python/Pillow 版本、
  可选组件安装状态（`importlib.util.find_spec` 探测）、MIT 协议

---

## 5.5 第四轮工具箱补全要点（Sprint 3）

设置面板行 0-23 已用满，新块从 **row 24 起**（`_add_section_label(row=N)` + 内容帧 `row=N+2`）：

| 区块 | label row | 内容帧 row | 控件 |
|---|---|---|---|
| Watermark 水印 | 24 | 26 | 文本 Entry、图片 Entry+浏览 FlatButton、位置 Combobox（`watermark.POSITIONS`）、透明度 ttk.Scale 0-100 |
| Multi-size 多尺寸 | 27 | 29 | `output_sizes` Entry（`label:WxH,...` → `_parse_sizes`） |
| Adjust 影调 | 30 | 32 | 5 条 ttk.Scale（brightness/contrast/saturation 0-2、gamma 0.1-3、sharpen 0-3，`_on_scale_change` 式取值 Label）+ 黑白/复古 checkbox |
| Composition 构图 | 33 | 35 | crop/crop_ratio/rotate/rotate_bg/pad/pad_bg Entry + flip Combobox `["","h","v"]` |

接口契约补充：

- **新 tk.Variable 必须放 `__init__`**（`_set_language` 销毁重建全部控件，状态只存活在变量里）。
- **队列追加**：`add_files_btn`/`add_folder_btn` 已存入 self 并豁免 `_set_state_recursive`（处理中保持可用）；`_append_files(new_paths)` 统一去重追加，处理中新增文件进 `_queued_files`；批完自动续跑（`_start_processing(pending, confirm_delete=False)`，取消不续跑、排队文件被删自动过滤）。
- **双击对比**：`file_tree` 绑定 `<Double-1>` → `_on_tree_double_click`；`_show_comparison` 已抽 `_show_comparison_for(r)` 供任意文件对比。
- `_build_options` 从 `.cli` 懒导入 `_parse_sizes`（无循环依赖）。
- `_set_state_recursive` 的 isinstance 列表无需新增类型（全部 Entry/Scale/Checkbutton/Combobox/FlatButton）。

---

## 6. 测试

```bash
python3 -m pytest tests/ -q     # 218 passed（Sprint 3 后）
```

- 新增 `TestBatchProcessCancel`（tests/test_engine.py）：串行取消跳过剩余、
  并行取消标记 Cancelled、无 cancel_checker 时全量处理。
- 冒烟测试模式（无显示环境也可参考）：直接实例化 `PhotoSApp(tk.Tk())`，
  可断言 grid 无重叠、设置栏 `reqwidth <= canvas 可见宽度`、
  `STRINGS["zh"]` 与 `STRINGS["en"]` key 集合相等、语言切换后状态保留。

## 7. 后续开发约定

1. GUI 内禁用 `tk.Button`，用 `FlatButton`；输入/勾选类用 `ttk.*`
2. 新文案双语同时添加，走 `_t()`；禁止在 GUI 文案中使用 emoji
3. Treeview 行 iid 必须是完整路径
4. 设置面板新增区块遵守 grid 行号分配与 canvas 宽度同步机制
5. 改 engine 批处理逻辑时保持 `cancel_checker`/`progress_callback` 向后兼容

---

## 8. 第六轮：工作流对话框（v1.2.0）

### 8.1 工具栏与处理期间锁定

文件面板第二行新增三个工作流按钮：`review_btn`（审查打分，主色）、
`dedup_btn`（去重）、`gallery_btn`（画廊）。`_set_state_recursive` 豁免元组
新增 `gallery_btn`（只读导出，处理期间可用）；`review_btn`/`dedup_btn`
处理期间自动禁用（EXIF 写入/文件移动会与管线竞争）。

### 8.2 审查打分灯箱（`_show_review`）

- 入口：选中树行 → 只审查选中；无选中 → 全部文件。
- **同步 helper（测试直接调用，无 Tk）**：
  `_review_scan(paths, progress_cb) -> {path: meta}`、
  `_review_save(path, rating, keywords, title) -> (ok, msg)`（差异计算 →
  `engine.apply_exif_tags` 部分更新：只改传入字段，其余 PhotoS: 段保留；
  PNG/无 piexif 逐文件捕获错误返回，不抛）。
- 交互：←/→ 导航、0-5 数字键评分（焦点在 Entry 时忽略）、关键词/标题、
  最低评分 + 关键词过滤（语义与 CLI `exif --show` 一致：`(rating or 0)`
  比较、关键词子串任一命中）、Escape/关闭前自动保存差异。
- 引擎修复：`_parse_usercomment` 多词标题回环（title 段为末段，剩余 token 合并）。

### 8.3 去重查看器（`_show_dedup`）

- **同步 helper**：`_dedup_scan(paths, threshold, progress_cb) -> (groups, scores)`
  （`dedup.find_duplicates` + 每图 `metrics.compute_blur_score`）、
  `_dedup_trash_path`/`_dedup_move_to_trash`（碰撞后缀 `a_1.jpg` 逻辑同
  dedup.py，移入首图目录的 `_duplicates_trash/`，**不删除**）。
- 交互：后台扫描（进度）→ 分组卡片（缩略图 + 清晰度 + ★最锐预勾选保留）
  → 执行：未勾选移入回收子文件夹（确认对话框）→ 主窗口 `self.files`
  同步剔除 + `_refresh_file_list`。

### 8.4 画廊导出（`_show_gallery_export`）

标题 / 缩略图尺寸（240-600）/ 输出目录 → 后台 `_gallery_build`（同步包装
`gallery.build_gallery`，测试可直接调）→ 完成显示路径 + 浏览器打开按钮。

### 8.5 摘要对话框（`_show_summary`）

messagebox → 可滚动只读 `tk.Text` Toplevel（长错误列表不再截断）+
「查看前后对比」按钮（`sum_view_compare`）。

### 8.6 线程约定（重要）

worker 线程**禁止**任何 Tk 调用（含 `win.after`——非主循环下会抛
`RuntimeError: main thread is not in main loop`）。统一模式：
worker 只 `queue.Queue.put(fn)`，主线程 `win.after(80, drain)` 循环消费；
对话框销毁后 drain 自动停止（`winfo_exists` 守卫）。

### 8.7 测试

新增 `tests/test_gui_workflows.py`（15 个）：同步 helper 全覆盖 +
对话框冒烟（有界 `root.update()` 轮询，不点启动按钮、不挂线程）。
全量 476 个（含安全回归测试，见 §8.12；更多工具与视觉预览见 §8.13）。

### 8.8 勾选式文件列表（替代选中集）

- **行式结构**：文件列表不再用 Treeview（单元格不能放控件、图像列渲染
  不可靠），改为滚动 canvas + 每行一个**真 `ttk.Checkbutton`**（与设置面板
  同款控件）+ 文件名/大小/格式/尺寸标签。滚动沿用设置面板方案（卡片级
  bind_all 滚轮 + 边界吸附 + 150ms 去抖）。
- **勾选**：状态存 `self._checked: set`（`__init__`，跨语言/主题重建存活）；
  每行的 `tk.BooleanVar` 每次构建时从集合重建；Checkbutton command 同步集合
  + 计数标签（不整表重渲染）。工具栏「全选/全不选」按钮 = `_toggle_all_checks`。
  程序化切换走 `_toggle_check(path)`（同步行变量，无全量刷新）。
- **选中（ephemeral）**：`self._selected_rows: set` — 点行切换高亮
  （accent 底色 + 白字），用于「移除」/曝光分析/双击对比；与勾选正交。
  BackSpace/Delete 绑在每行上删除选中行。
- **所有工作流动作作用于勾选文件**：`_start_processing`（交互启动）、
  `_preview`、`_show_review`、`_show_dedup`、`_show_gallery_export`。
  无勾选时提示 `check_none`。
- 维护规则：`_append_files` 新文件默认勾选；**目录递归扫描**
  （`scan_directory(p, recursive=True)` — 修复：照片在子文件夹时误报
  「没有图片」）；`_remove_selected`/`_clear_files`/去重移动同步剔除。
- `_set_state_recursive` 豁免 `file_rows_frame`/`file_list_canvas`
  （处理中列表区保持可用，同旧 file_tree 豁免）。
- 队列追加（处理中新增）不受影响：`_start_processing(pending)` 仍按显式
  列表运行。

- 勾选列渲染：Treeview 单元格只支持文字，勾选框是 16px PhotoImage 图形
  （`_make_check_images()`：未选=描边空框、选中=accent 填充+白勾），
  每次重建重新生成以跟随主题；引用存 `self._check_on_img/_off_img`
  （PIL 源图存 `_check_on_src/_off_src` 供像素级测试）。
- 修复：`PhotoSApp.__init__` 现在按本实例 `dark_mode` 重新 `_apply_palette`
  （COLORS 是模块级全局，前一个实例的切换会残留；同进程二次实例化或测试
  场景下第二个 app 会以错误的调色板构建）。

### 8.9 修复轮：跳过提醒 / 原生 RAW / 文件对话框焦点（v1.2.0 内）

- **跳过不支持文件**：`_append_files` 过滤 `ALL_INPUT_EXTENSIONS` 之外的文件
  （目录用 os.walk 计数、隐藏文件不计），计数进 `self._last_skipped`；
  `_add_folder`/`_add_files`/`_on_drop` 按通道弹窗：有跳过 → `dlg_skipped`
  （n=导入 m=跳过），全部不支持 → `dlg_no_supported`，不再直接报「没有图片」。
- **RAW 原生化**：`rawpy>=0.18.0` 从 `[raw]` extra 提升为核心依赖（三平台
  wheel）；`raw = []` 空 extra 保持 `pip install photo-s-tools[raw]` 兼容。
- **macOS Tk 文件对话框焦点 bug**：对话框关闭后按钮卡 hover 灰 + 任意点击
  重开对话框（Tk 8.6.18 仍存在）。`_after_file_dialog(btn)`（重置 hover 填充
  + 400ms 冷却门 `_dlg_guard_until`）+ `_dlg_cooldown_active()` 入口守卫，
  应用到添加图片/文件夹与全部浏览按钮（输出目录/白平衡/GPX/水印/画廊）。

### 8.10 修复轮：RAW 预览 / 全局快捷键（v1.2.0 内）

- **RAW 预览**：`_open_image_safe(path)` 模块 helper（PIL 打不开时回退
  `engine._get_image`（rawpy/HEIC））——审查灯箱、去重缩略图、前后对比、
  曝光分析直方图全部改走它；文件列表尺寸列对 RAW 走 rawpy 头部快读
  （`rawpy.imread(...).sizes`，不全量解码，防列表卡死）。
- **全局快捷键**（root 级绑定，跨语言/主题重建存活；⌘/Ctrl 双绑）：
  O 添加图片、⇧O 添加文件夹、R 开始处理、P 预览、E 审查、D 去重、
  G 画廊、**Esc 取消处理中任务**（空闲时无操作；Toplevel 事件不触达
  root 绑定，对话框自身 Esc 不受影响）。处理中仅添加类可用（与工具栏
  锁定一致）。About 对话框新增快捷键清单（`shortcuts_text`）。
- 注意：root 绑定在 `__init__` 时捕获方法引用——测试补丁需在建 app 前
  改类方法；macOS 合成按键事件需 `focus_force()`。

### 8.11 全局撤销（v1.2.0 内）

- **撤销栈**：`self._undo_stack`（上限 10，`__init__` 创建，跨重建存活）；
  `_push_undo(label, run)` 记录，工具栏「撤销」按钮（`undo_btn`）+
  ⌘Z/Ctrl+Z（`_undo`）。栈空时按钮禁用；处理中锁定（`_sync_undo_btn`
  尊重 `self.processing`）。
- **可撤销操作**：
  - 列表移除 → `_restore_removed(pairs, checked)` 按原索引插回 + 恢复勾选；
  - 去重移入回收 → `_dedup_move_to_trash` 现返回 `(moved, failed,
    moved_map)`（original→trash 路径），`_restore_dedup` 移回原位并回到
    列表（目标位被占则跳过）；
  - 审查打标写入 → `_review_save` 成功后入栈，**全量还原**：
    `apply_exif_tags` 现支持显式清除语义（`rating=None` / `keywords=""` /
    `title=""` 清空对应字段，三者全空时整个 PhotoS: 段被移除）——首次打分
    也能撤销回"未评分"（`_write_usercomment` 同时修正空段残留）。
  - 审查窗口每次翻页从磁盘重读元数据（撤销 / 外部 CLI 写入在下次翻页时
    可见，不再用过期缓存）。
  - **灯箱内撤销**：root 级 ⌘Z 到不了 Toplevel 窗口（用户在审查窗口里按
    ⌘Z 无响应 = "无法撤销"的真相）。窗口内新增 ⌘Z/Ctrl+Z + 「撤销」按钮
    （`undo_current`）：撤销当前图片最近一次保存（`_review_save` 现返回
    `(ok, msg, revert, entry)` 四元组），同步从全局栈移除该条目保持 LIFO
    一致，随后从磁盘重读并刷新评分/输入框。`_push_undo` 返回 entry 供
    调用方移除。
- 快捷键清单（About + STRINGS）同步加入 ⌘Z 行。

### 8.12 发布前安全修复（v1.2.0 内，security review 产出）

- **EXIF 重命名路径穿越**（engine/rename）：`{make}` 占位符曾直接使用
  未净化的 EXIF Make tag（仅剥 NUL）——攻击者可构造
  `Make = "../../target/evil"` 的图片，用户用 `--pattern '{make}_{original}'`
  + `-o out`（或 REST /process、/rename）处理时文件逃出输出目录覆盖任意
  路径。修复：
  - `_extract_exif_metadata` 现在像 `camera` 一样净化 `make`（不安全字符
    → `_`）；`DateTimeOriginal` 派生字段（`year`/`month`/`day`/`date`/
    `time`）仅当各段全为数字才采用（`"../../../etc:08:15…"` 这类被拒）；
    `iso` 仅保留数字。全部消费方（CLI rename/compress/batch、REST、
    GUI folder vars）共用此函数，一处净化全链安全。
  - 纵深防御 `_has_path_traversal()`：渲染出的文件名若含 `/`、`\`、
    `:`（Windows `C:` 段会让 `ntpath.join` 丢基础目录）或为 `.`/`..`
    则拒绝——rename 记 error，engine 回退 prefix/suffix 命名；folder
    pattern 段过滤同步补 `:`。
- **localhost CSRF 浏览器劫持**（server）：`photo-s serve` 默认无 token，
  `_read_json` 无视 Content-Type——恶意网页可用 `text/plain` 简单请求
  （无 CORS 预检）对 127.0.0.1 发 POST，`/process`（可 `remove_original` +
  递归扫目录）、`/rename`、`/contact-sheet` 均构成删图/改名原语。修复：
  `_authed` 无 token 时校验 `Origin` 头，跨域请求拒绝（浏览器 fetch/XHR
  必带 Origin；CLI/curl/agent 不带 Origin 不受影响）。`--token auto`
  仍是最强防护。

### 8.13 更多工具入口 + 视觉预览（v1.2.0 内）

审计发现 6 个 CLI/引擎功能无 GUI 入口，本轮补全：

- **工具栏「更多工具」菜单**（`more_btn` + `_post_more_menu`，`tk.Menu.tk_popup`）：
  目录监视 / 联系表 / 曝光筛选 / 校验和 / 预设。`more_btn` **不在**锁定豁免元组——
  批处理期间整体锁定（与 review/dedup 一致）；`preview_btn` 保持豁免（只写临时
  目录，安全）。
- **视觉预览**（`_preview` 从文字弹窗改为真实画面）：选中图经**真实管线**
  `process_image` 渲染到 `tempfile.mkdtemp`，原图↔处理后并排；drain 循环对比
  `_build_options()` 签名，连续 5 tick（~400ms）稳定且无 in-flight 才渲染；
  `_preview_options` **强制 `remove_original=False`**（预览永不删源，最高优先级
  不变量）；临时目录在窗口销毁、渲染结束后由 root-drain 清理（绝不边写边删）。
- **目录监视**（`_show_watch`）：watchdog 后台 daemon，`start_watching` 新增
  `stop_event` 参数（CLI 默认 None 行为不变）；关闭对话框即停止；成功结果
  `_append_files` 回主列表。缺 watchdog 给安装提示。
- **联系表**（`_show_contact_sheet`）：列数/缩略图/文件名/背景色 → 线程
  `build_contact_sheet` → 打开。
- **曝光筛选**（`_show_cull`）：5 个阈值 → `cull_files`（**新 `photo_s/cull.py`**，
  cli.py cull handler 委托复用，输出逐字节不变）→ 结果表 + 「仅保留符合的」
  从列表移除并 `_push_undo`（`_restore_removed` 还原）。
- **校验和**（`_show_hash`，ttk.Notebook 两 tab）：生成清单（`compute_checksums` +
  `write_manifest`）/ 校验（`verify_manifest`，缺失与不匹配明细表）。
- **预设**（`_show_presets`）：`list/save/load/delete`；`_apply_options_to_ui`
  把 ProcessOptions 反向映射回全部 tk.Var（含 `target_size_bytes`→模式+值+单位、
  `output_sizes`→`label:WxH` 序列化；无对应 var 字段跳过，逐字段 try/except）。
- **测试**：`tests/test_cull.py`（8）、`tests/test_watcher.py`（2，watchdog 启动
  竞态：观察器就绪前写入的文件会丢事件 → 先等 1.5s 再落文件）、
  `test_gui_workflows.py` 增 seam 直调 + 5 对话框 smoke + 预览渲染/临时目录清理 +
  锁定扩展。全量 476 个。

### 8.14 LUT 调色入口（v1.3.0 内）

- 设置面板「校正」区新增 **LUT 调色**：`.cube` 文件路径输入 + 浏览按钮
  （`_browse_lut`），也可直接填预设名（装 `photo-s-plugin-lut` 后可用
  `filmic-v1` 等）。`self.lut_file` 放 `__init__`（不变量 #4）；STRINGS zh/en
  各 2 key（`lut`/`lut_hint`，#5）。
- `_build_options` 接 `lut_file`（空 → None）；`_apply_options_to_ui` 反向映射
  加入 `lut_file`（预设加载往返）。
- 引擎侧：`ProcessOptions.lut_file` + 管线新 provider 槽位（影调段后、白平衡前，
  `find_provider("lut")` 优先，否则 `photo_s.lut.apply_lut` 内置三线性）。

---

## 9. 第七轮：v1.4.0 深化（EXIF 扩展 / 重命名预览 / 多图对比）

### 9.1 EXIF 编辑器扩展（review 灯箱内）

- `_review_save` 签名扩展：`make/model/lens/iso/shutter/aperture/date` 关键字参数。
  `None` = 不动；字符串（含空串 = 清除）= 写入；与当前值相同不进 tags（diff-only）。
  键映射：`aperture`→引擎 `fnumber`、`date`→引擎 `datetime`、`model` 对比 meta
  的 `camera` 键。undo revert 覆盖全部新字段。
- `_review_scan` 的 meta 含 `lens/fnumber/shutter`（来自 `read_exif_metadata` 新键）。
- 注意坑：meta 的 `date` 是 `YYYY-MM-DD` 显示格式，写 EXIF 前须经模块级
  `_exif_datetime_str(meta)` 拼 `time` 并转成 `YYYY:MM:DD HH:MM:SS`。
- 引擎侧（同轮落地）：`_EXIF_TYPED_TAGS`（engine.py）支持 SHORT/RATIONAL 写入
  （iso/fnumber/shutter/focal/lens），`_parse_rational_str` 容错；CLI `exif`
  新增 `--lens/--iso/--shutter/--aperture/--focal`。

### 9.2 批量重命名实时预览（`_show_rename`）

- 入口：工具行 `rename_btn`；作用于 `_checked_files()`。
- **同步 helper**：`_rename_preview(paths, pattern, output_dir, overwrite) -> rows`。
  `rename_files(dry_run=True)` + **批内撞名检测**：逐字重放引擎 `_unique_target`
  循环（原始 stem 上计 clean counter：`photo.jpg → photo_1.jpg → photo_2.jpg`；
  v1.5.0 修复了旧的 `photo_1_2.jpg` 连续加后缀怪癖——预览必须与真实执行逐字节
  一致，parity 测试钉住），重复目标标 `conflict`。
- UI：模板 Entry（默认取 `rename_pattern` var）/ 就地或复制单选 / overwrite 复选 /
  三列 Treeview（conflict 黄、error 红）；300ms debounce + token 防过期 worker 覆盖。
- 执行前 `askyesno`（不接 undo 体系）；就地重命名后 `self.files`/`self._checked`
  按 ok 行 old→new 重映射再 `_refresh_file_list()`。

### 9.3 多图并排对比（`_show_compare`）—— 首个 Canvas 缩放视口

- 入口：工具行 `compare_btn`（`_set_state_recursive` 白名单，处理中可用）；
  2-4 张 checked，超出取前 4。
- **Tk-free `_ZoomPanState`**（模块级纯数学）：zoom ∈ [1,16]（1=适配），中心点
  比例坐标 clamp 到 `[1/(2·zoom), 1-1/(2·zoom)]`；zoom 回 1 中心重置 (0.5,0.5)。
- N 个 `tk.Canvas` 各自持有独立 `_ZoomPanState`：滚轮缩放与左键拖拽默认只
  作用于鼠标下面板（per-panel）；左下角「同步缩放」勾选框（`compare_sync_zoom`，
  默认关）勾选后滚轮联动全部面板；双击全部复位。
- 渲染：比例窗口 → `Image.resize(size, LANCZOS, box=...)` 一步裁剪+缩放（保持
  宽高比，背景留白）→ ImageTk 存 panel dict 防 GC；`after(60)` 单槽 debounce；
  `<Configure>` 重绘。滚轮（macOS `<MouseWheel>` + X11 `Button-4/5` 按平台绑）
  缩放、左键拖拽 pan、双击 fit。
- 加载：worker `_open_image_safe(path).convert("RGB")`（解码留在 worker），
  queue+drain 回 UI；失败面板画错误文字。

### 9.4 测试

`test_gui_workflows.py` 新增 23 项：`TestReviewExifEditor`(6)、`TestRenamePreview`(6，
含预览=真实执行 parity)、`TestZoomPanState`(8 纯数学)、`TestCompareDialog`(3 smoke)。
全量 689 个。

## 10. 第八轮：启动语言自动检测 + 持久化（v1.5.0）

- **启动语言**：`DEFAULT_LANG="zh"` 不再是启动默认，只作 `_t` 缺 key 回退常量。
  启动语言来自 `photo_s/i18n.py` 的 `resolve_language(use_config=False, use_persisted=True)`：
  **持久化用户选择 > `PHOTO_S_LANG` env > 系统检测**（macOS `defaults read -g
  AppleLanguages` / Windows `GetUserDefaultUILanguage` / Linux `LANG`/`LC_ALL` /
  `locale.getlocale()` 兜底，每级 try/except 永不崩，`_system_language()` 记忆化）。
  接线点：`run_gui()` 预置标题、`PhotoSApp.__init__` 的 `self.lang`。
- **持久化**：用户经语言下拉手动切换（`_on_language_selected`）时写
  `~/.photos/language`（纯文本单 key，`i18n.save_language`）；重启后 persisted
  值优先于 auto-detect。**持久化只在用户动作处发生**，`_set_language` 内不写，
  程序化重建不会覆盖用户选择。文件读写 try/except 吞 OSError（GUI 永不崩）。
- **GUI 自己的 STRINGS 留在 gui.py 不动**，只 import i18n 的 resolve/save；
  CLI 字符串表在 `i18n.STRINGS`（zh/en parity 测试分开强制）。
- 测试：test_i18n.py（`TestPersistence` 磁盘回环、`resolve_language` 优先级链）。

## 11. 第九轮：选片归档 / HDR / 人脸模糊（v1.6.0）

- **评审灯箱「移动精选/淘汰」**：`_show_review` 过滤行下方新增 select 行
  （精选/淘汰目录 entry + 📁 浏览 + 主按钮）。作用对象 = 当前过滤集
  `state["seq"]`；先 `save_current()` 落盘待定评分再 `_select_move`（读 EXIF
  rating 判双阈值：≥4 精选、≤2 淘汰、3/未评分原地）。移动后从 seq 摘除已移
  文件并 `show()`（空 seq 回退全量）。Tk-free seam：`_select_move(paths,
  selects_dir, rejects_dir, keep_min, reject_max, mode)` → (results, ok,
  err, errmsg)，复刻 CLI `select` 语义（copy2→os.replace→删源原子 move）。
- **HDR 合并**：「更多工具」新增 `_show_hdr`：取勾选文件（需 ≥2），输出路径 +
  「手持对齐」勾选，worker 线程跑 Tk-free seam `_hdr_merge(paths, output,
  align)`（opencv MergeMertens 曝光融合；opencv 缺失/AlignMTB 坏 build 的
  错误经 status 显示，不静默）。
- **设置面板人脸模糊**：元数据区（`sec_metadata`，meta_frame row 6-7）新增
  blur_faces 下拉（关闭/模糊/马赛克，本地化标签）+ 外扩 % entry。⚠️
  `_build_options` 把**本地化标签反向映射**回 "blur"/"pixelate"（combobox
  values 是显示文本不是选项值）；`_apply_options_to_ui` 正向映射（预设加载
  时）。tk.Variable（`self.blur_faces`/`self.blur_faces_margin`）按约定放
  `__init__`。
- 新增 GUI STRINGS（zh/en 各 7+）：`review_select_lbl/rejects_lbl/go/browse/
  need_dir/done/done_warn`、`more_hdr`、`hdr_*`（title/need_files/count/output/
  align/merge/done/failed）、`blur_faces/blur_faces_off/blur_faces_blur/
  blur_faces_pixelate/blur_faces_margin_lbl/blur_faces_hint`。

## 13. 第十轮：RAW/JPEG 输出质量设定（v1.9.0）

- **设置面板「选项」区新增两行**（`opts_frame` row 11-12，jobs 之后）：
  - **JPEG 色度子采样**（`self.jpeg_subsampling`，tk.StringVar 放 `__init__`，
    combobox 444/422/420，默认 420）：444 = 全色彩（体积更大），422/420 依次
    更小。对应 `ProcessOptions.jpeg_subsampling` → `_save_image`
    `save_kwargs["subsampling"]`（PIL 0/1/2）。
  - **RAW 去马赛克算法**（`self.raw_demosaic`，combobox
    auto/ahd/vng/ppg/dcb/dht/amaze，默认 auto）：映射 rawpy.DemosaicAlgorithm；
    amaze 质量最高最慢。对应 `ProcessOptions.raw_demosaic` →
    `_load_raw_via_rawpy` kwargs。
- **RAW 解码自动打 sRGB ICC**（引擎层，非 GUI 选项）：rawpy 解码像素本就是
  sRGB（output_color=sRGB），解码后 `img.info["icc_profile"]` 自动补 sRGB
  profile → 输出 JPEG/TIFF/PNG 自带色彩空间标记（`--scrub` 仍会剥离）。
- **修复隐藏元数据丢失 bug**：`apply_tone_adjustments` 的
  `ImageEnhance.Brightness/Contrast` 返回空 `.info` 的新图，任何
  `--brightness`/`--contrast` 都会静默丢掉 EXIF/ICC/DPI——现已快照+回填
  `img.info`（grade.py/mask.py 已有同类约定，这是最后一处漏网）。
- 新增 GUI STRINGS（zh/en）：`jpeg_subsampling`、`raw_demosaic`。

- **导出锐化滑杆**（`adj_frame` row 7）：`self.export_sharpen`（tk.DoubleVar 放
  `__init__`，0-2，默认 0=关）。对应 `ProcessOptions.export_sharpen` →
  管线 blur_faces 之后、EXIF 提取之前的**输出级 USM**（`grade.apply_export_sharpen`，
  半径 `0.5 + max_dim/4000` 随最终输出分辨率缩放，LR 式）。与中段 `sharpen`
  并存；`_apply_options_to_ui` 把 None → 0.0。
- **内置预设 lr-look**（presets.py `BUILTIN_PRESETS`，零文件写入）：S 曲线 +
  微自然饱和 + export_sharpen=1.0。CLI/GUI/MCP 经 `load_preset` 统一可用；
  用户同名预设覆盖内置。⚠️ `_apply_preset_defaults` 现在跳过「等于 dataclass
  默认值」的字段——内置预设的默认 suffix 不再覆盖 batch 的 `_processed`
  （修了一个潜在的用户预设也受影响的问题）。

- **高光恢复滑杆**（`adj_frame` row 8）：`self.highlight_recovery`
  （tk.DoubleVar 放 `__init__`，0-1，默认 0=关）。对应
  `ProcessOptions.highlight_recovery` → 管线 auto_levels 之后、几何之前的
  LR 式高光压缩（`grade.apply_highlight_recovery`，200 起阈值 + 幂曲线 +
  天花板随强度下降，单调、中间调不动，LUT per-channel）。
- **RAW 色彩空间下拉**（`opts_frame` row 13）：`self.raw_color_space`
  （sRGB/AdobeRGB/ProPhotoRGB，默认 sRGB）。sRGB 自动打 ICC；宽色域不加
  标记（PIL 无对应内置 profile）。
- **RAW 16-bit 勾选**（`opts_frame` row 14）：`self.raw_16bit`
  （tk.BooleanVar）。解码 16-bit，TIFF 输出经 tifffile 写 16-bit（需
  `pip install tifffile`，缺失抛清晰 per-file 错误）；JPEG/PNG 回退 8-bit。
- **镜头档案下拉**（`sec_lens` row 6）：`self.lens_profile`
  （tk.StringVar，值 = lens-profile save 维护的档案名）。管线开头把档案
  解析进 lens_distort/vignette/ca（显式参数优先；未知档案 per-file 报错）。
- 新增 GUI STRINGS（zh/en）：`highlight_recovery`、`raw_color_space`、
  `raw_16bit`、`lens_profile`。
