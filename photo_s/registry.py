"""
PhotoS - Official Plugin Registry

The catalog of plugins maintained by the PhotoS project. Each official plugin
is a separate PyPI distribution ``photo-s-plugin-<name>`` so it can version
independently of the core package.

Weight metadata (url / sha256 / size) deliberately does NOT live here — it
changes with each plugin release and is exposed by the installed plugin via
``PhotoSPlugin.weight_specs()``. This registry only maps official names to
their distribution + catalog fields, so ``photo-s plugin list --json`` can show
available-but-not-installed plugins.
"""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from . import __version__


@dataclass(frozen=True)
class OfficialPlugin:
    """A single official plugin catalog entry."""
    name: str
    pypi_distribution: str       # e.g. "photo-s-plugin-scunet"
    description: str
    min_photo_s_version: str     # core version requirement
    requires: Optional[Tuple[str, ...]] = None  # pip names the plugin needs


OFFICIAL_PLUGINS: Dict[str, OfficialPlugin] = {
    "scunet": OfficialPlugin(
        name="scunet",
        pypi_distribution="photo-s-plugin-scunet",
        description="SCUNet 强降噪 Strong denoising (ONNX via onnxruntime)",
        min_photo_s_version="1.0.0",
        requires=("onnxruntime>=1.16.0",),
    ),
    "lut": OfficialPlugin(
        name="lut",
        pypi_distribution="photo-s-plugin-lut",
        description="LUT 调色: 四面体插值 + 电影预设 Tetrahedral .cube "
                    "grading + film presets (pure numpy)",
        min_photo_s_version="1.3.0",
    ),
    "auto-tone": OfficialPlugin(
        name="auto-tone",
        pypi_distribution="photo-s-plugin-auto-tone",
        description="AI 自动调色: CLIP+MLP 预测 9 字段 Lightroom 参数，"
                    "RAG 增强 + 可选 Qwen3-VL 美学评分/修图建议",
        min_photo_s_version="1.7.0",
        requires=("numpy", "pillow", "torch>=2.1", "open_clip_torch>=2.20"),
    ),
}


def get_official(name: str) -> Optional[OfficialPlugin]:
    """Registry lookup by name (case-sensitive). None if unknown."""
    return OFFICIAL_PLUGINS.get(name)


def to_dict(o: OfficialPlugin) -> dict:
    """JSON-serializable catalog dict for ``plugin list`` / ``plugin info``."""
    return {
        "name": o.name,
        "pypi_distribution": o.pypi_distribution,
        "description": o.description,
        "min_photo_s_version": o.min_photo_s_version,
        "requires": list(o.requires) if o.requires else None,
    }


def version_ok(o: OfficialPlugin) -> bool:
    """True iff the running core version meets the plugin's requirement."""
    try:
        cur = tuple(int(x) for x in __version__.split("."))
        req = tuple(int(x) for x in o.min_photo_s_version.split("."))
    except ValueError:
        return True  # non-semver — don't block on a parse quirk
    return cur >= req
