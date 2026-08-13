"""
PhotoS - Cull (exposure / sharpness filtering)

Shared by the CLI `cull` command, the REST API, and the GUI: given a list of
image paths and optional thresholds, classify each as kept or rejected.
"""

from typing import Callable, List, Optional


def cull_files(
    files: List[str],
    overexposed_max: Optional[float] = None,
    underexposed_max: Optional[float] = None,
    luminance_min: Optional[float] = None,
    luminance_max: Optional[float] = None,
    sharpness_min: Optional[float] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> List[dict]:
    """Classify each image against exposure/sharpness thresholds.

    Args:
        files: Image paths.
        overexposed_max: Reject if % pixels >= 250 exceeds this.
        underexposed_max: Reject if % pixels <= 5 exceeds this.
        luminance_min/max: Reject if mean luminance (0-1) outside this range.
        sharpness_min: Reject if blur score below this (higher = sharper).
        progress_callback: Optional (current, total) callback per file.

    Returns:
        List of dicts: {"path", "ok", "luminance", "overexposed_pct",
        "underexposed_pct", ["blur_score"], "kept"}. ``blur_score`` is only
        present when ``sharpness_min`` is set. A file passes iff it is
        readable (``ok``) AND every provided threshold is satisfied.
    """
    from .metrics import compute_exposure_stats, compute_blur_score

    results: List[dict] = []
    total = len(files)
    for i, f in enumerate(files):
        s = compute_exposure_stats(f)
        row = {"path": f, **s}
        if sharpness_min is not None:
            row["blur_score"] = round(compute_blur_score(f), 1)
        keep = (s["ok"]
                and (overexposed_max is None
                     or s["overexposed_pct"] <= overexposed_max)
                and (underexposed_max is None
                     or s["underexposed_pct"] <= underexposed_max)
                and (luminance_min is None or s["luminance"] >= luminance_min)
                and (luminance_max is None or s["luminance"] <= luminance_max)
                and (sharpness_min is None or row["blur_score"] >= sharpness_min))
        row["kept"] = keep
        results.append(row)
        if progress_callback:
            progress_callback(i + 1, total)
    return results
