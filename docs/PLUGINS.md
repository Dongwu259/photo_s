# PhotoS 插件开发指南 — Plugin Development Guide

PhotoS 通过 Python entry_points 加载第三方插件，插件可以在图片处理管线中
**前后两个钩子点**介入，无需修改 PhotoS 源码。

## 钩子总览

```
输入文件 → 加载 → [on_pre_process] → 旋转/调色/白平衡/曝光 → [denoise 槽位] → 自动色阶/裁剪/缩放 → 保存 → [on_post_process] → 清理
```

| 钩子 | 时机 | 能做什么 |
|---|---|---|
| `on_pre_process(img, options, ctx)` | 图片加载后、任何变换前 | 修改 `img`（PIL Image，就地可变）：滤镜、水印、检测 |
| `on_post_process(result, ctx)` | 保存后、临时文件清理前 | 读 `result`（输入/输出路径、尺寸、SSIM）、写旁路文件 |
| **Operation provider**（见下） | 管线内声明的槽位 | 接管某个处理步骤（如 `denoise`） |

- 过滤器插件（无 `provides`）抛出的异常会被静默吞掉（**不会中断管线**）——设计上保证插件坏不掉主流程。
- 钩子按 entry_point 注册顺序执行。

## 快速开始

### 1. 写插件类

```python
# my_package.py
from photo_s.hooks import PhotoSPlugin, PluginContext


class MyPlugin(PhotoSPlugin):
    def on_pre_process(self, img, options, ctx):
        # 例：把输出像素亮度记录到 ctx，供 post 钩子使用
        ctx.metadata["brightness_hint"] = "computed"

    def on_post_process(self, result, ctx):
        # 例：输出一个并行的 .txt 元数据文件
        with open(result.output_path + ".txt", "w") as f:
            f.write(f"{result.output_path} {result.output_size} bytes\n")
```

### 2. 注册 entry_point

```toml
# pyproject.toml（你的插件包里）
[project.entry-points."photo_s.plugins"]
my-plugin = "my_package:MyPlugin"
```

### 3. 安装插件包

```bash
pip install my-plugin-package   # 或 pip install -e .
```

### 4. 生效

```bash
photo-s compress *.jpg -o out/ --json
# 插件自动对所有输入生效；GET /info 的 plugins 字段也能看到：
photo-s serve &  curl -s localhost:8787/info
```

## 钩子签名

```python
from PIL import Image
from photo_s.hooks import PluginContext
from photo_s.engine import ProcessOptions, ProcessResult


class PhotoSPlugin:
    name: str = ""  # 自动设为 entry_point 名

    def on_pre_process(self, img: Image.Image,
                       options: ProcessOptions,
                       ctx: PluginContext) -> None:
        """变换前。img 就地可变。ctx.metadata 可跨钩子存状态。"""
        pass

    def on_post_process(self, result: ProcessResult,
                        ctx: PluginContext) -> None:
        """保存后。result 含 input_path/output_path/output_size/ssim 等。"""
        pass
```

## PluginContext

```python
@dataclass
class PluginContext:
    input_path: str = ""       # 当前输入文件路径
    output_path: str = ""      # post 钩子时已填充输出路径
    options: Any = None        # 当前 ProcessOptions
    metadata: Dict = {}        # 自由字典：pre → post 传状态
```

## Operation Providers（操作提供者）

过滤器钩子（pre/post）在管线最前/最后执行，无法在**管线中间槽位**介入
（例如降噪必须跑到曝光之后、自动色阶之前）。为此提供 **operation provider**
接口：插件声明 `provides`，引擎在对应槽位调用其同名方法。

```python
class ScunetPlugin(PhotoSPlugin):
    provides = ("denoise",)               # 声明提供哪个操作

    def denoise(self, img, strength, ctx):
        """img: PIL Image（就地可变）；strength: --denoise N 的值。返回修改后的 img。"""
        return run_scunet(img, strength)
```

| 槽位 | 声明 | 方法 | 引擎行为 |
|---|---|---|---|
| 降噪 | `provides = ("denoise",)` | `denoise(img, strength, ctx)` | `--denoise N` 有 provider 时用它，否则回退内置 NLM |

**关键规则**
- `provides` 非空的插件是 **provider**：**被排除在通用 `on_pre_process`/`on_post_process` 之外**，
  只在声明的槽位被调用。过滤器插件（`provides` 为空）行为不变。
- provider 的异常**按 per-file 错误传播**（与内置 NLM 缺 cv2 一致），不会被静默吞掉。
- 同一操作多个 provider 时**首个生效**（entry_point 顺序）。引擎侧查找：
  `find_provider("denoise")`（`photo_s.plugin`）。

### 模型权重（weight_specs）

官方插件把大模型权重（ONNX 等）**留在 wheel 之外**，首次使用时下载到缓存目录并做
sha256 校验。插件通过 `weight_specs()` 暴露权重描述：

```python
from photo_s.modelstore import WeightSpec, ensure

class ScunetPlugin(PhotoSPlugin):
    def weight_specs(self):
        return [WeightSpec(name="scunet.onnx",
                           url="https://.../releases/download/.../scunet.onnx",
                           sha256="<64-hex>", size=12345678)]

    def denoise(self, img, strength, ctx):
        path = ensure(self.weight_specs()[0])   # 下载/校验/缓存，返回路径
        return run_scunet(img, strength, path)
```

- 缓存目录：`~/.cache/photo-s/models/`（`$PHOTOS_CACHE_DIR` 或 `$XDG_CACHE_HOME` 可覆盖）。
- `photo-s plugin fetch <name>` 可预下载（不依赖首次处理）。
- `photo-s plugin info <name>` 显示每个权重的缓存状态。

## 官方可选插件（Official plugins）

PhotoS 项目维护的官方插件是**独立 PyPI 发行版** `photo-s-plugin-<name>`，版本独立；
模型权重从 GitHub Releases 下载（见上）。安装双通道：

```bash
# 通道一：PhotoS 插件管理器（agent 友好，--json）
photo-s plugin list                       # 已装 + 官方可用
photo-s plugin install scunet --json
photo-s plugin info scunet
photo-s plugin fetch scunet               # 预下载权重
photo-s plugin uninstall scunet

# 通道二：传统 pip
pip install photo-s-plugin-scunet
```

官方插件目录（`name` → 发行版/描述/最低版本要求）在核心包 `photo_s/registry.py`；
`photo-s plugin list` 据此显示"可用但未安装"的插件。

## 注意

- `options` 是每文件拷贝（并行模式互不共享），插件对它的修改只影响当前文件。
- `on_pre_process` 修改 `img` 会影响后续所有管线（旋转/裁剪/压缩都会作用于修改后的图）。
- 插件名应全局唯一（entry_point 名），重复名后注册者生效。
- 调试：钩子内 `print` 会出现在处理输出中（`--json` 模式下输出到 stderr）。

## 测试插件

```python
# 用一个空实现验证注册链路
def test_plugin_discovery(tmp_path):
    from photo_s.plugin import discover_plugins
    plugins = discover_plugins()          # 含第三方已注册的
    for p in plugins:
        p.on_pre_process(img, options, ctx)   # 不应抛异常
```

## 完整示例

见 `README.md` 的 "Plugin System" 章节与 `photo_s/hooks.py` 源码（约 60 行，
是接口的权威定义）。
