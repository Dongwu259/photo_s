# 贡献指南 — Contributing to PhotoS

> 中文优先。English speakers: the essentials are in every section header — the
> dev loop, test commands and pull-request rules are all code blocks, and
> [`CLAUDE.md`](CLAUDE.md) is the machine-readable architecture contract.

感谢你愿意贡献。PhotoS 的定位是 **"CLI for AI agents, GUI for humans"**，
所以最重要的两条规则是：**JSON 契约只做加性演进**、**改动必须带测试**。

---

## 1. 环境准备

```bash
git clone https://github.com/Dongwu259/photo_s.git
cd photo_s
python3 -m venv .venv && source .venv/bin/activate

pip install -e ".[all]"     # 核心 + 全部可选依赖（含 tkinter 的 GUI 依赖）
pip install pytest
```

最低支持 **Python 3.9**（CI 覆盖 3.9–3.12）。MCP server 需要 3.10+。
`rawpy` 是核心依赖；GUI 需要系统自带的 tkinter（macOS 官方 python.org 版自带，
Homebrew 版可能需要 `brew install python-tk`）。

## 2. 开发循环

```bash
python3 -m pytest tests/ -q                    # 全量（当前 1490 个，约 6 分钟）
python3 -m pytest tests/test_engine.py -q      # 单文件
python3 -m pytest tests/ -q -k mask            # 按关键字
python3 -m photo_s.cli --help                  # CLI 冒烟
python3 -m photo_s.cli mcp --list-tools        # MCP 工具 schema（需 [mcp]）
python3 main.py                                # 启动 GUI
```

提交前**必须**跑一次全量测试。CI 会在 Linux 3.9–3.12、Windows 真实 Tk、
装有 SCUNet 插件的环境下各跑一遍。

## 3. 改动规则（会被 review 直接打回的几条）

### 3.1 JSON 契约只做加性演进

所有 `--json` / REST / MCP 输出都经 `contract.versioned()` 带顶层
`schema_version`。**新增键是 additive（不递增版本）；禁止重命名/删除/改语义
已有键**——那属于 breaking，必须递增 `SCHEMA_VERSION` 并在 CHANGELOG 标注。
`tests/test_contract.py` 会强制这一点。

### 3.2 测试要求

- 纯 `assert` + `pytest` 的 `tmp_path`，用 PIL 生成小图，不依赖测试机上的真实照片。
- **GUI 测试必须隔离 HOME**（`tests/test_gui_*.py` 的 `_isolate_home` autouse
  夹具）。app 会从 `~/.photos/gui_state.json` 恢复几何/缩略图/活动模块，真实
  HOME 的污染会让无关测试意外渲染 Develop 面板并触发临时目录断言。
- **插件相关测试必须对已装插件 hermetic**：monkeypatch
  `photo_s.plugin.discover_plugins`，否则开发机上装过的插件会让结果不稳定。
- 引擎层用 `tests/test_features.py` 里的 `_process(src, out_dir, **kwargs)` 助手。

### 3.3 国际化（两套字符串表都必须齐）

CLI 的 `photo_s/i18n.py` 与 GUI 的 `photo_s/gui/strings.py` **zh/en key 集合
必须完全一致**（`_t` 缺 key 会静默回退，造成"看起来能用"的漏译）。
parity 由 `test_i18n.py` / `test_gui_settings.py` 强制。
新增 CLI 文案必须同时写 zh 与 en。`--json` 输出的键永远是英文；面向人的文本
走 `jout`（`--json` 时打到 stderr）。

### 3.4 命名（不要"统一"）

| 上下文 | 写法 |
|---|---|
| Python 包 / import | `photo_s` |
| CLI 命令 | `photo-s` |
| PyPI 发行名 | `photo-s-tools` |
| UI / 品牌 / 文档标题 | `PhotoS` |

### 3.5 架构不变量

`CLAUDE.md` 的「关键不变量」一节是权威来源，改引擎/GUI 前请先读。最常踩的两条：

- **`ProcessOptions` 拷贝统一走 `dataclasses.replace`**（不要手写字段同步）。
- **管线顺序固定**（镜头矫正 → 扶正 → LOG → 影调 → LUT → 白平衡 → 曝光 →
  LR 调色块 → 局部蒙版 → 降噪 → 自动色阶 → 暗角/颗粒 → 几何 → 水印 →
  人脸模糊 → EXIF → 保存）；新增阶段要说明插在哪一步、为什么。

## 4. 提交与 Pull Request

- 提交信息用 **Conventional Commits**：`feat(scope): ...` / `fix(scope): ...`
  / `docs: ...` / `test: ...` / `refactor: ...`。
  现有历史的 scope 有 `gui` / `xmp` / `lrxmp` / `ci` / `cli` / `engine` 等。
- 一个 PR 一件事。跨模块的大改请先开 issue 讨论。
- PR 描述里请写清：**改了什么、为什么、怎么验证的**（贴测试命令与结果）。
- 面向 UI 的改动请附截图（before/after 更好）。
- 新增 CLI 命令或 MCP 工具时，同步更新 `docs/FEATURES.md` 与
  `docs/AGENT_API.md`（计数与工具表是最容易陈旧的地方）。

## 5. 新增功能时的常规落点

| 你要做的事 | 落点 |
|---|---|
| 新的图像算法 | `photo_s/<feature>.py`（纯 numpy+PIL，零重依赖优先） |
| 接入引擎管线 | `photo_s/engine.py` 的 `ProcessOptions` + `process_image` 槽位 |
| CLI 子命令 | `photo_s/cli.py`（参数用 `default=argparse.SUPPRESS`） |
| MCP 工具 | `photo_s/mcp_server.py`（模块级零 `mcp` import） |
| GUI 控件 | `photo_s/gui/app.py`；新设计常量进 `gui/theme.py` |
| 后台线程 → UI | 用 `gui/bus.py` 的 `UiBus`，**禁止手写 drain 循环** |
| 官方插件 | `plugins/<name>/`（独立 PyPI 发行版，不进核心 wheel） |

## 6. 发布

维护者流程见 [`docs/RELEASE.md`](docs/RELEASE.md)。贡献者不需要发版，
但请注意你的改动会在下一个 minor/patch 随主题发布。

## 7. 许可

提交即表示你同意以 **MIT** 许可贡献你的代码（见 [`LICENSE`](LICENSE)）。
注意：`plugins/auto-tone` 的**模型权重**是 CC-BY-NC 4.0（非商用），
代码仍是 MIT——改动权重相关逻辑时请留意许可边界，见
[`docs/COMMERCIAL.md`](docs/COMMERCIAL.md)。
