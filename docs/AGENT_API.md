# PhotoS Agent 对接文档（CLI JSON + REST API）

> 给 host agent / 跨进程调用方的单一对接文档。定位：**CLI for AI agents**。
> 覆盖：CLI JSON 契约、退出码约定、`serve` REST API（含异步任务/进度/取消）、配置文件优先级。
> 面向 Python 宿主的最简路径：`from photo_s.engine import batch_process`（无 IPC 开销）。

---

## 1. 四通道速览

| 通道 | 适用场景 | 说明 |
|---|---|---|
| Python 直调 | 宿主是 Python | `from photo_s.engine import ProcessOptions, batch_process` |
| `photo-s ... --json` | 一次性脚本 / CI | 每次调用有 ~200-300ms 解释器启动开销 |
| `photo-s serve` | 跨进程 / 长任务 / 需进度与取消 | stdlib HTTP，同步 + 异步任务两种模式 |
| `photo-s mcp` | Claude Desktop / MCP 客户端 | stdio MCP server，26 核心工具 + 插件自动注册（需 py3.10+ 与 `photo-s-tools[mcp]`） |

---

## 2. CLI JSON 契约

### 2.0 `schema_version`（所有 JSON 输出的契约版本）

**所有 JSON 输出（CLI `--json`、REST 响应、MCP 工具返回）的顶层都带 `schema_version` 整数键**，
与业务键**并列（additive），不是信封**——即 `{"schema_version": 1, "summary": {...}, ...}`，
现有键完全保留，旧消费者照常工作。

契约规则：
- **新增 key 是 additive**：消费者必须**忽略未知键**（forward-compatible）。
- PhotoS **只在 breaking 变更**（重命名/删除/改语义的键）时递增 `schema_version`。
  纯新增 key 不递增。
- 它是**全局单一整数**（当前 = 1），不与 PhotoS 发布版本号绑定。

### 2.1 支持 `--json` 的命令与输出 shape

> 以下每行的 shape 均**额外包含 `schema_version` 顶层键**（表格不再逐行重复列出）。

| 命令 | stdout JSON shape | 说明 |
|---|---|---|
| `compress` / `batch` / `convert` | `BatchResult`：`{"summary": {total, success, failed, total_input_size, total_output_size, saved_bytes, saved_percent}, "results": [ProcessResult]}` | `ProcessResult` 含 `input/output/input_size/output_size/input_format/output_format/input_dims/output_dims/status/error/quality/ssim/blur_score` |
| `check` | `{"checked", "ok", "corrupt": [{"path", "error"}]}` | 损坏文件检测 |
| `dedup` | `{"count", "duplicate_count", "savings_bytes", "groups": [{"hash", "paths"}]}` | 感知哈希去重；`--action keep-sharpest` 连拍保留最清晰 |
| `rename` | `{"total", "ok", "results": [{"input", "output", "status", "error"}]}` | |
| `contact-sheet` | `{"output", "count"}` | |
| `info` | `{"version", "input_extensions", "formats", "writable"}` | 与 `GET /info` 一致 |
| `exif --show` | `{"count", "results": [{path, date, camera, iso, focal, rating, keywords[], title, caption}]}` | 读取 + 筛选（`--rating-min/--rating/--keywords/--camera/--date-from/--date-to`） |
| `exif --list` | 匹配路径（每行一个） | `--show` 的管道友好输出：`batch $(photo-s exif ... --list)` |
| `cull` | `{"count", "kept", "results": [{path, luminance, overexposed_pct, underexposed_pct, blur_score?, kept}]}` | 曝光/清晰度筛选 |
| `hash` | 生成 `{"output", "count"}`；`--verify` `{"algorithm", "total", "ok", "missing"[], "mismatched"[]}` | SHA-256 清单；verify 有缺失/不匹配时 exit 1 |
| `gallery` | `{"output", "count"}` | HTML 画廊（index.html + 缩略图） |
| `compress --dry-run` | `{"dry_run": true, "count", "files", "settings": {...}}` | 预览：返回将应用的配置，不处理 |
| `plugin list` | `{"installed": [{name, provides[], version?}], "available": [{name, pypi_distribution, description, min_photo_s_version, requires, installed}]}` | 已装 + 官方可用插件 |
| `plugin install NAME` | `{"ok", "name", "distribution", "version"?}`；已装 → `{"ok", "already_installed": true}`；未知名 → rc 1 `{"ok": false, "error"}`；`--dry-run` → `{"ok", "dry_run", "pip_argv"}` | 安装官方插件（shell 到 pip） |
| `plugin uninstall NAME` | `{"ok", "name", "distribution"}` | 卸载插件 |
| `plugin info NAME` | `{"name", "pypi_distribution", "description", "installed", "version", "provides"?, "weights"?[{name, cached, path, size}]}` | 插件详情 + 权重缓存状态 |
| `plugin fetch NAME` | `{"ok", "name", "weights": [{name, path, cached}]}` | 预下载模型权重（sha256 校验） |

