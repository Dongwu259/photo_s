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
| `photo-s mcp` | Claude Desktop / MCP 客户端 | stdio MCP server，19 个工具（需 py3.10+ 与 `photo-s-tools[mcp]`） |

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
| `POST /process` (dry-run) | 同上 + `"dry_run": true` | `{"dry_run", "count", "paths", "options"}`，不处理 |
| `GET /tasks` | — | 运行/已完成任务摘要 |
| `GET /tasks/<id>` | — | `{"status", "current", "total", "current_path", "result"?}` |
| `POST /tasks/<id>/cancel` | — | `{"task_id", "cancelled"}` |
| `POST /dedup` | `{"paths", "threshold"?, "recursive"?}` | 重复组 |
| `POST /analyze` | `{"paths", "recursive"?, "sample_size"? (默认 256)}` | `{"ok", "count", "results": [{path, size, histogram, stats, white_balance, exposure, blur_score}]}` 感知分析（v1.7.0，调色反馈闭环） |
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

`photo-s mcp --list-tools` 返回 19 个工具及 inputSchema（JSON，不启动服务器）。

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
| `process` | `paths[]`, `recursive`, `quality`, `output_format`, `output_dir`, `resize` "WxH", `scale`, `suffix`, `target_size` "500KB", `strip_gps`, `denoise`, `ev`, `log_curve`, `wb_temp`, `auto_straighten`, `crop_ratio` "16:9", `blur_faces` "blur"\|"pixelate", `blur_faces_margin`, v1.6 调色（`wb_tint`/`levels`/`curves`/`vibrance`/`color_grading`/`hsl`/`clarity`/`texture`/`dehaze`/`vignette`/`grain`），v1.7 局部与镜头（`masks`/`mask_adjust`/`point_color`/`lens_distort`/`lens_vignette`/`lens_ca`）, `jobs`, `dry_run`, `evaluate` | `BatchResult` JSON + `ok`；`dry_run` → `{"dry_run", "count", "files", "settings"}`；`evaluate=true` 时每文件带 `ssim`（同 `--evaluate`）。`blur_faces` 需 `photo-s-tools[enhance]`（opencv），缺失时 per-file 报错 |
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
| `analyze` | `paths[]`, `recursive`, `sample_size` (默认 256) | `{"ok", "count", "results": [{path, size, histogram {r,g,b,luma ×32}, stats, white_balance, exposure, blur_score}]}` 感知分析（v1.7.0） |

> `watch` 会话与 MCP 会话同生命周期（daemon 线程随进程退出消亡）；`_WATCHES`
> 上限 20，死线程自动清理。

**破坏性安全**：`dedup keep-sharpest` 默认 `dry_run=True`，删除需显式
`dry_run=False`；`process` 不覆盖输入（`overwrite` 默认 False）。MCP 模式仅
显式 `--config`（不自动发现 `photo-s.toml`）；工具显式参数优先于 config 默认值。

## 7. 感知反馈闭环（v1.7.0，多模态模型调色）

LLM/MLLM 不会"看"图，但可以**读统计**。v1.7.0 的 `analyze`（CLI 子命令 /
`POST /analyze` / MCP `analyze` 工具）把图像变成结构化数字，闭环由此成立：

```
analyze（读：直方图/通道统计/色温/曝光/模糊）
   ↓ 依据偏差决定参数（紧凑字符串即"模型输出词汇表"）
process（写：curves/levels/hsl/point_color/masks/...）
   ↓ 输出到临时目录
analyze（再读：验证偏差是否收敛）
   ↓ 不收敛则微调再来（2-4 轮通常足够）
process（最终交付输出）
```

**判读速查**（`analyze` 输出 -> 建议参数）：

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
