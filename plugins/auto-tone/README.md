# photo-s-plugin-auto-tone

PhotoS 官方 AI 自动调色插件：CLIP/SigLIP+MLP 模型预测 9 字段
Lightroom 调色参数（exposure / contrast / saturation / vibrance / wb_temp /
wb_tint / clarity / texture / dehaze），附带置信度评估、RAG 检索增强，
可选 Qwen3-VL 美学评分、修图建议、风格化调色与场景偏置。

- 训练数据：1295 张 Lightroom 修图记录（XMP sidecar → 参数）
- 基础模型 v7_clean（CLIP ViT-L-14）：PSNR 29.10 / SSIM 0.9775；
  RAG 在困难样本上 +1.93 dB
- 风格化主模型 siglip_h192_d03（SigLIP ViT-L-16-384）：PSNR 32.21，
  比 v7_clean 高 2.93 dB

## 安装

```bash
pip install photo-s-plugin-auto-tone          # 轻量安装（无重依赖）
pip install 'photo-s-plugin-auto-tone[model]' # + torch / open_clip（核心推理）
pip install 'photo-s-plugin-auto-tone[qwen]'  # + transformers / peft（美学评分、修图建议、Qwen 风格解析）
```

权重不打进 wheel：首次调用时从本仓库 GitHub Release 下载到
`~/.cache/photo-s/models/` 并做 sha256 校验（每次使用前重新校验）。
核心权重在 tag `auto-tone-v0.1.0`（约 4.6MB）；v2.1 风格化权重
`auto_tone_siglip_h192_d03.pt`（~850KB）在 tag `auto-tone-v2.1.0`。
可选 Qwen LoRA 共约 400MB，基座 Qwen3-VL-2B（约 4.3GB）需自备，
通过 `PHOTOS_AUTO_TONE_QWEN_BASE` 指向本地快照或 HF model id；
SigLIP 视觉塔（约 2.6GB）/ CLIP 塔（约 1.7GB）/ SigLIP tokenizer 经
modelstore 下载校验：默认 HuggingFace，国内推荐
`PHOTOS_AUTO_TONE_TOWER_SOURCE=modelscope` 走 ModelScope 镜像
（`auto` = 先 HF 失败自动回落镜像；镜像按上游 sha256 校验，不一致即报错；
HF hub 缓存已命中则零重复下载）。离线可用 `PHOTOS_AUTO_TONE_TOWER_URL` /
`_SHA256` 指向自备文件，其余权重变量见 `models.py` 文档字符串。

插件自身权重另有 ModelScope 镜像仓
[`dwphoto/photo-s-auto-tone-v2`](https://modelscope.cn/models/dwphoto/photo-s-auto-tone-v2)：
`PHOTOS_AUTO_TONE_WEIGHT_SOURCE=auto|github|modelscope`（auto=GitHub
优先失败回落；镜像仓可用 `PHOTOS_AUTO_TONE_MODELSCOPE_REPO` 覆盖）。
注意：`auto_tone_siglip_h192_d03.pt` 的 ModelScope 现存文件是 numpy-2
pickle（`torch.load(weights_only=True)` 拒载）——上传重存版
（`~/Desktop/auto_tone_siglip_h192_d03_resaved.pt`，权重逐位一致）后在
`models.py` 的 `MODELSCOPE_WEIGHTS` 取消注释该行即启用。

## v2.4 新增

- **局部调整词汇表**：`auto_tone` 输出可选 `local: [{region, params}]`
  （region ∈ subject/person/object:label）。引擎经真实管线应用全部
  9 个全局字段 + 蒙版局部调整（旧接线只落 3 个字段）。checkpoint 携带
  局部头即可启用（`local_state_dict` 等键，训练侧见主仓 TRAINING.md §5.1）。
- **美学验证（verify operation）**：`verify_aesthetic(image, prefer)` =
  SigLIP 回归头（毫秒级，`aesthetic_head.pt` 由主仓
  `tools/train_verifier.py` 用 LR 星级评分训练）+ Qwen VLM LoRA 终审。
  `photo-s audit IMG --aesthetic 6` 即美学闸门。

## 用法

```python
from photo_s_plugin_auto_tone import auto_tone, auto_tone_with_style, auto_tone_with_scene

# 普通自动调色
result = auto_tone("/path/to/photo.jpg", strength=0.8)
# {"options": {...9 字段...}, "confidence": 0.72, "warnings": [], ...}

# 风格化调色（v2.1）：任意自然语言风格描述；None 时 SigLIP 自动视觉分析
styled = auto_tone_with_style("/path/to/photo.jpg", "忧郁蓝调", strength=0.8)
# {"schema_version": 2, "options": {...}, "bias": {...}, "bias_source": "preset",
#  "style_desc": "忧郁蓝调", "visual_styles": [...top-3...], ...}

# 场景自适应（v2.1）：552 张 LR 目录统计的 7 场景数据驱动偏置
scene = auto_tone_with_scene("/path/to/photo.jpg", "portrait", strength=0.5)
```

风格化组合三种能力：SigLIP 视觉分析（16 风格 top-K）、Qwen3-VL 文本解析
（自然语言 → 9 字段偏置；`use_qwen=False` 或 Qwen 不可用时回退 8 种手工
预设，无需任何额外下载）。`analyze_visual_style(path)` 单独返回视觉风格。

MCP 工具（`auto_tone` / `aesthetic_score` / `verify_aesthetic`（v2.4）/
`tone_advisor` / `batch_auto_tone` / `auto_tone_with_style` /
`analyze_visual_style`，`batch_auto_tone` 支持 `style_desc` 参数）通过
`api/mcp_tools.register_mcp_tools(mcp)` 注册；REST 路由通过
`api/rest.register_routes(handler_class)` 挂到 `photo-s serve`。
LangChain 封装见 `api/langchain.py`（`get_style_tool()` /
`get_visual_style_tool()`）。

## 平台支持

- 推理设备自动选择：CUDA → Apple MPS → CPU
- Windows / macOS / Linux 均可运行；纯 CPU 可跑核心推理（较慢）
- Qwen 美学评分 / 建议 / 风格解析建议使用 CUDA（CPU 上可用但显著变慢）


## 许可

- **代码**：MIT（与 photo_s 主仓库一致）
- **模型权重**（GitHub Release `auto-tone-v0.1.0` / `auto-tone-v2.1.0`
  上的文件）：[CC-BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) —
  署名-非商用。允许自由使用/研究/再分发，但**禁止商业用途**，且需署名。
  权重由个人 Lightroom 修图记录训练（个人修图风格模型），
  不适合以 MIT 形式无限制商用。详见本目录 `LICENSE-WEIGHTS.txt`。

上游依赖：OpenAI CLIP ViT-L-14（MIT）、SigLIP webli 权重（Apache-2.0）、
Qwen3-VL-2B（Apache-2.0）均允许再发布衍生权重。