### 2.6 batch/compress/convert 的全局校正选项

`--ev STOPS`（2^EV 曝光补偿）、`--auto-exposure 0-1`（均值亮度归一化）、
`--log-curve NAME`（LOG 还原：SLOG3/CLOG3/LOGC3/DLOG/VLOG/HLG，纯 1D LUT）、
`--auto-straighten`（扶正地平线，`ProcessResult.auto_straightened` 报告是否旋转）、
`--max-straighten-angle DEG`。v1.7.0 局部调整与镜头矫正：
`--masks "sky:linear:0.5,0,0.5,1,feather=0.3"`（命名蒙版 linear/radial/color，
相对坐标 0-1）、`--mask-adjust "sky:exposure=-0.7,vibrance=0.2"`（蒙版内标量，
key ∈ exposure/brightness/contrast/saturation/vibrance/clarity/texture/sharpen/temp/tint/blur）、
`--point-color "200,120,80:30,0.2,-0.1,0.2"`（取样色定向）、
`--lens-distort K1`（畸变）、`--lens-vignette "0.3,0.4"`（去暗角）、`--lens-ca "0.999,1.001"`（消色差）。

**v1.8.0 蒙版扩展**（`--masks` 段可混用；`;` 分隔多蒙版、`|` 分隔笔刷点）：
- **AI 分割**：`subject:`（显著性主体）/ `person:`（人像）/ `object:car`（COCO 80 类，
  含空格类名可达如 `object:traffic light`）——需 `photo-s-tools[enhance]`（opencv），
  权重首次使用经 modelstore 下载 + sha256 校验（缺依赖/下载失败 → 该文件 per-file 报错，不静默）
- **笔刷**：`brush:0.5,0.5,0.05|0.6,0.5,0.05`（点间胶囊并集；负点 `-0.6,0.5,0.05` = 减去）
- **组合算子**：`combo:sky&face`（交集）/ `combo:sky-face`（差集），引用已命名蒙版并替换
- **蒙版内复杂参数**：`--mask-adjust "sky:curves={r:0,0;128,140;255,255};face:hsl={red:0.1,0.2,0}"`
  （curves/hsl/color_grading/vignette/grain 五个字符串键用 `{}` 包裹，与全局 grade 字符串同格式）
- 所有类型支持段尾 `,feather=0.3`/`,invert`（round-trip 保真）；数值参数拒绝 NaN/Inf（清晰报错）
- **per-photo 蒙版**：REST `process` 的 `options` 键与 CLI 同；逐照片差异经
  `batch_process(per_file_options=)` 钩子注入（钩子始终收到未变异的 base options）

**抠图 / 背景移除（v2.1.0，`--cutout`）**：蒙版 → alpha 通道 → 透明输出。

| spec | 含义 |
|---|---|
| `subject` / `person` | AI 分割（U2Netp / PP-HumanSeg，复用 v1.8 权重，需 `[enhance]`） |
| `object:car` | YOLOv8n-seg COCO 类 |
| `color:255,255,255,tol=30,feather=0,invert` | 颜色键控：欧氏 RGB 距离 ≤ tol 变透明；feather 为绝对像素羽化；`invert` 反选 |

约束：透明输出需 PNG/WebP/TIFF/AVIF/HEIC；**JPEG + cutout → per-file 报错**（不会静默拍平白底）。坏 spec 同样 per-file 报错（错误含原始 spec）。REST `process` 的 options 键与 MCP `process` 工具直接传 `cutout` 字符串即可。

### 2.7 LR 数据桥接（v1.7.1+，个人修图数据 → PhotoS 参数空间）

| 命令 | stdout JSON shape | 说明 |
|---|---|---|
| `lr-scan [--export-dir D] [--render-dir D] [--sanitize D]` | `{"catalogs": [...], "xmp_files", "coverage": {...}, "export"?}` | 只读扫描 .lrcat/.xmp → 覆盖报告 + 训练 JSONL + rawpy before 图；`--sanitize` 产出脱敏数据包（剥 EXIF、image 为 basename，配合 `--images` 直接可训） |
| `lr-merge PKG... -o OUT` | `{"packages", "records", "edited", "images_copied", "duplicates", "conflicts"}` | 多机数据包合并（去重 + 图集复制 + 绝对路径重写） |
| `lr-train --data lr_records.jsonl [--images DIR] --out m.npz` | 训练进度（stderr）+ 模型文件 | 岭回归 9 项全局参数，纯 numpy；sanitize 包缺 --images 时报"缺图跳过"诊断 |
| `lr-predict IMG [--model m.npz] --json` | `{"path", "options": {ev, contrast, saturation, vibrance, wb_temp, wb_tint, clarity, texture, dehaze}}` | **输出键与 ProcessOptions 字段一致（exposure→ev），REST/MCP/CLI 零映射可直接套用**；自动识别岭回归 / CLIP+MLP npz（后者需 torch + open-clip-torch，缺失报清晰 LrError） |
| `lr-recipes` / `lr-similar` / `lr-eval` | 配方聚类 / 相似编辑检索 / 教师评测集 | v1.7.1，见 `photo-s <cmd> --help` |

