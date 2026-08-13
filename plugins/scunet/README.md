# photo-s-plugin-scunet — PhotoS 官方 SCUNet 强降噪插件

PhotoS 官方可选插件：基于 SCUNet（ONNX，onnxruntime）的高强度降噪，
适用于高 ISO / 弱光照片。比核心内置的 OpenCV NLM 降噪更强（恢复更多纹理）。

## 安装

```bash
# 方式一（推荐，agent 友好）：PhotoS 插件管理器
photo-s plugin install scunet

# 方式二：传统 pip
pip install photo-s-plugin-scunet

# 查看状态
photo-s plugin list
photo-s plugin info scunet
```

## 使用

安装后，`--denoise N` 自动优先使用本插件（未装本插件时回退到内置 NLM）：

```bash
photo-s batch ~/highiso/ --denoise 12
```

> 强度语义：SCUNet 是固定噪声级盲降噪模型，`N` 映射为原始图与全量降噪
> 输出的线性混合 `t = clip(N/15, 0, 1)`——`N=0` 原图不动，`N>=15` 全量
> 模型输出，中间线性过渡（与核心 NLM 的 ~3-20 有效区间手感一致）。

## 模型权重

使用 SCUNet 彩色降噪 (noise-25) 检查点，由官方 cszn/SCUNet PyTorch 权重
重新导出为 ONNX（保留上游 MIT 许可），托管于 HuggingFace
[`Heliosoph/scunet-onnx`](https://huggingface.co/Heliosoph/scunet-onnx)。

权重**不进 wheel**，首次使用时自动下载到缓存目录
（`~/.cache/photo-s/models/`，可用 `$PHOTOS_CACHE_DIR` 覆盖），带 sha256 校验。
SCUNet 导出为 **external-data 格式**：图 (`.onnx`，~3.8MB) 与权重
(`.onnx.data`，~73MB) 两个文件都要下载；两者保持规范文件名以便 onnxruntime
解析。可预下载：

```bash
photo-s plugin fetch scunet
```

> 默认指向社区 HF 镜像。如需第一方托管，可把两个文件重新挂到自己的
> GitHub Release 并更新 `photo_s_plugin_scunet/__init__.py` 中的
> `DEFAULT_MODEL_URL/_SHA256/_SIZE` 与 `DEFAULT_DATA_*` 常量
> （或保留 `PHOTOS_SCUNET_MODEL_*` 环境变量覆盖，测试即用此机制）。
