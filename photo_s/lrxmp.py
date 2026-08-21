"""photo_s/lrxmp.py — Lightroom 数据桥接（个人修图数据管线，v1.9.0 阶段 1）

CLI 入口：``photo-s lr-scan [paths...] [--export-dir DIR] [--json]``——自动发现
catalog/XMP、聚合覆盖报告、可选导出训练数据 JSONL（每张已编辑照片的
``options`` = PhotoS 参数即训练标签）。

纯 stdlib 零依赖。四层：

1. :func:`parse_xmp_sidecar` — XMP sidecar 解析（LR 目录勾选「自动写入 XMP」
   后每张 RAW 一个 .xmp，字段名即 ``crs:`` 属性名）
2. :func:`parse_develop_blob` — LR catalog 快照解析（``Adobe_imageDevelopSettings.text``
   列，明文 ``s = { key = value }`` 格式，LR 18 实测）
3. :func:`crs_to_options` — crs 字段 → ``ProcessOptions`` kwargs（紧凑字符串，
   含 HSL/曲线/分级/几何蒙版/局部调整/点颜色）
4. :func:`scan_catalog` — SQLite 全目录扫描（settings + 历史步骤 + 文件路径关联，
   关联链已验证：settings.image → Adobe_images → AgLibraryFile → folder → root）

映射覆盖率速查（LR 字段 → PhotoS 字段）：

**直接映射**::

    Temperature          → wb_temp（Kelvin；仅当 white_balance 非 "As Shot"）
    Tint                 → wb_tint（G/M 轴，+ = 品红，LR 同号）
    Exposure2012         → exposure（EV）
    Contrast2012         → contrast = 1 + v/100（倍率）
    Saturation           → saturation = 1 + v/100（倍率）
    Vibrance/Texture/Clarity2012/Dehaze → 同名 /100（[-1, 1]）
    Hue/Saturation/LuminanceAdjustment*8 → hsl 紧凑串（hue*1.8 度，sat/lum /100）
    ToneCurvePV2012[/R/G/B] → curves 紧凑串（点对直传）
    ColorGrade*（3 路 + 每区 L）→ color_grading（hue>180 折到 -180..180，sat/lum /100）
    VignetteAmount/Midpoint → vignette（/100）
    CropLeft/Top/Right/Bottom → crop（相对 0-1 → 像素，需 image_size）
    Mask/CircularGradient、Mask/LinearGradient → masks radial/linear + mask_adjust
      （相对坐标 0-1 直传、Feather/100、MaskInverted → invert；LR 渐变角度按
      顺时针惯例近似；Local* → 11 项标量键）

**近似映射**（语义/数值有损）::

    Highlights2012/Shadows2012/Whites2012/Blacks2012 → curves 折线近似
    Sharpness/SharpenRadius → sharpen（倍率近似）
    LuminanceSmoothing/ColorNoiseReduction → denoise 强度（语义近似）
    GrainAmount/Size/Frequency → grain（近似）
    LensManualDistortionAmount → lens_distort（近似）
    LocalTemperature → temp = 5250 + v（LR 局部色温是偏移量，近似绝对温度）

**待标定**（结构已解析，数值映射需受控实验）::

    LocalPointColors（19 浮点元组：首 3 项 = 取样色 0-1；偏移/范围字段未知）

**v1.8 承接**（语法已预留，解析即归类报告）::

    Mask/Paint（笔刷）、Mask/Aggregate（AI 主题/人物/对象等）

**未覆盖**::

    PerspectiveUpright/Transform*（透视）、RetouchAreas（修复笔）、
    LensProfile*（镜头配置）、ColorGradeGlobal*（全局分级，PhotoS 无对应）
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import xml.etree.ElementTree as ET
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

__all__ = [
    "LrError", "parse_xmp_sidecar", "parse_develop_blob", "scan_catalog",
    "crs_to_options", "coverage", "scan_and_report", "discover_inputs",
    "write_export", "HSL_COLORS", "LOCAL_MAP",
]

_XMP_CRS = "{http://ns.adobe.com/camera-raw-settings/1.0/}"
_XMP_CRD = "{http://ns.adobe.com/camera-raw-defaults/1.0/}"

# Lightroom 8 色域顺序 = PhotoS hsl 顺序
HSL_COLORS: Tuple[str, ...] = (
    "red", "orange", "yellow", "green", "aqua", "blue", "purple", "magenta",
)

# LR 局部调整键（Local*）→ PhotoS mask_adjust 标量键
LOCAL_MAP: Dict[str, str] = {
    "LocalExposure2012": "exposure",    # EV 直传
    "LocalBrightness": "brightness",    # 1 + v/100
    "LocalContrast2012": "contrast",    # 1 + v/100
    "LocalSaturation": "saturation",    # 1 + v/100
    "LocalVibrance": "vibrance",        # v/100
    "LocalClarity": "clarity",          # v/100
    "LocalTexture": "texture",          # v/100
    "LocalSharpness": "sharpen",        # 1 + v/100
    "LocalTemperature": "temp",         # 5250 + v（偏移近似绝对温度）
    "LocalTint": "tint",                # 直传
}


class LrError(ValueError):
    """LR 数据解析/映射错误。"""


# ---------------------------------------------------------------- XMP sidecar

def parse_xmp_sidecar(source: Any) -> Dict[str, str]:
    """解析 XMP sidecar（文件路径或 XML 字符串）→ ``{crs字段: 值}``。

    值均为字符串（XMP 属性原始文本）；``crd:`` 默认段字段以 ``crd_`` 前缀并入。
    """
    if isinstance(source, (str, os.PathLike)) and os.path.exists(source):
        with open(source, "r", encoding="utf-8") as f:
            text = f.read()
    else:
        text = str(source)
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise LrError(f"XMP 解析失败: {e}") from e
    out: Dict[str, str] = {}
    for elem in root.iter():
        for key, value in elem.attrib.items():
            if key.startswith(_XMP_CRS):
                out[key[len(_XMP_CRS):]] = value
            elif key.startswith(_XMP_CRD):
                out["crd_" + key[len(_XMP_CRD):]] = value
    return out


# -------------------------------------------------------- catalog 快照（明文）

_TOKEN_RE = re.compile(r"""
    \s*(?:(\{|\}|,|=)                        # 标点
        |"((?:[^"\\]|\\.)*)"                 # 引号字符串
        |([A-Za-z_][A-Za-z0-9_.]*)           # 标识符/键名
        |([+-]?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)  # 数字
    )""", re.VERBOSE)


def _tokenize(text: str) -> List[Any]:
    toks: List[Any] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m:
            pos += 1
            continue
        pos = m.end()
        punc, qstr, ident, num = m.groups()
        if punc is not None:
            toks.append(punc)
        elif qstr is not None:
            toks.append(qstr)
        elif ident is not None:
            toks.append(ident)
        else:
            toks.append(float(num) if ("." in num or "e" in num.lower())
                        else int(num))
    return toks


def _parse_value(toks: List[Any], i: int) -> Tuple[Any, int]:
    t = toks[i]
    if t == "{":
        return _parse_block(toks, i)
    if t == "true":
        return True, i + 1
    if t == "false":
        return False, i + 1
    if isinstance(t, (int, float)):
        return t, i + 1
    return str(t), i + 1


def _parse_block(toks: List[Any], i: int) -> Tuple[Any, int]:
    """``{ ... }`` → (dict|list, 结束下标)。块内出现 ``key =`` 即 dict，否则 list。"""
    out: Any = None
    i += 1
    while i < len(toks):
        t = toks[i]
        if t == "}":
            return (out if out is not None else {}), i + 1
        if t == ",":
            i += 1
            continue
        if (isinstance(t, str) and i + 1 < len(toks) and toks[i + 1] == "="):
            if out is None:
                out = {}
            key = t
            i += 2
            val, i = _parse_value(toks, i)
            out[key] = val
        else:
            if out is None:
                out = []
            val, i = _parse_value(toks, i)
            out.append(val)
    return (out if out is not None else {}), i


def parse_develop_blob(text: str) -> Dict[str, Any]:
    """解析 LR catalog 的 ``s = { key = value, ... }`` 明文快照 → dict。

    值类型：数字（int/float）/ 字符串 / bool / 嵌套 dict / 数组；
    容错：未知字符跳过，遇块结束即返回（LR 18 实测格式）。
    """
    toks = _tokenize(text)
    try:
        start = toks.index("{")
    except ValueError:
        raise LrError("快照中找不到 '{'（非 s = { ... } 格式）") from None
    val, _ = _parse_block(toks, start)
    if not isinstance(val, dict):
        raise LrError("快照顶层应为 dict")
    return val


# ---------------------------------------------------------------- 映射

def _f(settings: Dict[str, Any], key: str) -> float:
    v = settings.get(key)
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _hsl_string(settings: Dict[str, Any]) -> str:
    """LR HSL 24 项 → PhotoS hsl 紧凑串（只含非零色域）。"""
    segs = []
    for color in HSL_COLORS:
        cap = color.capitalize()
        h = _f(settings, f"HueAdjustment{cap}")
        s = _f(settings, f"SaturationAdjustment{cap}")
        l = _f(settings, f"LuminanceAdjustment{cap}")
        if h or s or l:
            segs.append(f"{color}:{h * 1.8:.3f},{s / 100.0:.3f},{l / 100.0:.3f}")
    return ";".join(segs)


_CURVE_CHANNELS = (
    ("ToneCurvePV2012", "rgb"),
    ("ToneCurvePV2012Red", "r"),
    ("ToneCurvePV2012Green", "g"),
    ("ToneCurvePV2012Blue", "b"),
)


def _curves_string(settings: Dict[str, Any]) -> str:
    """ToneCurvePV2012 平铺点对 → PhotoS curves 紧凑串（'' = 无曲线编辑）。"""
    segs = []
    for key, ch in _CURVE_CHANNELS:
        pts = settings.get(key)
        if not isinstance(pts, list) or len(pts) < 4:
            continue
        pairs = [f"{pts[i]:g},{pts[i + 1]:g}" for i in range(0, len(pts) - 1, 2)]
        if len(pairs) == 2 and pairs[0] == "0,0" and pairs[1] == "255,255":
            continue  # 恒等曲线
        segs.append(f"{ch}:{';'.join(pairs)}")
    return "|".join(segs)


def _color_grading_string(settings: Dict[str, Any]) -> str:
    """ColorGrade 3 路 + 每区 L → PhotoS color_grading 紧凑串。"""
    zones = {
        "ColorGradeShadow": "shadows",
        "ColorGradeMidtone": "midtones",
        "ColorGradeHighlight": "highlights",
    }
    segs = []
    for key, zone in zones.items():
        hue = _f(settings, key + "Hue")
        sat = _f(settings, key + "Sat")
        lum = _f(settings, key + "Lum")
        if not (hue or sat or lum):
            continue
        h = hue - 360.0 if hue > 180.0 else hue
        segs.append(f"{zone}:{h:.1f},{sat / 100.0:.3f},{lum / 100.0:.3f}")
    return ";".join(segs)


def _point_color_tuples(settings: Dict[str, Any]) -> List[Dict[str, Any]]:
    """LocalPointColors 元组解析 → [{rgb: (r,g,b) 0-255, raw: 19 浮点}]。

    首 3 项为取样色（0-1 归一化）；其余字段（偏移/范围/曲线）待受控实验标定。
    """
    out = []
    for corr in _iter_corrections(settings):
        for raw in corr.get("LocalPointColors") or []:
            if not isinstance(raw, str):
                continue
            try:
                nums = [float(x) for x in raw.split(",")]
            except ValueError:
                continue
            if len(nums) >= 3:
                rgb = tuple(max(0, min(255, int(round(v * 255.0))))
                            for v in nums[:3])
                out.append({"rgb": rgb, "raw": nums})
    return out


def _iter_corrections(settings: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    """MaskGroupBasedCorrections（LR 17+；回退 legacy CorrectionMasks）。"""
    src = settings.get("MaskGroupBasedCorrections")
    if not isinstance(src, list):
        src = settings.get("CorrectionMasks")
    for corr in src or []:
        if isinstance(corr, dict):
            yield corr


def _safe_mask_name(name: str) -> str:
    """PhotoS 蒙版名不允许 ``:;,= `` 字符——LR 的「蒙版 1」等名替换为下划线。"""
    return re.sub(r"[:;,= ]", "_", name).strip() or "mask"


def _box(cm: Dict[str, Any]) -> Tuple[float, float, float, float]:
    l = _f(cm, "Left")
    t = _f(cm, "Top")
    r = _f(cm, "Right")
    b = _f(cm, "Bottom")
    if r <= l:
        r = l + 1e-6
    if b <= t:
        b = t + 1e-6
    return l, t, r, b


def _radial_mask(cm: Dict[str, Any], name: str) -> str:
    l, t, r, b = _box(cm)
    cx, cy = (l + r) / 2.0, (t + b) / 2.0
    rx, ry = (r - l) / 2.0, (b - t) / 2.0
    feather = min(1.0, _f(cm, "Feather") / 100.0)
    seg = (f"{name}:radial:{cx:.4f},{cy:.4f},{rx:.4f},{ry:.4f},"
           f"feather={feather:.3f}")
    if cm.get("MaskInverted"):
        seg += ",invert"
    return seg


def _linear_mask(cm: Dict[str, Any], name: str) -> str:
    l, t, r, b = _box(cm)
    cx, cy = (l + r) / 2.0, (t + b) / 2.0
    half = 0.5 * math.hypot(r - l, b - t)
    ang = math.radians(_f(cm, "Angle"))
    # LR Angle：0° = 自上而下，正角顺时针（屏幕坐标 y 向下）
    dx, dy = math.sin(ang) * half, math.cos(ang) * half
    feather = min(1.0, _f(cm, "Feather") / 100.0)
    seg = (f"{name}:linear:{cx - dx:.4f},{cy - dy:.4f},"
           f"{cx + dx:.4f},{cy + dy:.4f},feather={feather:.3f}")
    if cm.get("MaskInverted"):
        seg += ",invert"
    return seg


def _local_adjust(corr: Dict[str, Any], name: str) -> str:
    parts = []
    for lr_key, ps_key in LOCAL_MAP.items():
        v = _f(corr, lr_key)
        if v == 0.0:
            continue
        if ps_key in ("brightness", "contrast", "saturation", "sharpen"):
            parts.append(f"{ps_key}={(1.0 + v / 100.0):.4f}")
        elif ps_key in ("vibrance", "clarity", "texture"):
            parts.append(f"{ps_key}={(v / 100.0):.4f}")
        elif ps_key == "temp":
            parts.append(f"temp={5250.0 + v:.1f}")
        else:
            parts.append(f"{ps_key}={v:.4f}")
    return f"{name}:{','.join(parts)}" if parts else ""


def _masks_and_adjust(settings: Dict[str, Any]
                      ) -> Tuple[str, str, List[str]]:
    """(masks_str, mask_adjust_str, v1_8_names)——几何蒙版进 PhotoS，
    笔刷/AI 蒙版（Mask/Paint、Mask/Aggregate）归入 v1.8 待承接。"""
    masks_segs: List[str] = []
    adjust_segs: List[str] = []
    v18: List[str] = []
    for corr in _iter_corrections(settings):
        name = _safe_mask_name(str(corr.get("CorrectionName") or "mask"))
        geom: Optional[str] = None
        for cm in corr.get("CorrectionMasks") or []:
            if not isinstance(cm, dict):
                continue
            what = cm.get("What", "")
            if what == "Mask/CircularGradient":
                geom = _radial_mask(cm, name)
                break
            if what == "Mask/LinearGradient":
                geom = _linear_mask(cm, name)
                break
        if geom is not None:
            masks_segs.append(geom)
            adj = _local_adjust(corr, name)
            if adj:
                adjust_segs.append(adj)
        else:
            v18.append(name)
    return ";".join(masks_segs), ";".join(adjust_segs), v18


def _crop_relative(settings: Dict[str, Any]
                   ) -> Optional[Tuple[float, float, float, float]]:
    """LR 相对裁剪（0-1）→ (left, top, right, bottom)；未裁剪返回 None。"""
    try:
        l = _f(settings, "CropLeft")
        t = _f(settings, "CropTop")
        r = _f(settings, "CropRight") if "CropRight" in settings else 1.0
        b = _f(settings, "CropBottom") if "CropBottom" in settings else 1.0
    except (TypeError, ValueError):
        return None
    if l <= 0.0001 and t <= 0.0001 and r >= 0.9999 and b >= 0.9999:
        return None
    return (l, t, r, b)


def _crop_to_pixels(rel: Tuple[float, float, float, float],
                    w: int, h: int) -> str:
    l, t, r, b = rel
    x = int(round(l * w))
    y = int(round(t * h))
    cw = max(1, int(round((r - l) * w)))
    ch = max(1, int(round((b - t) * h)))
    return f"{cw}x{ch}+{x}+{y}"


def crs_to_options(settings: Dict[str, Any], *,
                   image_size: Optional[Tuple[int, int]] = None,
                   white_balance: Optional[str] = None) -> Dict[str, Any]:
    """crs 字段 → ``ProcessOptions`` kwargs（PhotoS 可直接消费的值）。

    ``image_size=(w, h)`` 时裁剪换算为像素；``white_balance`` 非 "As Shot" 时
    才映射 Temperature/Tint（避免把机内白平衡误当编辑）。数值换算见模块 docstring。
    """
    opts: Dict[str, Any] = {}
    try:
        if white_balance != "As Shot":
            if "Temperature" in settings:
                opts["wb_temp"] = int(round(_f(settings, "Temperature")))
            if "Tint" in settings:
                opts["wb_tint"] = _f(settings, "Tint")
        if "Exposure2012" in settings:
            opts["exposure"] = _f(settings, "Exposure2012")
        if "Contrast2012" in settings:
            opts["contrast"] = 1.0 + _f(settings, "Contrast2012") / 100.0
        if "Saturation" in settings:
            opts["saturation"] = 1.0 + _f(settings, "Saturation") / 100.0
        for key, ps_key in (("Vibrance", "vibrance"), ("Texture", "texture"),
                            ("Clarity2012", "clarity"), ("Dehaze", "dehaze")):
            if key in settings:
                opts[ps_key] = _f(settings, key) / 100.0
        hsl = _hsl_string(settings)
        if hsl:
            opts["hsl"] = hsl
        curves = _curves_string(settings)
        if curves:
            opts["curves"] = curves
        cg = _color_grading_string(settings)
        if cg:
            opts["color_grading"] = cg
        if "VignetteAmount" in settings and _f(settings, "VignetteAmount") != 0.0:
            mid = _f(settings, "VignetteMidpoint") / 100.0
            opts["vignette"] = f"{_f(settings, 'VignetteAmount') / 100.0:.3f},{mid:.3f}"
        if image_size:
            rel = _crop_relative(settings)
            if rel:
                opts["crop"] = _crop_to_pixels(rel, image_size[0], image_size[1])
        masks, adjust, _v18 = _masks_and_adjust(settings)
        if masks:
            opts["masks"] = masks
        if adjust:
            opts["mask_adjust"] = adjust
    except (TypeError, ValueError) as e:
        raise LrError(f"crs 字段映射失败: {e}") from e
    return opts


# ---------------------------------------------------------------- 覆盖率

# 结构字段（ID/版本/名称/常写默认），不计入"编辑"
_STRUCTURAL_KEYS = frozenset((
    "Version", "CompatibleVersion", "ProcessVersion", "HasSettings",
    "HasCrop", "HasToneCurve", "ToneCurveName2012", "CameraProfile",
    "CameraProfileDigest", "UUID", "CorrectionID", "CorrectionSyncID",
    "MaskID", "MaskSyncID", "MaskName", "CorrectionName", "CorrectionActive",
    "CorrectionAmount", "MaskActive", "MaskBlendMode", "MaskValue", "MaskInverted",
    "CenterWeight", "Feather", "Flipped", "Roundness", "Angle", "Midpoint",
    "SupportsAmount", "SupportsMonochrome", "SupportsOutputReferred",
    "Left", "Top", "Right", "Bottom", "What", "Masks", "MaskGroupBasedCorrections",
    "CorrectionMasks", "LocalPointColors", "PointColors", "CurveRefineSaturation",
    "Brightness", "Contrast",  # LR 2012 时代常写默认
    # 支持性字段（非编辑）
    "WhiteBalance", "CropConstrainAspectRatio", "CropConstrainToUnitSquare",
    "LensProfileEnable", "LensProfileName", "LensProfileDigest", "LensProfileSetup",
    "LensProfileFilename", "LensProfileDistortionScale", "LensProfileVignettingScale",
    "AutoLateralCA", "Look", "RedEyeInfo", "EnableDistractionRemoval", "FilterList",
    "HDRMaxValue", "LensBlur", "PerspectiveScale", "Shadows",
    "UprightCenterNormX", "UprightCenterNormY", "UprightFocalLength35mm",
    "UprightVersion", "UprightTransformCount",
    "DefringePurpleHueLo", "DefringePurpleHueHi", "DefringeGreenHueLo",
    "DefringeGreenHueHi",
    # XMP 侧格式支持字段（蒙版几何/相机配置/元数据）
    "AlreadyApplied", "RawFileName", "Copyright", "Name", "Amount",
    "ConvertToGrayscale", "LookTable", "OverrideLookVignette",
    "LensProfileIsEmbedded", "MaskVersion", "ModelVersion", "ReferencePoint",
    "InputDigest", "InputDigestVersion", "LocalInputDigest",
    "LocalInputDigestVersion", "MaskDigest", "WholeImageArea", "Origin",
    "FullMaskSize", "MaskSubType", "MaskSubCategoryID",
    "ZeroX", "ZeroY", "FullX", "FullY", "Radius", "Flow",
    "LocalCurveRefineSaturation",
))
# 常写默认值（不等于"编辑"）
_DEFAULT_VALUES: Dict[str, float] = {
    "Temperature": 5250.0, "Tint": 0.0, "Sharpness": 40.0,
    "ColorNoiseReduction": 25.0, "SharpenDetail": 25.0, "SharpenEdgeMasking": 0.0,
    "ParametricShadowSplit": 25.0, "ParametricMidtoneSplit": 50.0,
    "ParametricHighlightSplit": 75.0, "ColorGradeBlending": 50.0,
    "VignetteMidpoint": 50.0, "LuminanceSmoothing": 0.0,
    "SharpenRadius": 1.0, "GrainSize": 25.0,
    "ColorNoiseReductionDetail": 50.0, "ColorNoiseReductionSmoothness": 50.0,
}

# 直接映射（→ ProcessOptions 字段）
_MAPPED_KEYS = frozenset((
    "Temperature", "Tint", "Exposure2012", "Contrast2012", "Saturation",
    "Vibrance", "Texture", "Clarity2012", "Dehaze", "VignetteAmount",
    "CropLeft", "CropTop", "CropRight", "CropBottom",
    "ToneCurvePV2012", "ToneCurvePV2012Red", "ToneCurvePV2012Green",
    "ToneCurvePV2012Blue",
    "ColorGradeShadowHue", "ColorGradeShadowSat", "ColorGradeShadowLum",
    "ColorGradeMidtoneHue", "ColorGradeMidtoneSat", "ColorGradeMidtoneLum",
    "ColorGradeHighlightHue", "ColorGradeHighlightSat", "ColorGradeHighlightLum",
))
# 近似映射（有损）
_APPROX_KEYS = frozenset((
    "Highlights2012", "Shadows2012", "Whites2012", "Blacks2012",
    "Sharpness", "SharpenRadius", "GrainAmount", "GrainSize", "GrainFrequency",
    "LensManualDistortionAmount", "PostCropVignetteAmount",
))
# 半映射/待标定
_PARTIAL_KEYS = frozenset((
    "LocalPointColors", "LensProfileEnable", "LensProfileName",
    "AutoLateralCA",
    # XMP 顶层局部调整（真实编辑；与蒙版几何的配对结构待标定）
    "LocalExposure2012", "LocalBrightness", "LocalContrast2012",
    "LocalSaturation", "LocalVibrance", "LocalClarity", "LocalTexture",
    "LocalSharpness", "LocalTemperature", "LocalTint", "LocalShadows2012",
    "LocalBlacks2012", "LocalHighlights2012", "LocalWhites2012",
))
# 无对应（缺口）
_UNMAPPED_KEYS = frozenset((
    "PerspectiveUpright", "UprightTransformCount", "UprightTransform_1",
    "UprightTransform_2", "UprightTransform_3", "UprightTransform_4",
    "RetouchAreas", "RetouchInfo", "RetouchAreas1", "RetouchAreas2",
    "ColorGradeGlobalHue", "ColorGradeGlobalSat", "ColorGradeGlobalLum",
    "DefringePurpleAmount", "DefringeGreenAmount",
))
# v1.8 承接（AI 蒙版/笔刷）
_V18_MASKS = ("Mask/Paint", "Mask/Aggregate", "Mask/Subject", "Mask/Person",
              "Mask/Depth", "Mask/Background", "Mask/Object", "Mask/Brush")


def coverage(settings: Dict[str, Any], *,
             white_balance: Optional[str] = None) -> Dict[str, Any]:
    """非默认参数分类 → {mapped, approximate, partial, unmapped, v1_8, edited,
    mappable_ratio}。供训练数据可行性报告使用。"""
    out = {k: [] for k in
           ("mapped", "approximate", "partial", "unmapped", "v1_8")}
    if not isinstance(settings, dict):
        return {**out, "edited": False, "mappable_ratio": 0.0}

    # 蒙版归类：几何 → mapped；笔刷/AI → v1_8；局部调整也算编辑
    for corr in _iter_corrections(settings):
        kinds = [cm.get("What", "") for cm in corr.get("CorrectionMasks") or []
                 if isinstance(cm, dict)]
        name = _safe_mask_name(str(corr.get("CorrectionName") or "mask"))
        has_geom = any(k in ("Mask/CircularGradient", "Mask/LinearGradient")
                       for k in kinds)
        if has_geom:
            out["mapped"].append(f"mask:{name}")
            if any(_f(corr, lr_key) != 0.0 for lr_key in LOCAL_MAP):
                out["mapped"].append(f"local:{name}")
        elif any(k in _V18_MASKS for k in kinds):
            out["v1_8"].append(f"{name} ({';'.join(kinds) or 'composite'})")

    for key, value in settings.items():
        if key in _STRUCTURAL_KEYS or key.startswith("crd_"):
            continue
        if key in _DEFAULT_VALUES and _f(settings, key) == _DEFAULT_VALUES[key]:
            continue
        # 恒等曲线/零值 HSL 不算编辑
        if key.startswith("ToneCurvePV2012") and isinstance(value, list) and \
                len(value) == 4 and value[0] == 0 and value[1] == 0 and \
                value[2] == 255 and value[3] == 255:
            continue
        if isinstance(value, (int, float)):
            if float(value) == 0.0:
                continue
        elif isinstance(value, str):
            try:
                if float(value) == 0.0:
                    continue
            except ValueError:
                pass  # 非数字字符串（如 "As Shot"）
        if key.startswith(("HueAdjustment", "SaturationAdjustment",
                           "LuminanceAdjustment")):
            out["mapped"].append(key)
        elif key in _MAPPED_KEYS:
            if key in ("Temperature", "Tint") and white_balance == "As Shot":
                continue  # 机内白平衡，非编辑
            out["mapped"].append(key)
        elif key in _APPROX_KEYS:
            out["approximate"].append(key)
        elif key in _PARTIAL_KEYS:
            out["partial"].append(key)
        elif key in _UNMAPPED_KEYS:
            out["unmapped"].append(key)
        # 其余未分类但非默认：归 unmapped（保守）
        else:
            out["unmapped"].append(key)

    edited = bool(out["mapped"] or out["approximate"] or out["partial"]
                  or out["unmapped"] or out["v1_8"])
    total = sum(len(out[k]) for k in ("mapped", "approximate"))
    mappable_ratio = (total / (total + len(out["partial"])
                               + len(out["unmapped"]))) if total else 0.0
    out["edited"] = edited
    out["mappable_ratio"] = round(mappable_ratio, 3)
    return out


# ---------------------------------------------------------------- catalog 扫描

_SCAN_SQL = """
    SELECT s.id_local, s.image, s.text, s.hasMasks, s.hasAIMasks,
           s.hasPointColor, s.whiteBalance, im.fileWidth, im.fileHeight,
           f.baseName, f.extension, fo.pathFromRoot, rf.absolutePath
    FROM Adobe_imageDevelopSettings s
    JOIN Adobe_images im ON s.image = im.id_local
    LEFT JOIN AgLibraryFile f ON im.rootFile = f.id_local
    LEFT JOIN AgLibraryFolder fo ON f.folder = fo.id_local
    LEFT JOIN AgLibraryRootFolder rf ON fo.rootFolder = rf.id_local