`--denoise N` 与 `--auto-straighten` 需要
`pip install photo-s-tools[enhance]`（opencv-python-headless），未装时该文件报错
（错误信息含安装提示），server 端同样经 options 映射生效（enhance 选项缺依赖时按上述规则处理）。

> `--denoise N` 的 provider 语义：安装了官方 `photo-s-plugin-scunet`（SCUNet 强降噪）时
> 优先走 SCUNet（权重首次使用自动下载，`photo-s plugin fetch scunet` 可预取），
> 否则回退到内置 OpenCV NLM。agent 可用 `photo-s plugin list --json` 查询插件状态、
> `photo-s plugin install scunet --json` 安装 —— 插件管理器与 `pip install` 双通道。

### 2.2 输出通道约定

- **stdout 只输出 JSON**；进度、扫描日志、警告一律走 **stderr**。解析只认 stdout。
- 文件列表的 `--json` 模式同样遵循（`compress/batch/convert` 的文件清单在 stderr）。

### 2.3 退出码约定

| 退出码 | 含义 |
|---|---|
| `0` | 成功 |
| `1` | 有失败 / 发现问题：`batch/convert/rename` 有失败项、`check` 发现损坏、**`dedup` 发现重复** |
| `2` | argparse 用法错误（参数解析失败） |

> `dedup`：有重复 → `1`，无重复 → `0`，agent 可据此分支。

### 2.4 JSON 模式下的交互确认

以下交互确认在 `--json` 模式下**自动跳过**（agent 无 stdin，显式传参即视为确认）：
- `--remove-original`
- `dedup --action move|delete`

### 2.5 示例

```bash
# 压缩到 ≤5MB，8 线程，返回 JSON
photo-s compress *.jpg --target-size 5MB -j 8 --json

# 找重复，按退出码分支
if photo-s dedup ~/photos/ -r --json > /tmp/dupes.json; then
  echo "无重复"
else
  jq '.duplicate_count' /tmp/dupes.json
fi

# 预览（不处理）
photo-s batch ~/in/ -r --dry-run --json

# 打标 → 筛选 → 交付（核心工作流）
photo-s exif ~/shoot/ -r --rating 4 --keywords "keep"          # 批量打标
photo-s exif ~/shoot/ -r --show --rating-min 4 --list          # 筛出 ≥4 星路径
photo-s batch $(photo-s exif ~/shoot/ -r --show --rating-min 4 --list) -o /deliver/
```

> 元数据存储说明：`rating` / `keywords` / `title` 打包在 EXIF **UserComment** 的
> `PhotoS: rating=4 keywords=keep,beach` 段（保留原有的用户评注文本；ExifTool 可读）。
> 其余字段（artist/caption/date/software 等）写标准 EXIF 标签。

---

## 3. `serve` REST API

### 3.1 启动与握手（推荐）

```bash
photo-s serve --port 0 --token auto --ready-file ./photo-s.ready.json &
```

`--port 0` 随机端口；`--token auto` 随机 Bearer token；`--ready-file` 在监听成功后
**原子写入** `{"port", "token", "pid"}`。宿主轮询该文件（比解析 stdout 稳，Windows 亦然），然后：

```
GET  /health  带 Bearer → {"status": "ok", "version": "..."}
```

### 3.2 认证

所有端点都需 `Authorization: Bearer <token>`（未设 token 时本机免认证）。请求体为 JSON，`Content-Type: application/json`。

**未设 token 的安全边界**：Host 头必须是回环地址（`127.0.0.1`/`localhost`/`[::1]`）或实际绑定地址，
否则拒绝（防 DNS rebinding）；绑定非回环（如 `--host 0.0.0.0`）时**必须配 token**。
请求体上限 1MB，超限返回 413。

### 3.3 端点总表

