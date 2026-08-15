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
    auto_jobs,
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
from .i18n import _t  # reads i18n.CURRENT_LANG at call time; set in run_cli
from .contract import versioned  # additive schema_version on every --json output


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
            _t("val_size", val=size_str, supported="500, 500KB, 2MB, 1.5MB")
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
        help=_t('help___strip_gps'),
    )
    parser.add_argument(
        "--keep-mtime", action="store_true", default=argparse.SUPPRESS,
        help=_t('help___keep_mtime'),
    )
    parser.add_argument(
        "--max-pixels", type=int, default=argparse.SUPPRESS, metavar="N",
        help=_t('help___max_pixels'),
    )
    parser.add_argument(
        "--evaluate", action="store_true", default=argparse.SUPPRESS,
        help=_t('help___evaluate'),
    )
    parser.add_argument(
        "--resume", action="store_true", default=argparse.SUPPRESS,
        help=_t('help___resume'),
    )
    parser.add_argument(
        "--config", type=str, default=None, metavar="PATH",
        help=_t('help___config'),
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
            _t("val_format", fmt=fmt, formats=", ".join(sorted(SUPPORTED_FORMATS)))
        )
    return canonical


def _add_transform_args(parser):
    """Add shared transform options (tone, composition, metadata, quality).

    Config-capable args use default=argparse.SUPPRESS (see _add_advanced_args).
    """
    parser.add_argument(
        "--brightness", type=float, default=argparse.SUPPRESS,
        metavar="0-2", help=_t('help___brightness'),
    )
    parser.add_argument(
        "--contrast", type=float, default=argparse.SUPPRESS,
        metavar="0-2", help=_t('help___contrast'),
    )
    parser.add_argument(
        "--saturation", type=float, default=argparse.SUPPRESS,
        metavar="0-2", help=_t('help___saturation'),
    )
    parser.add_argument(
        "--gamma", type=float, default=argparse.SUPPRESS,
        metavar="0.1-3", help=_t('help___gamma'),
    )
    parser.add_argument(
        "--sharpen", type=float, default=argparse.SUPPRESS,
        metavar="0-3", help=_t('help___sharpen'),
    )
    parser.add_argument(
        "--grayscale", action="store_true", default=argparse.SUPPRESS,
        help=_t('help___grayscale'),
    )
    parser.add_argument(
        "--sepia", action="store_true", default=argparse.SUPPRESS,
        help=_t('help___sepia'),
    )
    parser.add_argument(
        "--auto-levels", action="store_true", default=argparse.SUPPRESS,
        help=_t('help___auto_levels'),
    )
    parser.add_argument(
        "--wb", type=float, default=argparse.SUPPRESS, metavar="KELVIN",
        help=_t('help___wb'),
    )
    parser.add_argument(
        "--wb-from", type=str, default=argparse.SUPPRESS, metavar="REF.jpg",
        help=_t('help___wb_from'),
    )
    parser.add_argument(
        "--ev", type=float, default=argparse.SUPPRESS, metavar="STOPS",
        help=_t('help___ev'),
    )
    parser.add_argument(
        "--auto-exposure", type=float, default=argparse.SUPPRESS, metavar="0-1",
        help=_t('help___auto_exposure'),
    )
    parser.add_argument(
        "--log-curve", type=str, default=argparse.SUPPRESS, metavar="NAME",
        choices=["SLOG3", "CLOG3", "LOGC3", "DLOG", "VLOG", "HLG"],
        help=_t('help___log_curve'),
    )
    parser.add_argument(
        "--denoise", type=float, default=argparse.SUPPRESS, metavar="N",
        help=_t('help___denoise'),
    )
    parser.add_argument(
        "--lut", type=str, default=argparse.SUPPRESS, metavar="FILE|PRESET",
        help=_t('help___lut'),
    )
    parser.add_argument(
        "--auto-straighten", action="store_true", default=argparse.SUPPRESS,
        help=_t('help___auto_straighten'),
    )
    parser.add_argument(
        "--max-straighten-angle", type=float, default=argparse.SUPPRESS,
        metavar="DEG",
        help=_t('help___max_straighten_angle'),
    )
    parser.add_argument(
        "--print-size", type=str, default=argparse.SUPPRESS, metavar="WxH@DPI",
        help=_t('help___print_size'),
    )
    parser.add_argument(
        "--crop", type=str, default=argparse.SUPPRESS, metavar="WxH+X+Y",
        help=_t('help___crop'),
    )
    parser.add_argument(
        "--crop-ratio", type=str, default=argparse.SUPPRESS, metavar="16:9",
        help=_t('help___crop_ratio'),
    )
    parser.add_argument(
        "--rotate", type=float, default=argparse.SUPPRESS, metavar="DEG",
        help=_t('help___rotate'),
    )
    parser.add_argument(
        "--rotate-bg", type=str, default=argparse.SUPPRESS, metavar="#RRGGBB",
        help=_t('help___rotate_bg'),
    )
    parser.add_argument(
        "--flip", type=str, default=argparse.SUPPRESS, choices=["h", "v"],
        help=_t('help___flip'),
    )
    parser.add_argument(
        "--pad", type=str, default=argparse.SUPPRESS, metavar="16:9",
        help=_t('help___pad'),
    )
    parser.add_argument(
        "--pad-bg", type=str, default=argparse.SUPPRESS, metavar="#RRGGBB",
        help=_t('help___pad_bg'),
    )
    parser.add_argument(
        "--date-shift", type=_date_shift_arg, default=argparse.SUPPRESS,
        metavar="OFFSET",
        help=_t('help___date_shift'),
    )
    parser.add_argument(
        "--scrub", action="store_true", default=argparse.SUPPRESS,
        help=_t('help___scrub'),
    )
    parser.add_argument(
        "--sync-date", action="store_true", default=argparse.SUPPRESS,
        help=_t('help___sync_date'),
    )
    parser.add_argument(
        "--srgb", action="store_true", default=argparse.SUPPRESS,
        help=_t('help___srgb'),
    )
    parser.add_argument(
        "--flatten-cmyk", action="store_true", default=argparse.SUPPRESS,
        help=_t('help___flatten_cmyk'),
    )
    parser.add_argument(
        "--blur-score", action="store_true", default=argparse.SUPPRESS,
        help=_t('help___blur_score'),
    )
    parser.add_argument(
        "--report", type=str, default=argparse.SUPPRESS, metavar="OUT.csv",
        help=_t('help___report'),
    )
    parser.add_argument(
        "--gpx-trace", type=str, default=argparse.SUPPRESS, metavar="TRACK.gpx",
        help=_t('help___gpx_trace'),
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
    from .config import _SIMPLE_FIELDS, _coerce_value
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
            setattr(options, field, _coerce_value(config_key, field,
                                                  opts[config_key]))

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
            print(f"     {_t('msg_quality')}: {result.achieved_quality}")
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
    print(f"📊 {_t('msg_summary')}")
    print(f"   {_t('msg_success')}: {result.success_count}")
    print(f"   {_t('msg_failed')}:  {result.fail_count}")
    print(f"   {_t('msg_total_original')}: {format_size(result.total_input_size)}")
    print(f"   {_t('msg_total_compressed')}: {format_size(result.total_output_size)}")
    savings = format_size(result.savings_bytes)
    print(f"   {_t('msg_saved')}: {savings} ({result.savings_percent:.1f}%)")
    print("─" * 60)


def _pre_parse_language(args):
    """Peek at --language/--lang and --config before the real parse.

    argparse bakes help= strings at parser-construction time, so the language
    must be resolved BEFORE the parser tree is built. A throwaway parser with
    ``parse_known_args`` tolerates the full real CLI, handles both
    ``--language zh`` and ``--language=zh``, and also surfaces ``--config`` so
    an explicit config file's ``language`` key takes effect.
    """
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--language", "--lang", default=None)
    p.add_argument("--config", default=None)
    try:
        ns, _ = p.parse_known_args(args)
        return ns.language, ns.config
    except SystemExit:
        return None, None


def run_cli(args: List[str] = None) -> int:
    """
    Parse CLI arguments and execute the requested operation.

    Returns exit code (0 = success, 1 = error).
    """
    if args is None:
        args = sys.argv[1:]

    # Resolve language first: all help= / message strings below are rendered
    # via i18n._t, which reads i18n.CURRENT_LANG at call time.
    lang_explicit, cfg_override = _pre_parse_language(args)
    from . import i18n
    i18n.CURRENT_LANG = i18n.resolve_language(
        explicit=lang_explicit, config_path=cfg_override,
        use_config=True, use_persisted=False)

    parser = argparse.ArgumentParser(
        prog="photo-s",
        description=_t("desc"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_t("epilog"),
    )
    parser.add_argument(
        "--json", action="store_true",
        help=_t("help___json"),
    )
    parser.add_argument(
        "--language", "--lang", choices=["en", "zh", "auto"],
        default="auto", help=_t("help___language"),
    )
    _version_str = f"photo-s {__version__}"
    if not _gui_module_available():
        # Lite build (no GUI module bundled) — mark it so bug reports can
        # tell the two editions apart.
        _version_str += " (lite)"
    parser.add_argument(
        "--version", action="version", version=_version_str,
        help=_t("help___version"),
    )

    subparsers = parser.add_subparsers(dest="command", help=_t("cmd_commands"))

    # ── compress subcommand ──────────────────────────────────────────────────
    compress_parser = subparsers.add_parser(
        "compress", help=_t('cmd_compress'),
    )
    compress_parser.add_argument(
        "files", nargs="+", help=_t('help___files'),
    )
    compress_parser.add_argument(
        "--json", action="store_true",
        help=_t('help___json'),
    )
    compress_parser.add_argument(
        "-q", "--quality", type=int, default=argparse.SUPPRESS,
        help=_t('help___quality'),
    )
    compress_parser.add_argument(
        "-o", "--output-dir", type=str, default=argparse.SUPPRESS,
        help=_t('help___output_dir'),
    )
    compress_parser.add_argument(
        "--suffix", type=str, default=argparse.SUPPRESS,
        help=_t('help___suffix'),
    )
    compress_parser.add_argument(
        "--no-exif", action="store_true",
        help=_t('help___no_exif'),
    )
    compress_parser.add_argument(
        "--resize", type=str, default=argparse.SUPPRESS, metavar="WxH",
        help=_t('help___resize'),
    )
    compress_parser.add_argument(
        "--scale", type=int, default=argparse.SUPPRESS, metavar="PCT",
        help=_t('help___scale'),
    )
    compress_parser.add_argument(
        "--dry-run", action="store_true",
        help=_t('help___dry_run'),
    )
    compress_parser.add_argument(
        "-r", "--recursive", action="store_true",
        help=_t('help___recursive'),
    )
    compress_parser.add_argument(
        "-j", "--jobs", type=int, default=argparse.SUPPRESS, metavar="N",
        help=_t('help___jobs'),
    )
    compress_parser.add_argument(
        "--target-size", type=str, default=argparse.SUPPRESS, metavar="SIZE",
        help=_t('help___target_size'),
    )
    compress_parser.add_argument(
        "--raw-half-size", action="store_true",
        help=_t('help___raw_half_size'),
    )
    compress_parser.add_argument(
        "--raw-no-auto-bright", action="store_true",
        help=_t('help___raw_no_auto_bright'),
    )
    compress_parser.add_argument(
        "--no-auto-rotate", action="store_true",
        help=_t('help___no_auto_rotate'),
    )
    compress_parser.add_argument(
        "--remove-original", action="store_true", default=argparse.SUPPRESS,
        help=_t('help___remove_original'),
    )
    compress_parser.add_argument(
        "-y", "--yes", action="store_true",
        help=_t('help___yes'),
    )
    compress_parser.add_argument(
        "--rename", type=str, default=argparse.SUPPRESS, metavar="PATTERN",
        help=_t('help___rename'),
    )
    compress_parser.add_argument(
        "--organize", type=str, default=argparse.SUPPRESS, metavar="PRESET|PATTERN",
        help=_t('help___organize'),
    )
    compress_parser.add_argument(
        "--sizes", type=str, default=None, metavar="LABEL:WxH,...",
        help=_t('help___sizes'),
    )
    compress_parser.add_argument(
        "--watermark-text", type=str, default=argparse.SUPPRESS, metavar="TEXT",
        help=_t('help___watermark_text'),
    )
    compress_parser.add_argument(
        "--watermark-pos", type=str, default=argparse.SUPPRESS,
        help=_t('help___watermark_pos'),
    )
    compress_parser.add_argument(
        "--watermark-opacity", type=int, default=argparse.SUPPRESS,
        help=_t('help___watermark_opacity'),
    )
    _add_advanced_args(compress_parser)
    _add_transform_args(compress_parser)

    # ── convert subcommand ───────────────────────────────────────────────────
    convert_parser = subparsers.add_parser(
        "convert", help=_t('cmd_convert'),
    )
    convert_parser.add_argument(
        "files", nargs="+", help=_t('help___files'),
    )
    convert_parser.add_argument(
        "--json", action="store_true",
        help=_t('help___json'),
    )
    convert_parser.add_argument(
        "-f", "--format", type=_format_arg, default=argparse.SUPPRESS,
        help=_t('help___format'),
    )
    convert_parser.add_argument(
        "-q", "--quality", type=int, default=argparse.SUPPRESS,
        help=_t('help___quality'),
    )
    convert_parser.add_argument(
        "-o", "--output-dir", type=str, default=argparse.SUPPRESS,
        help=_t('help___output_dir'),
    )
    convert_parser.add_argument(
        "--prefix", type=str, default=argparse.SUPPRESS,
        help=_t('help___prefix'),
    )
    convert_parser.add_argument(
        "--suffix", type=str, default=argparse.SUPPRESS,
        help=_t('help___suffix'),
    )
    convert_parser.add_argument(
        "--no-exif", action="store_true",
        help=_t('help___no_exif'),
    )
    convert_parser.add_argument(
        "--resize", type=str, default=argparse.SUPPRESS, metavar="WxH",
        help=_t('help___resize'),
    )
    convert_parser.add_argument(
        "--scale", type=int, default=argparse.SUPPRESS, metavar="PCT",
        help=_t('help___scale'),
    )
    convert_parser.add_argument(
        "--dry-run", action="store_true",
        help=_t('help___dry_run'),
    )
    convert_parser.add_argument(
        "-r", "--recursive", action="store_true",
        help=_t('help___recursive'),
    )
    convert_parser.add_argument(
        "--overwrite", action="store_true", default=argparse.SUPPRESS,
        help=_t('help___overwrite'),
    )
    convert_parser.add_argument(
        "--target-size", type=str, default=argparse.SUPPRESS, metavar="SIZE",
        help=_t('help___target_size'),
    )
    convert_parser.add_argument(
        "--raw-half-size", action="store_true",
        help=_t('help___raw_half_size'),
    )
    convert_parser.add_argument(
        "--raw-no-auto-bright", action="store_true",
        help=_t('help___raw_no_auto_bright'),
    )
    convert_parser.add_argument(
        "--no-auto-rotate", action="store_true",
        help=_t('help___no_auto_rotate'),
    )
    convert_parser.add_argument(
        "--remove-original", action="store_true", default=argparse.SUPPRESS,
        help=_t('help___remove_original'),
    )
    convert_parser.add_argument(
        "-y", "--yes", action="store_true",
        help=_t('help___yes'),
    )
    _add_advanced_args(convert_parser)
    _add_transform_args(convert_parser)

    # ── batch subcommand (combined) ──────────────────────────────────────────
    batch_parser = subparsers.add_parser(
        "batch", help=_t('cmd_batch'),
    )
    batch_parser.add_argument(
        "paths", nargs="+", help=_t('help___paths'),
    )
    batch_parser.add_argument(
        "--json", action="store_true",
        help=_t('help___json'),
    )
    batch_parser.add_argument(
        "-f", "--format", type=_format_arg, default=argparse.SUPPRESS,
        help=_t('help___format'),
    )
    batch_parser.add_argument(
        "-q", "--quality", type=int, default=argparse.SUPPRESS,
        help=_t('help___quality'),
    )
    batch_parser.add_argument(
        "-o", "--output-dir", type=str, default=argparse.SUPPRESS,
        help=_t('help___output_dir'),
    )
    batch_parser.add_argument(
        "--prefix", type=str, default=argparse.SUPPRESS,
        help=_t('help___prefix'),
    )
    batch_parser.add_argument(
        "--suffix", type=str, default=argparse.SUPPRESS,
        help=_t('help___suffix'),
    )
    batch_parser.add_argument(
        "--resize", type=str, default=argparse.SUPPRESS, metavar="WxH",
        help=_t('help___resize'),
    )
    batch_parser.add_argument(
        "--scale", type=int, default=argparse.SUPPRESS, metavar="PCT",
        help=_t('help___scale'),
    )
    batch_parser.add_argument(
        "--no-exif", action="store_true",
        help=_t('help___no_exif'),
    )
    batch_parser.add_argument(
        "--progressive", action="store_true", default=argparse.SUPPRESS,
        help=_t('help___progressive'),
    )
    batch_parser.add_argument(
        "--no-optimize", action="store_true",
        help=_t('help___no_optimize'),
    )
    batch_parser.add_argument(
        "-r", "--recursive", action="store_true",
        help=_t('help___recursive'),
    )
    batch_parser.add_argument(
        "-j", "--jobs", type=int, default=argparse.SUPPRESS, metavar="N",
        help=_t('help___jobs'),
    )
    batch_parser.add_argument(
        "--overwrite", action="store_true", default=argparse.SUPPRESS,
        help=_t('help___overwrite'),
    )
    batch_parser.add_argument(
        "--dry-run", action="store_true",
        help=_t('help___dry_run'),
    )
    batch_parser.add_argument(
        "--target-size", type=str, default=argparse.SUPPRESS, metavar="SIZE",
        help=_t('help___target_size'),
    )
    batch_parser.add_argument(
        "--raw-half-size", action="store_true",
        help=_t('help___raw_half_size'),
    )
    batch_parser.add_argument(
        "--raw-no-auto-bright", action="store_true",
        help=_t('help___raw_no_auto_bright'),
    )
    batch_parser.add_argument(
        "--no-auto-rotate", action="store_true",
        help=_t('help___no_auto_rotate'),
    )
    batch_parser.add_argument(
        "--remove-original", action="store_true", default=argparse.SUPPRESS,
        help=_t('help___remove_original'),
    )
    batch_parser.add_argument(
        "-y", "--yes", action="store_true",
        help=_t('help___yes'),
    )
    batch_parser.add_argument(
        "--rename", type=str, default=argparse.SUPPRESS, metavar="PATTERN",
        help=_t('help___rename'),
    )
    batch_parser.add_argument(
        "--organize", type=str, default=argparse.SUPPRESS, metavar="PRESET|PATTERN",
        help=_t('help___organize'),
    )
    batch_parser.add_argument(
        "--watermark-text", type=str, default=argparse.SUPPRESS, metavar="TEXT",
        help=_t('help___watermark_text'),
    )
    batch_parser.add_argument(
        "--watermark-image", type=str, default=argparse.SUPPRESS, metavar="PATH",
        help=_t('help___watermark_image'),
    )
    batch_parser.add_argument(
        "--watermark-pos", type=str, default=argparse.SUPPRESS,
        choices=["CENTER", "TOP_LEFT", "TOP_RIGHT", "BOTTOM_LEFT",
                 "BOTTOM_RIGHT", "TOP", "BOTTOM"],
        help=_t('help___watermark_pos'),
    )
    batch_parser.add_argument(
        "--watermark-opacity", type=int, default=argparse.SUPPRESS, metavar="0-100",
        help=_t('help___watermark_opacity'),
    )
    batch_parser.add_argument(
        "--sizes", type=str, default=None, metavar="LABEL:WxH,...",
        help=_t('help___sizes'),
    )
    _add_advanced_args(batch_parser)
    _add_transform_args(batch_parser)
    batch_parser.add_argument(
        "--profiles", type=str, default=None, metavar="P1,P2",
        help=_t('help___profiles'),
    )

    # ── exif subcommand ─────────────────────────────────────────────────────
    exif_parser = subparsers.add_parser(
        "exif", help=_t('cmd_exif'),
    )
    exif_parser.add_argument(
        "files", nargs="*", help=_t('help___image_files'),
    )
    exif_parser.add_argument(
        "-r", "--recursive", action="store_true",
        help=_t('help___recursive'),
    )
    exif_parser.add_argument(
        "--show", action="store_true",
        help=_t('help___show'),
    )
    exif_parser.add_argument(
        "--json", action="store_true",
        help=_t('help___json'),
    )
    exif_parser.add_argument(
        "--list", action="store_true",
        help=_t('help___list'),
    )
    # ── write tags ──
    exif_parser.add_argument(
        "--artist", type=str, default=None, help=_t('help___artist'),
    )
    exif_parser.add_argument(
        "--copyright", type=str, default=None, help=_t('help___copyright'),
    )
    exif_parser.add_argument(
        "--description", type=str, default=None, help=_t('help___description'),
    )
    exif_parser.add_argument(
        "--caption", type=str, default=None, help=_t('help___caption'),
    )
    exif_parser.add_argument(
        "--title", type=str, default=None, help=_t('help___title'),
    )
    exif_parser.add_argument(
        "--rating", type=int, default=None, metavar="0-5",
        help=_t('help___rating'),
    )
    exif_parser.add_argument(
        "--keywords", type=str, default=None, metavar="A,B",
        help=_t('help___keywords'),
    )
    exif_parser.add_argument(
        "--date", type=str, default=None, metavar="DATETIME",
        help=_t('help___date'),
    )
    exif_parser.add_argument(
        "--software", type=str, default=None, help=_t('help___software'),
    )
    exif_parser.add_argument(
        "--lens", type=str, default=None,
        help=_t('help___lens'),
    )
    exif_parser.add_argument(
        "--iso", type=int, default=None, metavar="N",
        help=_t('help___iso'),
    )
    exif_parser.add_argument(
        "--shutter", type=str, default=None, metavar="SEC",
        help=_t('help___shutter'),
    )
    exif_parser.add_argument(
        "--aperture", type=str, default=None, metavar="F",
        help=_t('help___aperture'),
    )
    exif_parser.add_argument(
        "--focal", type=str, default=None, metavar="MM",
        help=_t('help___focal'),
    )
    exif_parser.add_argument(
        "--date-from-mtime", action="store_true",
        help=_t('help___date_from_mtime'),
    )
    # ── filter (with --show) ──
    exif_parser.add_argument(
        "--rating-min", type=int, default=None, metavar="N",
        help=_t('help___rating_min'),
    )
    exif_parser.add_argument(
        "--camera", type=str, default=None, metavar="MODEL",
        help=_t('help___camera'),
    )
    exif_parser.add_argument(
        "--date-from", type=str, default=None, metavar="YYYY-MM-DD",
        help=_t('help___date_from'),
    )
    exif_parser.add_argument(
        "--date-to", type=str, default=None, metavar="YYYY-MM-DD",
        help=_t('help___date_to'),
    )
    # ── batch import ──
    exif_parser.add_argument(
        "--from-csv", type=str, default=None, metavar="meta.csv",
        help=_t('help___from_csv'),
    )
    exif_parser.add_argument(
        "--from-json", type=str, default=None, metavar="meta.json",
        help=_t('help___from_json'),
    )

    # ── preset subcommand ───────────────────────────────────────────────────
    preset_parser = subparsers.add_parser(
        "preset", help=_t('cmd_preset'),
    )
    preset_subs = preset_parser.add_subparsers(dest="preset_action")

    preset_save = preset_subs.add_parser("save", help=_t('cmd_save'))
    preset_save.add_argument("name", help=_t('help___preset_name'))
    preset_save.add_argument("-f", "--format", type=str, default="JPEG")
    preset_save.add_argument("-q", "--quality", type=int, default=85)
    preset_save.add_argument("--resize", type=str, default=None)
    preset_save.add_argument("--suffix", type=str, default="_compressed")
    preset_save.add_argument("--desc", type=str, default="", help=_t('help___desc'))

    preset_list = preset_subs.add_parser("list", help=_t('cmd_list'))
    preset_load = preset_subs.add_parser("load", help=_t('cmd_load'))
    preset_load.add_argument("name", help=_t('help___preset_name'))
    preset_delete = preset_subs.add_parser("delete", help=_t('cmd_delete'))
    preset_delete.add_argument("name", help=_t('help___preset_name'))

    # ── plugin subcommand ───────────────────────────────────────────────────
    plugin_parser = subparsers.add_parser(
        "plugin", help=_t('cmd_plugin'),
    )
    plugin_subs = plugin_parser.add_subparsers(dest="plugin_action")

    plugin_list = plugin_subs.add_parser(
        "list", help=_t('cmd_list'),
    )
    plugin_list.add_argument(
        "--json", action="store_true",
        help=_t('help___json'),
    )

    plugin_install = plugin_subs.add_parser(
        "install", help=_t('cmd_install'),
    )
    plugin_install.add_argument("name", help=_t('help___plugin_name_eg'))
    plugin_install.add_argument(
        "--json", action="store_true",
        help=_t('help___json'),
    )
    plugin_install.add_argument(
        "--dry-run", action="store_true",
        help=_t('help___dry_run'),
    )

    plugin_uninstall = plugin_subs.add_parser(
        "uninstall", help=_t('cmd_uninstall'),
    )
    plugin_uninstall.add_argument("name", help=_t('help___plugin_name'))
    plugin_uninstall.add_argument(
        "--json", action="store_true",
        help=_t('help___json'),
    )
    plugin_uninstall.add_argument(
        "--dry-run", action="store_true",
        help=_t('help___dry_run'),
    )

    plugin_info = plugin_subs.add_parser(
        "info", help=_t('cmd_info'),
    )
    plugin_info.add_argument("name", help=_t('help___plugin_name'))
    plugin_info.add_argument(
        "--json", action="store_true",
        help=_t('help___json'),
    )

    plugin_fetch = plugin_subs.add_parser(
        "fetch", help=_t('cmd_fetch'),
    )
    plugin_fetch.add_argument("name", help=_t('help___plugin_name'))
    plugin_fetch.add_argument(
        "--json", action="store_true",
        help=_t('help___json'),
    )

    plugin_scaffold = plugin_subs.add_parser(
        "scaffold", help=_t('cmd_scaffold'),
    )
    plugin_scaffold.add_argument(
        "name", help=_t('help___plugin_name_alnum'),
    )
    plugin_scaffold.add_argument(
        "--dir", type=str, default=None, metavar="DIR",
        help=_t('help___dir'),
    )
    plugin_scaffold.add_argument(
        "--json", action="store_true",
        help=_t('help___json'),
    )

    # ── watch subcommand ────────────────────────────────────────────────────
    watch_parser = subparsers.add_parser(
        "watch", help=_t('cmd_watch'),
    )
    watch_parser.add_argument(
        "directory", help=_t('help___directory'),
    )
    watch_parser.add_argument(
        "-f", "--format", type=_format_arg, default="JPEG",
        help=_t('help___format'),
    )
    watch_parser.add_argument(
        "-q", "--quality", type=int, default=85,
        help=_t('help___quality'),
    )
    watch_parser.add_argument(
        "-o", "--output-dir", type=str, default=None,
        help=_t('help___output_dir'),
    )
    watch_parser.add_argument(
        "-r", "--recursive", action="store_true",
        help=_t('help___recursive'),
    )
    watch_parser.add_argument(
        "--remove-original", action="store_true",
        help=_t('help___remove_original'),
    )
    watch_parser.add_argument(
        "--resize", type=str, default=None, metavar="WxH",
        help=_t('help___resize'),
    )

    # ── dedup subcommand ────────────────────────────────────────────────────
    dedup_parser = subparsers.add_parser(
        "dedup", help=_t('cmd_dedup'),
    )
    dedup_parser.add_argument(
        "paths", nargs="+", help=_t('help___paths'),
    )
    dedup_parser.add_argument(
        "--json", action="store_true",
        help=_t('help___json'),
    )
    dedup_parser.add_argument(
        "-r", "--recursive", action="store_true",
        help=_t('help___recursive'),
    )
    dedup_parser.add_argument(
        "--threshold", type=int, default=5, metavar="N",
        help=_t('help___threshold'),
    )
    dedup_parser.add_argument(
        "--action", type=str, default="report",
        choices=["report", "move", "delete", "keep-sharpest"],
        help=_t('help___action'),
    )
    dedup_parser.add_argument(
        "--dry-run", action="store_true",
        help=_t('help___dry_run'),
    )

    # ── info subcommand ─────────────────────────────────────────────────────
    info_parser = subparsers.add_parser(
        "info", help=_t('cmd_info'),
    )
    info_parser.add_argument(
        "--json", action="store_true",
        help=_t('help___json'),
    )

    # ── rename subcommand ───────────────────────────────────────────────────
    rename_parser = subparsers.add_parser(
        "rename", help=_t('cmd_rename'),
    )
    rename_parser.add_argument(
        "files", nargs="+", help=_t('help___files'),
    )
    rename_parser.add_argument(
        "--json", action="store_true",
        help=_t('help___json'),
    )
    rename_parser.add_argument(
        "--pattern", type=str, required=True, metavar="PATTERN",
        help=_t('help___pattern'),
    )
    rename_parser.add_argument(
        "-o", "--output-dir", type=str, default=None,
        help=_t('help___output_dir'),
    )
    rename_parser.add_argument(
        "--dry-run", action="store_true",
        help=_t('help___dry_run'),
    )
    rename_parser.add_argument(
        "--overwrite", action="store_true",
        help=_t('help___overwrite'),
    )
    rename_parser.add_argument(
        "-r", "--recursive", action="store_true",
        help=_t('help___recursive'),
    )

    # ── check subcommand ────────────────────────────────────────────────────
    check_parser = subparsers.add_parser(
        "check", help=_t('cmd_check'),
    )
    check_parser.add_argument(
        "files", nargs="+", help=_t('help___files'),
    )
    check_parser.add_argument(
        "-r", "--recursive", action="store_true",
        help=_t('help___recursive'),
    )
    check_parser.add_argument(
        "--json", action="store_true",
        help=_t('help___json'),
    )

    # ── contact-sheet subcommand ────────────────────────────────────────────
    sheet_parser = subparsers.add_parser(
        "contact-sheet", help=_t('cmd_contact_sheet'),
    )
    sheet_parser.add_argument(
        "files", nargs="+", help=_t('help___files'),
    )
    sheet_parser.add_argument(
        "--json", action="store_true",
        help=_t('help___json'),
    )
    sheet_parser.add_argument(
        "-o", "--output", type=str, required=True,
        help=_t('help___output'),
    )
    sheet_parser.add_argument(
        "--cols", type=int, default=4,
        help=_t('help___cols'),
    )
    sheet_parser.add_argument(
        "--thumb", type=str, default="240x240", metavar="WxH",
        help=_t('help___thumb'),
    )
    sheet_parser.add_argument(
        "--caption", action="store_true",
        help=_t('help___caption'),
    )
    sheet_parser.add_argument(
        "--bg", type=str, default="#000000",
        help=_t('help___bg'),
    )
    sheet_parser.add_argument(
        "-r", "--recursive", action="store_true",
        help=_t('help___recursive'),
    )

    # ── cull subcommand ─────────────────────────────────────────────────────
    cull_parser = subparsers.add_parser(
        "cull", help=_t('cmd_cull'),
    )
    cull_parser.add_argument(
        "paths", nargs="+", help=_t('help___paths'),
    )
    cull_parser.add_argument(
        "-r", "--recursive", action="store_true",
        help=_t('help___recursive'),
    )
    cull_parser.add_argument(
        "--overexposed-max", type=float, default=None, metavar="PCT",
        help=_t('help___overexposed_max'),
    )
    cull_parser.add_argument(
        "--underexposed-max", type=float, default=None, metavar="PCT",
        help=_t('help___underexposed_max'),
    )
    cull_parser.add_argument(
        "--luminance-min", type=float, default=None, metavar="0-1",
        help=_t('help___luminance_min'),
    )
    cull_parser.add_argument(
        "--luminance-max", type=float, default=None, metavar="0-1",
        help=_t('help___luminance_max'),
    )
    cull_parser.add_argument(
        "--sharpness-min", type=float, default=None, metavar="N",
        help=_t('help___sharpness_min'),
    )
    cull_parser.add_argument(
        "--json", action="store_true",
        help=_t('help___json'),
    )
    cull_parser.add_argument(
        "--list", action="store_true",
        help=_t('help___list'),
    )

    # ── hash subcommand ─────────────────────────────────────────────────────
    hash_parser = subparsers.add_parser(
        "hash", help=_t('cmd_hash'),
    )
    hash_parser.add_argument(
        "paths", nargs="*", help=_t('help___paths'),
    )
    hash_parser.add_argument(
        "-r", "--recursive", action="store_true",
        help=_t('help___recursive'),
    )
    hash_parser.add_argument(
        "-o", "--output", type=str, default=None, metavar="manifest.csv",
        help=_t('help___output'),
    )
    hash_parser.add_argument(
        "--verify", type=str, default=None, metavar="manifest.csv",
        help=_t('help___verify'),
    )
    hash_parser.add_argument(
        "--sha256", action="store_true", help=_t('help___sha256'),
    )
    hash_parser.add_argument(
        "--json", action="store_true",
        help=_t('help___json'),
    )

    # ── gallery subcommand ──────────────────────────────────────────────────
    gallery_parser = subparsers.add_parser(
        "gallery", help=_t('cmd_gallery'),
    )
    gallery_parser.add_argument(
        "paths", nargs="+", help=_t('help___paths'),
    )
    gallery_parser.add_argument(
        "-o", "--output", type=str, required=True, metavar="DIR",
        help=_t('help___output_dir'),
    )
    gallery_parser.add_argument(
        "--title", type=str, default="PhotoS Gallery", metavar="TITLE",
        help=_t('help___title'),
    )
    gallery_parser.add_argument(
        "--thumb", type=int, default=360, metavar="PX",
        help=_t('help___thumb'),
    )
    gallery_parser.add_argument(
        "-r", "--recursive", action="store_true",
        help=_t('help___recursive'),
    )
    gallery_parser.add_argument(
        "--json", action="store_true",
        help=_t('help___json'),
    )

    # ── bench subcommand ────────────────────────────────────────────────────
    bench_parser = subparsers.add_parser(
        "bench", help=_t('cmd_bench'),
    )
    bench_parser.add_argument(
        "--dir", type=str, required=True, metavar="DIR",
        help=_t('help___dir'),
    )
    bench_parser.add_argument(
        "-j", "--jobs", type=str, default="1,2,4,8", metavar="N,N,...",
        help=_t('help___jobs'),
    )
    bench_parser.add_argument(
        "--images", type=int, default=None, metavar="N",
        help=_t('help___images'),
    )
    bench_parser.add_argument(
        "--denoise", type=float, default=None, metavar="N",
        help=_t('help___denoise'),
    )
    bench_parser.add_argument(
        "--evaluate", action="store_true",
        help=_t('help___evaluate'),
    )
    bench_parser.add_argument(
        "--json", action="store_true",
        help=_t('help___json'),
    )

    # ── config subcommand ───────────────────────────────────────────────────
    config_parser = subparsers.add_parser(
        "config", help=_t('cmd_config'),
    )
    config_subs = config_parser.add_subparsers(dest="config_action")
    config_init = config_subs.add_parser(
        "init", help=_t('cmd_init'),
    )
    config_init.add_argument(
        "--path", type=str, default=None,
        help=_t('help___path'),
    )
    config_show = config_subs.add_parser(
        "show", help=_t('cmd_show'),
    )
    config_show.add_argument(
        "--path", type=str, default=None,
        help=_t('help___path'),
    )

    # ── serve subcommand ────────────────────────────────────────────────────
    serve_parser = subparsers.add_parser(
        "serve", help=_t('cmd_serve'),
    )
    serve_parser.add_argument(
        "--host", type=str, default="127.0.0.1",
        help=_t('help___host'),
    )
    serve_parser.add_argument(
        "--port", type=int, default=8787,
        help=_t('help___port'),
    )
    serve_parser.add_argument(
        "--token", type=str, default=None, metavar="TOKEN|auto",
        help=_t('help___token'),
    )
    serve_parser.add_argument(
        "--ready-file", type=str, default=None, metavar="PATH",
        help=_t('help___ready_file'),
    )
    serve_parser.add_argument(
        "--config", type=str, default=None,
        help=_t('help___path'),
    )

    # ── mcp subcommand ───────────────────────────────────────────────────────
    mcp_parser = subparsers.add_parser(
        "mcp", help=_t('cmd_mcp'),
    )
    mcp_parser.add_argument(
        "--config", type=str, default=None,
        help=_t('help___path'),
    )
    mcp_parser.add_argument(
        "--list-tools", action="store_true",
        help=_t('help___list_tools'),
    )

    # Accept --language anywhere (before or after a subcommand). Resolution
    # already happened in _pre_parse_language; these copies just let
    # parse_args tolerate the flag after a subcommand, hidden from --help.
    for _sub in (compress_parser, convert_parser, batch_parser, exif_parser,
                 preset_parser, plugin_parser, watch_parser, dedup_parser,
                 info_parser, rename_parser, check_parser, sheet_parser,
                 cull_parser, hash_parser, gallery_parser, bench_parser,
                 config_parser, serve_parser, mcp_parser,
                 preset_save, preset_load, preset_delete,
                 plugin_install, plugin_uninstall, plugin_info, plugin_fetch,
                 config_init, config_show):
        _sub.add_argument("--language", "--lang",
                          choices=["en", "zh", "auto"],
                          default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    parsed = parser.parse_args(args)

    if not parsed.command:
        parser.print_help()
        return 1

    # ── Handle 'watch' command ──────────────────────────────────────────────
    if parsed.command == "watch":
        from .watcher import start_watching

        watch_dir = parsed.directory
        if not os.path.isdir(watch_dir):
            print(f"{_t('msg_dir_not_found')}: {watch_dir}")
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
            print(_t("msg_no_images"))
            return 1

        dedup_json = getattr(parsed, 'json', False)
        print(_t("msg_scanning", n=len(files)), file=sys.stderr)
        print(file=sys.stderr)

        def progress_cb(current, total):
            print(f"  {_t('msg_hashing_progress')}: [{current}/{total}]",
                  end="\r", file=sys.stderr)

        dup_groups = find_duplicates(files, threshold=parsed.threshold,
                                     progress_callback=progress_cb)
        print(file=sys.stderr)

        total_dupes = sum(len(paths) - 1 for paths in dup_groups.values())
        savings = sum(os.path.getsize(p)
                      for g in dup_groups.values() for p in g[1:])

        if dedup_json:
            import json
            print(json.dumps(versioned({
                "count": len(dup_groups),
                "duplicate_count": total_dupes,
                "savings_bytes": savings,
                "groups": [{"hash": h, "paths": ps}
                           for h, ps in dup_groups.items()],
            }), indent=2, ensure_ascii=False))
        else:
            if not dup_groups:
                print(_t("msg_no_dupes"))
            else:
                print(_t("msg_dup_groups", n=len(dup_groups)))
                print()
                for i, (h, paths) in enumerate(dup_groups.items(), 1):
                    print(_t("msg_group_files", i=i, n=len(paths)))
                    for p in paths:
                        print(f"    {'⭐' if p == paths[0] else '📎'} {p} "
                              f"({format_size(os.path.getsize(p))})")
                    print()
                print(_t("msg_dupes_total", n=total_dupes, savings=savings))

        if parsed.action in ("move", "delete", "keep-sharpest"):
            if parsed.dry_run:
                print()
                print(_t("msg_dry_run"))
            elif not dedup_json:
                # JSON callers have no stdin; requesting the action explicitly
                # IS the confirmation (same rule as --remove-original --json).
                verb = (_t("msg_verb_keep_sharpest")
                        if parsed.action == "keep-sharpest"
                        else (_t("msg_verb_move")
                              if parsed.action == "move" else _t("msg_verb_delete")))
                confirm = input(_t("msg_confirm_dedup", verb=verb,
                                   n=total_dupes)).strip().lower()
                if confirm not in ("y", "yes"):
                    print(_t("msg_cancelled"))
                    return 0

            kept, removed = handle_duplicates(dup_groups, action=parsed.action,
                                              dry_run=parsed.dry_run)
            if dedup_json:
                print(json.dumps(versioned({"action": parsed.action, "kept": kept,
                                  "removed": removed}),
                                 indent=2, ensure_ascii=False))
            else:
                _will = {
                    "move": _t("msg_will_move", removed=removed, kept=kept),
                    "delete": _t("msg_will_delete", removed=removed, kept=kept),
                    "keep-sharpest": _t("msg_will_keep", removed=removed, kept=kept),
                }[parsed.action]
                _done = {
                    "move": _t("msg_done_move", removed=removed, kept=kept),
                    "delete": _t("msg_done_delete", removed=removed, kept=kept),
                    "keep-sharpest": _t("msg_done_keep", removed=removed, kept=kept),
                }[parsed.action]
                print(_will if parsed.dry_run else _done)

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
            print(f"{_t('msg_preset_saved')}: {parsed.name}")

        elif parsed.preset_action == "list":
            presets = list_presets()
            if presets:
                print(_t("msg_presets_available"))
                for p in presets:
                    print(f"   {p}")
            else:
                print(_t("msg_no_presets"))

        elif parsed.preset_action == "load":
            opts = load_preset(parsed.name)
            if opts:
                print(_t("msg_preset_show", name=parsed.name))
                print(f"   photo-s batch <files> -f {opts.output_format} -q {opts.quality}", end="")
                if opts.max_width or opts.max_height:
                    print(f" --resize {opts.max_width or ''}x{opts.max_height or ''}", end="")
                print(f" --suffix {opts.suffix}")
            else:
                print(f"{_t('msg_preset_not_found')}: {parsed.name}")
                return 1

        elif parsed.preset_action == "delete":
            if delete_preset(parsed.name):
                print(f"{_t('msg_preset_deleted')}: {parsed.name}")
            else:
                print(f"{_t('msg_preset_not_found')}: {parsed.name}")
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
                      ("keywords", "keywords"), ("lens", "lens"),
                      ("iso", "iso"), ("shutter", "shutter"),
                      ("aperture", "aperture"), ("focal", "focal")]

        def _apply_batch_meta(rows, source):
            """Write metadata for a list of {path, tag...} dicts."""
            tags_cols = [n for _, n in _TAG_FLAGS]
            done = 0
            failed = 0
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
                try:
                    apply_exif_tags(p, tags)
                except Exception as e:  # per-file: keep going, report at end
                    failed += 1
                    print(f"  ❌ {os.path.basename(p)}: {e}", file=sys.stderr)
                    continue
                done += 1
            return done, failed

        # ── Batch import from CSV / JSON (paths come from the file) ──
        if getattr(parsed, 'from_csv', None):
            import csv
            with open(parsed.from_csv, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            done, failed = _apply_batch_meta(rows, parsed.from_csv)
            print(f"{_t('msg_written_csv')}: {done} {_t('msg_files_suffix')}")
            if failed:
                print(_t("msg_write_failed", n=failed), file=sys.stderr)
            return 0 if failed == 0 else 1
        if getattr(parsed, 'from_json', None):
            import json
            rows = json.loads(Path(parsed.from_json).read_text(encoding="utf-8"))
            if not isinstance(rows, list):
                rows = [rows]
            done, failed = _apply_batch_meta(rows, parsed.from_json)
            print(f"{_t('msg_written_json')}: {done} {_t('msg_files_suffix')}")
            if failed:
                print(_t("msg_write_failed", n=failed), file=sys.stderr)
            return 0 if failed == 0 else 1

        # ── Read / filter mode ──
        if getattr(parsed, 'show', False):
            files = _collect_files(parsed.files,
                                   recursive=getattr(parsed, 'recursive', False))
            if not files:
                print(_t("msg_no_images"))
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
                print(json.dumps(versioned({"count": len(results), "results": results}),
                                 indent=2, ensure_ascii=False))
            else:
                for r in results:
                    print(f"  {r['path']}")
                    print(f"     {_t('msg_date_label')}: {r['date']} {r['time']}"
                          f" | camera: {r['camera'] or '-'}"
                          f" | ISO: {r['iso'] or '-'} | focal: {r['focal'] or '-'}")
                    print(f"     {_t('msg_rating_label')}: {r['rating']}"
                          f" | keywords: {', '.join(r['keywords']) or '-'}"
                          f" | title: {r['title'] or '-'}"
                          f" | caption: {r['caption'] or '-'}")
            return 0

        # ── Write mode: collect tags from flags ──
        tags = {}
        for flag, name in _TAG_FLAGS:
            val = getattr(parsed, flag, None)
            if val is not None:
                tags[name] = val

        if getattr(parsed, 'date_from_mtime', False):
            # reverse sync: DateTimeOriginal ← file mtime (per file)
            failed = 0
            for f in _collect_files(parsed.files,
                                    recursive=getattr(parsed, 'recursive', False)):
                try:
                    ts = os.path.getmtime(f)
                except OSError:
                    continue
                dt = datetime.fromtimestamp(ts)
                try:
                    apply_exif_tags(f, {"date": dt.strftime("%Y:%m:%d %H:%M:%S")})
                except Exception as e:  # per-file: keep going, report at end
                    failed += 1
                    print(f"  ❌ {os.path.basename(f)}: {e}", file=sys.stderr)
                    continue
            print(_t("msg_synced_date"))
            if failed:
                print(_t("msg_write_failed", n=failed), file=sys.stderr)
            return 0 if failed == 0 else 1

        if not tags:
            print(_t("msg_no_exif_tags"))
            return 1

        files = _collect_files(parsed.files,
                               recursive=getattr(parsed, 'recursive', False))
        if not files:
            print(_t("msg_no_images"))
            return 1

        print(f"{_t('msg_editing_exif')} ({len(files)} {_t('msg_files_suffix')})...")
        for tag, val in tags.items():
            print(f"   {tag}: {val}")
        print()

        failed = 0
        for f in files:
            try:
                msg = apply_exif_tags(f, tags)
            except Exception as e:  # per-file: keep going, report at end
                failed += 1
                print(f"  ❌ {os.path.basename(f)}: {e}")
                continue
            print(f"  {os.path.basename(f)}: {msg}")

        print(f"\n{_t('msg_exif_done')}")
        if failed:
            print(_t("msg_write_failed", n=failed), file=sys.stderr)
        return 0 if failed == 0 else 1

    # ── Handle 'info' command ────────────────────────────────────────────────
    if parsed.command == "info":
        from .engine import _HAS_PILLOW_HEIF
        from .envinfo import optional_features, plugins

        if getattr(parsed, 'json', False):
            import json
            print(json.dumps(versioned({
                "version": __version__,
                "input_extensions": sorted(ALL_INPUT_EXTENSIONS),
                "formats": sorted(SUPPORTED_FORMATS),
                "writable": sorted(PIL_WRITABLE),
                "optional_features": optional_features(),
                "plugins": plugins(),
            }), indent=2, ensure_ascii=False))
            return 0
        print(_t("msg_formats_title"))
        print("=" * 50)
        print()
        print(_t("msg_input_formats"))
        for ext in sorted(ALL_INPUT_EXTENSIONS):
            print(f"  {ext}")
        print()
        print(_t("msg_output_formats"))
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
            print(_t("msg_heic_hint"))
            print("   pip install pillow-heif")
        print()
        print(_t("msg_optional_features"))
        for name, installed in optional_features().items():
            print(f"  {'✅' if installed else '·'} {name}")
        plugins = plugins()
        print()
        print(_t("msg_installed_plugins"))
        if plugins:
            for p in plugins:
                provides = ", ".join(p["provides"]) or "-"
                print(f"  {p['name']}  [{provides}]")
        else:
            print(f"  {_t('msg_none')}")
        return 0

    # ── Handle 'config' command ─────────────────────────────────────────────
    if parsed.command == "config":
        from .config import (find_config, load_config, default_config_text,
                             save_config, apply_config)
        if parsed.config_action == "init":
            path = parsed.path or "photo-s.toml"
            save_config(path, default_config_text())
            print(f"{_t('msg_config_created')}: {os.path.abspath(path)}")
            print(f"   {_t('msg_config_hint')}")
            return 0
        elif parsed.config_action == "show":
            path = parsed.path or find_config()
            if not path:
                print(_t("msg_no_config"))
                print(f"   {_t('msg_config_init_hint')}")
                return 0
            try:
                cfg = load_config(path)
                apply_config(cfg, ProcessOptions())
            except Exception as e:
                print(f"{_t('msg_config_load_err')}: {e}")
                return 1
            print(f"{_t('msg_config_file')} {path}")
            opts_dict = cfg.get("options", {})
            if not opts_dict:
                print(f"   {_t('msg_no_custom_opts')}")
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
            try:
                cfg = load_config(parsed.config)
                base_options = apply_config(cfg, base_options)
            except Exception as e:
                print(f"{_t('msg_config_load_err')}: {e}")
                return 1
        token = parsed.token
        if token == "auto":
            token = generate_token()
            print(f"{_t('msg_token_generated')}: {token}", file=sys.stderr)
        run_server(parsed.host, parsed.port, options=base_options,
                   token=token, ready_file=parsed.ready_file)
        return 0

    # ── Handle 'mcp' command ─────────────────────────────────────────────────
    if parsed.command == "mcp":
        # The mcp SDK requires Python >= 3.10 — check before any import so
        # py3.9 gets a clear message instead of an ImportError.
        if sys.version_info < (3, 10):
            print(_t("msg_mcp_py310"), file=sys.stderr)
            return 1
        try:
            if parsed.list_tools:
                import json
                from .mcp_server import list_tools_json
                print(json.dumps(versioned({"tools": list_tools_json()}),
                                 indent=2, ensure_ascii=False))
                return 0
            from .mcp_server import run_stdio
            run_stdio(config_path=parsed.config)
        except RuntimeError as e:
            # missing mcp extra / bad config
            print(f"❌ {e}", file=sys.stderr)
            return 1
        return 0

    # ── Handle 'rename' command ─────────────────────────────────────────────
    if parsed.command == "rename":
        from .rename import rename_files

        files = _collect_files(parsed.files, recursive=parsed.recursive)
        if not files:
            print(_t("msg_no_images"))
            return 1

        rename_json = getattr(parsed, 'json', False)
        if rename_json:
            pass  # machine output only — no human preamble on stdout
        elif parsed.dry_run:
            print(_t("msg_dry_run_settings"))
        elif parsed.output_dir:
            print(f"{_t('msg_copy_to')}: {parsed.output_dir}")
        else:
            print(_t("msg_rename_in_place"))
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
            print(json.dumps(versioned({"total": len(results), "ok": ok,
                              "results": results}),
                             indent=2, ensure_ascii=False))
        else:
            for r in results:
                extra = f": {r['error']}" if r["error"] else ""
                print(f"  {'→' if r['status'] == 'ok' else '❌'} "
                      f"{os.path.basename(r['input'])} → "
                      f"{os.path.basename(r['output'])}{extra}")
            print()
            print(_t("msg_rename_ok", ok=ok, total=len(results)))
            if not parsed.dry_run and not parsed.output_dir:
                print(f"   {_t('msg_rename_note')}")
        return 0 if ok == len(results) else 1

    # ── Handle 'check' command ──────────────────────────────────────────────
    if parsed.command == "check":
        from .check import verify_images

        files = _collect_files(parsed.files, recursive=parsed.recursive)
        if not files:
            print(_t("msg_no_images"))
            return 1

        results = verify_images(files)
        corrupt = [r for r in results if not r["ok"]]

        if parsed.json:
            import json
            print(json.dumps(versioned({
                "checked": len(results),
                "ok": len(results) - len(corrupt),
                "corrupt": [{"path": r["path"], "error": r["error"]}
                            for r in corrupt],
            }), indent=2, ensure_ascii=False))
        else:
            for r in results:
                mark = "✅" if r["ok"] else "❌"
                extra = "" if r["ok"] else f" — {r['error']}"
                print(f"  {mark} {r['path']}{extra}")
            print(f"\n{_t('msg_check_done')}: {len(results)} {_t('msg_files_suffix')}, "
                  f"{len(corrupt)} {_t('msg_check_corrupt')}")

        return 0 if not corrupt else 1

    # ── Handle 'contact-sheet' command ──────────────────────────────────────
    if parsed.command == "contact-sheet":
        from .contact import build_contact_sheet
        from .adjust import hex_to_rgb

        files = _collect_files(parsed.files, recursive=parsed.recursive)
        if not files:
            print(_t("msg_no_images"))
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
            print(json.dumps(versioned({"output": out, "count": len(files)}),
                             indent=2, ensure_ascii=False))
        else:
            print(f"{_t('msg_contact_sheet')}: {out}  "
                  f"({_t('msg_images_count', n=len(files))})")
        return 0

    # ── Handle 'cull' command ───────────────────────────────────────────────
    if parsed.command == "cull":
        from .cull import cull_files
        files = _collect_files(parsed.paths, recursive=parsed.recursive)
        if not files:
            print(_t("msg_no_images"))
            return 1

        results = cull_files(
            files,
            overexposed_max=parsed.overexposed_max,
            underexposed_max=parsed.underexposed_max,
            luminance_min=parsed.luminance_min,
            luminance_max=parsed.luminance_max,
            sharpness_min=parsed.sharpness_min,
        )

        kept_paths = [r["path"] for r in results if r["kept"]]
        if getattr(parsed, 'list', False):
            for p in kept_paths:
                print(p)
        elif getattr(parsed, 'json', False):
            import json
            print(json.dumps(versioned({"count": len(results), "kept": len(kept_paths),
                              "results": results}),
                             indent=2, ensure_ascii=False))
        else:
            for r in results:
                mark = "✅" if r["kept"] else "❌"
                extra = (f"  sharp={r['blur_score']}"
                         if "blur_score" in r else "")
                print(f"  {mark} {r['path']}  lum={r['luminance']} "
                      f"over={r['overexposed_pct']}% "
                      f"under={r['underexposed_pct']}%{extra}")
            print(f"\n{_t('msg_cull_kept')}: {len(kept_paths)}/{len(results)}")
        return 0

    # ── Handle 'hash' command ───────────────────────────────────────────────
    if parsed.command == "hash":
        from .check import (collect_files, compute_checksums, write_manifest,
                            verify_manifest)
        import json

        if parsed.verify:
            report = verify_manifest(parsed.verify)
            if parsed.json:
                print(json.dumps(versioned(report), indent=2, ensure_ascii=False))
            else:
                print(f"{_t('msg_manifest')}: {parsed.verify}  ({report['algorithm']})")
                print(_t("msg_total_ok", total=report["total"], ok=report["ok"]))
                if report["missing"]:
                    print(f"  {_t('msg_missing')} ({len(report['missing'])}):")
                    for p in report["missing"]:
                        print(f"    {p}")
                if report["mismatched"]:
                    print(f"  {_t('msg_mismatched')} ({len(report['mismatched'])}):")
                    for m in report["mismatched"]:
                        print(f"    {m['path']}")
                        print(f"     {_t('msg_expected')}: {m['expected']}")
                        print(f"     {_t('msg_actual')}:   {m['actual']}")
            return 0 if (not report["missing"] and not report["mismatched"]) else 1

        # Hash every file (not just images — for archives)
        files = collect_files(parsed.paths, recursive=parsed.recursive)
        if not files:
            print(_t("msg_no_files"))
            return 1

        print(_t("msg_hashing_start", n=len(files)), file=sys.stderr)
        entries = compute_checksums(files)
        out = parsed.output or "manifest.csv"
        write_manifest(out, entries)
        if parsed.json:
            print(json.dumps(versioned({"output": os.path.abspath(out),
                              "count": len(files)}), indent=2, ensure_ascii=False))
        else:
            print(f"{_t('msg_manifest_written')}: {os.path.abspath(out)} "
                  f"({len(files)} 项)")
        return 0

    # ── Handle 'bench' command ───────────────────────────────────────────────
    if parsed.command == "bench":
        import json as _json
        from .bench import run_benchmark
        files = _collect_files([parsed.dir], recursive=True)
        if not files:
            print(_t("msg_no_images_dir"), file=sys.stderr)
            return 1
        if parsed.images:
            files = files[:parsed.images]
        try:
            job_list = [int(x.strip()) for x in parsed.jobs.split(",") if x.strip()]
        except ValueError:
            print(_t("msg_bad_jobs"), file=sys.stderr)
            return 1
        if not job_list or any(j < 1 for j in job_list):
            print(_t("msg_jobs_ints"), file=sys.stderr)
            return 1
        job_list = list(dict.fromkeys(job_list))  # dedupe, keep order

        base = ProcessOptions(
            quality=getattr(parsed, 'quality', 85),
            output_format=getattr(parsed, 'format', 'JPEG'),
            denoise=parsed.denoise,
        )
        # Outputs go to a temp dir cleaned up by run_benchmark — the
        # source directory is never polluted.
        report = run_benchmark(files, job_list, base, evaluate=parsed.evaluate)
        out = {"dir": parsed.dir, "files": len(files), **report}
        if getattr(parsed, 'json', False):
            print(_json.dumps(versioned(out), indent=2, ensure_ascii=False))
        else:
            print(f"bench: {len(files)} files in {parsed.dir}")
            for r in report["runs"]:
                st = r["stages"]
                print(f"  jobs={r['jobs']:<3} {r['seconds']:>6.2f}s  "
                      f"speedup={r['speedup']:>4.2f}x  errors={r['errors']}  "
                      f"load={st['load']:.2f}s process={st['process']:.2f}s "
                      f"save={st['save']:.2f}s")
            ev = report.get("evaluate")
            if ev is not None:
                if ev["files"]:
                    psnr = (f"{ev['psnr_db']:.2f}dB"
                            if ev["psnr_db"] is not None else "inf")
                    print(f"  evaluate: {ev['files']} files  "
                          f"PSNR={psnr}  SSIM={ev['ssim']:.4f}")
                else:
                    print(f"  {_t('msg_eval_no_output')}")
            print(_t("msg_bench_tip"))
        return 0

    # ── Handle 'gallery' command ────────────────────────────────────────────
    if parsed.command == "gallery":
        from .gallery import build_gallery
        files = _collect_files(parsed.paths, recursive=parsed.recursive)
        if not files:
            print(_t("msg_no_images"))
            return 1
        res = build_gallery(files, parsed.output, title=parsed.title,
                            thumb_size=parsed.thumb)
        if getattr(parsed, 'json', False):
            import json
            print(json.dumps(versioned(res), indent=2, ensure_ascii=False))
        else:
            print(f"{_t('msg_gallery')}: {res['output']}  "
                  f"({_t('msg_images_count', n=res['count'])})")
        return 0

    # ── Build options from parsed args ──────────────────────────────────────
    # Parse target size if provided
    target_size_bytes = None
    target_size_str = getattr(parsed, 'target_size', None)
    if target_size_str:
        target_size_bytes = _parse_size(target_size_str)

    # auto-jobs: explicit -j / config wins, else smart default (CPU count)
    _jobs = getattr(parsed, 'jobs', None)
    if _jobs is None:
        _jobs = auto_jobs()

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
        lut_file=getattr(parsed, 'lut', None),
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
        jobs=_jobs,
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
                print(f"{_t('msg_config_load_err')}: {e}")
                return 1
            print(f"⚠️  {_t('msg_config_load_err')}: {e}", file=sys.stderr)

    # ── Collect files ───────────────────────────────────────────────────────
    file_patterns = getattr(parsed, 'files', None) or getattr(parsed, 'paths', [])
    recursive = getattr(parsed, 'recursive', False)
    files = _collect_files(file_patterns, recursive=recursive)

    if not files:
        print(_t("msg_no_images"))
        return 1

    is_json = getattr(parsed, 'json', False)
    jout = sys.stderr if is_json else sys.stdout

    print(_t("msg_files_found", n=len(files)), file=jout)
    for f in files:
        sz = format_size(os.path.getsize(f))
        print(f"    {f} ({sz})", file=jout)
    print(file=jout)

    # ── Dry run ─────────────────────────────────────────────────────────────
    if getattr(parsed, 'dry_run', False):
        if is_json:
            import json
            print(json.dumps(versioned({
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
            }), indent=2, ensure_ascii=False))
            return 0
        print(_t("msg_dry_run_settings"))
        print()
        print(_t("msg_settings_applied"))
        print(f"  {_t('msg_target_format')}: {options.output_format}")
        if options.target_size_bytes:
            print(f"  {_t('msg_target_size')}: {format_size(options.target_size_bytes)} {_t('msg_auto_tune')}")
            print(f"  {_t('msg_quality_max')}: {options.quality} {_t('msg_ceiling')}")
        else:
            print(f"  {_t('msg_quality_label')}: {options.quality}")
        if options.max_width or options.max_height:
            print(f"  {_t('msg_resize_label')}: {options.max_width or 'auto'}×{options.max_height or 'auto'}")
        if options.scale_percent:
            print(f"  {_t('msg_scale_label')}: {options.scale_percent}%")
        print(f"  {_t('msg_exif_label')}: {_t('msg_yes') if options.preserve_exif else _t('msg_no')}")
        print(f"  {_t('msg_optimize_label')}: {_t('msg_yes') if options.optimize else _t('msg_no')}")
        print(f"  {_t('msg_output_dir_label')}: {options.output_dir or _t('msg_same_as_source')}")
        if options.folder_pattern:
            print(f"  {_t('msg_subfolder')}: {options.folder_pattern}")
        return 0

    def progress_callback(current, total, path):
        if path:
            name = os.path.basename(path)
            print(f"  {_t('msg_processing', i=current, n=total, name=name)}",
                  end="\r", file=jout)
        else:
            print(f"  {_t('msg_done', n=total)}" + " " * 20, file=jout)

    # ── Safety check for --remove-original ──────────────────────────────────
    # In --json mode the caller is an agent with no stdin to confirm against;
    # passing --remove-original explicitly IS the confirmation, so skip the
    # prompt (otherwise input() hangs forever on a closed stdin).
    if (options.remove_original and not getattr(parsed, 'yes', False)
            and not is_json):
        print(_t("msg_confirm_delete", n=len(files)))
        try:
            confirm = input(f"   {_t('msg_confirm_continue')}").strip().lower()
        except EOFError:
            # stdin closed (pipe/agent): treat as refusal, not a traceback
            print(_t("msg_cancel_input_err"), file=sys.stderr)
            return 1
        if confirm not in ("y", "yes"):
            print(f"   {_t('msg_cancelled')}")
            return 0

    # ── Multi-profile batch run (--profiles web,thumb) ──────────────────────
    if getattr(parsed, 'profiles', None):
        from .presets import load_preset
        from dataclasses import asdict, replace

        names = [n.strip() for n in parsed.profiles.split(",") if n.strip()]
        if not names:
            print(_t("msg_profiles_need"))
            return 1

        if getattr(parsed, 'report', None):
            print(_t("msg_report_profiles_conflict"), file=sys.stderr)

        profile_results = {}
        failed_total = 0
        for name in names:
            base = load_preset(name)
            if base is None:
                print(_t("msg_preset_not_found_generic", name=name))
                return 1
            # Preset values win over CLI/config EXCEPT output_dir/suffix
            # (presets serialize stale directories — those come from CLI/config),
            # runtime fields (jobs/target_size_bytes), and serialized None
            # defaults (must not clobber explicit CLI/config values)
            fields = {k: v for k, v in asdict(base).items()
                      if k in ProcessOptions.__dataclass_fields__
                      and k not in ("output_dir", "suffix", "jobs",
                                    "target_size_bytes")
                      and v is not None}
            prof_opts = replace(options, **fields)
            prof_result = batch_process(files, prof_opts,
                                        progress_callback=progress_callback)
            profile_results[name] = prof_result
            failed_total += prof_result.fail_count
            if not is_json:
                print(f"\n{_t('msg_profile_start', name=name, n=len(files))}")
                _print_batch_summary(prof_result)

        if is_json:
            import json
            print(json.dumps(versioned({"profiles": {n: r.to_dict() for n, r in profile_results.items()}}),
                indent=2, ensure_ascii=False))
        return 0 if failed_total == 0 else 1

    # ── Execute ──────────────────────────────────────────────────────────────
    if not is_json:
        print(_t("msg_start_processing"))
        if options.target_size_bytes:
            lossy_fmts = {"JPEG", "WebP", "HEIC"}
            if options.output_format not in lossy_fmts:
                print(_t("msg_lossless_note", fmt=options.output_format))
            print(_t("msg_target_size_header", size=format_size(options.target_size_bytes)))
            print(f"   {_t('msg_quality_range', q=options.quality)}")
        print()

    result = batch_process(files, options, progress_callback=progress_callback)

    # ── Write CSV report if requested ───────────────────────────────────────
    if getattr(parsed, 'report', None):
        from .engine import _write_report
        try:
            _write_report(parsed.report, result)
        except OSError as e:
            print(f"{_t('msg_report_err')}: {e}", file=sys.stderr)

    # ── Print results ───────────────────────────────────────────────────────
    if is_json:
        import json
        print(json.dumps(versioned(result.to_dict()), indent=2, ensure_ascii=False))
    else:
        print()
        for r in result.results:
            _print_result(r)
            print()
        _print_batch_summary(result)

    return 0 if result.fail_count == 0 else 1


def _no_gui_msg() -> str:
    """Lite-build hint — rendered in the current language."""
    return (
        f"{_t('msg_no_gui')}\n"
        f"   {_t('msg_full_edition')}: "
        "https://github.com/Dongwu259/photo_s/releases")


def _gui_module_available() -> bool:
    """Whether the GUI module exists in this build.

    The lite executable excludes ``photo_s.gui`` at PyInstaller level, so
    this is False there; full wheels/exes always ship the module.
    """
    import importlib.util
    try:
        return importlib.util.find_spec("photo_s.gui") is not None
    except (ImportError, ValueError):
        return False


def _run_gui() -> bool:
    """Launch the GUI; print a hint and return False when this build /
    system has no GUI (lite exe, or tkinter missing)."""
    from . import i18n
    i18n.CURRENT_LANG = i18n.resolve_language(use_config=True, use_persisted=False)
    try:
        from .gui import run_gui
    except ImportError:
        print(_no_gui_msg(), file=sys.stderr)
        return False
    run_gui()
    return True


def main():
    """Entry point for the photo-s command.

    Dispatches to GUI if no args are given or first arg is 'gui',
    otherwise runs CLI mode. Builds without the GUI (lite) print a hint
    and fall back to --help / exit 1 instead of crashing on ImportError.
    """
    # Force UTF-8 console output: CLI status lines use emoji, which crashes
    # on Windows' default cp1252 code page (e.g. redirected/piped output).
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    if len(sys.argv) <= 1:
        if _run_gui():
            return 0
        try:
            run_cli(["--help"])
        except SystemExit as e:  # argparse --help raises SystemExit(0)
            return int(e.code or 0)
        return 0
    if sys.argv[1] == "gui":
        return 0 if _run_gui() else 1
    return run_cli(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
