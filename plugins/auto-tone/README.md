# photo-s-plugin-auto-tone

PhotoS 官方 AI 自动调色插件：CLIP+MLP 模型（v7_clean）预测 9 字段
Lightroom 调色参数（exposure / contrast / saturation / vibrance / wb_temp /
wb_tint / clarity / texture / dehaze），附带置信度评估、RAG 检索增强，
可选 Qwen3-VL 美学评分与修图建议。

- 训练数据：1295 张 Lightroom 修图记录（XMP sidecar → 参数）
- 测试集指标：PSNR 29.10 / SSIM 0.9775；RAG 在困难样本上 +1.93 dB

## 安装

```bash
pip install photo-s-plugin-auto-tone          # 轻量安装（无重依赖）
pip install 'photo-s-plugin-auto-tone[model]' # + torch / open_clip（核心推理）
pip install 'photo-s-plugin-auto-tone[qwen]'  # + transformers / peft（美学评分、修图建议）
```

权重不打进 wheel：首次调用时从本仓库 GitHub Release（tag
`auto-tone-v0.1.0`）下载到 `~/.cache/photo-s/models/` 并做 sha256 校验。
核心权重约 4.6MB；可选 Qwen LoRA 共约 400MB，基座 Qwen3-VL-2B（约 4.3GB）
需自备，通过 `PHOTOS_AUTO_TONE_QWEN_BASE` 指向本地快照或 HF model id。

离线 / 镜像场景可用环境变量覆盖下载地址（见 `models.py` 文档字符串）。

## 用法

```python
from photo_s_plugin_auto_tone import auto_tone
result = auto_tone("/path/to/photo.jpg", strength=0.8)
# {"options": {...9 字段...}, "confidence": 0.72, "warnings": [], ...}
```

MCP 工具（`auto_tone` / `aesthetic_score` / `tone_advisor` /
`batch_auto_tone`）通过 `api/mcp_tools.register_mcp_tools(mcp)` 注册；
REST 路由通过 `api/rest.register_routes(handler_class)` 挂到
`photo-s serve`。LangChain 封装见 `api/langchain.py`。

## 平台支持

- 推理设备自动选择：CUDA → Apple MPS → CPU
- Windows / macOS / Linux 均可运行；纯 CPU 可跑核心推理（较慢）
- Qwen 美学评分 / 建议建议使用 CUDA（CPU 上可用但显著变慢）
