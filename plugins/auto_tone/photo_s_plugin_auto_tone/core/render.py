"""渲染模块：把 9 字段 options 应用到图像（numpy 简化渲染）

只渲染 exposure / contrast / saturation 三个核心字段；完整渲染
（vibrance/wb/clarity/...）建议把 options 交给 photo_s 引擎管线
（engine.batch_process），字段名与 ProcessOptions 对齐。
"""

import os

import numpy as np
from PIL import Image

# 各字段的"中性值"（等于不改图）
NEUTRAL = {
    "exposure": 0.0,
    "contrast": 1.0,
    "saturation": 1.0,
    "vibrance": 0.0,
    "wb_temp": 5500.0,
    "wb_tint": 0.0,
    "clarity": 0.0,
    "texture": 0.0,
    "dehaze": 0.0,
}


def apply_strength(options: dict, strength: float) -> dict:
    """把 options 向中性值插值（strength=0 → 原图，1 → 完全采用预测）"""
    if strength >= 1.0:
        return dict(options)
    out = {}
    for f, v in options.items():
        neutral = NEUTRAL.get(f, 0.0)
        out[f] = float(neutral + strength * (v - neutral))
    return out


def render_options(
    img: Image.Image,
    options: dict,
    output_path: str,
    strength: float = 1.0,
) -> str:
    """根据 options 渲染调整后的图

    Args:
        img: 输入 PIL.Image
        options: 9 字段 dict（实际值空间）
        output_path: 输出文件路径
        strength: 调色强度 0-1

    Returns:
        output_path

    Raises:
        失败时直接抛出异常（由调用方决定如何降级），
        不再静默保存原图冒充结果。
    """
    import numpy as np

    opts = apply_strength(options, strength)

    arr = np.asarray(img.convert("RGB")).astype(np.float32)

    # 曝光（线性 EV）
    if 'exposure' in opts:
        ev = opts['exposure']
        arr = arr * (2 ** ev)

    # 对比度（围绕图像均值；contrast 在 [0.5, 1.5]，1.0 = 不变）
    if 'contrast' in opts:
        gain = opts['contrast'] - 1.0
        mean = arr.mean(axis=(0, 1), keepdims=True)
        arr = mean + (arr - mean) * (1 + gain)

    # 饱和度（saturation 在 [0, 2]，1.0 = 不变）
    if 'saturation' in opts:
        gain = opts['saturation'] - 1.0
        luma = 0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]
        luma = luma[..., None]
        arr = luma + (arr - luma) * (1 + gain)

    arr = np.clip(arr, 0, 255).astype(np.uint8)
    out = Image.fromarray(arr)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or '.', exist_ok=True)
    out.save(output_path, quality=95)

    return output_path
