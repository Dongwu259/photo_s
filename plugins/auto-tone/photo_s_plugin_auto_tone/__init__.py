"""photo-s-plugin-auto-tone: AI 自动调色插件（photo-s 官方插件）

CLIP+MLP（v7_clean）预测 9 字段 Lightroom 调色参数，可选 RAG 增强、
Qwen3-VL 美学评分与修图建议。所有重依赖（torch/open_clip/transformers）
懒加载——本包可安全地被 photo-s 的 entry-point 发现机制导入。

用法：
    from photo_s_plugin_auto_tone import auto_tone
    result = auto_tone("/path/to/img.jpg")
"""

__version__ = "0.1.0"

__all__ = [
    "AutoTonePlugin",
    "auto_tone",
    "aesthetic_score",
    "tone_advisor",
    "INPUT_SCHEMA",
    "OUTPUT_SCHEMA",
]


def __getattr__(name):
    # 懒加载：torch 未安装时 import 本包依然可用
    if name == "AutoTonePlugin":
        from .plugin import AutoTonePlugin
        return AutoTonePlugin
    if name == "INPUT_SCHEMA":
        from .core.schema import INPUT_SCHEMA
        return INPUT_SCHEMA
    if name == "OUTPUT_SCHEMA":
        from .core.schema import OUTPUT_SCHEMA
        return OUTPUT_SCHEMA
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def auto_tone(image_path, strength=1.0, render=True, use_rag=True,
              output_path=None, **kwargs):
    """便捷入口：单图自动调色

    Returns:
        dict: options / confidence / warnings / rendered_path / metadata
    """
    from .core.pipeline import run_auto_tone
    return run_auto_tone(image_path, strength=strength, render=render,
                         use_rag=use_rag, output_path=output_path, **kwargs)


def aesthetic_score(image_path):
    """便捷入口：美学评分 1-10（需 qwen extra）"""
    from .core.aesthetic import AestheticScorer
    return AestheticScorer().score(image_path)


def tone_advisor(image_path, current_options=None):
    """便捷入口：修图建议（需 qwen extra）"""
    from .core.advisor import ToneAdvisor
    return ToneAdvisor().advise(image_path, current_options or {})
