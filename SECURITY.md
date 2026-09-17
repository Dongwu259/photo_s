# 安全政策 — Security Policy

## 支持的版本

只对**最新发布版本**提供安全修复。请先升级再报告：

```bash
pip install -U photo-s-tools
photo-s --version
```

| 版本 | 支持 |
|---|---|
| 2.5.x（最新） | ✅ |
| 更早版本 | ❌（请升级） |

官方插件（`photo-s-plugin-*`）按其自身版本独立支持，同样只覆盖最新版。

## 如何报告漏洞

**请不要开公开 issue。**

优先使用 GitHub 的私密报告通道：

> 仓库 → **Security** 标签 → **Report a vulnerability**
> （<https://github.com/Dongwu259/photo_s/security/advisories/new>）

也可以直接发邮件到 **1634103640@qq.com**，标题前缀 `[SECURITY]`。

请尽量包含：

- 影响的版本与平台（macOS / Windows / Linux，Python 版本）
- 复现步骤或最小复现仓库（涉及照片的话，请用可公开的图或合成图）
- 影响评估（能读到什么、能改到什么、是否需要用户交互）
- 如有，建议的修复方向

**请不要在报告里附带真实个人照片或 EXIF 中的隐私信息**——需要样本时请自行
合成或使用公开素材。

## 响应时限

| 阶段 | 目标 |
|---|---|
| 确认收到 | 3 天内 |
| 初步评估（是否漏洞、严重级别） | 7 天内 |
| 修复 + 发布 patch | 视严重级别，高危尽量 30 天内 |
| 公开致谢（征得同意后） | 随修复版本发布 |

这是个人维护的开源项目，时限是尽力而为的承诺，不是 SLA。

## 本项目特别关注的攻击面

PhotoS 会读写用户自己的照片目录，并对外提供 REST / MCP 接口，以下区域是
我们最在意的，欢迎针对它们做安全测试：

- **路径穿越**：`--output-dir` / 重命名模板 / `select` 归档的 basename 平铺
  与目录逃逸（`_has_path_traversal` / `_sanitize_stem`）
- **REST server**：认证与 token 处理、DNS-rebinding 防护、请求体上限、
  绑定地址默认值
- **MCP server**：工具参数注入、把任意路径当输入/输出目录
- **元数据注入**：EXIF / XMP 写出时的 XML 转义与长度溢出（`embed_xmp_jpeg`、
  `options_to_xmp`）
- **解压炸弹 / 资源耗尽**：超大图、恶意构造的图片文件（`MAX_IMAGE_PIXELS`
  为 512MP 有界放宽）
- **模型权重供应链**：`modelstore` 的下载 URL 与 sha256 校验是否可被绕过
- **插件加载**：`entry_points` 发现机制与 provider 槽位调用

以下是**已知且有意为之**的行为，不算漏洞：

- 本地 CLI/GUI 默认对用户指定的路径有完全读写权限（这是工具的本职）。
- `photo-s serve` 未显式设置 token 时的行为由文档定义，请以
  [`docs/AGENT_API.md`](docs/AGENT_API.md) §3.2 为准；把服务暴露到公网
  是使用者自己的部署决策。
- `--scrub` 之外的元数据保留（EXIF/ICC/DPI）是设计目标，不是泄漏。

## 依赖与权重

第三方依赖的漏洞请直接报给上游，同时也欢迎告诉我们，我们会在下一个 patch
升级。模型权重的完整性由各固定 URL + sha256 钉死；若发现校验可被绕过，
请按上面的流程私密报告。