| 方法 / 路径 | 请求体 | 响应 |
|---|---|---|
| `GET /health` | — | `{"status", "version"}` |
| `GET /info` | — | 格式清单 + 已装插件 + `optional_features`（可选依赖状态） |
| `GET /plugins` | — | `{"installed": [{name, provides, version?}], "available": [{name, pypi_distribution, description, min_photo_s_version, requires, installed}]}` |
| `POST /plugins` | `{"action": "install\|uninstall\|fetch", "name": "scunet", "dry_run"?: bool}` | 远程插件管理：`{"ok", "name", "action", "distribution"}`；`dry_run` → `{"ok", "dry_run", "pip_argv"}`；fetch → `{"ok", "name", "weights": [{path}]}` |
| `POST /process` | `{"paths": [...], "options": {...}}` | `BatchResult` JSON |
| `POST /process` (async) | 同上 + `"async": true` | `202 {"task_id", "poll", "total"}` |
| `POST /process` (async+audit) | 同上 + `"audit": true` | 任务完成后 result 附每文件 `audit {passed, reason}` + `audit_summary {pass_rate}`（v2.3，stop 条件内建） |
| `POST /v1/suggest` | `{"paths", "recursive"?, "scale"? (默认 1.0)}` | `{"ok", "count", "neutral", "results": [{path, suggested{}, reasons[], neutral}]}` 规则型参数推荐（v2.3，零模型） |
| `POST /process` (dry-run) | 同上 + `"dry_run": true` | `{"dry_run", "count", "paths", "options"}`，不处理 |
| `GET /tasks` | — | 运行/已完成任务摘要 |
| `GET /tasks/<id>` | — | `{"status", "current", "total", "current_path", "result"?}` |
| `POST /tasks/<id>/cancel` | — | `{"task_id", "cancelled"}` |
| `POST /dedup` | `{"paths", "threshold"?, "recursive"?}` | 重复组 |
| `POST /analyze` | `{"paths", "recursive"?, "sample_size"? (默认 256), "grid"? (4\|8)}` | `{"ok", "count", "results": [{path, size, histogram, stats, white_balance, exposure, blur_score, grid?, regions?}]}` 感知分析（v1.7.0 闭环；v1.7.1 加 `grid` 区域反馈 + `regions` 天空/肤色/过曝框） |
| `POST /diff` | `{"path_a", "path_b", "sample_size"? (默认 256)}` | `{"ok", "psnr", "ssim", "mean_abs_diff", "size"}` 版本数值对比（v1.7.1，before/after 判定） |
| `POST /audit` | `{"paths", "recursive"?, "overexposed_max"?, "underexposed_max"?, "blur_min"?, "aesthetic"?}` | `{"ok", "count", "passed", "results": [{ok, passed, checks[], reason}]}` 出片质量闸门（v1.7.1，agent 终止条件）；`aesthetic`（1-10，v2.4）追加美学闸门（需 auto-tone 插件） |
| `POST /preview` | `{"path", "max_dim"? (默认 1024), "include_histogram"? (默认 true)}` | `{"ok", "path", "size", "jpeg_base64", "jpeg_bytes", "histogram_png_base64"?}` 视觉快照（v1.7.1，多模态 agent 的像素输入） |
| `POST /rename` | `{"paths", "pattern", "output_dir"?, "overwrite"?, "dry_run"?, "recursive"?}` | `{"total", "ok", "results"}` |
| `POST /contact-sheet` | `{"paths", "output", "cols"?, "thumb_width"?, "thumb_height"?, "captions"?, "bg"?, "recursive"?}` | `{"output", "count"}` |
| `POST /check` | `{"paths", "recursive"?}` | `{"checked", "ok", "corrupt"}` |

所有接受 `paths` 的端点都支持 **`"recursive": true`**（目录递归扫描子目录，默认只扫一层）。

### 3.4 `/process` 的 `options` 映射

`options` 里的字段名与 `ProcessOptions` 字段一一对应（server 按注解自动派生，新字段无需改白名单），
按 JSON 类型自动转 int/float/str/bool。特殊项：

| 字段 | 说明 |
|---|---|
| `output_sizes` | 多尺寸：`[["thumb", 480, null], {"label": "screen", "width": 1920}]`（tuple 或 dict 两种写法） |
| `pad` | 配置式别名，等价于 `pad_ratio`（如 `"16:9"`） |
| `target_size` | 人类可读目标体积：`"500KB"` / `"2MB"`（转成 `target_size_bytes`） |
| `output_format` | 大小写不敏感：`"png"` / `"WEBP"` 均接受，归一化为规范大小写 |
| `jpeg_subsampling` | `"444"`/`"422"`/`"420"`（默认 `"420"`；444 保留全色彩，体积更大） |
| `raw_demosaic` | `"auto"`/`"ahd"`/`"vng"`/`"ppg"`/`"dcb"`/`"dht"`/`"amaze"`（默认 `"auto"`；amaze 质量最高最慢） |
| `export_sharpen` | `0-2` 浮点（默认 null=关；LR 式输出级 USM，半径随输出分辨率缩放） |
| `highlight_recovery` | `0-1` 浮点（默认 null=关；LR 式高光恢复，压缩硬切高光恢复渐变） |
| `raw_color_space` | `"sRGB"`（默认，自动打 ICC）/ `"AdobeRGB"` / `"ProPhotoRGB"`（宽色域不加标记） |
| `raw_16bit` | bool（16-bit 解码；`output_format: "TIFF"` 时写 16-bit，需 tifffile；JPEG 无意义） |
| `lens_profile` | 命名镜头档案（`lens-profile save` 维护）；显式 `lens_distort`/`lens_vignette`/`lens_ca` 优先 |

