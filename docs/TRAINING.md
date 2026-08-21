# PhotoS 训练管线（个人 Lightroom 数据 → 自动调色模型）

> v1.7.1 · 定位：**你的修图数据 + PhotoS 参数空间 = 专属调色模型**。
> 全部基础设施已在核心包内（纯 stdlib/numpy，任何电脑可跑）；本文档同时面向
> 人（你在 5080 那台电脑训练）与 agent（另一台电脑产数据包）。

## 1. 数据包格式（lr_records.jsonl）

`photo-s lr-scan --export-dir DIR` 产出，每行一个 JSON：

```json
{"source": "catalog", "catalog": "/path/1.lrcat", "path": "/原始/RAW路径.ARW",
 "edited": true, "options": {"exposure": 0.4, "contrast": 1.26, "masks": "..."},
 "image_size": [6000, 4000], "white_balance": "As Shot",
 "history": [{"name": "曝光度", "value": "0.40"}], "coverage": {...}}
```

- **`options` 即标签**——与 `ProcessOptions` 字段 / `photo-s batch` 参数同构
- `--render-dir` 产出 before 图（rawpy 默认显影 JPEG，1536px），`image` 键指向
- `--sanitize` 分享前必开：path 只留 basename，原始映射在 `lr_paths.json`（勿外发）

## 2. 产包流程（每台电脑）

```bash
pip install -U photo-s-tools        # 任意电脑
photo-s lr-scan --export-dir ./data --render-dir ./data/before --sanitize
# → data/lr_records.jsonl + data/lr_paths.json + data/before/*.jpg（已编辑照片才渲染）
```

## 2.1 传输（多机 → 训练机）

数据包 = JSONL（几十 KB）+ before 图（每张 ~200-500KB）——整包通常几十 MB：

```bash
# 局域网（推荐，私有不落第三方）
rsync -av data/ user@5080-machine:~/photo_data/mac1/     # 每台电脑一个子目录
# 或 scp / AirDrop / U 盘（单次批量）
```
> 隐私：JSONL 必须 `--sanitize` 过（路径脱敏）；before 图是你自己的照片，
> 走私有通道，勿上传公有云/网盘。

## 2.2 合并（训练机上一条命令）

```bash
photo-s lr-merge ~/photo_data/mac1 ~/photo_data/mac2 ~/photo_data/mac3 \
    --out ./data --json
# → data/lr_records.jsonl（去重 + source_pkg 溯源 + image 绝对路径）
#   data/before/*.jpg（幂等复制，重复文件不重复拷贝）
#   data/lr_paths.json（如有 sanitize 映射）
```
之后直接 `photo-s lr-train --data data/lr_records.jsonl --images data/before`。

## 3. 模型 A：自动基调回归（先做，纯 numpy 零 torch）

```bash
# 任何机器（含产数据的电脑）
photo-s lr-train --data data/lr_records.jsonl --images data/before --out auto_tone.npz
photo-s lr-predict new.jpg --model auto_tone.npz        # → 9 项全局参数
```
- 目标 9 项：exposure/contrast/saturation/vibrance/wb_temp/wb_tint/clarity/texture/dehaze
  （**裁剪/扶正是意图，不学**）；特征 84 维（luma+RGB 直方图+统计）
- 岭回归闭式解，177 样本实测 R²≈0.18（线性基线，数据翻倍会涨）
- 评估：留出 10-15% 后对比预测 vs 真实的 L1；端到端用 `photo-s diff`（PSNR/SSIM）

### 3.1 升级：CLIP + MLP（torch，5080 分钟级）

冻结 `open_clip` ViT-L/14 → 768 维 embedding → MLP(768→256→9)，MSELoss，
lr 1e-3，AdamW，几十 epoch。参考实现 `tools/train_tone_torch.py`
（train 子命令训练存 npz，predict 子命令推理，open_clip 按需安装）。

## 4. 模型 B：小 VLM LoRA（数据 1000+ 后，全功能近似）

基座 **MiniCPM-V 4.6（1.3B，Apache 2.0）** 或 **Qwen3-VL-3B**。任务格式：
`(before 图, 指令) → PhotoS 紧凑字符串`（hsl/curves/masks 全部进文本）。

用 LLaMA-Factory（无需自写训练循环）：

```yaml
# tools/llama_factory_lora.yaml
model_name_or_path: openbmb/MiniCPM-V-4.6
stage: sft
finetuning_type: lora
dataset: photo_s_tone
template: minicpm-v
cutoff_len: 2048
learning_rate: 1.0e-4
num_train_epochs: 5.0
per_device_train_batch_size: 8
gradient_accumulation_steps: 2
lora_rank: 64
lora_alpha: 128
```
数据转换（JSONL → sharegpt 格式）：
```json
{"images": ["before/_DSC0402.jpg"],
 "conversations": [{"role": "user", "content": "给出一组调色参数（PhotoS 紧凑字符串）"},
                    {"role": "assistant", "content": "exposure=0.4,contrast=1.26,hsl=..."}]}
```

**5080-16GB 环境**：PyTorch 2.8+（Blackwell sm_120）、CUDA 12.8、bitsandbytes 0.45+、
`pip install llamafactory`。1.3B QLoRA batch 8 无压力；3B batch 4-8。

## 5. 评估闭环（PhotoS 是渲染器，评估零胶水）

1. `photo-s lr-eval --data data/lr_records.jsonl --images data/before --out eval/ --sample 200`
   → eval_before_*/eval_after_* 对（after 由 PhotoS 用真实 options 渲染）+ 打分模板
2. 预测参数渲染后：`photo-s batch new.jpg --exposure ... ` 或 lr-predict → batch
3. 对比：`photo-s diff before.jpg result.jpg`（PSNR/SSIM）+
   `photo-s audit result.jpg`（质量闸门 pass/fail）+ 教师打分（eval_prompt.md）

## 6. 隐私边界（读前必看）

| 数据 | 内容 | 泄露风险 |
|---|---|---|
| 仓库 fixtures | 纯开发参数 + crs 字段（已裁剪 EXIF/GPS/路径） | 无 |
| lr_records.jsonl（未 sanitize） | **绝对路径**（目录名可能暴露拍摄地/客户） | 分享前必须 `--sanitize` |
| lr_records.jsonl（sanitize） | basename + 参数 | 低（basename 可反查机型序列） |
| before/*.jpg | 你的照片本身 | 你控制分享 |
| 报告/统计 | 聚合计数 | 无 |

**lrxmp 只读 develop 设置 + 文件路径，不读 GPS/EXIF 私有字段**；catalog 以
`mode=ro` 打开，永不写库。训练数据请勿上传公有云；多机传输走私有通道。

## 7. agent 对接速览

```bash
photo-s lr-scan --help          # 产包
photo-s lr-train --help         # 训练（numpy 基线）
photo-s lr-predict --help       # 推理
photo-s lr-recipes --help       # 配方库（风格签名）
photo-s lr-eval --help          # 评测集
photo-s audit --help            # 出片质量闸门
```
技能包 `skills/photo-s/SKILL.md` 已含上述工作流；MCP 25 工具覆盖全部端点。
