# PhotoS 版本路线 — Roadmap

> 节奏（2026-08-14 定）：**patch 随时发**（bug 修复 / 依赖升级 / 小优化 → vX.Y.Z+1，
> 不必凑轮）；**主题大轮攒 1-2 月发 minor**。每个 minor 一个清晰主题。

## 已发布

| 版本 | 主题 | 内容 |
|---|---|---|
| v1.0.0 | 首发 | CLI + 引擎核心 |
| v1.2.0 | GUI 补全 | 6 工作流入口（预览/监视/联系表/cull/hash/预设）+ 安全修复 |
| v1.3.0 | Agent 集成 + LUT + 性能工具 | MCP 7→11 工具、SSE 进度、LUT 调色 + 插件、auto-jobs、`bench`、`plugin scaffold`、Pillow14 兼容 |

## 规划中

### v1.3.1+（patch 轨道，随时发）
- [ ] 依赖升级与平台坑修复（rawpy / Pillow 小版本、Windows/Linux 真机问题）
- [ ] bench 命令顺手增强（如需：--evaluate 加 SSIM、每阶段计时）
- [ ] 文档/示例补全

### v1.4.0（主题：性能实测收尾 + GUI 深化）
**A. 性能实测收尾（数据驱动，v1.3.0 的 bench 就是为这轮铺路）**
- [ ] 用户在真实照片集跑 `photo-s bench --dir <photos> -j 1,2,4,8`，记录加速比
- [ ] 据数据决策：线程已饱和 → 多进程不值得做，改线程调优文档
      （`OMP_NUM_THREADS` / onnxruntime intra-op threads）
- [ ] 若纯 Python 段（piexif EXIF / rename 渲染 / 插件分派）占比大 → CLI/server
      加 ProcessPool（模块级 worker + picklable 参数，GUI 保持线程池）

**B. GUI for humans 深化**
- [ ] EXIF 编辑器 UI：从 rating/keywords/title 扩到相机/镜头/ISO/快门/光圈/日期等
- [ ] 批量重命名实时预览：`{date}_{camera}_{seq}` 模板渲染预览 + 冲突检查
- [ ] 多图并排对比（2+ 张，含放大/同步滚动）

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
