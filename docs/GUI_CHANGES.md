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
| 第六轮 | 工作流补全 | 审查打分灯箱、去重查看器、画廊导出、摘要对话框可滚动（v1.1.0，见 §8） |

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

## 8. 第六轮：工作流对话框（v1.1.0）

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
全量 416 个。

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
