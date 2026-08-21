"""photo_s/audit.py — 出片质量闸门（agent 终止条件，v1.9.0 阶段 1）

组合现有感知指标给出明确的 pass/fail + 原因——**agent 全自动修图的 stop
条件**：没有终止判据，"全自动"要么无限调要么错误时机停。

阈值均为保守出片标准（可 CLI 覆盖），纯 stdlib 复用 metrics。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

__all__ = ["audit_image", "DEFAULT_THRESHOLDS"]

DEFAULT_THRESHOLDS: Dict[str, float] = {
    "overexposed_max": 2.0,    # 过曝像素占比 %（高光死白上限）
    "underexposed_max": 2.0,   # 欠曝像素占比 %
    "blur_min": 0.05,          # Laplacian 方差模糊分下限
    "luminance_min": 0.05,     # 平均亮度下限（0-1）
    "luminance_max": 0.95,     # 平均亮度上限
    "contrast_min": 0.05,      # 对比度下限
    "kelvin_min": 2500.0,      # 色温估计范围
    "kelvin_max": 10000.0,
}


def audit_image(path: str, *, sample_size: int = 256,
                **thresholds: float) -> Dict[str, Any]:
    """单图出片审计 → ``{ok, passed, checks, reason}``。

    ``checks``：每项 ``{name, ok, value, threshold, direction}``；
    ``reason``：失败项摘要（agent 可直接读）；不可读图返回 ``ok=False``。
    阈值经 ``DEFAULT_THRESHOLDS`` 合并，可逐项覆盖。
    """
    from .metrics import analyze_image
    a = analyze_image(path, sample_size=sample_size)
    if not a.get("ok"):
        return {"ok": False, "path": path, "error": a.get("error",
                                                          "unreadable image"),
                "passed": False, "checks": [], "reason": "unreadable image"}
    th = {**DEFAULT_THRESHOLDS, **{k: float(v) for k, v in thresholds.items()
                                   if v is not None}}
    ex = a["exposure"]
    st = a["stats"]
    wb = a["white_balance"]
    checks: List[Dict[str, Any]] = []

    def check(name, ok, value, threshold, direction):
        try:
            thr = round(float(threshold), 3)
        except (TypeError, ValueError):
            thr = str(threshold)  # range 阈值（如 "0.05-0.95"）
        checks.append({"name": name, "ok": bool(ok),
                       "value": round(float(value), 3),
                       "threshold": thr, "direction": direction})

    check("overexposed", ex["overexposed_pct"] <= th["overexposed_max"],
          ex["overexposed_pct"], th["overexposed_max"], "<=")
    check("underexposed", ex["underexposed_pct"] <= th["underexposed_max"],
          ex["underexposed_pct"], th["underexposed_max"], "<=")
    check("blur", a["blur_score"] >= th["blur_min"], a["blur_score"],
          th["blur_min"], ">=")
    lum = ex["luminance"]
    check("luminance",
          th["luminance_min"] <= lum <= th["luminance_max"], lum,
          f"{th['luminance_min']}-{th['luminance_max']}", "range")
    check("contrast", st["contrast"] >= th["contrast_min"], st["contrast"],
          th["contrast_min"], ">=")
    kelvin = wb["kelvin_estimate"]
    check("white_balance", th["kelvin_min"] <= kelvin <= th["kelvin_max"],
          kelvin, f"{th['kelvin_min']:.0f}-{th['kelvin_max']:.0f}", "range")

    failed = [c for c in checks if not c["ok"]]
    reason = "ok" if not failed else "; ".join(
        f"{c['name']}={c['value']}{c['direction']}{c['threshold']}"
        for c in failed)
    return {"ok": True, "path": path, "passed": not failed,
            "checks": checks, "reason": reason}
