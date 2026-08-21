# PhotoS 发布清单 — Release Checklist

从源码到可安装的两个发行版：**`photo-s-tools`**（核心）与 **`photo-s-plugin-scunet`**（官方插件）。
定位 "CLI for AI agents"，发布后 agent 才能 `pip install photo-s-tools`。

## 前置（一次性，需要 GitHub / PyPI 账号）

1. **GitHub 创建仓库**，推送本仓库：
   ```bash
   git remote add origin git@github.com:Dongwu259/photo_s.git
   git push -u origin main
   ```
   推送前确认 `.gitignore` 已排除 `.claude/`、`*.egg-info/`、`build/`、`dist/`。

2. **PyPI 配置 Trusted Publishers**（PyPI 没有"新建项目"按钮——项目在首次
   上传时自动创建）：pypi.org → Account settings → Publishing → Add publisher：
   PyPI Project 填 **`photo-s-tools`**（项目尚不存在没关系，会成为 pending
   project）、Owner `Dongwu259`、Repository `photo_s`、Workflow `publish.yml`、
   Environment **`pypi`**（与 publish.yml 的 `environment: pypi` 一致）。
   > 发行名为什么是 `photo-s-tools`：`photo-s` 被 PyPI 拒收（与已有 `photos`
   > 包太相似，防抢注检查无申诉通道）；CLI 命令 `photo-s`、包名 `photo_s` 不变。

## 发布核心 `photo-s-tools`（每次发版）

```bash
# 0. v1.8.0+ 专属：先上传三个 AI 分割权重为 GitHub release 附件
#    （URL 写死在 photo_s/segmask.py WEIGHTS：u2netp.onnx /
#     pphumanseg.onnx / yolov8n-seg-fp16.onnx，tag 必须正好 v1.8.0；
#     本地验证文件 /tmp/v18_weights/，shasum -a 256 与 pin 值复核一致）
#    gh release create v1.8.0 --title "v1.8.0" --notes "..." \
#      /tmp/v18_weights/u2netp.onnx /tmp/v18_weights/pphumanseg.onnx \
#      /tmp/v18_weights/yolov8n-seg-fp16.onnx
#    不传则 AI 蒙版首次使用下载失败（不静默）。

# 1. 本地验证（必须全绿）
python3 -m pytest tests/ -q                 # 1072 个
python3 -m photo_s.cli --help               # CLI 冒烟
python3 -m photo_s.cli plugin list --json   # 官方插件目录

# 2. 构建 wheel（验证干净构建 + entry_points 正确）
python3 -m pip install build
python3 -m build --wheel
# 检查 dist/*.whl: entry_points.txt 应为 `photo-s = photo_s.cli:main`
# 不应包含 plugins/scunet（那是独立发行版）
unzip -p dist/*.whl '*/entry_points.txt'

# 3. 提交 + 打 tag → 触发 publish.yml → PyPI trusted publishing
git add -A && git commit -m "Release vX.Y.Z"
git tag vX.Y.Z
git push origin main --tags

# 4. 验证安装
python3 -m pip install photo-s-tools
photo-s --version
```

## 发布官方插件 `photo-s-plugin-scunet`（独立版本）

SCUNet 权重（ONNX，图 + 外部数据两个文件，约 77MB）**不进 wheel**，已托管在
HuggingFace `Heliosoph/scunet-onnx`（MIT，由官方 cszn/SCUNet 权重重新导出）。
若想改为第一方托管：把两个文件挂到本仓库 GitHub Release，再更新
`plugins/scunet/photo_s_plugin_scunet/__init__.py` 里的 `DEFAULT_*` 常量。

```bash
# 1. 一次性：在 PyPI 的 photo-s-plugin-scunet 项目添加 trusted publisher
#    （与核心同一个仓库/环境）：
#    Publishing → Add trusted publisher →
#    owner Dongwu259 / repo photo_s / workflow publish.yml / environment pypi

# 2. 打 tag 即发布（publish.yml 的 publish-plugin job，
#    在 plugins/scunet/ 下 python -m build，wheel 不带权重）
git tag scunet-v0.2.0 && git push origin scunet-v0.2.0

# 3. 验证：安装后 photo-s 能看到 provider
pip install photo-s-tools photo-s-plugin-scunet
photo-s plugin list --json                  # installed: scunet, provides: [denoise]
photo-s plugin fetch scunet                 # 预下载权重（~77MB, sha256 校验）
photo-s batch ~/highiso/ --denoise 12       # 端到端（首次使用自动下载权重）
```

> 插件与核心是**独立发行版**：插件修复不必等核心发版。`registry.py` 里
> `min_photo_s_version` 约束核心最低版本；核心发版无需重新发布插件。
>
> **新插件发布（v1.3.0 起）**：publish.yml 的 publish-plugin job 已参数化——插件
> 目录从 tag 前缀自动推导（`scunet-v*` → plugins/scunet，`lut-v*` → plugins/lut）。
> 发布 `photo-s-plugin-lut`（纯 numpy，无权重）：
> ```bash
> git tag lut-v0.1.0 && git push origin lut-v0.1.0
> pip install photo-s-tools photo-s-plugin-lut
> photo-s plugin list --json                  # installed: lut, provides: [lut]
> photo-s batch ~/shoot/ --lut filmic-v1      # 预设名即用（无插件时用内置三线性读 .cube）
> ```

## 常见问题

- **publish.yml 没触发**：确认 tag 是 `vX.Y.Z` 格式（以 `v` 开头）、已 push、
  PyPI trusted publisher 已配置 `Dongwu259/photo_s` + environment `pypi`。
- **wheel 里混入 scunet**：核心 `pyproject.toml` 的 `packages.find` 只含
  `photo_s*`，`plugins/` 不在内——如果出现，检查是否误把 `plugins` 加进了包含。
- **Windows 打包**：`python packaging/build.py` 构建完整版 `.exe`（GUI+CLI+MCP）；
  `--lite` 构建精简版 `photo-s-lite.exe`（CLI+MCP，构建期剔除 gui/tkinter）。
  注意 `plugins/` 插件是独立包，打包核心 exe 时默认不带（需要时单独处理）。
