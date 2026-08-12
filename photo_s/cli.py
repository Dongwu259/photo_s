"""
PhotoS - Command Line Interface

Batch compress and convert images from the terminal.

Examples:
    # Compress all JPEGs in current directory to quality 80
    photo-s compress *.jpg -q 80

    # Convert PNGs to WebP format
    photo-s convert *.png -f webp

    # Batch process a directory recursively
    photo-s batch ~/Pictures/ -r -f JPEG -q 70 --resize 1920x1080

    # Target size mode: auto-tune quality to fit within 500KB
    photo-s compress *.jpg --target-size 500KB

    # Target size + quality ceiling: max quality 90, fit within 2MB
    photo-s batch ~/Pictures/ -r --target-size 2MB -q 90

    # Preview what would happen without actually processing
    photo-s batch ~/Pictures/ --dry-run
"""

import argparse
import glob
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from .engine import (
    ProcessOptions,
    ProcessResult,
    BatchResult,
    batch_process,
    scan_directory,
    format_size,
    apply_exif_tags,
    _resolve_folder_pattern,
    _canonical_format,
    SUPPORTED_FORMATS,
    ALL_INPUT_EXTENSIONS,
    PIL_WRITABLE,
)
from . import __version__


def _collect_files(patterns: List[str], recursive: bool = False) -> List[str]:
    """Collect image files from glob patterns and/or directories."""
    all_files = set()

    for pattern in patterns:
        # Check if pattern is a directory
        p = Path(pattern)
        if p.is_dir():
            all_files.update(scan_directory(pattern, recursive=recursive))
        else:
            # Treat as glob pattern
            matches = glob.glob(pattern, recursive=recursive)
            for match in matches:
                mp = Path(match)
                if mp.is_file() and mp.suffix.lower() in ALL_INPUT_EXTENSIONS:
                    all_files.add(str(mp.absolute()))
                elif mp.is_dir():
                    all_files.update(scan_directory(str(mp), recursive=recursive))

    return sorted(all_files)


def _parse_dimensions(dim_str: str) -> tuple:
    """Parse dimension string like '1920x1080' or '1920' or 'x1080'."""
    dim_str = dim_str.strip().lower()
    if 'x' in dim_str:
        parts = dim_str.split('x')
        w = int(parts[0]) if parts[0] else None
        h = int(parts[1]) if parts[1] else None
        return w, h
    else:
        return int(dim_str), None


def _parse_size(size_str: str) -> int:
    """Parse human-readable size string to bytes.

    Examples: '500' → 500, '500KB' → 512000, '2MB' → 2097152, '1.5MB' → 1572864
    """
    size_str = size_str.strip().upper()
    if not size_str:
        return 0

    # Check for suffix
    multiplier = 1
    for suffix, mult in [("KB", 1024), ("MB", 1024**2), ("GB", 1024**3),
                          ("K", 1024), ("M", 1024**2), ("G", 1024**3)]:
        if size_str.endswith(suffix):
            multiplier = mult
            size_str = size_str[:-len(suffix)]
            break

    try:
        value = float(size_str)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"无效的大小格式 invalid size format: '{size_str}'. "
            f"支持的格式 supported: 500, 500KB, 2MB, 1.5MB"
        )

    return int(value * multiplier)


def _parse_sizes(sizes_str: Optional[str]) -> Optional[List[Tuple[str, Optional[int], Optional[int]]]]:
    """Parse --sizes string like 'thumb:480x,screen:1920x1080'.

    Returns list of (label, max_w, max_h) tuples, or None.
    """
    if not sizes_str:
        return None

    result = []
    for part in sizes_str.split(","):
        part = part.strip()
        if ":" not in part:
            continue
        label, dims = part.split(":", 1)
        label = label.strip()
        dims = dims.strip()
        w, h = _parse_dimensions(dims)
        result.append((label, w, h))

    return result if result else None


def _add_advanced_args(parser):
    """Add shared advanced options (privacy, pixel cap, mtime, evaluate, config).

    Config-capable flags use ``default=argparse.SUPPRESS`` so the config layer
    can tell "explicitly set" from "not set" via ``hasattr(parsed, attr)``
    (plain defaults would be indistinguishable when the user passes a value
    equal to the default, e.g. ``-q 85``).
    """
    parser.add_argument(
        "--strip-gps", action="store_true", default=argparse.SUPPRESS,
        help="移除GPS位置信息 Strip GPS location data",
    )
    parser.add_argument(
        "--keep-mtime", action="store_true", default=argparse.SUPPRESS,
        help="保留原始文件修改时间 Preserve source modification time",
    )
    parser.add_argument(
        "--max-pixels", type=int, default=argparse.SUPPRESS, metavar="N",
        help="最长边像素上限 Max pixels on longest side, e.g. 8000. "
             "仅缩小 Only downscales.",
    )
    parser.add_argument(
        "--evaluate", action="store_true", default=argparse.SUPPRESS,
        help="计算SSIM质量评分 Compute SSIM quality score (input vs output)",
    )
    parser.add_argument(
        "--resume", action="store_true", default=argparse.SUPPRESS,
        help="跳过输出已存在的文件（断点续跑）Skip files whose output "
             "already exists (resume)",
    )
    parser.add_argument(
        "--config", type=str, default=None, metavar="PATH",
        help="配置文件路径 Config file path (photo-s.toml)",
    )


def _date_shift_arg(spec: str) -> str:
    """argparse type for --date-shift: validates the offset syntax."""
    from .engine import parse_date_shift
    try:
        parse_date_shift(spec)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e))
    return spec


def _format_arg(fmt: str) -> str:
    """argparse type for -f/--format: case-insensitive canonical format name.

    Accepts 'png'/'PNG'/'webp' → returns the canonical SUPPORTED_FORMATS key.
    """
    fmt = fmt.strip()
    canonical = _canonical_format(fmt)
    if canonical not in SUPPORTED_FORMATS:
        raise argparse.ArgumentTypeError(
            f"无效格式 invalid format: '{fmt}'. "
            f"可选 Choose from: {', '.join(sorted(SUPPORTED_FORMATS))}"
        )
    return canonical


def _add_transform_args(parser):
    """Add shared transform options (tone, composition, metadata, quality).

    Config-capable args use default=argparse.SUPPRESS (see _add_advanced_args).
    """
    parser.add_argument(
        "--brightness", type=float, default=argparse.SUPPRESS,
        metavar="0-2", help="亮度 Brightness multiplier (1.0 = 不变 unchanged)",
    )
    parser.add_argument(
        "--contrast", type=float, default=argparse.SUPPRESS,
        metavar="0-2", help="对比度 Contrast multiplier (1.0 = 不变)",
    )
    parser.add_argument(
        "--saturation", type=float, default=argparse.SUPPRESS,
        metavar="0-2", help="饱和度 Saturation multiplier (1.0 = 不变)",
    )
    parser.add_argument(
        "--gamma", type=float, default=argparse.SUPPRESS,
        metavar="0.1-3", help="伽马 Gamma (1.0 = 不变, 显示亮度)",
    )
    parser.add_argument(
        "--sharpen", type=float, default=argparse.SUPPRESS,
        metavar="0-3", help="锐化 Sharpen (1.0 = 不变)",
    )
    parser.add_argument(
        "--grayscale", action="store_true", default=argparse.SUPPRESS,
        help="转为黑白 Convert to grayscale",
    )
    parser.add_argument(
        "--sepia", action="store_true", default=argparse.SUPPRESS,
        help="复古色调 Apply sepia toning",
    )
    parser.add_argument(
        "--auto-levels", action="store_true", default=argparse.SUPPRESS,
        help="自动色阶 Auto levels (2%% clip histogram stretch)",
    )
    parser.add_argument(
        "--wb", type=float, default=argparse.SUPPRESS, metavar="KELVIN",
        help="白平衡色温 White balance in Kelvin, e.g. 5600",
    )
    parser.add_argument(
        "--wb-from", type=str, default=argparse.SUPPRESS, metavar="REF.jpg",
        help="从参考图取样白平衡 White balance from a reference image",
    )
    parser.add_argument(
        "--ev", type=float, default=argparse.SUPPRESS, metavar="STOPS",
        help="曝光补偿 EV compensation in stops, e.g. -1.5 / +1",
    )
    parser.add_argument(
        "--auto-exposure", type=float, default=argparse.SUPPRESS, metavar="0-1",
        help="自动曝光: 均值亮度归一化到目标 Auto-exposure target luminance",
    )
    parser.add_argument(
        "--log-curve", type=str, default=argparse.SUPPRESS, metavar="NAME",
        choices=["SLOG3", "CLOG3", "LOGC3", "DLOG", "VLOG", "HLG"],
        help="LOG/平面文件还原曲线 LOG recovery curve (SLOG3 CLOG3 LOGC3 "
             "DLOG VLOG HLG)",
    )
    parser.add_argument(
        "--denoise", type=float, default=argparse.SUPPRESS, metavar="N",
        help="降噪强度（需 photo-s[enhance]）NLM denoise strength 3-20 "
             "(needs optional opencv)",
    )
    parser.add_argument(
        "--auto-straighten", action="store_true", default=argparse.SUPPRESS,
        help="自动扶正地平线（需 photo-s[enhance]）Auto-level the horizon "
             "(needs optional opencv)",
    )
    parser.add_argument(
        "--max-straighten-angle", type=float, default=argparse.SUPPRESS,
        metavar="DEG",
        help="扶正最大允许倾斜角 Max horizon tilt to correct (默认 default: 10°)",
    )
    parser.add_argument(
        "--print-size", type=str, default=argparse.SUPPRESS, metavar="WxH@DPI",
        help="打印尺寸 Print size, e.g. 8x10@300dpi (中心裁剪+精确像素)",
    )
    parser.add_argument(
        "--crop", type=str, default=argparse.SUPPRESS, metavar="WxH+X+Y",
        help="裁剪 Crop, e.g. 800x600+100+50 (偏移可省 → 居中 centered)",
    )
    parser.add_argument(
        "--crop-ratio", type=str, default=argparse.SUPPRESS, metavar="16:9",
        help="按比例居中裁剪 Center-crop to aspect ratio, e.g. 16:9",
    )
    parser.add_argument(
        "--rotate", type=float, default=argparse.SUPPRESS, metavar="DEG",
        help="任意角度旋转 Rotate degrees (正数 = 顺时针 clockwise)",
    )
    parser.add_argument(
        "--rotate-bg", type=str, default=argparse.SUPPRESS, metavar="#RRGGBB",
        help="旋转背景填充色 Rotation corner fill color (默认 black)",
    )
    parser.add_argument(
        "--flip", type=str, default=argparse.SUPPRESS, choices=["h", "v"],
        help="镜像翻转 Mirror: h 水平 horizontal / v 垂直 vertical",
    )
    parser.add_argument(
        "--pad", type=str, default=argparse.SUPPRESS, metavar="16:9",
        help="留白补边到目标比例 Letterbox to aspect ratio, e.g. 16:9",
    )
    parser.add_argument(
        "--pad-bg", type=str, default=argparse.SUPPRESS, metavar="#RRGGBB",
        help="留白背景色 Letterbox background (默认 #000000)",
    )
    parser.add_argument(
        "--date-shift", type=_date_shift_arg, default=argparse.SUPPRESS,
        metavar="OFFSET",
        help="EXIF 日期偏移 Date shift, e.g. \"-5h30m\" / \"+2h\" / \"1d\"",
    )
    parser.add_argument(
        "--scrub", action="store_true", default=argparse.SUPPRESS,
        help="清除全部元数据（EXIF+ICC+注释）Strip ALL metadata (EXIF+ICC+comment)",
    )
    parser.add_argument(
        "--sync-date", action="store_true", default=argparse.SUPPRESS,
        help="输出时间设为 EXIF 拍摄时间 Set output mtime from EXIF datetime",
    )
    parser.add_argument(
        "--srgb", action="store_true", default=argparse.SUPPRESS,
        help="输出标记 sRGB 色彩配置文件 Tag output with sRGB ICC profile",
    )
    parser.add_argument(
        "--flatten-cmyk", action="store_true", default=argparse.SUPPRESS,
        help="CMYK 输入转 RGB Convert CMYK input to RGB",
    )
    parser.add_argument(
        "--blur-score", action="store_true", default=argparse.SUPPRESS,
        help="计算输入图模糊度评分 Compute blur heuristic for inputs",
    )
    parser.add_argument(
        "--report", type=str, default=argparse.SUPPRESS, metavar="OUT.csv",
        help="导出 CSV 处理报告 Write per-file CSV report",
    )
    parser.add_argument(
        "--gpx-trace", type=str, default=argparse.SUPPRESS, metavar="TRACK.gpx",
        help="按 GPX 轨迹注入 GPS 坐标 Geo-tag from a GPX track "
             "(matches EXIF datetime)",
    )


