"""LangChain 工具封装"""
import json
from typing import Optional


def get_langchain_tool():
    """获取 LangChain Tool 实例

    Returns:
        langchain.tools.BaseTool
    """
    try:
        from langchain.tools import BaseTool
        from pydantic import BaseModel, Field
    except ImportError:
        raise ImportError(
            "LangChain not installed. Install with: pip install langchain"
        )

    class AutoToneInput(BaseModel):
        image_path: str = Field(..., description="图像绝对路径（jpg/png/raw）")
        strength: float = Field(
            default=1.0,
            description="调色强度 0-1，0=原图 1=完全采用模型预测",
        )
        render: bool = Field(default=True, description="是否渲染输出图")

    class AutoToneTool(BaseTool):
        name = "auto_tone"
        description = (
            "调用 AI 自动调色模型。基于 CLIP+MLP 的图像理解模型，"
            "返回 9 字段调整参数（曝光/对比度/饱和度/鲜艳度/白平衡/清晰度等）"
            "以及置信度评分。适用于批量修图场景。"
        )
        args_schema = AutoToneInput

        def _run(self, image_path: str, strength: float = 1.0, render: bool = True) -> str:
            from photo_s_plugin_auto_tone.core.pipeline import run_auto_tone
            result = run_auto_tone(
                image_path, strength=strength, render=render, use_rag=True
            )
            return json.dumps(result, ensure_ascii=False)

        async def _arun(self, image_path: str, strength: float = 1.0, render: bool = True) -> str:
            return self._run(image_path, strength, render)

    return AutoToneTool()


def get_aesthetic_tool():
    """获取 LangChain 美学评分 Tool"""
    try:
        from langchain.tools import BaseTool
        from pydantic import BaseModel, Field
    except ImportError:
        raise ImportError("pip install langchain")

    class AestheticInput(BaseModel):
        image_path: str = Field(..., description="图像绝对路径")

    class AestheticTool(BaseTool):
        name = "aesthetic_score"
        description = (
            "评估图像美学质量（1-10 分）。基于 Qwen3-VL + AVA 美学数据集微调。"
            "返回分数 + bucket (low/medium-low/medium/medium-high/high) + 置信度。"
        )
        args_schema = AestheticInput

        def _run(self, image_path: str) -> str:
            from photo_s_plugin_auto_tone.core.aesthetic import AestheticScorer
            scorer = AestheticScorer()
            result = scorer.score(image_path)
            return json.dumps({
                "schema_version": 1,
                **result,
            }, ensure_ascii=False)

        async def _arun(self, image_path: str) -> str:
            return self._run(image_path)

    return AestheticTool()