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

## 模型权重

模型权重（ONNX，约 10-40MB）**不进 wheel**。首次使用时自动从 GitHub Releases
下载到缓存目录（`~/.cache/photo-s/models/`，可用 `$PHOTOS_CACHE_DIR` 覆盖），
带 sha256 校验。可预下载：

```bash
photo-s plugin fetch scunet
```

> 维护者发布前需在 `photo_s_plugin_scunet/__init__.py` 中把
> `DEFAULT_MODEL_URL` / `DEFAULT_MODEL_SHA256` / `DEFAULT_MODEL_SIZE`
> 更新为真实 GitHub Release 资产（当前为占位值）。