# Config keys the CLI applies outside the generic field mapping
# (inverse booleans; handled below). Everything else in
# config._SIMPLE_FIELDS is applied by the generic loop in
# _apply_config_defaults.
_SEPARATE_CONFIG_KEYS = {"auto_rotate", "optimize"}

# Config key → CLI dest name when they differ (most are identical).
# This is the CLI half of the config mapping — the key set must stay in
# sync with config._SIMPLE_FIELDS (guarded by a parity test in
# tests/test_config.py).
_CONFIG_CLI_DESTS = {
    "output_format": "format",
    "watermark_position": "watermark_pos",
    "rotate_degrees": "rotate",
    "scale_percent": "scale",
    "max_width": "resize",
    "max_height": "resize",
    "rename_pattern": "rename",
}


def _apply_config_defaults(options: ProcessOptions, parsed, cfg: dict) -> ProcessOptions:
    """Apply config-file defaults for options the user did not set on the CLI.

    Precedence: explicit CLI > config file > built-in defaults.
    A CLI option counts as "set" when it appears in the parsed namespace —
    config-capable argparse args use ``default=argparse.SUPPRESS`` so absent
    attributes mean "not passed" (an equals-the-default value like ``-q 85``
    is still a real value and wins over the config file).
    """
    from .config import _SIMPLE_FIELDS
    opts = cfg.get("options", {}) if isinstance(cfg, dict) else {}

    # Generic mapping: config key → ProcessOptions field (config._SIMPLE_FIELDS
    # is the single source of truth for the key→field direction). A config key
    # is applied only when its CLI counterpart was not explicitly passed —
    # checked via the CLI dest name (_CONFIG_CLI_DESTS handles renames).
    for config_key, field in _SIMPLE_FIELDS.items():
        if config_key in _SEPARATE_CONFIG_KEYS:
            continue
        if config_key not in opts or opts[config_key] is None:
            continue
        cli_dest = _CONFIG_CLI_DESTS.get(config_key, config_key)
        if not hasattr(parsed, cli_dest):
            setattr(options, field, opts[config_key])

    # inverse boolean flags (CLI uses --no-*, config uses positive form)
    if "preserve_exif" in opts and not getattr(parsed, "no_exif", False):
        options.preserve_exif = bool(opts["preserve_exif"])
    if "auto_rotate" in opts and not getattr(parsed, "no_auto_rotate", False):
        options.auto_rotate = bool(opts["auto_rotate"])
    if "optimize" in opts and not getattr(parsed, "no_optimize", False):
        options.optimize = bool(opts["optimize"])
    if "raw_auto_bright" in opts and not getattr(parsed, "raw_no_auto_bright", False):
        options.raw_auto_bright = bool(opts["raw_auto_bright"])

    if "target_size" in opts and not getattr(parsed, "target_size", None):
        from .config import _parse_size as _cfg_parse_size
        size = _cfg_parse_size(opts["target_size"])
        if size is not None:
            options.target_size_bytes = size

    if "folder_pattern" in opts and not getattr(parsed, "organize", None):
        options.folder_pattern = _resolve_folder_pattern(str(opts["folder_pattern"]))

    # case-insensitive format from config ("png" / "WEBP" → "PNG" / "WebP")
    options.output_format = _canonical_format(options.output_format)

    return options


def _print_result(result: ProcessResult):
    """Print a single processing result."""
    if result.success:
        savings = format_size(result.input_size - result.output_size)
        pct = ((result.input_size - result.output_size) / result.input_size * 100
               if result.input_size > 0 else 0)
        print(f"  ✅ {os.path.basename(result.input_path)}")
        if result.input_format == "RAW":
            print(f"     📷 RAW → {result.output_format}")
        else:
            print(f"     {result.input_format} → {result.output_format}")
        if result.achieved_quality:
            print(f"     质量 Quality: {result.achieved_quality}")
        if result.ssim is not None:
            print(f"     SSIM: {result.ssim:.3f}")
        print(f"     {result.input_dims[0]}×{result.input_dims[1]} → "
              f"{result.output_dims[0]}×{result.output_dims[1]}")
        print(f"     {format_size(result.input_size)} → {format_size(result.output_size)} "
              f"(-{savings}, -{pct:.1f}%)")
        print(f"     → {result.output_path}")
        if result.error:  # target-size warning
            print(f"     ⚠️  {result.error}")
    else:
        print(f"  ❌ {os.path.basename(result.input_path)}: {result.error}")


def _print_batch_summary(result: BatchResult):
    """Print batch processing summary."""
    print()
    print("─" * 60)
    print(f"📊 处理完成 Summary")
    print(f"   成功 Success: {result.success_count}")
    print(f"   失败 Failed:  {result.fail_count}")
    print(f"   原始总大小 Total original: {format_size(result.total_input_size)}")
    print(f"   压缩后总大小 Total compressed: {format_size(result.total_output_size)}")
    savings = format_size(result.savings_bytes)
    print(f"   节省 Saved: {savings} ({result.savings_percent:.1f}%)")
    print("─" * 60)


