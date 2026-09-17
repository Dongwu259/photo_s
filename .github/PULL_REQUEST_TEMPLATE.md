<!--
  感谢提交 PR。请把下面填完——reviewer 不需要猜你想做什么。
  小改动（typo / 注释）可以简化，但「改了什么 + 怎么验证的」必须有。
-->

## 改了什么

<!-- 一到三句话。如果是多个不相关的改动，请拆成多个 PR。 -->

## 为什么

<!-- 关联 issue：Fixes #123 / Closes #123。没有 issue 的话说明动机。 -->

## 类型

- [ ] 🐛 Bug 修复（patch）
- [ ] ✨ 新功能（minor）
- [ ] 💥 破坏性变更（需要递增 `schema_version` 或改 CLI 行为）
- [ ] 📝 文档
- [ ] ♻️ 重构 / 性能（行为不变）
- [ ] 🧪 测试
- [ ] 🔧 CI / 构建 / 依赖

## 怎么验证的

<!-- 贴你实际跑过的命令与结果 -->

```bash
python3 -m pytest tests/ -q
# → 1490 passed, 6 skipped
```

## 检查清单

- [ ] **全量测试通过**（`python3 -m pytest tests/ -q`）
- [ ] 新增/修改的行为**有测试覆盖**（纯 assert + `tmp_path` + PIL 小图）
- [ ] GUI 测试若涉及 app，已走 `_isolate_home` 隔离 HOME
- [ ] 插件相关测试对已装插件 hermetic（monkeypatch `discover_plugins`）
- [ ] **JSON 契约只做加性演进**（未重命名/删除/改语义已有键）
- [ ] 新增 CLI 文案已同时写 `i18n.py` 的 **zh 与 en** 两表
- [ ] 新增 GUI 文案已同时写 `gui/strings.py` 的 **zh 与 en** 两表
- [ ] 命名符合约定（`photo_s` / `photo-s` / `photo-s-tools` / `PhotoS`）
- [ ] 若改了 CLI 命令、MCP 工具或功能计数，已同步 `docs/FEATURES.md`、
      `docs/AGENT_API.md`、`CHANGELOG.md`

## 截图 / 录屏

<!-- GUI 改动请务必附上；before/after 更好。注意不要包含真实私人照片或 GPS 信息。 -->