> 内置预设 `lr-look`（S 曲线+自然饱和+导出锐化，接近 LR 默认渲染）经 MCP
> `preset load lr-look` 取回 options dict，再并入 `process` 的 `options` 即可
> （CLI 侧直接 `--preset lr-look`）。

### 3.5 异步任务（长批处理：进度 + 取消）

单个大 batch 不应在同步 `/process` 里等数分钟。流程：

```bash
# 1. 提交 → 202 {task_id, poll}
curl -X POST .../process -H "Authorization: Bearer $TOKEN" \
     -d '{"paths": ["/photos/*.jpg"], "options": {"jobs": 4}, "async": true}'

# 2. 轮询进度
curl -s .../tasks/<task_id>
# → {"status": "running", "current": 37, "total": 200, "current_path": "..."}

# 3. 完成 → status: "done"，result 为完整 BatchResult JSON
# 4. 中途取消（进行中的图片完成后停止）
curl -X POST .../tasks/<task_id>/cancel   # → {"cancelled": true}
```

取消语义：**进行中的图片正常完成**，尚未开始的排队图片以 `"已取消 Cancelled"` 失败项收尾，
任务最终 `status: "cancelled"`（与 GUI 取消行为一致）。任务表有上限（默认 100），完成的任务按序淘汰。

### 3.6 同步调用示例

```bash
curl -X POST .../process -H "Authorization: Bearer $TOKEN" \
     -d '{"paths": ["/tmp/in.jpg"], "options": {"quality": 70, "evaluate": true, "output_dir": "/tmp/out"}}'
```

---

## 4. 配置文件 `photo-s.toml`

优先级：**显式 CLI 参数 > 配置文件 > 内置默认值**。`--config PATH` 指定，否则沿当前目录向上找
`photo-s.toml`，再到 `$XDG_CONFIG_HOME/photo-s/config.toml`。

- `photo-s config init` 生成带注释的模板；`photo-s config show` 显示生效配置。
- 配置键与 CLI 参数对应（`pad = "16:9"`、`output_format = "png"` 大小写不敏感）。
- 对 CLI 而言：只要参数被显式传入（即使等于默认值，如 `-q 85`），就优先于配置文件。

---

## 5. Agent 对接 Checklist

- [ ] 解析 stdout JSON，忽略 stderr（进度/诊断都在 stderr）。
- [ ] 解析前先读顶层 `schema_version`；未知键一律忽略（additive 契约）。
- [ ] 用退出码判断结果类别（`dedup`/`check` 的 `1` = 发现问题）。
- [ ] 大 batch 用 `serve --token auto --ready-file` + 握手文件 + 异步任务。
- [ ] `paths` 里的目录默认只扫一层；需要子目录时传 `recursive: true`。
- [ ] `--remove-original` / `dedup --action delete` 在 JSON 模式下直接执行，无确认。
- [ ] `-f` / `output_format` 大小写随意（自动归一化）。

---

## 6. MCP server（Claude Desktop / MCP 客户端）

需要 Python 3.10+ 与可选依赖：`pip install "photo-s-tools[mcp]"`。stdio 协议，
Claude Desktop 配置（`claude_desktop_config.json`）：

```json
{
  "mcpServers": {
    "photo-s": { "command": "photo-s", "args": ["mcp"] }
  }
}
```

`photo-s mcp --list-tools` 返回全部工具及 inputSchema（JSON，不启动服务器；26 核心 + 已装插件的工具）。

零安装变体（uvx 自动解析 PyPI 依赖，与官方 MCP Registry
`io.github.Dongwu259/photo-s` 发布的调用一致）：

```json
{
  "mcpServers": {
    "photo-s": { "command": "uvx", "args": ["--from", "photo-s-tools[mcp]", "photo-s", "mcp"] }
  }
}
```

Claude Code 连接（与上面 Claude Desktop 配置等价，经 `claude mcp add` 写入配置）：

```bash
claude mcp add photo-s -- photo-s mcp                          # 用户级
claude mcp add photo-s --scope project -- photo-s mcp          # 项目级
claude mcp add photo-s -- uvx --from "photo-s-tools[mcp]" photo-s mcp   # 零安装变体
claude mcp list                                                # 验证（应列出 photo-s）
```

其他 MCP 客户端（Cursor / Cline / Windsurf 等）填入同样的 `mcpServers` 条目即可。
不想用 MCP 时，agents 也可以直接用 `skills/photo-s/SKILL.md`（skill 包，
shell 调 CLI `--json`，无需 py3.10+ / `[mcp]` extra）。

