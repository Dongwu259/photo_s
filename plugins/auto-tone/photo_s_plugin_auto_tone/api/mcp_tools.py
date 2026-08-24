"""MCP 工具实现

注册到 photo-s 的 MCP server（mcp.add_tool）：
    from photo_s_plugin_auto_tone.api.mcp_tools import auto_tone_tool, ...
"""
import json
import os
import time
from typing import List, Optional


def register_mcp_tools(mcp):
    """注册 MCP 工具到 photo-s 的 FastMCP 实例"""
    mcp.add_tool(auto_tone_tool, name="auto_tone",
                 description="AI 自动调色：预测 9 字段 Lightroom 参数并渲染")
    mcp.add_tool(aesthetic_score_tool, name="aesthetic_score",
                 description="美学评分 1-10（需 qwen extra）")
    mcp.add_tool(tone_advisor_tool, name="tone_advisor",
                 description="修图建议（需 qwen extra）")
    mcp.add_tool(batch_auto_tone_tool, name="batch_auto_tone",
                 description="批量自动调色")


def auto_tone_tool(
    image_path: str,
    strength: float = 1.0,
    render: bool = True,
    use_rag: bool = True,
) -> str:
    """AI 自动调色工具。

    Args:
        image_path: 图像绝对路径
        strength: 调色强度 0-1
        render: 是否渲染输出
        use_rag: 是否启用 RAG

    Returns:
        JSON 字符串（含 schema_version, options, confidence, warnings）
    """
    from photo_s_plugin_auto_tone.core.pipeline import run_auto_tone

    result = run_auto_tone(image_path, strength=strength, render=render,
                           use_rag=use_rag)
    return json.dumps(result, ensure_ascii=False)


def aesthetic_score_tool(image_path: str) -> str:
    """美学评分工具。

    Args:
        image_path: 图像绝对路径

    Returns:
        JSON 字符串（含 score 1-10, bucket, confidence）
    """
    from photo_s_plugin_auto_tone.core.aesthetic import AestheticScorer

    result = AestheticScorer().score(image_path)
    return json.dumps({"schema_version": 1, **result}, ensure_ascii=False)


def tone_advisor_tool(image_path: str, current_options: Optional[str] = None) -> str:
    """修图建议工具。

    Args:
        image_path: 图像绝对路径
        current_options: JSON 字符串格式的当前 9 字段参数（None 时用 auto_tone 预测）

    Returns:
        JSON 字符串（含 current_options, suggested_delta, reason）
    """
    from photo_s_plugin_auto_tone.core.advisor import ToneAdvisor
    from photo_s_plugin_auto_tone.core.pipeline import run_auto_tone

    if current_options:
        options = json.loads(current_options)
    else:
        result = run_auto_tone(image_path, render=False, use_rag=True)
        options = result.get("options", {})

    advice = ToneAdvisor().advise(image_path, options)
    return json.dumps({"schema_version": 1, **advice}, ensure_ascii=False)


def batch_auto_tone_tool(
    image_paths: List[str],
    strength: float = 1.0,
    skip_low_confidence: bool = True,
    output_dir: Optional[str] = None,
) -> str:
    """批量自动调色工具。

    Args:
        image_paths: 图像路径列表
        strength: 调色强度
        skip_low_confidence: 跳过低置信度图（不渲染输出）
        output_dir: 输出目录（None 写到原图同目录）

    Returns:
        JSON 字符串（含 total, processed, skipped, failed, results）
    """
    from photo_s_plugin_auto_tone.core.pipeline import run_auto_tone

    results = []
    t0 = time.time()
    for path in image_paths:
        try:
            out_path = None
            if output_dir:
                stem, ext = os.path.splitext(os.path.basename(path))
                out_path = os.path.join(
                    output_dir, f"{stem}_auto{ext or '.jpg'}")

            # min_confidence：低置信图直接不渲染（避免先写文件再标记 skipped）
            r = run_auto_tone(
                path, strength=strength, render=True,
                use_rag=True, output_path=out_path,
                min_confidence=0.3 if skip_low_confidence else None,
            )

            skipped = bool(r["metadata"].get("skipped"))
            status = "skipped" if skipped else "ok"
            if not skipped and any("render failed" in w for w in r["warnings"]):
                status = "failed"

            results.append({
                "image_path": path,
                "status": status,
                "confidence": r["confidence"],
                "rendered_path": r.get("rendered_path"),
                "warnings": r["warnings"],
            })
        except Exception as e:
            results.append({
                "image_path": path,
                "status": "failed",
                "reason": str(e),
            })

    elapsed = time.time() - t0
    summary = {
        "schema_version": 1,
        "total": len(image_paths),
        "processed": sum(1 for r in results if r["status"] == "ok"),
        "skipped": sum(1 for r in results if r["status"] == "skipped"),
        "failed": sum(1 for r in results if r["status"] == "failed"),
        "elapsed_sec": round(elapsed, 2),
        "results": results,
        "metadata": {
            "throughput_imgs_per_sec": round(len(image_paths) / max(elapsed, 0.1), 2),
        },
    }
    return json.dumps(summary, ensure_ascii=False)