def run_cli(args: List[str] = None) -> int:
    """
    Parse CLI arguments and execute the requested operation.

    Returns exit code (0 = success, 1 = error).
    """
    if args is None:
        args = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="photo-s",
        description="PhotoS — 批量图片压缩与格式转换工具 Batch Image Compression & Format Conversion",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例 Examples:
  photo-s compress *.jpg -q 80                 批量压缩JPEG图片
  photo-s compress *.jpg --target-size 500KB   自动调优质量至500KB以内
  photo-s compress *.ARW -q 90                 将RAW照片转为JPEG
  photo-s compress *.ARW --raw-half-size -q 85  RAW半尺寸快速处理
  photo-s convert *.png -f webp -q 85          转换PNG为WebP
  photo-s batch ~/Pictures/ -r -f JPEG -q 70   递归处理整个目录
  photo-s batch ~/Pictures/ -r --target-size 2MB  自动调优质量至2MB以内
  photo-s batch . --resize 1920x1080           批量缩放图片
  photo-s batch . --scale 50                    缩小到50%%
  photo-s batch . --no-exif                     不保留EXIF信息
  photo-s batch . --dry-run                      预览模式（不实际处理）
  photo-s batch . --organize date                按日期创建子文件夹
  photo-s batch . --organize date-camera         按日期+相机创建子文件夹
        """,
    )
    parser.add_argument(
        "--json", action="store_true",
        help="输出 JSON 格式（供 AI agent 调用）Output JSON format for AI agents",
    )
    parser.add_argument(
        "--version", action="version", version=f"photo-s {__version__}",
        help="显示版本号 Show version",
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令 Commands")

    # ── compress subcommand ──────────────────────────────────────────────────
    compress_parser = subparsers.add_parser(
        "compress", help="压缩图片体积 Compress image file size",
    )
    compress_parser.add_argument(
        "files", nargs="+", help="图片文件或通配符 Image files or glob patterns",
    )
    compress_parser.add_argument(
        "--json", action="store_true",
        help="输出 JSON 格式（供 AI agent 调用）Output JSON format for AI agents",
    )
    compress_parser.add_argument(
        "-q", "--quality", type=int, default=argparse.SUPPRESS,
        help="输出质量 Output quality 1-100 (默认 default: 85)",
    )
    compress_parser.add_argument(
        "-o", "--output-dir", type=str, default=argparse.SUPPRESS,
        help="输出目录 Output directory (默认 default: 与源文件相同 same as source)",
    )
    compress_parser.add_argument(
        "--suffix", type=str, default=argparse.SUPPRESS,
        help="输出文件名后缀 Output filename suffix (默认 default: _compressed)",
    )
    compress_parser.add_argument(
        "--no-exif", action="store_true",
        help="不保留EXIF元数据 Strip EXIF metadata",
    )
    compress_parser.add_argument(
        "--resize", type=str, default=argparse.SUPPRESS, metavar="WxH",
        help="缩放尺寸 Resize dimensions, e.g. 1920x1080, 800x, x600",
    )
    compress_parser.add_argument(
        "--scale", type=int, default=argparse.SUPPRESS, metavar="PCT",
        help="缩放百分比 Scale percentage, e.g. 50",
    )
    compress_parser.add_argument(
        "--dry-run", action="store_true",
        help="预览模式，不实际处理 Dry run — preview only",
    )
    compress_parser.add_argument(
        "-r", "--recursive", action="store_true",
        help="递归搜索目录 Recursively search directories",
    )
    compress_parser.add_argument(
        "-j", "--jobs", type=int, default=argparse.SUPPRESS, metavar="N",
        help="并行处理线程数 Parallel worker threads (默认 default: 1)",
    )
    compress_parser.add_argument(
        "--target-size", type=str, default=argparse.SUPPRESS, metavar="SIZE",
        help="目标文件体积 Target file size, e.g. 500KB, 2MB. "
             "自动调整质量以适应该大小 Auto-tune quality to fit.",
    )
    compress_parser.add_argument(
        "--raw-half-size", action="store_true",
        help="RAW文件半尺寸解码（更快）RAW half-size decode (faster)",
    )
    compress_parser.add_argument(
        "--raw-no-auto-bright", action="store_true",
        help="禁用RAW自动亮度 Disable RAW auto brightness",
    )
    compress_parser.add_argument(
        "--no-auto-rotate", action="store_true",
        help="禁用自动旋转 Disable auto-rotate by EXIF",
    )
    compress_parser.add_argument(
        "--remove-original", action="store_true", default=argparse.SUPPRESS,
        help="处理后删除原文件 Delete original after processing",
    )
    compress_parser.add_argument(
        "--rename", type=str, default=argparse.SUPPRESS, metavar="PATTERN",
        help="智能重命名 Smart rename, 变量 vars: {year} {month} {day} {date} {time} "
             "{camera} {make} {original} {iso} {focal} {seq}",
    )
    compress_parser.add_argument(
        "--organize", type=str, default=argparse.SUPPRESS, metavar="PRESET|PATTERN",
        help="按模板创建子文件夹 Organize into subfolders. "
             "预设 Presets: date, camera, date-camera. "
             "自定义 Custom: {year}/{month}/{camera} 等 etc.",
    )
    compress_parser.add_argument(
        "--sizes", type=str, default=None, metavar="LABEL:WxH,...",
        help="多尺寸输出 Multi-size, e.g. thumb:480x,screen:1920x1080",
    )
    compress_parser.add_argument(
        "--watermark-text", type=str, default=argparse.SUPPRESS, metavar="TEXT",
        help="文字水印 Text watermark",
    )
    compress_parser.add_argument(
        "--watermark-pos", type=str, default=argparse.SUPPRESS,
        help="水印位置 Watermark position",
    )
    compress_parser.add_argument(
        "--watermark-opacity", type=int, default=argparse.SUPPRESS,
        help="水印透明度 Watermark opacity 0-100",
    )
    _add_advanced_args(compress_parser)
    _add_transform_args(compress_parser)

    # ── convert subcommand ───────────────────────────────────────────────────
    convert_parser = subparsers.add_parser(
        "convert", help="转换图片格式 Convert image format",
    )
    convert_parser.add_argument(
        "files", nargs="+", help="图片文件或通配符 Image files or glob patterns",
    )
    convert_parser.add_argument(
        "--json", action="store_true",
        help="输出 JSON 格式（供 AI agent 调用）Output JSON format for AI agents",
    )
    convert_parser.add_argument(
        "-f", "--format", type=_format_arg, default=argparse.SUPPRESS,
        help="目标格式 Target format (默认 default: JPEG, 大小写不敏感 case-insensitive)",
    )
    convert_parser.add_argument(
        "-q", "--quality", type=int, default=argparse.SUPPRESS,
        help="输出质量 Output quality 1-100 (JPEG/WebP/HEIC)",
    )
    convert_parser.add_argument(
        "-o", "--output-dir", type=str, default=argparse.SUPPRESS,
        help="输出目录 Output directory",
    )
    convert_parser.add_argument(
        "--prefix", type=str, default=argparse.SUPPRESS,
        help="输出文件名前缀 Output filename prefix",
    )
    convert_parser.add_argument(
        "--suffix", type=str, default=argparse.SUPPRESS,
        help="输出文件名后缀 Output filename suffix",
    )
    convert_parser.add_argument(
        "--no-exif", action="store_true",
        help="不保留EXIF元数据 Strip EXIF metadata",
    )
    convert_parser.add_argument(
        "--resize", type=str, default=argparse.SUPPRESS, metavar="WxH",
        help="缩放尺寸 Resize dimensions",
    )
    convert_parser.add_argument(
        "--scale", type=int, default=argparse.SUPPRESS, metavar="PCT",
        help="缩放百分比 Scale percentage",
    )
    convert_parser.add_argument(
        "--dry-run", action="store_true",
        help="预览模式 Dry run — preview only",
    )
    convert_parser.add_argument(
        "-r", "--recursive", action="store_true",
        help="递归搜索目录 Recursively search directories",
    )
    convert_parser.add_argument(
        "--overwrite", action="store_true", default=argparse.SUPPRESS,
        help="覆盖已存在的文件 Overwrite existing files",
    )
    convert_parser.add_argument(
        "--target-size", type=str, default=argparse.SUPPRESS, metavar="SIZE",
        help="目标文件体积 Target file size, e.g. 500KB, 2MB. "
             "自动调整质量以适应该大小 Auto-tune quality to fit.",
    )
    convert_parser.add_argument(
        "--raw-half-size", action="store_true",
        help="RAW文件半尺寸解码（更快）RAW half-size decode (faster)",
    )
    convert_parser.add_argument(
        "--raw-no-auto-bright", action="store_true",
        help="禁用RAW自动亮度 Disable RAW auto brightness",
    )
    convert_parser.add_argument(
        "--no-auto-rotate", action="store_true",
        help="禁用自动旋转 Disable auto-rotate by EXIF",
    )
    convert_parser.add_argument(
        "--remove-original", action="store_true", default=argparse.SUPPRESS,
        help="处理后删除原文件 Delete original after processing",
    )
    _add_advanced_args(convert_parser)
    _add_transform_args(convert_parser)

    # ── batch subcommand (combined) ──────────────────────────────────────────
    batch_parser = subparsers.add_parser(
        "batch", help="批量处理（压缩+转换+缩放）Batch process (compress + convert + resize)",
    )
    batch_parser.add_argument(
        "paths", nargs="+", help="文件/目录/通配符 Files, directories, or glob patterns",
    )
    batch_parser.add_argument(
        "--json", action="store_true",
        help="输出 JSON 格式（供 AI agent 调用）Output JSON format for AI agents",
    )
    batch_parser.add_argument(
        "-f", "--format", type=_format_arg, default=argparse.SUPPRESS,
        help="目标格式 Target format (默认 default: JPEG, 大小写不敏感 case-insensitive)",
    )
    batch_parser.add_argument(
        "-q", "--quality", type=int, default=argparse.SUPPRESS,
        help="输出质量 Output quality 1-100",
    )
    batch_parser.add_argument(
        "-o", "--output-dir", type=str, default=argparse.SUPPRESS,
        help="输出目录 Output directory",
    )
    batch_parser.add_argument(
        "--prefix", type=str, default=argparse.SUPPRESS,
        help="输出文件名前缀 Output filename prefix",
    )
    batch_parser.add_argument(
        "--suffix", type=str, default=argparse.SUPPRESS,
        help="输出文件名后缀 Output filename suffix (默认 default: _processed)",
    )
    batch_parser.add_argument(
        "--resize", type=str, default=argparse.SUPPRESS, metavar="WxH",
        help="缩放尺寸 Resize dimensions, e.g. 1920x1080",
    )
    batch_parser.add_argument(
        "--scale", type=int, default=argparse.SUPPRESS, metavar="PCT",
        help="缩放百分比 Scale percentage, e.g. 50",
    )
    batch_parser.add_argument(
        "--no-exif", action="store_true",
        help="不保留EXIF元数据 Strip EXIF metadata",
    )
    batch_parser.add_argument(
        "--progressive", action="store_true", default=argparse.SUPPRESS,
        help="使用渐进式JPEG Use progressive JPEG encoding",
    )
    batch_parser.add_argument(
        "--no-optimize", action="store_true",
        help="禁用PIL优化 Disable PIL optimize pass",
    )
    batch_parser.add_argument(
        "-r", "--recursive", action="store_true",
        help="递归搜索目录 Recursively search directories",
    )
    batch_parser.add_argument(
        "-j", "--jobs", type=int, default=argparse.SUPPRESS, metavar="N",
        help="并行处理线程数 Parallel worker threads (默认 default: 1)",
    )
    batch_parser.add_argument(
        "--overwrite", action="store_true", default=argparse.SUPPRESS,
        help="覆盖已存在的文件 Overwrite existing files",
    )
    batch_parser.add_argument(
        "--dry-run", action="store_true",
        help="预览模式，不实际处理 Dry run — preview only",
    )
    batch_parser.add_argument(
        "--target-size", type=str, default=argparse.SUPPRESS, metavar="SIZE",
        help="目标文件体积 Target file size, e.g. 500KB, 2MB. "
             "自动调整质量以适应该大小 Auto-tune quality to fit.",
    )
    batch_parser.add_argument(
        "--raw-half-size", action="store_true",
        help="RAW文件半尺寸解码（更快）RAW half-size decode (faster)",
    )
    batch_parser.add_argument(
        "--raw-no-auto-bright", action="store_true",
        help="禁用RAW自动亮度 Disable RAW auto brightness",
    )
    batch_parser.add_argument(
        "--no-auto-rotate", action="store_true",
        help="禁用自动旋转 Disable auto-rotate by EXIF",
    )
    batch_parser.add_argument(
        "--remove-original", action="store_true", default=argparse.SUPPRESS,
        help="处理后删除原文件 Delete original after processing",
    )
    batch_parser.add_argument(
        "-y", "--yes", action="store_true",
        help="跳过所有确认提示 Skip all confirmation prompts",
    )
    batch_parser.add_argument(
        "--rename", type=str, default=argparse.SUPPRESS, metavar="PATTERN",
        help="智能重命名 Smart rename, 变量 vars: {year} {month} {day} {date} {time} "
             "{camera} {make} {original} {iso} {focal} {seq}",
    )
    batch_parser.add_argument(
        "--organize", type=str, default=argparse.SUPPRESS, metavar="PRESET|PATTERN",
        help="按模板创建子文件夹 Organize into subfolders. "
             "预设 Presets: date, camera, date-camera. "
             "自定义 Custom: {year}/{month}/{camera} 等 etc.",
    )
    batch_parser.add_argument(
        "--watermark-text", type=str, default=argparse.SUPPRESS, metavar="TEXT",
        help="文字水印 Text watermark",
    )
    batch_parser.add_argument(
        "--watermark-image", type=str, default=argparse.SUPPRESS, metavar="PATH",
        help="图片水印路径 Image watermark path",
    )
    batch_parser.add_argument(
        "--watermark-pos", type=str, default=argparse.SUPPRESS,
        choices=["CENTER", "TOP_LEFT", "TOP_RIGHT", "BOTTOM_LEFT",
                 "BOTTOM_RIGHT", "TOP", "BOTTOM"],
        help="水印位置 Watermark position",
    )
    batch_parser.add_argument(
        "--watermark-opacity", type=int, default=argparse.SUPPRESS, metavar="0-100",
        help="水印透明度 Watermark opacity",
    )
    batch_parser.add_argument(
        "--sizes", type=str, default=None, metavar="LABEL:WxH,...",
        help="多尺寸输出 Multi-size, e.g. thumb:480x,screen:1920x1080",
    )
    _add_advanced_args(batch_parser)
    _add_transform_args(batch_parser)
    batch_parser.add_argument(
        "--profiles", type=str, default=None, metavar="P1,P2",
        help="按预设多跑 Multi-profile: 同一批文件按每个预设各输出一份 "
             "(preset names, comma-separated, e.g. web,thumb)",
    )

    # ── exif subcommand ─────────────────────────────────────────────────────
    exif_parser = subparsers.add_parser(
        "exif", help="批量读写EXIF元数据/打标/筛选 Read, write & filter EXIF metadata",
    )
    exif_parser.add_argument(
        "files", nargs="*", help="图片文件 Image files",
    )
    exif_parser.add_argument(
        "-r", "--recursive", action="store_true",
        help="递归搜索目录 Recursively search directories",
    )
    exif_parser.add_argument(
        "--show", action="store_true",
        help="读取模式: 显示元数据并按条件筛选 Read mode (filters apply)",
    )
    exif_parser.add_argument(
        "--json", action="store_true",
        help="输出 JSON 格式（供 AI agent 调用）Output JSON format for AI agents",
    )
    exif_parser.add_argument(
        "--list", action="store_true",
        help="仅输出匹配文件路径（供管道）Output matching paths only (for piping)",
    )
    # ── write tags ──
    exif_parser.add_argument(
        "--artist", type=str, default=None, help="作者 Artist / Photographer",
    )
    exif_parser.add_argument(
        "--copyright", type=str, default=None, help="版权 Copyright",
    )
    exif_parser.add_argument(
        "--description", type=str, default=None, help="图片描述 Image description",
    )
    exif_parser.add_argument(
        "--caption", type=str, default=None, help="图注 Caption (= description)",
    )
    exif_parser.add_argument(
        "--title", type=str, default=None, help="标题 Title",
    )
    exif_parser.add_argument(
        "--rating", type=int, default=None, metavar="0-5",
        help="星级 Rating 0-5（写模式=赋值；--show 下=精确筛选）"
             "(write: set; --show: exact filter)",
    )
    exif_parser.add_argument(
        "--keywords", type=str, default=None, metavar="A,B",
        help="关键词 Keywords，逗号分隔（写模式=赋值；--show 下=任意命中筛选）"
             "(write: set; --show: any-match filter)",
    )
    exif_parser.add_argument(
        "--date", type=str, default=None, metavar="DATETIME",
        help="拍摄日期 Date taken, e.g. '2024:07:30 14:30:00'",
    )
    exif_parser.add_argument(
        "--software", type=str, default=None, help="软件 Software tag",
    )
    exif_parser.add_argument(
        "--date-from-mtime", action="store_true",
        help="用文件修改时间写拍摄日期（反向同步）Set DateTimeOriginal "
             "from the file's mtime (reverse sync)",
    )
    # ── filter (with --show) ──
    exif_parser.add_argument(
        "--rating-min", type=int, default=None, metavar="N",
        help="筛选: 最低星级 Minimum rating (with --show)",
    )
    exif_parser.add_argument(
        "--camera", type=str, default=None, metavar="MODEL",
        help="筛选: 相机型号子串 Camera model substring (with --show)",
    )
    exif_parser.add_argument(
        "--date-from", type=str, default=None, metavar="YYYY-MM-DD",
        help="筛选: 起始日期 (with --show)",
    )
    exif_parser.add_argument(
        "--date-to", type=str, default=None, metavar="YYYY-MM-DD",
        help="筛选: 结束日期 (with --show)",
    )
    # ── batch import ──
    exif_parser.add_argument(
        "--from-csv", type=str, default=None, metavar="meta.csv",
        help="从CSV批量写入元数据（首列 path）Batch write from CSV "
             "(columns: path,rating,keywords,caption,title,...)",
    )
    exif_parser.add_argument(
        "--from-json", type=str, default=None, metavar="meta.json",
        help="从JSON批量写入元数据 Batch write from JSON "
             "([{path, rating, keywords, ...}, ...])",
    )

    # ── preset subcommand ───────────────────────────────────────────────────
    preset_parser = subparsers.add_parser(
        "preset", help="管理预设配置 Manage presets",
    )
    preset_subs = preset_parser.add_subparsers(dest="preset_action")

    preset_save = preset_subs.add_parser("save", help="保存预设 Save a preset")
    preset_save.add_argument("name", help="预设名称 Preset name")
    preset_save.add_argument("-f", "--format", type=str, default="JPEG")
    preset_save.add_argument("-q", "--quality", type=int, default=85)
    preset_save.add_argument("--resize", type=str, default=None)
    preset_save.add_argument("--suffix", type=str, default="_compressed")
    preset_save.add_argument("--desc", type=str, default="", help="描述 Description")

    preset_list = preset_subs.add_parser("list", help="列出所有预设 List presets")
    preset_load = preset_subs.add_parser("load", help="加载预设 Print preset config")
    preset_load.add_argument("name", help="预设名称 Preset name")
    preset_delete = preset_subs.add_parser("delete", help="删除预设 Delete preset")
    preset_delete.add_argument("name", help="预设名称 Preset name")

    # ── plugin subcommand ───────────────────────────────────────────────────
    plugin_parser = subparsers.add_parser(
        "plugin", help="管理官方插件 Manage official plugins",
    )
    plugin_subs = plugin_parser.add_subparsers(dest="plugin_action")

    plugin_list = plugin_subs.add_parser(
        "list", help="列出已装/可用插件 List installed & available",
    )
    plugin_list.add_argument(
        "--json", action="store_true",
        help="输出 JSON 格式（供 AI agent 调用）Output JSON format for AI agents",
    )

    plugin_install = plugin_subs.add_parser(
        "install", help="安装官方插件 Install an official plugin",
    )
    plugin_install.add_argument("name", help="插件名 Plugin name (如 scunet)")
    plugin_install.add_argument(
        "--json", action="store_true",
        help="输出 JSON 格式（供 AI agent 调用）Output JSON format for AI agents",
    )
    plugin_install.add_argument(
        "--dry-run", action="store_true",
        help="只显示将执行的 pip 命令，不实际安装 Preview pip command",
    )

    plugin_uninstall = plugin_subs.add_parser(
        "uninstall", help="卸载插件 Uninstall a plugin",
    )
    plugin_uninstall.add_argument("name", help="插件名 Plugin name")
    plugin_uninstall.add_argument(
        "--json", action="store_true",
        help="输出 JSON 格式（供 AI agent 调用）Output JSON format for AI agents",
    )
    plugin_uninstall.add_argument(
        "--dry-run", action="store_true",
        help="只显示将执行的 pip 命令，不实际卸载 Preview pip command",
    )

    plugin_info = plugin_subs.add_parser(
        "info", help="插件详情 + 权重状态 Plugin details & weight status",
    )
    plugin_info.add_argument("name", help="插件名 Plugin name")
    plugin_info.add_argument(
        "--json", action="store_true",
        help="输出 JSON 格式（供 AI agent 调用）Output JSON format for AI agents",
    )

    plugin_fetch = plugin_subs.add_parser(
        "fetch", help="预下载模型权重 Pre-download model weights",
    )
    plugin_fetch.add_argument("name", help="插件名 Plugin name")
    plugin_fetch.add_argument(
        "--json", action="store_true",
        help="输出 JSON 格式（供 AI agent 调用）Output JSON format for AI agents",
    )

    # ── watch subcommand ────────────────────────────────────────────────────
    watch_parser = subparsers.add_parser(
        "watch", help="监视文件夹自动处理 Watch folder and auto-process",
    )
    watch_parser.add_argument(
        "directory", help="要监视的文件夹 Directory to watch",
    )
    watch_parser.add_argument(
        "-f", "--format", type=_format_arg, default="JPEG",
        help="目标格式 Target format (大小写不敏感 case-insensitive)",
    )
    watch_parser.add_argument(
        "-q", "--quality", type=int, default=85,
        help="输出质量 Output quality 1-100",
    )
    watch_parser.add_argument(
        "-o", "--output-dir", type=str, default=None,
        help="输出目录 Output directory",
    )
    watch_parser.add_argument(
        "-r", "--recursive", action="store_true",
        help="递归监视子目录 Watch subdirectories",
    )
    watch_parser.add_argument(
        "--remove-original", action="store_true",
        help="处理后删除原文件 Delete original after processing",
    )
    watch_parser.add_argument(
        "--resize", type=str, default=None, metavar="WxH",
        help="缩放尺寸 Resize dimensions",
    )

    # ── dedup subcommand ────────────────────────────────────────────────────
    dedup_parser = subparsers.add_parser(
        "dedup", help="查找重复图片 Find duplicate images",
    )
    dedup_parser.add_argument(
        "paths", nargs="+", help="文件/目录/通配符 Files, directories, or glob patterns",
    )
    dedup_parser.add_argument(
        "--json", action="store_true",
        help="输出 JSON 格式（供 AI agent 调用）Output JSON format for AI agents",
    )
    dedup_parser.add_argument(
        "-r", "--recursive", action="store_true",
        help="递归搜索目录 Recursively search subdirectories",
    )
    dedup_parser.add_argument(
        "--threshold", type=int, default=5, metavar="N",
        help="汉明距离阈值 Hamming distance threshold (默认 default: 5, 越小越严格 stricter)",
    )
    dedup_parser.add_argument(
        "--action", type=str, default="report",
        choices=["report", "move", "delete", "keep-sharpest"],
        help="操作: report=仅报告, move=移到_duplicates文件夹, delete=删除, "
             "keep-sharpest=连拍保留最清晰 (默认 default: report)",
    )
    dedup_parser.add_argument(
        "--dry-run", action="store_true",
        help="预览模式 不实际移动/删除 Dry run — only show what would happen",
    )

    # ── info subcommand ─────────────────────────────────────────────────────
    info_parser = subparsers.add_parser(
        "info", help="显示支持的格式列表 Show supported formats",
    )
    info_parser.add_argument(
        "--json", action="store_true",
        help="输出 JSON 格式（供 AI agent 调用）Output JSON format for AI agents",
    )

    # ── rename subcommand ───────────────────────────────────────────────────
    rename_parser = subparsers.add_parser(
        "rename", help="批量重命名图片 Batch rename images",
    )
    rename_parser.add_argument(
        "files", nargs="+", help="图片文件或通配符 Image files or glob patterns",
    )
    rename_parser.add_argument(
        "--json", action="store_true",
        help="输出 JSON 格式（供 AI agent 调用）Output JSON format for AI agents",
    )
    rename_parser.add_argument(
        "--pattern", type=str, required=True, metavar="PATTERN",
        help="命名模板 Rename pattern, 变量 vars: {year} {month} {day} {date} {time} "
             "{camera} {make} {original} {iso} {focal} {seq}",
    )
    rename_parser.add_argument(
        "-o", "--output-dir", type=str, default=None,
        help="输出目录（复制改名而非就地）Copy to directory instead of renaming in place",
    )
    rename_parser.add_argument(
        "--dry-run", action="store_true",
        help="预览模式 Dry run — preview only",
    )
    rename_parser.add_argument(
        "--overwrite", action="store_true",
        help="覆盖已存在的文件 Overwrite existing files",
    )
    rename_parser.add_argument(
        "-r", "--recursive", action="store_true",
        help="递归搜索目录 Recursively search directories",
    )

    # ── check subcommand ────────────────────────────────────────────────────
    check_parser = subparsers.add_parser(
        "check", help="检查图片完整性 Verify image integrity",
    )
    check_parser.add_argument(
        "files", nargs="+", help="图片文件或通配符 Image files or glob patterns",
    )
    check_parser.add_argument(
        "-r", "--recursive", action="store_true",
        help="递归搜索目录 Recursively search directories",
    )
    check_parser.add_argument(
        "--json", action="store_true",
        help="输出 JSON 格式（供 AI agent 调用）Output JSON format for AI agents",
    )

    # ── contact-sheet subcommand ────────────────────────────────────────────
    sheet_parser = subparsers.add_parser(
        "contact-sheet", help="生成联系表 Contact sheet (grid montage)",
    )
    sheet_parser.add_argument(
        "files", nargs="+", help="图片文件或通配符 Image files or glob patterns",
    )
    sheet_parser.add_argument(
        "--json", action="store_true",
        help="输出 JSON 格式（供 AI agent 调用）Output JSON format for AI agents",
    )
    sheet_parser.add_argument(
        "-o", "--output", type=str, required=True,
        help="输出文件路径 Output image path (.jpg/.png)",
    )
    sheet_parser.add_argument(
        "--cols", type=int, default=4,
        help="每行列数 Columns per row (默认 default: 4)",
    )
    sheet_parser.add_argument(
        "--thumb", type=str, default="240x240", metavar="WxH",
        help="缩略图尺寸 Thumbnail size (默认 default: 240x240)",
    )
    sheet_parser.add_argument(
        "--caption", action="store_true",
        help="显示文件名 Show filename captions",
    )
    sheet_parser.add_argument(
        "--bg", type=str, default="#000000",
        help="背景色 Background color, e.g. #1a1a1a",
    )
    sheet_parser.add_argument(
        "-r", "--recursive", action="store_true",
        help="递归搜索目录 Recursively search directories",
    )

    # ── cull subcommand ─────────────────────────────────────────────────────
    cull_parser = subparsers.add_parser(
        "cull", help="曝光/清晰度筛选 Cull by exposure & sharpness",
    )
    cull_parser.add_argument(
        "paths", nargs="+", help="文件/目录/通配符 Files, directories, or glob patterns",
    )
    cull_parser.add_argument(
        "-r", "--recursive", action="store_true",
        help="递归搜索目录 Recursively search subdirectories",
    )
    cull_parser.add_argument(
        "--overexposed-max", type=float, default=None, metavar="PCT",
        help="筛选: 过曝像素上限 Max overexposed %% (default: 不筛选 no filter)",
    )
    cull_parser.add_argument(
        "--underexposed-max", type=float, default=None, metavar="PCT",
        help="筛选: 欠曝像素上限 Max underexposed %%",
    )
    cull_parser.add_argument(
        "--luminance-min", type=float, default=None, metavar="0-1",
        help="筛选: 最低平均亮度 Min mean luminance (0-1)",
    )
    cull_parser.add_argument(
        "--luminance-max", type=float, default=None, metavar="0-1",
        help="筛选: 最高平均亮度 Max mean luminance (0-1)",
    )
    cull_parser.add_argument(
        "--sharpness-min", type=float, default=None, metavar="N",
        help="筛选: 最低清晰度分 Min blur-score",
    )
    cull_parser.add_argument(
        "--json", action="store_true",
        help="输出 JSON 格式（供 AI agent 调用）Output JSON format for AI agents",
    )
    cull_parser.add_argument(
        "--list", action="store_true",
        help="仅输出通过筛选的路径（供管道）Output passing paths only (for piping)",
    )

    # ── hash subcommand ─────────────────────────────────────────────────────
    hash_parser = subparsers.add_parser(
        "hash", help="生成/校验校验和清单 Checksum manifest (SHA-256)",
    )
    hash_parser.add_argument(
        "paths", nargs="*", help="文件/目录/通配符 Files, directories, or glob patterns",
    )
    hash_parser.add_argument(
        "-r", "--recursive", action="store_true",
        help="递归搜索目录 Recursively search subdirectories",
    )
    hash_parser.add_argument(
        "-o", "--output", type=str, default=None, metavar="manifest.csv",
        help="清单输出路径 Manifest output (默认 default: ./manifest.csv)",
    )
    hash_parser.add_argument(
        "--verify", type=str, default=None, metavar="manifest.csv",
        help="校验模式: 重新哈希并对照清单 Verify mode",
    )
    hash_parser.add_argument(
        "--sha256", action="store_true", help="使用 SHA-256（默认）Use SHA-256",
    )
    hash_parser.add_argument(
        "--json", action="store_true",
        help="输出 JSON 格式（供 AI agent 调用）Output JSON format for AI agents",
    )

    # ── gallery subcommand ──────────────────────────────────────────────────
    gallery_parser = subparsers.add_parser(
        "gallery", help="生成 HTML 画廊 Generate HTML gallery",
    )
    gallery_parser.add_argument(
        "paths", nargs="+", help="文件/目录/通配符 Files, directories, or glob patterns",
    )
    gallery_parser.add_argument(
        "-o", "--output", type=str, required=True, metavar="DIR",
        help="输出目录 Output directory",
    )
    gallery_parser.add_argument(
        "--title", type=str, default="PhotoS Gallery", metavar="TITLE",
        help="画廊标题 Gallery title (默认 default: PhotoS Gallery)",
    )
    gallery_parser.add_argument(
        "--thumb", type=int, default=360, metavar="PX",
        help="缩略图最长边 Thumbnail longest side (默认 default: 360)",
    )
    gallery_parser.add_argument(
        "-r", "--recursive", action="store_true",
        help="递归搜索目录 Recursively search subdirectories",
    )
    gallery_parser.add_argument(
        "--json", action="store_true",
        help="输出 JSON 格式（供 AI agent 调用）Output JSON format for AI agents",
    )

    # ── config subcommand ───────────────────────────────────────────────────
    config_parser = subparsers.add_parser(
        "config", help="管理配置文件 Manage config file (photo-s.toml)",
    )
    config_subs = config_parser.add_subparsers(dest="config_action")
    config_init = config_subs.add_parser(
        "init", help="创建默认配置文件 Create a default config file",
    )
    config_init.add_argument(
        "--path", type=str, default=None,
        help="输出路径 Output path (默认 default: ./photo-s.toml)",
    )
    config_show = config_subs.add_parser(
        "show", help="显示生效配置 Show effective config",
    )
    config_show.add_argument(
        "--path", type=str, default=None,
        help="配置文件路径 Config file path",
    )

    # ── serve subcommand ────────────────────────────────────────────────────
    serve_parser = subparsers.add_parser(
        "serve", help="启动REST API服务（供 AI agent 调用）Start REST API server",
    )
    serve_parser.add_argument(
        "--host", type=str, default="127.0.0.1",
        help="监听地址 Listen address (默认 default: 127.0.0.1)",
    )
    serve_parser.add_argument(
        "--port", type=int, default=8787,
        help="监听端口 Port (默认 default: 8787)",
    )
    serve_parser.add_argument(
        "--token", type=str, default=None, metavar="TOKEN|auto",
        help="Bearer token 认证；auto = 随机生成 Bearer auth. "
             "'auto' generates a random token",
    )
    serve_parser.add_argument(
        "--ready-file", type=str, default=None, metavar="PATH",
        help="监听成功后写入 {port, token, pid} 握手文件（供宿主 agent 读取）"
             "Write a handshake JSON for host agents",
    )
    serve_parser.add_argument(
        "--config", type=str, default=None,
        help="配置文件路径 Config file path",
    )

    parsed = parser.parse_args(args)

    if not parsed.command:
        parser.print_help()
        return 1

    # ── Handle 'watch' command ──────────────────────────────────────────────
    if parsed.command == "watch":
        from .watcher import start_watching

        watch_dir = parsed.directory
        if not os.path.isdir(watch_dir):
            print(f"❌ 目录不存在 Directory not found: {watch_dir}")
            return 1

        w, h = _parse_dimensions(parsed.resize) if parsed.resize else (None, None)
        options = ProcessOptions(
            quality=parsed.quality,
            output_format=parsed.format,
            output_dir=parsed.output_dir,
            max_width=w, max_height=h,
            remove_original=getattr(parsed, 'remove_original', False),
        )
        start_watching(watch_dir, options, recursive=parsed.recursive)
        return 0

    # ── Handle 'dedup' command ──────────────────────────────────────────────
    if parsed.command == "dedup":
        from .dedup import find_duplicates, handle_duplicates

        files = _collect_files(parsed.paths, recursive=parsed.recursive)
        if not files:
            print("❌ 没有找到支持的图片文件。No supported image files found.")
            return 1

        dedup_json = getattr(parsed, 'json', False)
        print(f"🔍 正在扫描 {len(files)} 个文件 Scanning...", file=sys.stderr)
        print(file=sys.stderr)

        def progress_cb(current, total):
            print(f"  计算哈希 Hashing: [{current}/{total}]", end="\r",
                  file=sys.stderr)

        dup_groups = find_duplicates(files, threshold=parsed.threshold,
                                     progress_callback=progress_cb)
        print(file=sys.stderr)

        total_dupes = sum(len(paths) - 1 for paths in dup_groups.values())
        savings = sum(os.path.getsize(p)
                      for g in dup_groups.values() for p in g[1:])

        if dedup_json:
            import json
            print(json.dumps({
                "count": len(dup_groups),
                "duplicate_count": total_dupes,
                "savings_bytes": savings,
                "groups": [{"hash": h, "paths": ps}
                           for h, ps in dup_groups.items()],
            }, indent=2, ensure_ascii=False))
        else:
            if not dup_groups:
                print("✅ 未发现重复图片。No duplicates found.")
            else:
                print(f"📊 发现 {len(dup_groups)} 组重复 Found duplicate groups:")
                print()
                for i, (h, paths) in enumerate(dup_groups.items(), 1):
                    print(f"  组 #{i}: {len(paths)} 个文件 files")
                    for p in paths:
                        print(f"    {'⭐' if p == paths[0] else '📎'} {p} "
                              f"({format_size(os.path.getsize(p))})")
                    print()
                print(f"共 {total_dupes} 个重复文件 duplicate files, "
                      f"可节省 {savings:,} 字节")

        if parsed.action in ("move", "delete", "keep-sharpest"):
            if parsed.dry_run:
                print()
                print("🔍 预览模式 Dry run — 不会实际操作 no files will be changed")
            elif not dedup_json:
                # JSON callers have no stdin; requesting the action explicitly
                # IS the confirmation (same rule as --remove-original --json).
                verb = ("保留最清晰并移动其余" if parsed.action == "keep-sharpest"
                        else ("移动" if parsed.action == "move" else "删除"))
                confirm = input(f"\n⚠️  即将{verb} {total_dupes} 个文件. 确认? [y/N]: "
                                ).strip().lower()
                if confirm not in ("y", "yes"):
                    print("已取消 Cancelled.")
                    return 0

            kept, removed = handle_duplicates(dup_groups, action=parsed.action,
                                              dry_run=parsed.dry_run)
            if dedup_json:
                print(json.dumps({"action": parsed.action, "kept": kept,
                                  "removed": removed},
                                 indent=2, ensure_ascii=False))
            else:
                action_verb = {
                    "move": "移动 moved",
                    "delete": "删除 deleted",
                    "keep-sharpest": "保留最清晰并移除",
                }[parsed.action]
                if parsed.dry_run:
                    print(f"将{action_verb} {removed} 个文件, 保留 {kept} 个")
                else:
                    print(f"已{action_verb} {removed} files, 保留 kept {kept}")

        # report mode: exit 1 when duplicates were found — agents can branch on
        # the exit code, consistent with `check` (1 = problems found)
        if parsed.action == "report":
            return 0 if not dup_groups else 1
        return 0

    # ── Handle 'preset' command ─────────────────────────────────────────────
    if parsed.command == "preset":
        from .presets import save_preset, load_preset, list_presets, delete_preset

        if parsed.preset_action == "save":
            w, h = _parse_dimensions(parsed.resize) if parsed.resize else (None, None)
            opts = ProcessOptions(
                quality=parsed.quality,
                output_format=parsed.format,
                max_width=w, max_height=h,
                suffix=parsed.suffix,
            )
            save_preset(parsed.name, opts, parsed.desc)
            print(f"✅ 预设已保存 Preset saved: {parsed.name}")

        elif parsed.preset_action == "list":
            presets = list_presets()
            if presets:
                print("📋 可用预设 Available presets:")
                for p in presets:
                    print(f"   {p}")
            else:
                print("📋 暂无预设 No presets saved yet.")

        elif parsed.preset_action == "load":
            opts = load_preset(parsed.name)
            if opts:
                print(f"📋 预设 Preset '{parsed.name}':")
                print(f"   photo-s batch <files> -f {opts.output_format} -q {opts.quality}", end="")
                if opts.max_width or opts.max_height:
                    print(f" --resize {opts.max_width or ''}x{opts.max_height or ''}", end="")
                print(f" --suffix {opts.suffix}")
            else:
                print(f"❌ 预设不存在 Preset not found: {parsed.name}")
                return 1

        elif parsed.preset_action == "delete":
            if delete_preset(parsed.name):
                print(f"✅ 预设已删除 Preset deleted: {parsed.name}")
            else:
                print(f"❌ 预设不存在 Preset not found: {parsed.name}")
                return 1

        else:
            preset_parser.print_help()
            return 1

        return 0

    # ── Handle 'plugin' command ──────────────────────────────────────────────
    if parsed.command == "plugin":
        from .plugincmd import run as _plugin_run
        return _plugin_run(parsed)

    # ── Handle 'exif' command ────────────────────────────────────────────────
    if parsed.command == "exif":
        from .engine import apply_exif_tags, read_exif_metadata
        exif_json = getattr(parsed, 'json', False)

        _TAG_FLAGS = [("artist", "artist"), ("copyright", "copyright"),
                      ("description", "description"), ("caption", "caption"),
                      ("title", "title"), ("date", "date"),
                      ("software", "software"), ("rating", "rating"),
                      ("keywords", "keywords")]

        def _apply_batch_meta(rows, source):
            """Write metadata for a list of {path, tag...} dicts."""
            tags_cols = [n for _, n in _TAG_FLAGS]
            done = 0
            for row in rows:
                p = (row.get("path") or "").strip()
                if not p:
                    continue
                if not os.path.isabs(p):
                    p = os.path.abspath(p)
                tags = {k: row.get(k) for k in tags_cols
                        if row.get(k) not in (None, "")}
                if not tags:
                    continue
                apply_exif_tags(p, tags)
                done += 1
            return done

        # ── Batch import from CSV / JSON (paths come from the file) ──
        if getattr(parsed, 'from_csv', None):
            import csv
            with open(parsed.from_csv, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            done = _apply_batch_meta(rows, parsed.from_csv)
            print(f"✅ 已从CSV写入元数据 Written from CSV: {done} 个文件 files")
            return 0
        if getattr(parsed, 'from_json', None):
            import json
            rows = json.loads(Path(parsed.from_json).read_text(encoding="utf-8"))
            if not isinstance(rows, list):
                rows = [rows]
            done = _apply_batch_meta(rows, parsed.from_json)
            print(f"✅ 已从JSON写入元数据 Written from JSON: {done} 个文件 files")
            return 0

        # ── Read / filter mode ──
        if getattr(parsed, 'show', False):
            files = _collect_files(parsed.files,
                                   recursive=getattr(parsed, 'recursive', False))
            if not files:
                print("❌ 没有找到支持的图片文件。No supported image files found.")
                return 1

            rating_min = parsed.rating_min
            rating_exact = parsed.rating          # --rating = exact filter in --show
            kw_wanted = {k.strip() for k in (parsed.keywords or "").split(",")
                         if k.strip()}
            camera = (parsed.camera or "").lower()
            d_from, d_to = parsed.date_from, parsed.date_to

            results = []
            for f in files:
                m = read_exif_metadata(f)
                if rating_min is not None and (m["rating"] or 0) < rating_min:
                    continue
                if rating_exact is not None and m["rating"] != rating_exact:
                    continue
                if kw_wanted and not (kw_wanted & set(m["keywords"])):
                    continue
                if camera and camera not in (m["camera"] or "").lower():
                    continue
                if d_from and m["date"] and m["date"] < d_from:
                    continue
                if d_to and m["date"] and m["date"] > d_to:
                    continue
                results.append({"path": f, **m})

            if getattr(parsed, 'list', False):
                for r in results:
                    print(r["path"])
            elif exif_json:
                import json
                print(json.dumps({"count": len(results), "results": results},
                                 indent=2, ensure_ascii=False))
            else:
                for r in results:
                    print(f"  {r['path']}")
                    print(f"     日期 date: {r['date']} {r['time']}"
                          f" | 相机 camera: {r['camera'] or '-'}"
                          f" | ISO: {r['iso'] or '-'} | 焦距 focal: {r['focal'] or '-'}")
                    print(f"     星级 rating: {r['rating']}"
                          f" | 关键词 keywords: {', '.join(r['keywords']) or '-'}"
                          f" | 标题 title: {r['title'] or '-'}"
                          f" | 图注 caption: {r['caption'] or '-'}")
            return 0

        # ── Write mode: collect tags from flags ──
        tags = {}
        for flag, name in _TAG_FLAGS:
            val = getattr(parsed, flag, None)
            if val is not None:
                tags[name] = val

        if getattr(parsed, 'date_from_mtime', False):
            # reverse sync: DateTimeOriginal ← file mtime (per file)
            for f in _collect_files(parsed.files,
                                    recursive=getattr(parsed, 'recursive', False)):
                try:
                    ts = os.path.getmtime(f)
                except OSError:
                    continue
                dt = datetime.fromtimestamp(ts)
                apply_exif_tags(f, {"date": dt.strftime("%Y:%m:%d %H:%M:%S")})
            print("✅ 已用文件修改时间写入拍摄日期 DateTimeOriginal ← mtime")
            return 0

        if not tags:
            print("❌ 请指定至少一个EXIF标签，或 --show 读取。"
                  "Specify at least one EXIF tag, or --show to read.")
            return 1

        files = _collect_files(parsed.files,
                               recursive=getattr(parsed, 'recursive', False))
        if not files:
            print("❌ 没有找到支持的图片文件。No supported image files found.")
            return 1

        print(f"📝 编辑EXIF标签 Editing EXIF tags on {len(files)} file(s)...")
        for tag, val in tags.items():
            print(f"   {tag}: {val}")
        print()

        for f in files:
            msg = apply_exif_tags(f, tags)
            print(f"  {os.path.basename(f)}: {msg}")

        print("\n✅ EXIF编辑完成 EXIF editing done.")
        return 0

    # ── Handle 'info' command ────────────────────────────────────────────────
    if parsed.command == "info":
        from .engine import _HAS_PILLOW_HEIF
        if getattr(parsed, 'json', False):
            import json
            print(json.dumps({
                "version": __version__,
                "input_extensions": sorted(ALL_INPUT_EXTENSIONS),
                "formats": sorted(SUPPORTED_FORMATS),
                "writable": sorted(PIL_WRITABLE),
            }, indent=2, ensure_ascii=False))
            return 0
        print("PhotoS — 支持的图片格式 Supported Formats")
        print("=" * 50)
        print()
        print("输入格式 Input (可读取 can read):")
        for ext in sorted(ALL_INPUT_EXTENSIONS):
            print(f"  {ext}")
        print()
        print("输出格式 Output (可写入 can write):")
        for fmt, info in SUPPORTED_FORMATS.items():
            if fmt in PIL_WRITABLE:
                pil = "✅"
            elif fmt == "HEIC":
                pil = "🔄 (via sips, macOS only)"
            else:
                pil = "❌"
            print(f"  {fmt}  {info['ext']}  {pil}")
        if not _HAS_PILLOW_HEIF:
            print()
            print("💡 提示: 安装 pillow-heif 可获得跨平台 HEIC 支持")
            print("   pip install pillow-heif")
        return 0

    # ── Handle 'config' command ─────────────────────────────────────────────
    if parsed.command == "config":
        from .config import (find_config, load_config, default_config_text,
                             save_config, apply_config)
        if parsed.config_action == "init":
            path = parsed.path or "photo-s.toml"
            save_config(path, default_config_text())
            print(f"✅ 已创建配置文件 Created config file: {os.path.abspath(path)}")
            print("   在此文件设置默认值, 之后用 --config 指定或放在工作目录自动生效")
            return 0
        elif parsed.config_action == "show":
            path = parsed.path or find_config()
            if not path:
                print("⚠️  未找到配置文件。No config file found.")
                print("   用 `photo-s config init` 创建 Create with `photo-s config init`")
                return 0
            cfg = load_config(path)
            apply_config(cfg, ProcessOptions())
            print(f"📋 配置文件 Config file: {path}")
            opts_dict = cfg.get("options", {})
            if not opts_dict:
                print("   (无自定义选项 no custom options)")
            for key, value in opts_dict.items():
                print(f"   {key} = {value}")
            return 0
        else:
            config_parser.print_help()
            return 1

    # ── Handle 'serve' command ──────────────────────────────────────────────
    if parsed.command == "serve":
        from .server import run_server, generate_token
        base_options = ProcessOptions()
        if parsed.config:
            from .config import load_config, apply_config
            cfg = load_config(parsed.config)
            base_options = apply_config(cfg, base_options)
        token = parsed.token
        if token == "auto":
            token = generate_token()
            print(f"🔐 已生成 token Generated: {token}", file=sys.stderr)
        run_server(parsed.host, parsed.port, options=base_options,
                   token=token, ready_file=parsed.ready_file)
        return 0

    # ── Handle 'rename' command ─────────────────────────────────────────────
    if parsed.command == "rename":
        from .rename import rename_files

        files = _collect_files(parsed.files, recursive=parsed.recursive)
        if not files:
            print("❌ 没有找到支持的图片文件。No supported image files found.")
            return 1

        rename_json = getattr(parsed, 'json', False)
        if rename_json:
            pass  # machine output only — no human preamble on stdout
        elif parsed.dry_run:
            print("🔍 预览模式 Dry Run — 不会改动任何文件 (no files will be changed)")
        elif parsed.output_dir:
            print(f"📁 将复制到 Copy to: {parsed.output_dir}")
        else:
            print("📝 将就地改名 Renaming in place")
        if not rename_json:
            print()

        results = rename_files(
            files, parsed.pattern,
            output_dir=parsed.output_dir,
            overwrite=parsed.overwrite,
            dry_run=parsed.dry_run,
        )
        ok = sum(1 for r in results if r["status"] == "ok")
        if rename_json:
            import json
            print(json.dumps({"total": len(results), "ok": ok,
                              "results": results},
                             indent=2, ensure_ascii=False))
        else:
            for r in results:
                extra = f": {r['error']}" if r["error"] else ""
                print(f"  {'→' if r['status'] == 'ok' else '❌'} "
                      f"{os.path.basename(r['input'])} → "
                      f"{os.path.basename(r['output'])}{extra}")
            print()
            print(f"📊 成功 {ok}/{len(results)} files")
            if not parsed.dry_run and not parsed.output_dir:
                print("   （注意: 就地改名会替换原文件名 in-place rename replaces the original name）")
        return 0 if ok == len(results) else 1

    # ── Handle 'check' command ──────────────────────────────────────────────
    if parsed.command == "check":
        from .check import verify_images

        files = _collect_files(parsed.files, recursive=parsed.recursive)
        if not files:
            print("❌ 没有找到支持的图片文件。No supported image files found.")
            return 1

        results = verify_images(files)
        corrupt = [r for r in results if not r["ok"]]

        if parsed.json:
            import json
            print(json.dumps({
                "checked": len(results),
                "ok": len(results) - len(corrupt),
                "corrupt": [{"path": r["path"], "error": r["error"]}
                            for r in corrupt],
            }, indent=2, ensure_ascii=False))
        else:
            for r in results:
                mark = "✅" if r["ok"] else "❌"
                extra = "" if r["ok"] else f" — {r['error']}"
                print(f"  {mark} {r['path']}{extra}")
            print(f"\n📊 检查完成 Checked {len(results)} 个文件 files, "
                  f"{len(corrupt)} 个损坏 corrupt")

        return 0 if not corrupt else 1

    # ── Handle 'contact-sheet' command ──────────────────────────────────────
    if parsed.command == "contact-sheet":
        from .contact import build_contact_sheet
        from .adjust import hex_to_rgb

        files = _collect_files(parsed.files, recursive=parsed.recursive)
        if not files:
            print("❌ 没有找到支持的图片文件。No supported image files found.")
            return 1

        tw, th = _parse_dimensions(parsed.thumb) if parsed.thumb else (240, 240)
        try:
            bg = hex_to_rgb(parsed.bg)
        except ValueError:
            bg = (0, 0, 0)
        out = build_contact_sheet(
            files, parsed.output, cols=parsed.cols,
            thumb_size=(tw or 240, th or 240),
            captions=parsed.caption, bg=bg,
        )
        if getattr(parsed, 'json', False):
            import json
            print(json.dumps({"output": out, "count": len(files)},
                             indent=2, ensure_ascii=False))
        else:
            print(f"✅ 已生成 Generated contact sheet: {out}  ({len(files)} 张 images)")
        return 0

    # ── Handle 'cull' command ───────────────────────────────────────────────
    if parsed.command == "cull":
        from .metrics import compute_exposure_stats, compute_blur_score
        files = _collect_files(parsed.paths, recursive=parsed.recursive)
        if not files:
            print("❌ 没有找到支持的图片文件。No supported image files found.")
            return 1

        results = []
        for f in files:
            s = compute_exposure_stats(f)
            row = {"path": f, **s}
            if parsed.sharpness_min is not None:
                row["blur_score"] = round(compute_blur_score(f), 1)
            keep = (s["ok"]
                    and (parsed.overexposed_max is None
                         or s["overexposed_pct"] <= parsed.overexposed_max)
                    and (parsed.underexposed_max is None
                         or s["underexposed_pct"] <= parsed.underexposed_max)
                    and (parsed.luminance_min is None
                         or s["luminance"] >= parsed.luminance_min)
                    and (parsed.luminance_max is None
                         or s["luminance"] <= parsed.luminance_max)
                    and (parsed.sharpness_min is None
                         or row["blur_score"] >= parsed.sharpness_min))
            row["kept"] = keep
            results.append(row)

        kept_paths = [r["path"] for r in results if r["kept"]]
        if getattr(parsed, 'list', False):
            for p in kept_paths:
                print(p)
        elif getattr(parsed, 'json', False):
            import json
            print(json.dumps({"count": len(results), "kept": len(kept_paths),
                              "results": results},
                             indent=2, ensure_ascii=False))
        else:
            for r in results:
                mark = "✅" if r["kept"] else "❌"
                extra = (f"  sharp={r['blur_score']}"
                         if "blur_score" in r else "")
                print(f"  {mark} {r['path']}  lum={r['luminance']} "
                      f"over={r['overexposed_pct']}% "
                      f"under={r['underexposed_pct']}%{extra}")
            print(f"\n📊 通过 Kept: {len(kept_paths)}/{len(results)}")
        return 0

    # ── Handle 'hash' command ───────────────────────────────────────────────
    if parsed.command == "hash":
        from .check import compute_checksums, write_manifest, verify_manifest
        import json

        if parsed.verify:
            report = verify_manifest(parsed.verify)
            if parsed.json:
                print(json.dumps(report, indent=2, ensure_ascii=False))
            else:
                print(f"清单 Manifest: {parsed.verify}  ({report['algorithm']})")
                print(f"  共 {report['total']} 项, 一致 OK: {report['ok']}")
                if report["missing"]:
                    print(f"  ❌ 缺失 Missing ({len(report['missing'])}):")
                    for p in report["missing"]:
                        print(f"    {p}")
                if report["mismatched"]:
                    print(f"  ⚠️  不匹配 Mismatched ({len(report['mismatched'])}):")
                    for m in report["mismatched"]:
                        print(f"    {m['path']}")
                        print(f"     期望 expected: {m['expected']}")
                        print(f"     实际 actual:   {m['actual']}")
            return 0 if (not report["missing"] and not report["mismatched"]) else 1

        # Hash every file (not just images — for archives)
        files = []
        for pat in parsed.paths:
            p = Path(pat)
            if p.is_dir():
                if parsed.recursive:
                    files.extend(str(x) for x in p.rglob("*") if x.is_file())
                else:
                    files.extend(str(x) for x in p.iterdir() if x.is_file())
            elif p.is_file():
                files.append(str(p.absolute()))
            else:
                files.extend(m for m in glob.glob(pat) if os.path.isfile(m))
        files = sorted(set(files))
        if not files:
            print("❌ 没有找到文件。No files found.")
            return 1

        print(f"🔍 计算哈希 Hashing {len(files)} 个文件...", file=sys.stderr)
        entries = compute_checksums(files)
        out = parsed.output or "manifest.csv"
        write_manifest(out, entries)
        if parsed.json:
            print(json.dumps({"output": os.path.abspath(out),
                              "count": len(files)}, indent=2, ensure_ascii=False))
        else:
            print(f"✅ 清单已写入 Written manifest: {os.path.abspath(out)} "
                  f"({len(files)} 项)")
        return 0

    # ── Handle 'gallery' command ────────────────────────────────────────────
    if parsed.command == "gallery":
        from .gallery import build_gallery
        files = _collect_files(parsed.paths, recursive=parsed.recursive)
        if not files:
            print("❌ 没有找到支持的图片文件。No supported image files found.")
            return 1
        res = build_gallery(files, parsed.output, title=parsed.title,
                            thumb_size=parsed.thumb)
        if getattr(parsed, 'json', False):
            import json
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            print(f"✅ 已生成 Gallery: {res['output']}  ({res['count']} 张 images)")
        return 0

    # ── Build options from parsed args ──────────────────────────────────────
    # Parse target size if provided
    target_size_bytes = None
    target_size_str = getattr(parsed, 'target_size', None)
    if target_size_str:
        target_size_bytes = _parse_size(target_size_str)

    options = ProcessOptions(
        quality=getattr(parsed, 'quality', 85),
        output_format=getattr(parsed, 'format', 'JPEG'),
        output_dir=getattr(parsed, 'output_dir', None),
        preserve_exif=not getattr(parsed, 'no_exif', False),
        optimize=not getattr(parsed, 'no_optimize', False),
        progressive=getattr(parsed, 'progressive', False),
        overwrite=getattr(parsed, 'overwrite', False),
        prefix=getattr(parsed, 'prefix', ''),
        suffix=getattr(parsed, 'suffix', None),  # resolved per-command below
        target_size_bytes=target_size_bytes,
        raw_half_size=getattr(parsed, 'raw_half_size', False),
        raw_auto_bright=not getattr(parsed, 'raw_no_auto_bright', False),
        auto_rotate=not getattr(parsed, 'no_auto_rotate', False),
        remove_original=getattr(parsed, 'remove_original', False),
        rename_pattern=getattr(parsed, 'rename', None) or "",
        folder_pattern=_resolve_folder_pattern(getattr(parsed, 'organize', None) or ""),
        watermark_text=getattr(parsed, 'watermark_text', None) or "",
        watermark_image=getattr(parsed, 'watermark_image', None) or "",
        watermark_position=getattr(parsed, 'watermark_pos', None) or "BOTTOM_RIGHT",
        watermark_opacity=getattr(parsed, 'watermark_opacity', 50),
        output_sizes=_parse_sizes(getattr(parsed, 'sizes', None)),
        strip_gps=getattr(parsed, 'strip_gps', False),
        keep_mtime=getattr(parsed, 'keep_mtime', False),
        max_pixels=getattr(parsed, 'max_pixels', None),
        evaluate=getattr(parsed, 'evaluate', False),
        brightness=getattr(parsed, 'brightness', 1.0),
        contrast=getattr(parsed, 'contrast', 1.0),
        saturation=getattr(parsed, 'saturation', 1.0),
        gamma=getattr(parsed, 'gamma', 1.0),
        sharpen=getattr(parsed, 'sharpen', 1.0),
        grayscale=getattr(parsed, 'grayscale', False),
        sepia=getattr(parsed, 'sepia', False),
        auto_levels=getattr(parsed, 'auto_levels', False),
        wb_temp=getattr(parsed, 'wb', None),
        wb_reference=getattr(parsed, 'wb_from', None),
        ev=getattr(parsed, 'ev', None),
        auto_exposure=getattr(parsed, 'auto_exposure', None),
        log_curve=getattr(parsed, 'log_curve', None),
        denoise=getattr(parsed, 'denoise', None),
        auto_straighten=getattr(parsed, 'auto_straighten', False),
        max_straighten_angle=getattr(parsed, 'max_straighten_angle', 10.0),
        print_size=getattr(parsed, 'print_size', None),
        crop=getattr(parsed, 'crop', None),
        crop_ratio=getattr(parsed, 'crop_ratio', None),
        rotate_degrees=float(getattr(parsed, 'rotate', 0) or 0),
        rotate_bg=getattr(parsed, 'rotate_bg', None),
        flip=getattr(parsed, 'flip', None),
        pad_ratio=getattr(parsed, 'pad', None),
        pad_bg=getattr(parsed, 'pad_bg', None) or "#000000",
        date_shift=getattr(parsed, 'date_shift', None),
        scrub=getattr(parsed, 'scrub', False),
        sync_date=getattr(parsed, 'sync_date', False),
        blur_score=getattr(parsed, 'blur_score', False),
        srgb=getattr(parsed, 'srgb', False),
        flatten_cmyk=getattr(parsed, 'flatten_cmyk', False),
        resume=getattr(parsed, 'resume', False),
        gpx_trace=getattr(parsed, 'gpx_trace', None),
        jobs=getattr(parsed, 'jobs', 1),
    )

    # Handle --resize
    resize_str = getattr(parsed, 'resize', None)
    if resize_str:
        w, h = _parse_dimensions(resize_str)
        options.max_width = w
        options.max_height = h

    # Handle --scale
    options.scale_percent = getattr(parsed, 'scale', None)

    # Fix suffix for 'compress' command
    if parsed.command == "compress":
        if not getattr(parsed, 'suffix', None) or parsed.suffix == '_processed':
            options.suffix = "_compressed"
    elif parsed.command == "convert":
        options.suffix = getattr(parsed, 'suffix', '')
        options.output_format = getattr(parsed, 'format', 'JPEG')
    else:  # batch
        options.suffix = getattr(parsed, 'suffix', None) or "_processed"

    # ── Apply config file defaults (explicit CLI args take precedence) ──────
    config_path = getattr(parsed, "config", None)
    explicit_config = config_path is not None
    if config_path is None:
        from .config import find_config
        config_path = find_config()
    if config_path:
        try:
            from .config import load_config
            cfg = load_config(config_path)
            _apply_config_defaults(options, parsed, cfg)
        except Exception as e:
            if explicit_config:
                print(f"❌ 配置文件加载失败 Config load error: {e}")
                return 1
            print(f"⚠️  配置文件加载失败 Config load error: {e}", file=sys.stderr)

    # ── Collect files ───────────────────────────────────────────────────────
    file_patterns = getattr(parsed, 'files', None) or getattr(parsed, 'paths', [])
    recursive = getattr(parsed, 'recursive', False)
    files = _collect_files(file_patterns, recursive=recursive)

    if not files:
        print("❌ 没有找到支持的图片文件。No supported image files found.")
        return 1

    is_json = getattr(parsed, 'json', False)
    jout = sys.stderr if is_json else sys.stdout

    print(f"📁 找到 Found {len(files)} 个图片文件 image file(s):", file=jout)
    for f in files:
        sz = format_size(os.path.getsize(f))
        print(f"    {f} ({sz})", file=jout)
    print(file=jout)

    # ── Dry run ─────────────────────────────────────────────────────────────
    if getattr(parsed, 'dry_run', False):
        if is_json:
            import json
            print(json.dumps({
                "dry_run": True,
                "count": len(files),
                "files": files,
                "settings": {
                    "output_format": options.output_format,
                    "quality": options.quality,
                    "target_size": (format_size(options.target_size_bytes)
                                    if options.target_size_bytes else None),
                    "max_width": options.max_width,
                    "max_height": options.max_height,
                    "scale_percent": options.scale_percent,
                    "preserve_exif": options.preserve_exif,
                    "optimize": options.optimize,
                    "output_dir": options.output_dir,
                    "folder_pattern": options.folder_pattern,
                },
            }, indent=2, ensure_ascii=False))
            return 0
        print("🔍 预览模式 Dry Run — 不会实际处理文件 (no files will be modified)")
        print()
        print("将应用的设置 Settings that would be applied:")
        print(f"  目标格式 Target format: {options.output_format}")
        if options.target_size_bytes:
            print(f"  目标体积 Target size:   {format_size(options.target_size_bytes)} (自动调优 auto-tune)")
            print(f"  质量上限 Quality max:   {options.quality} (上限 ceiling)")
        else:
            print(f"  质量 Quality:          {options.quality}")
        if options.max_width or options.max_height:
            print(f"  缩放 Resize:           {options.max_width or 'auto'}×{options.max_height or 'auto'}")
        if options.scale_percent:
            print(f"  缩放 Scale:            {options.scale_percent}%")
        print(f"  保留EXIF EXIF:         {'是 Yes' if options.preserve_exif else '否 No'}")
        print(f"  优化 Optimize:         {'是 Yes' if options.optimize else '否 No'}")
        print(f"  输出目录 Output dir:   {options.output_dir or '(与源文件相同 same as source)'}")
        if options.folder_pattern:
            print(f"  子文件夹 Subfolder:     {options.folder_pattern}")
        return 0

    def progress_callback(current, total, path):
        if path:
            name = os.path.basename(path)
            print(f"  [{current+1}/{total}] 处理中 {name}...", end="\r", file=jout)
        else:
            print(f"  [{total}/{total}] 完成 Done!" + " " * 20, file=jout)

    # ── Safety check for --remove-original ──────────────────────────────────
    # In --json mode the caller is an agent with no stdin to confirm against;
    # passing --remove-original explicitly IS the confirmation, so skip the
    # prompt (otherwise input() hangs forever on a closed stdin).
    if (options.remove_original and not getattr(parsed, 'yes', False)
            and not is_json):
        print(f"⚠️  警告: 将删除 {len(files)} 个原始文件！")
        print(f"   Warning: {len(files)} original file(s) will be deleted!")
        confirm = input("   确认继续? Confirm? [y/N]: ").strip().lower()
        if confirm not in ("y", "yes"):
            print("   已取消 Cancelled.")
            return 0

    # ── Multi-profile batch run (--profiles web,thumb) ──────────────────────
    if getattr(parsed, 'profiles', None):
        from .presets import load_preset
        from dataclasses import asdict, replace

        names = [n.strip() for n in parsed.profiles.split(",") if n.strip()]
        if not names:
            print("❌ --profiles 需要至少一个预设名 Need at least one preset name")
            return 1

        if getattr(parsed, 'report', None):
            print("⚠️  --report 与 --profiles 不能同时使用; 已跳过 report "
                  "(skipped, incompatible with --profiles)", file=sys.stderr)

        profile_results = {}
        failed_total = 0
        for name in names:
            base = load_preset(name)
            if base is None:
                print(f"❌ 预设不存在 Preset not found: {name}")
                return 1
            # Preset values win over CLI/config EXCEPT output_dir/suffix
            # (presets serialize stale directories — those come from CLI/config)
            fields = {k: v for k, v in asdict(base).items()
                      if k in ProcessOptions.__dataclass_fields__
                      and k not in ("output_dir", "suffix")}
            prof_opts = replace(options, **fields)
            prof_result = batch_process(files, prof_opts,
                                        progress_callback=progress_callback)
            profile_results[name] = prof_result
            failed_total += prof_result.fail_count
            if not is_json:
                print(f"\n📦 预设 Profile: {name}  ({len(files)} files)")
                _print_batch_summary(prof_result)

        if is_json:
            import json
            print(json.dumps(
                {"profiles": {n: r.to_dict() for n, r in profile_results.items()}},
                indent=2, ensure_ascii=False))
        return 0 if failed_total == 0 else 1

    # ── Execute ──────────────────────────────────────────────────────────────
    if not is_json:
        print("🚀 开始处理 Processing...")
        if options.target_size_bytes:
            lossy_fmts = {"JPEG", "WebP", "HEIC"}
            if options.output_format not in lossy_fmts:
                print(f"⚠️  注意: {options.output_format} 是无损/弱压缩格式，目标体积控制效果有限。")
                print(f"   Note: {options.output_format} is lossless/weakly-compressed, "
                      f"target size control is limited.")
            print(f"🎯 目标体积 Target: ≤ {format_size(options.target_size_bytes)}")
            print(f"   质量范围 Quality range: 5–{options.quality}")
        print()

    result = batch_process(files, options, progress_callback=progress_callback)

    # ── Write CSV report if requested ───────────────────────────────────────
    if getattr(parsed, 'report', None):
        from .engine import _write_report
        try:
            _write_report(parsed.report, result)
        except OSError as e:
            print(f"❌ 报告写入失败 Report write error: {e}", file=sys.stderr)

    # ── Print results ───────────────────────────────────────────────────────
    if is_json:
        import json
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    else:
        print()
        for r in result.results:
            _print_result(r)
            print()
        _print_batch_summary(result)

    return 0 if result.fail_count == 0 else 1


def main():
    """Entry point for the photo-s command.

    Dispatches to GUI if no args are given or first arg is 'gui',
    otherwise runs CLI mode.
    """
    if len(sys.argv) <= 1:
        from .gui import run_gui
        run_gui()
        return 0
    if sys.argv[1] == "gui":
        from .gui import run_gui
        run_gui()
        return 0
    return run_cli(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