### 工具表（输出结构与 CLI `--json` 一致）

| 工具 | 关键参数 | 输出 |
|---|---|---|
| `process` | `paths[]`, `recursive`, `quality`, `output_format`, `output_dir`, `resize` "WxH", `scale`, `suffix`, `target_size` "500KB", `strip_gps`, `denoise`, `ev`, `log_curve`, `wb_temp`, `auto_straighten`, `crop_ratio` "16:9", `blur_faces` "blur"\|"pixelate", `blur_faces_margin`, v1.6 调色（`wb_tint`/`levels`/`curves`/`vibrance`/`color_grading`/`hsl`/`clarity`/`texture`/`dehaze`/`vignette`/`grain`），v1.7 局部与镜头（`masks`/`mask_adjust`/`point_color`/`lens_distort`/`lens_vignette`/`lens_ca`/`lens_profile`），v1.9 输出质量（`jpeg_subsampling`/`raw_demosaic`/`export_sharpen`/`highlight_recovery`/`raw_color_space`/`raw_16bit`），v2.1 抠图（`cutout`，见 §2.6）, `jobs`, `dry_run`, `evaluate` | `BatchResult` JSON + `ok`；`dry_run` → `{"dry_run", "count", "files", "settings"}`；`evaluate=true` 时每文件带 `ssim`（同 `--evaluate`）。`blur_faces` 需 `photo-s-tools[enhance]`（opencv），缺失时 per-file 报错 |
| `info` | — | 同 `photo-s info --json`（含 `optional_features`/`plugins`） |
| `exif` | `action` "show"\|"write", `paths[]`, `recursive`, `rating_min`, `rating`, `keywords`, `camera`, `tags` {"path": {…}}, `gps` "lat,lon" | show → `{"count", "results": [{path, rating, keywords, …}]}`；write → `{"written", "errors"}`。`gps` 把同一坐标批量写入 `paths` 全部文件 |
| `dedup` | `paths[]`, `recursive`, `threshold` (默认 5), `action` "report"\|"keep-sharpest", `dry_run` (默认 **True**) | report → `{"count", "duplicate_count", "savings_bytes", "groups"}`；keep-sharpest → `{"kept", "removed", "dry_run"}` |
| `cull` | `paths[]`, `recursive`, `overexposed_max`, `underexposed_max`, `luminance_min/max`, `sharpness_min` | `{"count", "kept", "results": [{path, luminance, …, kept}]}` |
| `select` | `paths[]`, `recursive`, `keep_min` (默认 4), `reject_max` (默认 2), `selects_dir`, `rejects_dir`, `mode` "move"\|"copy", `dry_run` | 读 EXIF rating 分拣：≥keep_min → 精选目录、≤reject_max → 淘汰目录、其余原地。`{"ok", "count", "kept", "rejected", "moved", "dry_run", "results": [{path, rating, status, action, dest}]}`；`dry_run` 报 would-move 且零写入（同 `photo-s select --json`） |
| `hdr` | `paths[]` (≥2), `output`, `align` | 包围曝光曝光融合 → `{"ok", "output", "count", "align", "dims"}`。需 `photo-s-tools[enhance]`；`align=true` 用 AlignMTB 消手持鬼影（个别 opencv 构建缺 AlignMTB 时返回清晰报错） |
| `blurfaces` | `paths[]`, `recursive`, `mode` "blur"\|"pixelate", `margin` (默认 20), `output_dir` | 人脸检测 + 高斯模糊/马赛克（隐私保护）→ `{"ok", "count", "success", "results": [ProcessResult…]}`。需 `photo-s-tools[enhance]`；缺失时 per-file 报错不致命 |
| `hash` | `paths[]`, `recursive`, `output`, `verify` (清单路径) | 生成 → `{"output", "count", "entries"}`；verify → `{"ok", "missing", "mismatched"}` |
| `plugin` | `action` "list"\|"install"\|"uninstall", `name`, `dry_run` | list → `{"installed", "available"}`；install/uninstall → `{"ok", "name", "distribution", "version"?}` |
| `contact_sheet` | `paths[]`, `output`, `recursive`, `cols` (默认 4), `thumb` (默认 240), `captions`, `bg` | `{"ok", "output", "count"}`（网格拼图输出路径） |
| `gallery` | `paths[]`, `out_dir`, `recursive`, `title`, `thumb` (默认 360) | `{"ok", "output", "count"}`（同 `photo-s gallery --json`） |
| `watermark` | `paths[]`, `text`/`image`, `position` (默认 BOTTOM_RIGHT), `opacity`, `output_format`, `quality`, `output_dir` | 走批量管线，返回 `BatchResult` JSON |
| `preset` | `action` "list"\|"save"\|"load"\|"delete", `name`, `description`, `options{}` | list → 预设清单；load → 可直接喂给 `process` 的 options JSON |
| `bench` | `dir` (必填), `jobs[]` (默认 [1,2,4,8]), `images`, `denoise`, `evaluate` | `{"ok", "dir", "files", "runs": [{jobs, files, seconds, speedup, errors, stages:{load,process,save}}], "evaluate": {files, psnr_db, ssim}\|null}`（同 `photo-s bench --json`；临时目录输出，源目录不动） |
| `watch` | `dir` (必填), `recursive`, `quality`, `output_format`, `output_dir`, `resize`, `timeout` | 立即返回 `{"started", "id", "dir", "recursive", "options", "timeout"}`；失败 → `{"started": false, "error"}`。后台线程监视目录自动处理；进度用 `watch_status` 轮询、`watch_stop` 结束。**需 `photo-s-tools[watch]`（watchdog）**；`remove_original` 刻意不支持（agent 驱动的删除太危险） |
| `watch_status` | `id` | `{"ok", "id", "dir", "recursive", "running", "stopped", "processed_count", "results": [ProcessResult…], "error", "started_at"}` |
| `watch_stop` | `id` | `{"ok", "id", "stopped", "processed_count"}`（幂等） |
| `analyze` | `paths[]`, `recursive`, `sample_size` (默认 256), `grid` (0\|4\|8) | `{"ok", "count", "results": [{path, size, histogram {r,g,b,luma ×32}, stats, white_balance, exposure, blur_score, grid?, regions?}]}` 感知分析（v1.7.0；`grid`/`regions` v1.7.1：逐格亮度色偏 + 天空/肤色占比 + 过曝/欠曝区域框） |
| `preview` | `path`, `max_dim` (默认 1024), `include_histogram` (默认 true) | `{"ok", "size", "jpeg_base64", "jpeg_bytes", "histogram_png_base64"?}` 视觉快照（v1.7.1）——多模态 agent 直接看图 |
| `diff` | `path_a`, `path_b`, `sample_size` (默认 256) | `{"ok", "psnr", "ssim", "mean_abs_diff"}` 版本数值对比（v1.7.1） |
| `audit` | `paths[]`, `recursive`, `overexposed_max`?, `underexposed_max`?, `blur_min`?, `aesthetic`?（1-10，v2.4 美学闸门） | `{"ok", "count", "passed", "results": [{passed, checks[], reason}]}` 出片质量闸门（v1.7.1，终止条件） |
| `batch_start` | `paths[]`, `options{}`（同 `process` 的键）, `recursive`, `jobs` (默认 4), `audit` (v2.3), `aesthetic`? (v2.4) | `{"ok", "job_id", "total"}` 异步目录任务（v1.7.1）——选项对整批文件统一生效（masks/lens 等共享 spec）；`audit=true` 完成后结果附 `audit_summary` + 每文件 `audit`（v2.3） |
| `batch_status` | `job_id` | `{"ok", "phase" (starting/processing/done), "done", "total", "current", "fail_count", "results"?}` 轮询 |
| `batch_cancel` | `job_id` | `{"ok", "cancelled"}` 取消（在跑的文件跑完，未开始的跳过） |
| `suggest` | `paths[]`, `recursive`, `scale` (默认 1.0) | `{"ok", "count", "neutral", "results": [{path, suggested{}, reasons[], neutral}]}` 规则型参数推荐（v2.3，零模型零依赖；见 §7.1） |

