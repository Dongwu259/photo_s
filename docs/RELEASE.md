# PhotoS 发布清单 — Release Checklist

从源码到可安装的两个发行版：**`photo-s`**（核心）与 **`photo-s-plugin-scunet`**（官方插件）。
定位 "CLI for AI agents"，发布后 agent 才能 `pip install photo-s`。

## 前置（一次性，需要 GitHub / PyPI 账号）

1. **GitHub 创建仓库**，推送本仓库：
   ```bash
   git remote add origin git@github.com:Dongwu259/photo_s.git
   git push -u origin main
   ```
   推送前确认 `.gitignore` 已排除 `.claude/`、`*.egg-info/`、`build/`、`dist/`。

2. **PyPI 建项目 `photo-s`**：登录 pypi.org → 右上角 Account settings →
   Add API token → 或直接「Add a new project」创建 `photo-s`。

3. **PyPI 启用 Trusted Publishers**：PyPI 项目 `photo-s` → Manage →
   Publishing → 添加 `Dongwu259/photo_s`，环境名 **`pypi`**（与 publish.yml 的
   `environment: pypi` 一致）。

## 发布核心 `photo-s`（每次发版）

```bash
# 1. 本地验证（必须全绿）
python3 -m pytest tests/ -q                 # 352 个
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
python3 -m pip install photo-s
photo-s --version
```

## 发布官方插件 `photo-s-plugin-scunet`（独立版本）

SCUNet 权重（ONNX，图 + 外部数据两个文件，约 77MB）**不进 wheel**，已托管在
HuggingFace `Heliosoph/scunet-onnx`（MIT，由官方 cszn/SCUNet 权重重新导出）。
若想改为第一方托管：把两个文件挂到本仓库 GitHub Release，再更新
`plugins/scunet/photo_s_plugin_scunet/__init__.py` 里的 `DEFAULT_*` 常量。

```bash
# 1. 独立构建插件 wheel
cd plugins/scunet
python3 -m build --wheel
# dist/photo_s_plugin_scunet-0.1.0-py3-none-any.whl

# 2. 上传到 PyPI（需在 PyPI 建 photo-s-plugin-scunet 项目并加信任）
python3 -m twine upload dist/*.whl          # 或单独加 trusted publisher

# 3. 验证：安装后 photo-s 能看到 provider
pip install photo-s-plugin-scunet
photo-s plugin list --json                  # installed: scunet, provides: [denoise]
photo-s plugin fetch scunet                 # 预下载权重（~77MB, sha256 校验）
```

> 插件与核心是**独立发行版**：插件修复不必等核心发版。`registry.py` 里
> `min_photo_s_version` 约束核心最低版本；核心发版无需重新发布插件。

## 常见问题

- **publish.yml 没触发**：确认 tag 是 `vX.Y.Z` 格式（以 `v` 开头）、已 push、
  PyPI trusted publisher 已配置 `Dongwu259/photo_s` + environment `pypi`。
- **wheel 里混入 scunet**：核心 `pyproject.toml` 的 `packages.find` 只含
  `photo_s*`，`plugins/` 不在内——如果出现，检查是否误把 `plugins` 加进了包含。
- **Windows 打包**：`python packaging/build.py` 构建 `.exe`；注意 `plugins/`
  插件是独立包，打包核心 exe 时默认不带（需要时单独处理）。
