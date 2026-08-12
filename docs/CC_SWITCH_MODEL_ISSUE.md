# cc-switch 模型配置问题排查记录（DeepSeek via 火山 Ark）

> 记录时间：2026-08-10
> 环境：Claude Code 2.1.226（darwin-arm64），经 cc-switch 配置第三方模型端点（火山引擎 Ark `/api/coding`）
> 本文档记录一次"模型不识别 + 子代理失败"问题的完整排查、根因和修复，**重点说明 cc-switch 配置侧的问题**。

---

## 1. 症状

1. 会话启动时 Claude Code 弹警告：

   > `"deepseek-v4-flash-ga-260731" is not a model this version of Claude Code recognizes, so auto-compact will keep this session within 200k tokens (the context window it assumes).`

2. 派生子代理（Agent tool / claude-code-guide 等）报错：

   > `There's an issue with the selected model (doubao-1-5-lite-32k-250115). It may not exist or you may not have access to it.`

两件事同源：`~/.claude/settings.json` 的 `env` 块被 cc-switch 写入了不一致的模型配置。

---

## 2. 根因

### 2.1 直接原因：`ANTHROPIC_MODEL` 缺 `[1M]` 后缀

Claude Code 判断上下文窗口的逻辑（反编译 2.1.226 二进制，函数 `Qmf`）：

- 模型名匹配 `/\[1m\]/i` → 窗口 1M；
- 模型在**内置模型表**（`claude-*` 等）内 → 用其官方窗口；
- 否则默认 **200k**，且当窗口来源分类为 `"unknown-model"` 时弹警告。

主会话实际生效的模型来自 `process.env.ANTHROPIC_MODEL ?? settings.model`。当时配置：

| 变量 | 值 | 后果 |
|---|---|---|
| `ANTHROPIC_MODEL` | `deepseek-v4-flash-ga-260731`（**无后缀**） | 主会话按 200k 处理 + 弹警告 |
| `ANTHROPIC_DEFAULT_OPUS/SONNET/FABLE_MODEL` | `deepseek-v4-flash-ga-260731[1M]` | 仅作用于 tier 别名，对主循环**无效** |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | `doubao-1-5-lite-32k-250115` | 子代理（Haiku 层）解析到它 → 端点未开通 → 失败 |

关键结论：**`[1M]` 后缀必须加在 `ANTHROPIC_MODEL` 上**，只加在 `ANTHROPIC_DEFAULT_*_MODEL` 不会消除主会话警告。该后缀在发请求前会被剥离（`(\[1m\])+$`），代理端点收到的仍是裸模型 ID。

### 2.2 根源：cc-switch 的「火山Agentplan」provider 配置不完整

cc-switch 把每个 provider 的配置存在 `~/.cc-switch/cc-switch.db` 的 `providers.settings_config`（JSON），**切换时整体覆盖写入 `~/.claude/settings.json`**。问题 provider（当前启用）如下，与另一个配置正确的 DeepSeek provider 对比：

| 项 | 火山Agentplan（问题） | DeepSeek（正确） |
|---|---|---|
| `ANTHROPIC_MODEL` | `deepseek-v4-flash-ga-260731` ❌ 缺 `[1M]` | `deepseek-v4-flash[1m]` ✅ |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | `doubao-1-5-lite-32k-250115` ❌ 端点未开通、32k 过小 | `deepseek-v4-flash[1m]` ✅ |
| `CLAUDE_CODE_MAX_CONTEXT_TOKENS` | 缺失 | `1000000` ✅ |

**问题定位**：`ANTHROPIC_MODEL` 与 tier 默认变量不一致（主模型漏加 `[1M]`），且 Haiku 层填了一个在 `/api/coding` 端点上未开通/不可用的 doubao 模型 ID。属于在 cc-switch 里新建/编辑该 provider 时手工填写不一致所致。cc-switch 本身只是如实把 `settings_config` 写进 settings.json，**不会校验**模型 ID 可用性、上下文后缀是否齐全。

---

## 3. 已做的修复（`~/.claude/settings.json`）

```jsonc
{
  "env": {
    // ...其余不变...
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "deepseek-v4-flash-ga-260731[1M]",   // 原: doubao-1-5-lite-32k-250115
    "ANTHROPIC_DEFAULT_HAIKU_MODEL_NAME": "deepseek-v4-flash-ga-260731",  // 原: doubao-1-5-lite-32k-250115
    "ANTHROPIC_MODEL": "deepseek-v4-flash-ga-260731[1M]"                  // 原: 无 [1M] 后缀
  }
}
```

- `ANTHROPIC_MODEL` 加 `[1M]` → 主会话窗口升 1M + 警告消除；
- Haiku 层指向已在 `/api/coding` 验证可用的 deepseek 模型 → 子代理不再失败。

> 注意：`ANTHROPIC_DEFAULT_*_MODEL_NAME` 是**显示名**，保持无后缀，无需改动。

---

## 4. ⚠️ 待办：cc-switch 侧必须同步修（否则会复发）