> `watch` 会话与 MCP 会话同生命周期（daemon 线程随进程退出消亡）；`_WATCHES`
> 上限 20，死线程自动清理。
>
> **插件工具（v2.3 自动注册）**：装了 `photo-s-plugin-auto-tone` 的环境自动多出
> `auto_tone` / `aesthetic_score` / `tone_advisor` / `batch_auto_tone` /
> `auto_tone_with_style`（v2.1，任意自然语言风格描述 → 9 字段参数 + 风格偏置）/
> `analyze_visual_style`（v2.1，SigLIP 视觉风格 top-K）/
> `verify_aesthetic`（v2.4，美学验证：SigLIP 回归头快速分，缺席回落 Qwen VLM）
> 七个工具（装即所见，无需配置）；`batch_auto_tone` 新增 `style_desc` 参数走风格化分支。

**破坏性安全**：`dedup keep-sharpest` 默认 `dry_run=True`，删除需显式
`dry_run=False`；`process` 不覆盖输入（`overwrite` 默认 False）。MCP 模式仅
显式 `--config`（不自动发现 `photo-s.toml`）；工具显式参数优先于 config 默认值。

## 7. 感知反馈闭环（v1.7.0 起逐步自动化）

LLM/MLLM 不会"看"图，但可以**读统计**。v1.7.0 的 `analyze`（CLI 子命令 /
`POST /analyze` / MCP `analyze` 工具）把图像变成结构化数字，闭环由此成立。
**v2.3 起闭环三环都有工具承接**——读（analyze）、算（suggest / auto-tone）、
验（batch 内建 audit）：

