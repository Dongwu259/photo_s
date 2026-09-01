"""Pipeline: 串联 anomaly → predict → RAG → confidence → (advisor) → render"""
import os
import time
from typing import Any, Dict, Optional

import numpy as np
from PIL import Image

from .anomaly import AnomalyDetector
from .confidence import estimate_confidence, should_use_advisor, should_skip
from .predictor import AutoTonePredictor
from .rag import RAGEnhancer


def run_auto_tone(
    image_path: str,
    strength: float = 1.0,
    render: bool = True,
    use_rag: bool = True,
    use_advisor: bool = False,
    output_path: Optional[str] = None,
    min_confidence: Optional[float] = None,
    predictor: Optional[AutoTonePredictor] = None,
    anomaly_detector: Optional[AnomalyDetector] = None,
    rag_enhancer: Optional[RAGEnhancer] = None,
) -> Dict[str, Any]:
    """主流程：单图自动调色

    Args:
        image_path: 图像绝对路径
        strength: 调色强度 0-1
        render: 是否渲染输出
        use_rag: 是否启用 RAG
        use_advisor: 是否启用 Advisor（低置信度时）
        output_path: 自定义输出路径
        min_confidence: 渲染阈值（None = 不启用）。置信度低于该值时
            不渲染输出、状态记为 skipped（批量场景用于跳过低置信图）。
        predictor / anomaly_detector / rag_enhancer: 注入依赖（测试用）

    Returns:
        标准 OUTPUT_SCHEMA dict
    """
    t0 = time.time()

    img = Image.open(image_path).convert("RGB")
    predictor = predictor or AutoTonePredictor()
    predictor.load()
    anomaly_detector = anomaly_detector or AnomalyDetector()
    anomaly_detector.load()

    # 1. 异常检测
    anomaly_score, anomaly_info = anomaly_detector.score(img)

    def _result(options, confidence, warnings, rendered_path, extra_meta=None,
                local=None):
        out = {
            "schema_version": 1,
            "options": options,
            "confidence": confidence,
            "warnings": warnings,
            "rendered_path": rendered_path,
            "metadata": {
                "anomaly_score": round(anomaly_score, 3),
                "model_version": "v7_clean",
                "duration_ms": int((time.time() - t0) * 1000),
                **(extra_meta or {}),
            },
        }
        # 词汇表扩展（加性键）：局部调整仅在预测到非空时携带
        if local:
            out["local"] = local
        return out

    # 高异常图直接跳过（无需预测）
    if anomaly_score > 0.7:
        return _result({}, 0.0,
                       [f"image anomaly too high ({anomaly_score:.2f}), skipped"],
                       None, {"skipped": True})

    # 2. v7_clean 预测
    options = predictor.predict(img)
    pred_norm = np.array([
        (options[f] - predictor.ranges[f][0])
        / (predictor.ranges[f][1] - predictor.ranges[f][0]) * 2 - 1
        for f in predictor.targets
    ], dtype=np.float32)

    # 3. RAG 增强（可选）
    rag_used = False
    max_rag_sim = None
    if use_rag:
        rag = rag_enhancer or RAGEnhancer()
        rag.load()
        if rag.train_clip is not None:
            fused_norm, rag_info = rag.enhance(
                img, pred_norm, predictor.ranges, predictor.targets)
            if rag_info.get("rag_used"):
                pred_norm = fused_norm
                rag_used = True
                max_rag_sim = rag_info.get("max_sim")

                options = {}
                for j, f in enumerate(predictor.targets):
                    lo, hi = predictor.ranges[f]
                    options[f] = float((pred_norm[j] + 1) / 2 * (hi - lo) + lo)

    # 4. 置信度
    pred_std = float(np.std(pred_norm))
    confidence = estimate_confidence(
        pred=pred_norm,
        rag_sim=max_rag_sim,
        anomaly_score=anomaly_score,
        model_std=pred_std,
    )

    warnings = []
    if confidence < 0.4:
        warnings.append(f"low confidence ({confidence:.2f}), manual review suggested")
    if anomaly_score > 0.5:
        warnings.append(f"high anomaly ({anomaly_score:.2f})")

    # 5. 低置信度整体跳过（含渲染）
    if should_skip(confidence, anomaly_score):
        return _result(options, round(confidence, 3),
                       warnings + [f"confidence too low ({confidence:.2f}), skipped"],
                       None, {"skipped": True, "rag_used": rag_used})

    # 6. Advisor（可选）
    if use_advisor and should_use_advisor(confidence, anomaly_score):
        from .advisor import ToneAdvisor
        advisor = ToneAdvisor()
        advice = advisor.advise(img, options)
        delta = advice.get("suggested_delta", {})
        if delta:
            warnings.append(f"advisor: {advice.get('reason', '')}")
            for f, d in delta.items():
                if f in options and f not in ("wb_temp", "wb_tint"):
                    lo, hi = predictor.ranges[f]
                    options[f] = float(options[f] + d * (hi - lo) / 2)

    # 7. 局部调整预测（checkpoint 携带局部头时；全中性 → 空列表）。
    #    hasattr 守卫：注入的旧式/测试桩 predictor 无此方法时保持空局部
    local = (predictor.predict_local(img)
             if hasattr(predictor, "predict_local") else [])

    # 8. 应用 strength（向中性值插值；渲染时不再重复缩放）
    from .render import apply_strength
    options = apply_strength(options, strength)
    if local and strength < 1.0:
        local = [
            {"region": item["region"],
             "params": {k: float(strength * v)
                        for k, v in item["params"].items()}}
            for item in local
        ]
        # strength 缩放后可能全部回到中性 → 空蒙版没有意义
        local = [item for item in local if item["params"]]

    # 9. 渲染
    rendered_path = None
    if render:
        if min_confidence is not None and confidence < min_confidence:
            warnings.append(
                f"confidence {confidence:.2f} < min_confidence {min_confidence}, render skipped")
        else:
            try:
                from .render import render_options
                if output_path is None:
                    base, ext = os.path.splitext(image_path)
                    output_path = f"{base}_auto{ext or '.jpg'}"
                render_options(img, options, output_path, strength=1.0,
                               local=local)
                rendered_path = output_path
            except Exception as e:
                warnings.append(f"render failed: {e}")

    return _result(options, round(confidence, 3), warnings, rendered_path,
                   {"rag_used": rag_used}, local=local)