只改 `~/.claude/settings.json` 是**治标**。cc-switch 每次切换 provider 都会把 `settings_config` 整体**覆盖写回** settings.json，下次切走再切回（或 cc-switch 重写配置），问题配置会原样回来。

请到 **cc-switch GUI → Claude → 编辑「火山Agentplan」provider**，修正：

1. **主模型（`ANTHROPIC_MODEL`）加后缀**：`deepseek-v4-flash-ga-260731[1M]`；
2. **Haiku 层模型**：改成已在 `/api/coding` 可用的模型，如 `deepseek-v4-flash-ga-260731[1M]`（显示名填 `deepseek-v4-flash-ga-260731`），或删除该项让端点走默认；
3. **可选**：补 `CLAUDE_CODE_MAX_CONTEXT_TOKENS=1000000`（与 DeepSeek provider 对齐，作为显式兜底）。

**不要**直接手动改 `~/.cc-switch/cc-switch.db`（应用运行时会持有连接，直接写库有被覆盖/损坏风险）；在 GUI 里改最安全。

---

## 5. 验证

- 改完 settings 后**重启 Claude Code**（`env` 在进程启动时读取）。
- 重启后无"not a model ... recognizes"警告，即修复生效。
- 会话内 `/status` 或 `/config` 可确认生效模型；派生子代理不再报 doubao 错误。
- 若在 cc-switch 里重新切换过 provider，`claude --version` 后启动并观察是否复现警告（复发即说明第 4 节未同步修）。

---

## 6. 补充核查（2026-08-10）：cc-switch 更新文档 + 时间线

### 6.1 cc-switch v3.19.x 发布说明：**均未修复此问题**

核查了 GitHub Releases（经 GitHub API 获取）：`v3.19.0`（2026-07-30）、`v3.19.1`（2026-07-31）、`v3.19.2`（2026-08-06，当前最新）。三版正文中 **0 处** 提及 `ANTHROPIC_MODEL`、`[1m]`/`[1M]` 上下文后缀、`CLAUDE_CODE_MAX_CONTEXT_TOKENS`、Haiku 层模型、`"not a model ... recognizes"` 警告或「Claude Code 更新后的配置不一致」。

v3.19.x 的改动集中在：图片经代理不再撑爆上下文（Codex `view_image` 的 base64 计 token 膨胀，与本文问题无关）、用量统计/定价（models.dev 同步、Grok 用量、双算修复）、安全加固（Skill 安装、`ccswitch://` 导入、Gemini 密钥泄漏）、Codex 直连预设等。**结论：升级 cc-switch 不能解决本文问题**，仍需按第 4 节修 provider 配置。

> 相关但不同的一处：v3.19.2 提到「新版 Claude Code 对不认识的 API key 会弹确认框」，cc-switch 为此改写了 `ANTHROPIC_AUTH_TOKEN` 占位符——说明「Claude Code 更新 → cc-switch 配置需适配」这个方向确实存在，但本次的模型上下文问题不在其修复范围内。

### 6.2 时间线核查：「Claude Code 更新后不一致」假设**不成立**

| 事件 | 时间 |
|---|---|
| Claude Code 2.1.226 二进制安装 | 2026-08-08 19:47 |
| 「火山Agentplan」provider 创建 | **2026-08-10 19:47**（当天新建） |
| 本次 settings.json 被写入 | 2026-08-10 19:48 |

历史 cc-switch DB 备份（6/29、7/30、8/8）中**没有**火山/volces provider，当时的启用项是配置正确的 DeepSeek provider（`ANTHROPIC_MODEL` 带 `[1m]`、有 `CLAUDE_CODE_MAX_CONTEXT_TOKENS=1000000`，因此不弹警告）。

结论：**火山Agentplan 是 2026-08-10 新建、且在 Claude Code 已更新之后**。不一致（主模型缺 `[1M]` + Haiku 指向未开通的 doubao）在**创建时**就被写入 provider 记录，并非旧配置因 Claude Code 更新而"显形"。Claude Code 的 unknown-model 窗口机制只是让问题可见；问题的产生在 cc-switch 侧的新建/编辑环节。这也是第 4 节要求在 cc-switch GUI 里修正 provider 的原因——不修则切回即复发。

---

## 7. 附：技术依据（Claude Code 2.1.226 二进制反编译要点）

- 上下文窗口解析：模型名 `/\[1m\]/i` → 1M；内置表识别 → 官方窗口；否则 200k + `"unknown-model"` 警告。
- 警告抑制：`[1m]` 后缀命中后跳过 `"unknown-model"` 分支；`CLAUDE_CODE_MAX_CONTEXT_TOKENS>0`（非 `claude-` 模型）同样抑制并覆盖窗口；`CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT=1` **只消音、窗口仍 200k**。
- tier 解析：Haiku 层优先读 `ANTHROPIC_DEFAULT_HAIKU_MODEL`（其次 `ANTHROPIC_SMALL_FAST_MODEL`）——这就是子代理失败的直接来源。
- `modelOverrides`：本版本为纯 string→string 映射（键须为内置认可的 Anthropic ID），不推荐用于代理场景。