```
analyze（读：直方图/通道统计/色温/曝光/模糊）
   ↓
suggest（算：规则层把偏差映射为保守参数 + 理由；或 auto-tone 插件预测个人风格）
   ↓
process / batch_start(audit=true)（写 + 验：结果自带 pass/fail 与 pass 率）
   ↓ 未收敛则 scale 调幅再来（2-4 轮通常足够）
最终交付输出
```

### 7.1 `suggest`（v2.3，零模型规则层）

`photo-s suggest IMG... [--scale 0-1]` / `POST /v1/suggest` / MCP `suggest`。
输出 `suggested`（ProcessOptions 字段名 → 建议值，`process` 直接可用）+
`reasons`（每条 `{field, metric, value, advice}`——可解释、可转述）。
中性图返回空 `suggested` + `neutral=true`：客观上没有可修项。
`--scale 0.5` 整体减半幅度（温和模式）。

与 auto-tone 插件的分工：**suggest = 确定性规则层**（离线、快速、修"客观偏差"：
曝光/白平衡/对比/黑白场），**auto-tone = 个人风格 AI 层**（4.6MB 权重预测 9 字段
"风格参数"）。无网络/无插件时 suggest 是保底；两者可叠加（先 suggest 修偏，再
auto-tone 上风格）。

### 7.2 batch 内建 audit（v2.3，stop 条件进任务）

`POST /process {"async":true, "audit":true, "aesthetic":6}` /
MCP `batch_start(audit=True, aesthetic=6.0)`：
批处理完成后自动对**输出**跑质量闸门，任务结果附每文件 `audit: {passed, reason}`
+ `audit_summary: {audited, passed, failed, pass_rate}`——agent 的终止判据
不再需要另一次 `/audit` 往返。`aesthetic`（1-10，v2.4）在技术闸门之上追加
美学分下限（需 auto-tone 插件）。

### 7.3 美学闸门 + 局部调整词汇表（v2.4）

**美学闸门（模型层 stop 条件）**：`photo-s audit IMG --aesthetic 6` /
`POST /audit {"aesthetic": 6}` / MCP `audit(aesthetic=6)`。分数来自插件的
`verify` 槽位：SigLIP 回归头（单次前向，毫秒级——候选排序/循环 reward 用），
头未训练时回落 Qwen3-VL LoRA 评分（终审级）。**stop 条件语义**：请求了美学
闸门但插件缺席 → 显式报错（agent 不会在错误的"通过"上停机）；verifier 给不出
分数 → 该项 fail（value=null，原因进 reason）。

**局部调整词汇表**：`auto_tone` 输出新增加性键 `local:
[{region, params}]`（region ∈ `subject`/`person`/`object:label`，params 为
mask_adjust 标量子集）。引擎 `--auto-tone` 经真实管线应用全部 9 个全局字段
（旧接线只落 3 个）+ 局部调整过蒙版管线；GUI「AI 调色」把局部预测写进
per-photo 蒙版（蒙版编辑器可改可删）。训练侧见 `docs/TRAINING.md` §5.1/§5.2。

**判读速查**（`analyze` 输出 -> 建议参数；`suggest` 已把此表代码化）：

| 观测 | 字段 | 建议 |
|---|---|---|
| 偏暗/偏亮 | `exposure.luminance`（0-1） | `ev` 补偿，或 `auto_exposure 0.45` |
| 死白/死黑 | `exposure.overexposed_pct` / `underexposed_pct` | `levels` 收黑白场；`curves` 压高光/抬阴影 |
| 发灰不通透 | `stats.contrast`（<0.15 偏平） | `contrast`/`clarity`/`curves` S 曲线 |
| 白平衡偏暖/冷 | `white_balance.kelvin_estimate` | `wb_temp` 反向补偿（估计 4000K = 偏暖 -> 降温） |
| 绿/品红偏 | `white_balance.tint_gm`（正=偏品红） | `wb_tint` 负值补偿 |
| 饱和不足 | `stats.saturation_mean` | `vibrance`（比 `saturation` 不爆肤色） |
| 局部色偏（如天空过亮） | `histogram` 通道分布 | `masks` + `mask_adjust` 局部压暗 |

**参数词汇表**：全部调色/局部/镜头参数均为 ProcessOptions 标量或紧凑字符串字段
（语法见 §2.6），REST `/process` 的 `options` 直接透传，MCP `process` 工具同名参数。
未来训练专有调色模型时，这套字符串 schema 即模型输出空间（约束解码友好：有限
token、无自由文本），`analyze` 统计即监督信号来源。