"""

_HISTORY_SQL = """
    SELECT image, name, valueString, relValueString
    FROM Adobe_libraryImageDevelopHistoryStep
"""


def scan_catalog(db_path: str, *, with_history: bool = True,
                 parse: bool = True) -> List[Dict[str, Any]]:
    """扫描一个 LR catalog（只读）→ 逐图记录。

    记录：``{path, image_id, image_size, white_balance, has_masks,
    has_ai_masks, has_point_color, settings, history}``——``settings`` 为解析后
    的 crs dict（``parse=False`` 时为原始文本）；``history`` 为 ``{name, value}``
    工具使用轨迹（仅 ``with_history=True``）。关联链已验证（LR 18）：
    settings.image → Adobe_images → AgLibraryFile → folder → root。
    """
    uri = f"file:{os.path.abspath(db_path)}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as e:
        raise LrError(f"无法打开 catalog {db_path}: {e}") from e
    try:
        rows = conn.execute(_SCAN_SQL).fetchall()
        history: Dict[int, List[Dict[str, Any]]] = {}
        if with_history:
            for image, name, value, rel in conn.execute(_HISTORY_SQL):
                history.setdefault(image, []).append(
                    {"name": name, "value": value or rel or ""})
    finally:
        conn.close()

    records: List[Dict[str, Any]] = []
    for row in rows:
        (sid, image, text, has_masks, has_ai, has_pc, white_balance,
         fw, fh, base, ext, path_from_root, root_path) = row
        path = ""
        if base and root_path:
            path = os.path.join(root_path, path_from_root or "",
                                f"{base}.{ext or ''}")
        rec: Dict[str, Any] = {
            "path": path,
            "image_id": image,  # Adobe_images.id_local —— 与历史步骤 image 同空间
            "image_size": (fw, fh) if fw and fh else None,
            "white_balance": white_balance,
            "has_masks": bool(has_masks),
            "has_ai_masks": bool(has_ai),
            "has_point_color": bool(has_pc),
            "settings": None,
            "history": history.get(image),
        }
        if parse and text:
            try:
                rec["settings"] = parse_develop_blob(text)
            except LrError:
                rec["settings"] = None
        elif parse:
            rec["settings"] = {}
        records.append(rec)
    return records


# ---------------------------------------------------------------- 发现 + 报告

def discover_inputs(paths: Optional[Sequence[str]] = None,
                    max_depth: int = 5) -> Tuple[List[str], List[str]]:
    """展开输入为 (.lrcat, .xmp) 列表。

    文件直接采纳；目录递归发现（跳过隐藏目录）。无参数时默认扫
    ``~/Pictures`` 与 ``~/Desktop``（LR 常见位置），其他机器零配置可跑。
    """
    catalogs: List[str] = []
    xmp: List[str] = []
    if paths:
        roots = [os.path.abspath(os.path.expanduser(p)) for p in paths]
    else:
        roots = [os.path.join(os.path.expanduser("~"), d)
                 for d in ("Pictures", "Desktop")]
    for root in roots:
        if os.path.isfile(root):
            if root.endswith(".lrcat"):
                catalogs.append(root)
            elif root.lower().endswith(".xmp"):
                xmp.append(root)
            continue
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            depth = dirpath[len(root):].count(os.sep)
            if depth >= max_depth:
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for fn in filenames:
                if fn.endswith(".lrcat"):
                    catalogs.append(os.path.join(dirpath, fn))
                elif fn.lower().endswith(".xmp"):
                    xmp.append(os.path.join(dirpath, fn))
    return sorted(set(catalogs)), sorted(set(xmp))


def _export_record(r: Dict[str, Any], source: str) -> Dict[str, Any]:
    """一张照片的训练数据记录：path + options（PhotoS 参数即标签）。"""
    s = r.get("settings") or {}
    if s:
        c = coverage(s, white_balance=r.get("white_balance"))
        o = crs_to_options(
            s,
            image_size=tuple(r["image_size"]) if r.get("image_size") else None,
            white_balance=r.get("white_balance"))
    else:
        c, o = {"edited": False, "mapped": [], "approximate": [],
                "partial": [], "unmapped": [], "v1_8": []}, {}
    return {
        "source": source,
        "catalog": r.get("catalog"),
        "path": r["path"],
        "edited": bool(c["edited"]),
        "options": o,
        "image_size": list(r["image_size"]) if r.get("image_size") else None,
        "white_balance": r.get("white_balance"),
        "history": r.get("history"),
        "coverage": {k: len(v) for k, v in c.items()
                     if isinstance(v, (list, tuple))},
    }


def aggregate_report(catalog_records: Sequence[Dict[str, Any]],
                     xmp_records: Sequence[Dict[str, Any]],
                     catalog_paths: Sequence[str]) -> Dict[str, Any]:
    """聚合覆盖报告（JSON 安全）——lr-scan 的数据核心。"""
    from collections import Counter
    param_usage: Counter = Counter()
    tool_usage: Counter = Counter()
    mask_kinds: Counter = Counter()
    approx: Counter = Counter()
    unmapped: Counter = Counter()
    total = edited = v18 = pc = failed = 0
    cat_totals: Dict[str, Dict[str, int]] = {}
    for cat in catalog_paths:
        cat_totals[cat] = {"photos": 0, "edited": 0, "v1_8": 0,
                           "point_color": 0, "failed": 0}
    # 统计（catalog 记录）
    for r in catalog_records:
        total += 1
        ct = cat_totals.get(r.get("catalog", ""))
        if ct:
            ct["photos"] += 1
        s = r.get("settings")
        if not s:
            failed += 1
            if ct:
                ct["failed"] += 1
            continue
        c = coverage(s, white_balance=r.get("white_balance"))
        if c["edited"]:
            edited += 1
            if ct:
                ct["edited"] += 1
        for k in c["mapped"]:
            if k.startswith("mask:") or k.startswith("local:"):
                continue
            param_usage[k] += 1
        if c["mapped"]:
            o = crs_to_options(
                s, image_size=tuple(r["image_size"])
                if r.get("image_size") else None,
                white_balance=r.get("white_balance"))
            for m in o.get("masks", "").split(";"):
                if m:
                    mask_kinds[m.split(":")[1]] += 1
        for k in c["approximate"]:
            approx[k] += 1
        for k in c["unmapped"]:
            unmapped[k] += 1
        if c["v1_8"]:
            v18 += 1
            if ct:
                ct["v1_8"] += 1
        if _point_color_tuples(s):
            pc += 1
            if ct:
                ct["point_color"] += 1
        if r.get("history"):
            for h in r["history"]:
                if h["name"] and not h["name"].startswith("导入"):
                    tool_usage[h["name"]] += 1
    # 统计（XMP 记录）
    xmp_edited = 0
    for r in xmp_records:
        s = r.get("settings") or {}
        c = coverage(s, white_balance=r.get("white_balance"))
        if c["edited"]:
            xmp_edited += 1
            edited += 1
        for k in c["mapped"]:
            if not (k.startswith("mask:") or k.startswith("local:")):
                param_usage[k] += 1
        for k in c["approximate"]:
            approx[k] += 1
        for k in c["unmapped"]:
            unmapped[k] += 1
        if _point_color_tuples(s):
            pc += 1
    return {
        "inputs": {"catalogs": list(catalog_paths), "xmp_files": len(xmp_records)},
        "catalogs": [{"name": os.path.basename(os.path.dirname(
            os.path.dirname(cat))) or cat, **cat_totals[cat]}
            for cat in catalog_paths],
        "param_usage": dict(param_usage.most_common()),
        "tool_usage": dict(tool_usage.most_common()),
        "mask_kinds": dict(mask_kinds.most_common()),
        "approximate": dict(approx.most_common()),
        "unmapped": dict(unmapped.most_common()),
        "summary": {
            "photos": total,
            "xmp_photos": len(xmp_records),
            "edited": edited,
            "xmp_edited": xmp_edited,
            "v1_8_photos": v18,
            "point_color_photos": pc,
            "failed": failed,
            "mapped_fields": sum(param_usage.values()),
        },
    }


def scan_and_report(paths: Optional[Sequence[str]] = None
                    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """发现输入 → 扫描/解析 → (报告 dict, 训练数据记录 list)。

    报告与记录均为 JSON 安全（list/tuple 已转）。失败项记入统计不中断。
    """
    catalogs, xmp_files = discover_inputs(paths)
    catalog_records: List[Dict[str, Any]] = []
    for cat in catalogs:
        try:
            recs = scan_catalog(cat)
        except LrError:
            recs = [{"path": cat, "settings": None, "history": None,
                     "image_size": None, "white_balance": None,
                     "has_masks": False, "has_ai_masks": False,
                     "has_point_color": False}]
        for rec in recs:
            rec["catalog"] = cat
            catalog_records.append(rec)
    xmp_records: List[Dict[str, Any]] = []
    for p in xmp_files:
        try:
            s = parse_xmp_sidecar(p)
        except LrError:
            s = {}
        xmp_records.append({
            "path": p[:-4] if p.lower().endswith(".xmp") else p,
            "image_size": None, "white_balance": s.get("WhiteBalance"),
            "settings": s, "history": None,
            "has_masks": False, "has_ai_masks": False, "has_point_color": False,
        })
    report = aggregate_report(catalog_records, xmp_records, catalogs)
    records = ([_export_record(r, "catalog") for r in catalog_records]
               + [_export_record(r, "xmp") for r in xmp_records])
    return report, records


def write_export(records: Sequence[Dict[str, Any]], out_dir: str) -> str:
    """写训练数据 JSONL（每行一张照片：path + options）→ 返回文件路径。"""
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "lr_records.jsonl")
    with open(out, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return out
