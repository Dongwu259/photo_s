# 📷 PhotoS

<!-- mcp-name: io.github.Dongwu259/photo-s -->

[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Windows%20%7C%20Linux-lightgrey)](https://github.com)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![PyPI](https://img.shields.io/badge/pypi-photo--s--tools-orange)](https://pypi.org/project/photo-s-tools/)

**CLI 给 AI agent 用，GUI 给人用。** PhotoS 是一个跨平台批量照片处理工具箱：
给摄影师一套完整的 Tkinter GUI（v2.2 工作区：图库 / 修图（真实管线实时预览 + 直方图 + 旁侧调整工具 + 照片间复制粘贴设置 + 逐照片撤销）/ 导出（照片队列 + 输出设置 + 命名导出配方）/ 工具四大模块，含审查打分灯箱、去重查看器），
给 AI agent 一套带统一版本化 JSON 契约的 CLI / REST / MCP 接口。

> 🖥 GUI 给人用 — ⌨️ CLI 给 AI agent 用 — `pip install photo-s-tools`

**中文** · [English](docs/README.en.md)

---

## 🤖 为 AI agent 而生

PhotoS 首先是一个 **AI agent 就绪的图像管线**：四条集成通道，全部挂在同一个
版本化 JSON 契约上（`schema_version`，加性演进——升级永不破坏消费者）。

| 通道 | 接入方式 |
|---|---|
| **MCP server** — 26 核心工具 + 插件自动注册（process / suggest / select / hdr / blurfaces / dedup …） | `claude mcp add photo-s -- photo-s mcp` |
| **现成 SKILL.md** — 支持 skill 的 agent 即取即用，零额外依赖 | `cp -r skills/photo-s ~/.claude/skills/` |
| **REST API** — 异步任务 + SSE 进度 | `photo-s serve --port 0 --token auto --ready-file x.json` |
| **Python 库直调** — 无 IPC 开销 | `from photo_s.engine import batch_process` |

所有输出带 `schema_version`；JSON 键永远英文；单文件错误不中断整批；
破坏性操作必须显式传参。完整契约见 [`docs/AGENT_API.md`](docs/AGENT_API.md)。

---

## ✨ 功能特性

| 功能 | GUI | CLI | 说明 |
|---|---|---|---|
| 批量压缩 | ✅ | ✅ | JPEG/WebP/HEIC/AVIF 质量调优、色度子采样（444/422/420） |
| 目标体积模式 | ✅ | ✅ | 自动调优质量以控制在目标文件体积以内 |
| 格式转换 | ✅ | ✅ | JPEG / PNG / WebP / TIFF / BMP / HEIC / AVIF |
| RAW 解码 | ✅ | ✅ | 22+ 种相机 RAW 格式，内置支持（rawpy/libraw）；去马赛克算法可选、色彩空间（sRGB/AdobeRGB/ProPhotoRGB）、16-bit TIFF 输出、自动打 sRGB ICC |
| 缩放 / 比例 | ✅ | ✅ | 最大尺寸、百分比或最长边上限 |
| 视觉预览 | ✅ | — | 原图↔处理后实时并排预览（经真实管线渲染，v2.4 含逐照片调整注入） |
| 影调与色彩 | ✅ | ✅ | 亮度/对比度/饱和度/伽马/锐化，黑白、复古 |
| 导出锐化 | ✅ | ✅ | LR 式输出级 USM，半径随输出分辨率缩放 |
| 白平衡 | ✅ | ✅ | 色温 K，或灰卡采样 |
| WB tint 轴 | ✅ | ✅ | 绿(-)/品红(+) G-M 轴 |
| 点曲线 / 色阶 | ✅ | ✅ | PCHIP 点曲线，手动黑/白场/伽马 |
| 三向颜色分级 | ✅ | ✅ | 阴影/中间调/高光 色相 + 饱和分区 |
| HSL 分色 | ✅ | ✅ | 8 色域，色相/饱和/亮度偏移 |
| 点颜色 | ✅ | ✅ | 取样色定向色相/饱和/亮度 + 范围容差 |
| 局部蒙版 | ✅ | ✅ | 命名线性/径向/颜色范围蒙版，蒙版内 11 项局部调整 |
| 镜头矫正 | ✅ | ✅ | 手动畸变 k1 / 去暗角 / 消色差（纯 numpy）；用户维护的命名镜头档案 |
| 感知分析 | ✅ | ✅ | 直方图/通道统计/色温倾向/曝光/模糊（`analyze`） |
| 参数推荐 | — | ✅ | 规则型 `suggest`：分析统计 → 保守修复参数 + 理由（零模型离线） |
| 自然饱和度 / 清晰度 / 纹理 | ✅ | ✅ | 反向加权饱和，局部对比 |
| 去雾 / 暗角 / 颗粒 | ✅ | ✅ | 暗通道去雾，径向暗角，胶片颗粒 |
| 曝光 | ✅ | ✅ | 曝光档位调整，或自动归一化到目标 |
| 自动色阶 | ✅ | ✅ | 2% 裁切直方图拉伸 |
| 高光恢复 | ✅ | ✅ | LR 式：压缩硬切高光，恢复出渐变细节 |
| LOG 还原 | ✅ | ✅ | SLOG3/CLOG3/LOGC3/DLOG/VLOG/HLG（1D LUT，零依赖） |
| LUT 调色 | ✅ | ✅ | .cube 三线性（插件加四面体 + 5 个电影预设） |
| 降噪 | ✅ | ✅¹ | NLM（`[enhance]` 可选依赖） |
| 自动扶正 | ✅ | ✅¹ | 校正地平线，置信度门控（`[enhance]` 可选依赖） |
| HDR 合并 | ✅ | ✅¹ | 曝光融合，手持对齐（`[enhance]` 可选依赖） |
| 人脸模糊 | ✅ | ✅¹ | 模糊或马赛克人脸，Haar cascade（`[enhance]` 可选依赖） |
| 抠图 / 背景移除 | ✅ | ✅ | AI 分割（`subject`/`person`/`object:类别`）或颜色键控（`color:R,G,B[tol,feather,invert]`——白底文字/logo 专用）→ alpha 透明输出，PNG/WebP/TIFF/AVIF/HEIC（JPEG 按文件报错，绝不静默拍平） |
| 裁剪 / 旋转 / 翻转 / 留边 | ✅ | ✅ | 统一比例裁剪 + 任意几何 |
| 打印尺寸 | ✅ | ✅ | 中心裁剪 + 指定 DPI 的精确打印像素 |
| 智能重命名 | ✅ | ✅ | 日期/相机/序号模板 |
| 自动整理归档 | ✅ | ✅ | 日期/相机子文件夹归类 |
| 水印 | ✅ | ✅ | 文字 + 图片水印，7 个位置 |
| 多尺寸输出 | ✅ | ✅ | 一份输入，N 份带标签输出 |
| 元数据打标 | ✅ | ✅ | 评分/关键词/标题批量打标（UserComment） |
| 元数据筛选 | ✅ | ✅ | 按评分/关键词筛出照片 |
| 元数据导入 | — | ✅ | 从表格批量写入 |
| 选片（筛选） | ✅ | ✅ | 曝光/清晰度筛选（GUI 仅保留符合项，可撤销）；`--score` 质量评分排序 + `--burst` 连拍组留最佳 |
| 选片归档（评分） | ✅ | ✅ | 按评分分拣——精选/淘汰双阈值（≥4 精选、≤2 淘汰） |
| 连拍选图 | ✅ | ✅ | 每组保留最清晰 |
| 校验和清单 | ✅ | ✅ | SHA-256 归档完整性 + 校验 |
| HTML 画廊 | ✅ | ✅ | 自包含 index.html + 缩略图 |
| 预设 | ✅ | ✅ | 保存/加载命名配置 + 内置 `lr-look`（LR 风格：S 曲线+自然饱和+导出锐化） |
| 多配置批量 | — | ✅ | 一份输入，N 份输出配置 |
| 并行处理 | ✅ | ✅ | 多线程 |
| JSON 输出 | — | ✅ | 供 AI agent 消费的机器可读输出 |
| 配置文件 | — | ✅ | TOML 默认值 |
| EXIF 编辑 | — | ✅ | 批量版权/作者/GPS |
| 预设一键套用 | — | ✅ | 一键套用已存风格 |
| EXIF 日期偏移 | — | ✅ | 时区/相机时钟修正 |
| 隐私清理 | — | ✅ | 移除 EXIF + ICC + GPS |
| 同步日期 | — | ✅ | 输出 mtime ← EXIF 拍摄时间 |
| 文件夹监视 | ✅ | ✅ | 自动处理新文件（`[watch]` 可选依赖） |
| 自动旋转 | ✅ | ✅ | 基于 EXIF Orientation |
| 图片去重 | ✅ | ✅ | 感知哈希重复检测 |
| 质量指标 | ✅ | ✅ | SSIM / 模糊分 |
| CSV 报告 | — | ✅ | 逐文件统计 |
| 完整性检查 | — | ✅ | 损坏文件扫描 |
| 联系表 | ✅ | ✅ | 网格拼图 |
| 色彩管理 | — | ✅ | sRGB / CMYK 展平 |
| REST API | — | ✅ | 供 agent 使用的 HTTP 服务（异步任务 + SSE 进度） |
| 插件系统 | — | ✅ | 第三方插件支持 |
| 官方插件管理 | — | ✅ | list/install/info/fetch + pip 安装 |
| MCP server | — | ✅ | 向 MCP 客户端（Claude Desktop / Claude Code / 任意客户端）暴露 26 个核心工具（插件自动追加） |
| 批量基准 | — | ✅ | 并发扩展实测 |
| AI 识别蒙版 | ✅ | ✅¹ | 主体/人物/物体（80 类）一键生成蒙版，U2Netp/HumanSeg/YOLOv8n-seg（v1.8，onnx 权重自动下载校验） |
| 笔刷 + 组合蒙版 | ✅ | ✅ | 笔刷涂抹蒙版；A&B / A-B 组合引用已命名蒙版（v1.8） |
| AI 自动调色 | ✅ | ✅ | auto-tone 官方插件：CLIP+MLP 预测 9 项全局参数 + RAG 检索历史修图（权重 CC-BY-NC 4.0，非商用）；v2.3 引擎槽位接线（`--auto-tone`），装后 MCP/REST 工具自动注册；v2.4 Develop「AI 调色」按钮——参数写入逐照片覆盖层，可微调/可撤销；v2.4 局部调整词汇表（模型预测 subject/person/object 蒙版内调整，经蒙版管线应用） + 美学 verifier（`audit --aesthetic`，SigLIP 头/Qwen 终审）|
| LR 数据桥 | — | ✅ | `lr-scan` 扫描 Lightroom 目录/XMP → 训练数据；`lr-train`/`lr-predict` 岭回归基调模型；`lr-merge` 合并多机数据包（v1.9） |
| 出片审计 | — | ✅ | `audit` 质量闸门（pass/fail + 原因，agent 终止条件）；`--aesthetic 1-10` 模型美学闸门（v2.4，auto-tone 插件：SigLIP 头/Qwen 终审）；`diff` 前后对比；`preview` base64 快照（v1.9） |
| GPS 地理标记 | — | ✅ | GPX 轨迹插值写 GPS EXIF（时区偏移自动换算，跨日期变更线正确插值） |
| SCUNet 强降噪 | — | ✅ | 官方插件（ONNX）：强度感知混合 + 分块推理，大图不 OOM |

> ¹ 降噪 / 自动扶正 / HDR / 人脸模糊需要可选依赖：
> `pip install photo-s-tools[enhance]`（opencv-python-headless）。
> 未安装时给出明确安装提示，不影响其余功能。

---

## 📦 安装

```bash
pip install photo-s-tools            # 核心——内置 RAW 解码（rawpy）
pip install "photo-s-tools[enhance]" # + opencv：人脸模糊 / HDR / 降噪 / 扶正
pip install "photo-s-tools[tiff16]"  # + tifffile：16-bit RAW → TIFF 输出
pip install "photo-s-tools[mcp]"     # + MCP server（Python 3.10+）
```

零安装（uvx）：`uvx --from photo-s-tools photo-s --help` ·
`uvx --from "photo-s-tools[mcp]" photo-s mcp`

## 🚀 快速上手

```bash
photo-s batch 'RAW/*.ARW' --format jpeg -o out/ -q 90   # 批量 RAW → JPEG
photo-s batch 'RAW/*.ARW' -o out/ -q 95 --jpeg-subsampling 444 \
  --raw-demosaic amaze                                # 极致画质 RAW → JPEG
photo-s batch 'RAW/*.ARW' -o out/ --preset lr-look      # 内置 LR 风格出片
photo-s compress *.jpg --target-size 5MB -j 8           # 自动调优到 ≤5MB
photo-s select ~/shoot/ -r --selects-dir 精选 --rejects-dir 淘汰 --dry-run
photo-s hash ~/deliver/ -o manifest.csv --verify manifest.csv
```

`photo-s --help` 列出全部 35 个子命令。语言：`--language en|zh|auto`。

---

## 🧭 文档

| 文档 | 内容 |
|---|---|
| [`docs/FEATURES.md`](docs/FEATURES.md) | 完整功能清单——35 个 CLI 命令、引擎管线 |
| [`docs/AGENT_API.md`](docs/AGENT_API.md) | Agent 契约：JSON 结构、退出码、REST、MCP |
| [`docs/PLUGINS.md`](docs/PLUGINS.md) | 插件系统：SCUNet 降噪、LUT、自己写插件 |
| [`docs/GUI_CHANGES.md`](docs/GUI_CHANGES.md) | GUI 行为与接口契约 |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | 版本路线（v1.6.0：Lightroom 方向调色） |

> 命名：PyPI 发行名 **`photo-s-tools`**（原名 `photo-s` 被 PyPI 拦截）·
> CLI 命令 `photo-s` · Python 包 `photo_s` · 品牌 **PhotoS**。

---

## ⚠️ 限制与说明

PhotoS 是**批量 / 交付导向管线**，不是交互式编辑器——不做 RAW 域编辑。局部编辑是规格驱动的：命名蒙版（linear/radial/color/AI 分割/笔刷/组合算子）+ 蒙版内局部调整，全部以紧凑字符串建模，经 CLI/REST/MCP/preset 零胶水传递。

- **设备上推理，无云端。** 降噪模型权重（SCUNet）首次使用时下载到本机；不上传任何数据。
- **许可。** 官方代码与多数官方模型权重（含 SCUNet 检查点）为 **MIT**——可自由商用；
  但 auto-tone 插件的权重为 **CC-BY-NC 4.0**（非商用，训练数据来自个人照片库），
  商用需另行授权。第三方插件与模型各自持有自己的许可；商用再分发前请自行核实。

## 📄 许可证

MIT
