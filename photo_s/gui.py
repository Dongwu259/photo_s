"""
PhotoS - Graphical User Interface

A macOS-native Tkinter application for batch image compression,
format conversion, and resizing.

Features:
  - Chinese / English UI language switching
  - Drag-and-drop file addition (via tkinterdnd2, optional)
  - File list with size/format/dimensions preview
  - Adjustable quality, format, resize options
  - Real-time progress tracking with cancellation
  - Batch summary with space savings and before/after comparison
"""

import os
import queue
import subprocess
import sys
import threading
import time
import webbrowser
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from typing import List

from . import watermark  # for POSITIONS on the watermark section

from .engine import (
    ProcessOptions,
    BatchResult,
    batch_process,
    scan_directory,
    format_size,
    _resolve_folder_pattern,
    SUPPORTED_FORMATS,
    INPUT_EXTENSIONS,
    ALL_INPUT_EXTENSIONS,
    RAW_EXTENSIONS,
)


# ── Optional drag-and-drop support ─────────────────────────────────────────

DND_AVAILABLE = False
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    DND_AVAILABLE = True
except ImportError:
    pass


# ── Constants ───────────────────────────────────────────────────────────────

APP_NAME = "PhotoS"
APP_VERSION = "1.1.0"
WINDOW_WIDTH = 1120
WINDOW_HEIGHT = 720
MIN_WIDTH = 980
MIN_HEIGHT = 640
SETTINGS_WIDTH = 400

# Color scheme — picked at import time from the system appearance.
# ttk controls on macOS use the native aqua theme and follow the system
# dark/light mode; a hardcoded light palette made dark-mode systems render
# dark native controls on a light background (the "black boxes" report).
# So the layout palette must match the system: light or dark.

_LIGHT_COLORS = {
    "bg": "#f5f5f7",
    "card": "#ffffff",
    "border": "#d2d2d7",
    "divider": "#e8e8ed",  # hairline separators / scroll troughs
    "text": "#1d1d1f",
    "text_secondary": "#6e6e73",
    "accent": "#007aff",
    "accent_hover": "#0062cc",
    "danger": "#d70015",
    "danger_hover": "#a80010",
    "success": "#248a3d",
    "warning": "#b25000",
    "row_alt": "#f7f7fa",
    "progress_bg": "#e5e5ea",
}

_DARK_COLORS = {
    "bg": "#1e1e1e",
    "card": "#2c2c2e",
    "border": "#48484a",
    "divider": "#3a3a3c",  # hairline separators / scroll troughs
    "text": "#f5f5f7",
    "text_secondary": "#a1a1a6",
    "accent": "#0a84ff",
    "accent_hover": "#409cff",
    "danger": "#ff453a",
    "danger_hover": "#ff6b61",
    "success": "#30d158",
    "warning": "#ff9f0a",
    "row_alt": "#262628",
    "progress_bg": "#3a3a3c",
}


def _system_dark_mode() -> bool:
    """Detect the OS appearance: True for dark mode.

    macOS: `defaults read -g AppleInterfaceStyle` → "Dark".
    Windows: AppsUseLightTheme registry value == 0.
    Linux/unknown: falls back to light, override with $PHOTOS_DARK=1.
    """
    env = os.environ.get("PHOTOS_DARK")
    if env is not None:
        return env.lower() in ("1", "true", "yes", "on")
    if sys.platform == "darwin":
        try:
            out = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True, text=True, timeout=5).stdout.strip()
            return out == "Dark"
        except Exception:
            return False
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return val == 0
        except Exception:
            return False
    return False


# Runtime-mutable palette: widgets read COLORS[key] at build time, so an
# in-place update followed by a UI rebuild switches the theme instantly.
COLORS = dict(_DARK_COLORS if _system_dark_mode() else _LIGHT_COLORS)


def _apply_palette(dark: bool) -> None:
    """Switch the active color palette (in-place; existing widgets unaffected
    until the UI is rebuilt)."""
    COLORS.clear()
    COLORS.update(_DARK_COLORS if dark else _LIGHT_COLORS)


# ── Cross-platform font detection ─────────────────────────────────────────────

def _detect_fonts():
    """Return the best UI fonts for the current platform.

    Uses well-known system fonts that are guaranteed to exist on each platform.
    Tk will silently fall back to its default if a font is missing.
    """
    if sys.platform == "darwin":
        return {"title": "Helvetica Neue", "body": "Helvetica Neue"}
    elif sys.platform == "win32":
        return {"title": "Segoe UI", "body": "Segoe UI"}
    else:  # Linux and others
        return {"title": "Noto Sans", "body": "Noto Sans"}

PLATFORM_FONTS = _detect_fonts()
FONT_TITLE = (PLATFORM_FONTS["title"], 22, "bold")
FONT_SECTION = (PLATFORM_FONTS["body"], 11, "bold")
FONT_BODY = (PLATFORM_FONTS["body"], 11)
FONT_SMALL = (PLATFORM_FONTS["body"], 10)
FONT_TINY = (PLATFORM_FONTS["body"], 9)
FONT_BUTTON = (PLATFORM_FONTS["body"], 11)
FONT_BUTTON_LG = (PLATFORM_FONTS["body"], 12, "bold")


# ── UI strings (zh / en) ─────────────────────────────────────────────────────

DEFAULT_LANG = "zh"

STRINGS = {
    "zh": {
        "window_title": "PhotoS — 图片批量压缩与格式转换",
        "subtitle": "批量图片压缩与格式转换工具",
        "about": "关于",
        "theme_toggle": "切换深色/浅色模式",
        # Toolbar / file list
        "add_images": "添加图片",
        "add_folder": "添加文件夹",
        "remove": "移除",
        "clear": "清除全部",
        "files_count": "{n} 个文件",
        "files_count_checked": "{n} 个文件 · 已勾选 {m} 个",
        "check_none": "请先勾选要处理的图片（勾选框切换，用「全选/全不选」按钮批量切换）",
        "check_toggle_all": "全选/全不选",
        "about_shortcuts": "快捷键 Shortcuts",
        "shortcuts_text": "⌘O / Ctrl+O 添加图片\n⌘⇧O / Ctrl+Shift+O 添加文件夹\n⌘R / Ctrl+R 开始处理（Esc 取消）\n⌘P / Ctrl+P 预览参数\n⌘E / Ctrl+E 审查打分\n⌘D / Ctrl+D 去重查看\n⌘G / Ctrl+G 导出画廊\n（审查窗口内：←/→ 翻页，0-5 评分，Esc 关闭）",
        "dlg_skipped": "已导入 {n} 张图片，跳过 {m} 个不支持的文件",
        "dlg_no_supported": "未找到支持的图片（跳过 {m} 个不支持的文件）",
        "hint_dnd": "将图片或文件夹拖入列表，或使用上方按钮添加",
        "hint_no_dnd": "使用上方按钮添加图片文件（安装 tkinterdnd2 可启用拖放）",
        "col_name": "文件名",
        "col_size": "大小",
        "col_format": "格式",
        "col_dims": "尺寸",
        # Settings sections
        "sec_format": "输出格式",
        "sec_mode": "压缩模式",
        "manual_quality": "手动质量",
        "target_size_mode": "目标大小",
        "quality": "质量",
        "max_quality": "最高质量上限",
        "target_size": "目标大小",
        "autotune_hint": "自动调整质量",
        "sec_resize": "缩放",
        "width": "宽",
        "height": "高",
        "pixels_hint": "像素，留空 = 不缩放",
        "scale": "缩放比例 %",
        "sec_output": "输出位置",
        "browse": "浏览…",
        "sec_naming": "文件命名",
        "prefix": "前缀",
        "suffix": "后缀",
        "smart_rename": "智能重命名",
        "rename_vars": "变量: {date} {camera} {original} {seq} {iso} {focal}",
        "sec_subfolder": "子文件夹",
        "template": "模板",
        "preset_flat": "不分类",
        "preset_date": "按日期",
        "preset_camera": "按相机",
        "preset_date_camera": "按日期+相机",
        "preset_custom": "自定义…",
        "custom": "自定义",
        "folder_vars": "留空 = 不分类。变量: {year} {month} {day} {date} {camera} {make}",
        "sec_options": "选项",
        "preserve_exif": "保留 EXIF 信息",
        "optimize": "优化压缩",
        "progressive": "渐进式 JPEG",
        "overwrite": "覆盖已存在文件",
        "auto_rotate": "按 EXIF 方向自动旋转",
        "raw_half_size": "RAW 半尺寸解码（更快）",
        "raw_auto_bright": "RAW 自动亮度",
        "delete_original": "处理后删除原文件",
        "strip_gps": "移除 GPS 位置信息",
        "keep_mtime": "保留修改时间",
        "max_pixels": "最长边像素上限",
        "max_pixels_hint": "像素，留空 = 不限制，仅缩小",
        "jobs": "并行线程",
        # Bottom bar
        "ready": "就绪 — 添加图片文件开始处理",
        "preview": "预览",
        "start": "开始处理",
        "cancel": "取消",
        "cancelling": "正在取消…",
        "processing": "正在处理…",
        "processing_item": "正在处理 [{cur}/{total}] {name}",
        "tuning": "调整质量中…",
        "cancelled_status": "已取消 — {ok} 个完成，{fail} 个失败/未处理",
        "done_status": "完成 — {ok}/{total} 成功，节省 {savings} ({pct}%)",
        "failed_status": "处理失败",
        "stats_result": "原始: {sin} → 压缩后: {sout}  |  节省 {pct}%",
        "stats_files": "已选择 {n} 个文件  |  总大小: {size}",
        "stats_files_only": "已选择 {n} 个文件",
        # Dialogs
        "dlg_no_files_title": "无文件",
        "dlg_no_files": "请先添加图片文件。",
        "dlg_confirm_clear_title": "确认清除",
        "dlg_confirm_clear": "确定要清除所有 {n} 个文件吗？",
        "dlg_added_title": "已添加",
        "dlg_added": "文件夹中的 {n} 个图片已在列表中。",
        "dlg_no_images_title": "未找到图片",
        "dlg_no_images": "该文件夹中没有支持的图片文件。",
        "dlg_drop_none": "拖入的内容中没有可添加的图片文件。",
        "dlg_confirm_delete_title": "确认删除",
        "dlg_confirm_delete": "处理完成后将删除 {n} 个原始文件！\n\n确定继续？",
        "dlg_error_title": "处理错误",
        "dlg_error": "批处理过程中发生错误:\n\n{err}",
        # Preview
        "preview_title": "预览",
        "preview_header": "预览 — 不会实际处理文件",
        "pv_files": "文件数量: {n}",
        "pv_format": "目标格式: {fmt}",
        "pv_target": "目标大小: {size}（自动调优）",
        "pv_qmax": "质量上限: {q}",
        "pv_quality": "质量: {q}",
        "pv_maxsize": "最大尺寸: {w}×{h}",
        "pv_scale": "缩放比例: {s}%",
        "pv_exif": "保留 EXIF: {yn}",
        "pv_optimize": "优化: {yn}",
        "pv_progressive": "渐进式: {yn}",
        "pv_overwrite": "覆盖: {yn}",
        "pv_outdir": "输出目录: {d}",
        "pv_outdir_same": "（与源文件相同）",
        "pv_subfolder": "子文件夹: {p}",
        "pv_prefix": "前缀: '{p}'",
        "pv_suffix": "后缀: '{s}'",
        "pv_total": "源文件总大小: {size}",
        "yes": "是",
        "no": "否",
        "auto": "自动",
        # Summary / comparison
        "summary_title": "处理完成",
        "sum_header": "处理完成",
        "sum_success": "成功",
        "sum_failed": "失败",
        "sum_original": "原始大小",
        "sum_compressed": "压缩后",
        "sum_saved": "节省",
        "sum_ask_compare": "显示压缩对比？",
        "sum_view_compare": "查看前后对比",
        "compare_title": "压缩对比",
        "compare_header": "压缩前后对比",
        "before": "原始",
        "after": "压缩后",
        "saved": "节省",
        "quality_lbl": "质量",
        "cannot_load": "无法加载",
        "close": "关闭",
        # Plugins
        "plugins": "插件",
        "plugins_title": "插件管理",
        "plugins_installed": "已安装插件",
        "plugins_available": "官方可用插件",
        "plugins_none": "（无）",
        "plugins_install": "安装",
        "plugins_uninstall": "卸载",
        "plugins_fetch": "预下载权重",
        "plugins_refresh": "刷新",
        "plugins_ok": "✅ {}",
        "plugins_err": "❌ {}",
        # Exposure analysis
        "analyze": "曝光分析",
        "review_btn": "审查打分",
        "dedup_btn": "去重",
        "gallery_btn": "画廊",
        "gallery_title": "导出画廊",
        "gallery_name": "画廊标题",
        "gallery_thumb": "缩略图尺寸",
        "gallery_out": "输出目录",
        "gallery_generate": "生成画廊",
        "gallery_generating": "生成中…",
        "gallery_done": "已生成 {count} 张 → {path}",
        "gallery_open": "在浏览器打开",
        "gallery_need_files": "请先添加图片",
        "gallery_need_dir": "请选择输出目录",
        "gallery_error": "生成失败: {err}",
        "op_failed": "操作失败: {err}",
        "dedup_title": "去重查看",
        "dedup_scanning": "扫描中… {n}/{total}",
        "dedup_none": "未发现重复图片",
        "dedup_group": "第 {i} 组",
        "dedup_keep": "保留",
        "dedup_sharpest": "★最锐",
        "dedup_blur": "锐度",
        "dedup_execute": "移入回收子文件夹",
        "dedup_moving": "移动中…",
        "dedup_moved": "已移动 {n} 张到 {dir}",
        "dedup_rescan": "重新扫描",
        "dedup_confirm": "将 {n} 张图片移动到回收子文件夹（不会删除），继续？",
        "dedup_none_selected": "没有要清理的图片（每组至少保留一张）",
        "review_title": "审查打分",
        "review_pos": "{i} / {n}",
        "review_loading": "读取元数据… {n}/{total}",
        "review_rating": "评分",
        "review_keywords": "关键词",
        "review_title_lbl": "标题",
        "review_save": "保存",
        "review_saved": "已保存",
        "review_save_failed": "写入失败: {err}",
        "review_filter": "过滤",
        "review_min_rating": "最低评分",
        "review_filter_kw": "关键词包含",
        "review_apply_filter": "应用过滤",
        "review_clear_filter": "清除过滤",
        "review_empty": "没有匹配的图片",
        "review_no_piexif": "⚠️ 未安装 piexif：只能查看，无法写入（pip install photo-s-tools[exif]）",
        "review_prev": "◀ 上一张",
        "review_next": "下一张 ▶",
        "review_none": "请先添加图片",
        "analyze_title": "曝光统计",
        "analyze_none": "请先在文件列表中选择一张图片",
        "analyze_err": "无法读取该图片",
        "analyze_luminance": "平均亮度",
        "analyze_over": "过曝 (≥250)",
        "analyze_under": "欠曝 (≤5)",
        "analyze_blur": "模糊分",
        "analyze_histogram": "亮度直方图",
        # Settings dialog (MCP + optional deps)
        "settings": "设置",
        "settings_title": "设置",
        "set_mcp": "MCP 服务器",
        "set_mcp_desc": "让 Claude Desktop 等 MCP 客户端直接调用 PhotoS 工具",
        "mcp_installed": "已安装",
        "mcp_missing": "未安装",
        "mcp_install_hint": "安装 Install: pip install 'photo-s-tools[mcp]'",
        "mcp_launch": "启动命令 Launch command",
        "mcp_claude_config": "Claude Desktop 配置 Claude Desktop config",
        "mcp_claude_snippet": (
            "{\n  \"mcpServers\": {\n    \"photo-s\": {\n"
            "      \"command\": \"photo-s\",\n      \"args\": [\"mcp\"]\n"
            "    }\n  }\n}"
        ),
        "copy": "复制",
        "copied": "已复制",
        "set_deps": "可选依赖 Optional dependencies",
        "dep_install": "安装",
        "dep_installing": "安装中…",
        "set_plugins_link": "打开插件管理器 Open Plugin Manager",
        # Watermark
        "sec_watermark": "水印",
        "wm_text": "文字",
        "wm_image": "图片",
        "wm_position": "位置",
        "wm_opacity": "透明度",
        # Multi-size
        "sec_sizes": "多尺寸输出",
        "sizes_hint": "格式 format: 标签:宽x高, e.g. thumb:480x,screen:1920x1080",
        # Adjust
        "sec_adjust": "影调调整",
        "brightness": "亮度",
        "contrast": "对比度",
        "saturation": "饱和度",
        "gamma": "伽马",
        "sharpen": "锐化",
        "grayscale": "黑白",
        "sepia": "复古",
        # Composition
        "sec_composition": "构图",
        "crop": "裁剪",
        "crop_hint": "格式 format: 宽x高+偏移 800x600+100+50",
        "crop_ratio": "比例裁剪",
        "rotate": "旋转°",
        "rotate_bg": "旋转底色",
        "flip": "翻转",
        "flip_hint": "h = 水平, v = 垂直",
        "pad": "留白比例",
        "pad_bg": "留白底色",
        "pad_hint": "e.g. 16:9, 1:1（空 = 不补边）",
        # Correction (exposure / LOG / denoise / straighten)
        "sec_correction": "校正",
        "ev": "曝光补偿 (EV)",
        "ev_hint": "EV 档位，2^EV 增益（0 = 不变）",
        "auto_exposure": "自动曝光目标 (0-1)",
        "auto_exposure_hint": "均值亮度归一化（空 = 关闭）",
        "log_curve": "LOG 还原",
        "log_curve_hint": "SLOG3/CLOG3/LOGC3/DLOG/VLOG/HLG（空 = 关闭）",
        "denoise": "降噪强度 (0-20)",
        "denoise_hint": "NLM 降噪（空 = 关闭；需 photo-s-tools[enhance] 或 SCUNet 插件）",
        "auto_straighten": "自动扶正地平线",
        "max_straighten_angle": "最大扶正角°",
        # White balance / color / evaluation
        "wb_temp": "白平衡色温 (K)",
        "wb_temp_hint": "如 5600；空 = 不调整",
        "wb_reference": "白平衡参考图",
        "wb_reference_hint": "灰卡图路径；空 = 不采样",
        "browse_ref": "浏览…",
        "auto_levels": "自动色阶（直方图拉伸）",
        "srgb": "转 sRGB 色彩空间",
        "flatten_cmyk": "CMYK 转 RGB",
        "evaluate": "计算 SSIM 质量评分",
        "blur_score": "计算模糊评分",
        "resume": "断点续传（跳过已处理文件）",
        "print_size": "打印尺寸",
        "print_size_hint": "如 8x10@300dpi；空 = 不裁剪",
        # Metadata
        "sec_metadata": "元数据",
        "date_shift": "EXIF 日期偏移",
        "date_shift_hint": "如 -5h30m；空 = 不改",
        "sync_date": "输出时间 ← EXIF 拍摄时间",
        "scrub": "清除全部元数据 (EXIF+ICC+GPS)",
        "gpx_trace": "GPX 轨迹文件",
        "gpx_trace_hint": "按拍摄时间插值写入 GPS；空 = 不写入",
        "browse_gpx": "浏览…",
        "cmp_no_result": "无对比结果",
        "cmp_no_result_body": "该文件尚未处理或处理失败。\nProcess this file first to compare before/after.",
        # About
        "about_title": "关于 PhotoS",
        "about_desc": "批量图片压缩与格式转换工具（命令行 + 图形界面）",
        "about_features": "功能特性",
        "about_feature_list": (
            "· 批量压缩 JPEG / PNG / WebP / TIFF / BMP / HEIC / AVIF\n"
            "· 支持相机 RAW 格式（需安装 rawpy）\n"
            "· 目标大小自动调优、缩放、智能重命名\n"
            "· 并行处理、EXIF 保留、子文件夹整理"
        ),
        "about_env": "运行环境",
        "about_deps": "可选组件",
        "dep_installed": "已安装",
        "dep_missing": "未安装",
        "about_license": "开源协议: MIT License",
    },
    "en": {
        "window_title": "PhotoS — Batch Image Compression & Conversion",
        "subtitle": "Batch Image Compression & Conversion",
        "about": "About",
        "theme_toggle": "Toggle dark/light mode",
        # Toolbar / file list
        "add_images": "Add Images",
        "add_folder": "Add Folder",
        "remove": "Remove",
        "clear": "Clear All",
        "files_count": "{n} files",
        "files_count_checked": "{n} files · {m} checked",
        "check_none": "Check the images to process first (use the checkboxes, or the check-all button)",
        "check_toggle_all": "Check all / none",
        "about_shortcuts": "Shortcuts 快捷键",
        "shortcuts_text": "⌘O / Ctrl+O Add images\n⌘⇧O / Ctrl+Shift+O Add folder\n⌘R / Ctrl+R Start processing (Esc cancels)\n⌘P / Ctrl+P Preview options\n⌘E / Ctrl+E Review & rate\n⌘D / Ctrl+D Duplicates\n⌘G / Ctrl+G Export gallery\n(In review: ←/→ navigate, 0-5 rate, Esc close)",
        "dlg_skipped": "Imported {n} images, skipped {m} unsupported files",
        "dlg_no_supported": "No supported images found (skipped {m} unsupported files)",
        "hint_dnd": "Drag & drop images/folders into the list, or use the buttons above",
        "hint_no_dnd": "Use the buttons above to add images (install tkinterdnd2 for drag & drop)",
        "col_name": "Name",
        "col_size": "Size",
        "col_format": "Format",
        "col_dims": "Dimensions",
        # Settings sections
        "sec_format": "Output Format",
        "sec_mode": "Compression Mode",
        "manual_quality": "Manual Quality",
        "target_size_mode": "Target Size",
        "quality": "Quality",
        "max_quality": "Max Quality",
        "target_size": "Target Size",
        "autotune_hint": "auto-tune quality",
        "sec_resize": "Resize",
        "width": "W",
        "height": "H",
        "pixels_hint": "pixels, blank = no resize",
        "scale": "Scale %",
        "sec_output": "Output Location",
        "browse": "Browse…",
        "sec_naming": "Naming",
        "prefix": "Prefix",
        "suffix": "Suffix",
        "smart_rename": "Smart Rename",
        "rename_vars": "vars: {date} {camera} {original} {seq} {iso} {focal}",
        "sec_subfolder": "Subfolder",
        "template": "Template",
        "preset_flat": "Flat (no grouping)",
        "preset_date": "By date",
        "preset_camera": "By camera",
        "preset_date_camera": "By date+camera",
        "preset_custom": "Custom…",
        "custom": "Custom",
        "folder_vars": "blank = flat. vars: {year} {month} {day} {date} {camera} {make}",
        "sec_options": "Options",
        "preserve_exif": "Preserve EXIF",
        "optimize": "Optimize",
        "progressive": "Progressive JPEG",
        "overwrite": "Overwrite existing files",
        "auto_rotate": "Auto-rotate (EXIF Orientation)",
        "raw_half_size": "RAW half-size decode (faster)",
        "raw_auto_bright": "RAW auto brightness",
        "delete_original": "Delete original after processing",
        "strip_gps": "Strip GPS data",
        "keep_mtime": "Keep file mtime",
        "max_pixels": "Max pixels (longest side)",
        "max_pixels_hint": "pixels, blank = no limit, downscale only",
        "jobs": "Parallel jobs",
        # Bottom bar
        "ready": "Ready — add images to begin",
        "preview": "Preview",
        "start": "Start",
        "cancel": "Cancel",
        "cancelling": "Cancelling…",
        "processing": "Processing…",
        "processing_item": "Processing [{cur}/{total}] {name}",
        "tuning": "Tuning quality…",
        "cancelled_status": "Cancelled — {ok} done, {fail} failed/skipped",
        "done_status": "Done — {ok}/{total} succeeded, saved {savings} ({pct}%)",
        "failed_status": "Processing failed",
        "stats_result": "Original: {sin} → Compressed: {sout}  |  Saved {pct}%",
        "stats_files": "{n} files selected  |  Total: {size}",
        "stats_files_only": "{n} files selected",
        # Dialogs
        "dlg_no_files_title": "No Files",
        "dlg_no_files": "Please add images first.",
        "dlg_confirm_clear_title": "Confirm Clear",
        "dlg_confirm_clear": "Clear all {n} files from the list?",
        "dlg_added_title": "Already Added",
        "dlg_added": "All {n} images from the folder are already in the list.",
        "dlg_no_images_title": "No Images",
        "dlg_no_images": "No supported image files found in this folder.",
        "dlg_drop_none": "No addable image files found in the dropped content.",
        "dlg_confirm_delete_title": "Confirm Delete",
        "dlg_confirm_delete": "{n} original file(s) will be deleted after processing!\n\nAre you sure?",
        "dlg_error_title": "Processing Error",
        "dlg_error": "An error occurred during batch processing:\n\n{err}",
        # Preview
        "preview_title": "Preview",
        "preview_header": "Preview — no files will be modified",
        "pv_files": "Files: {n}",
        "pv_format": "Format: {fmt}",
        "pv_target": "Target size: {size} (auto-tune)",
        "pv_qmax": "Quality max: {q}",
        "pv_quality": "Quality: {q}",
        "pv_maxsize": "Max size: {w}×{h}",
        "pv_scale": "Scale: {s}%",
        "pv_exif": "Preserve EXIF: {yn}",
        "pv_optimize": "Optimize: {yn}",
        "pv_progressive": "Progressive: {yn}",
        "pv_overwrite": "Overwrite: {yn}",
        "pv_outdir": "Output dir: {d}",
        "pv_outdir_same": "(same as source)",
        "pv_subfolder": "Subfolder: {p}",
        "pv_prefix": "Prefix: '{p}'",
        "pv_suffix": "Suffix: '{s}'",
        "pv_total": "Total source size: {size}",
        "yes": "Yes",
        "no": "No",
        "auto": "auto",
        # Summary / comparison
        "summary_title": "Complete",
        "sum_header": "Processing Complete",
        "sum_success": "Successful",
        "sum_failed": "Failed",
        "sum_original": "Original",
        "sum_compressed": "Compressed",
        "sum_saved": "Saved",
        "sum_ask_compare": "Show before/after comparison?",
        "sum_view_compare": "View comparison",
        "compare_title": "Comparison",
        "compare_header": "Before & After",
        "before": "Original",
        "after": "Compressed",
        "saved": "Saved",
        "quality_lbl": "Quality",
        "cannot_load": "Cannot load",
        "close": "Close",
        # Plugins
        "plugins": "Plugins",
        "plugins_title": "Plugin Manager",
        "plugins_installed": "Installed plugins",
        "plugins_available": "Available official plugins",
        "plugins_none": "(none)",
        "plugins_install": "Install",
        "plugins_uninstall": "Uninstall",
        "plugins_fetch": "Fetch weights",
        "plugins_refresh": "Refresh",
        "plugins_ok": "✅ {}",
        "plugins_err": "❌ {}",
        # Exposure analysis
        "analyze": "Exposure analysis",
        "review_btn": "Review & Rate",
        "dedup_btn": "Duplicates",
        "gallery_btn": "Gallery",
        "gallery_title": "Export Gallery",
        "gallery_name": "Gallery title",
        "gallery_thumb": "Thumbnail size",
        "gallery_out": "Output directory",
        "gallery_generate": "Generate",
        "gallery_generating": "Generating…",
        "gallery_done": "Generated {count} images → {path}",
        "gallery_open": "Open in browser",
        "gallery_need_files": "Add images first",
        "gallery_need_dir": "Choose an output directory",
        "gallery_error": "Failed: {err}",
        "op_failed": "Operation failed: {err}",
        "dedup_title": "Duplicate Viewer",
        "dedup_scanning": "Scanning… {n}/{total}",
        "dedup_none": "No duplicates found",
        "dedup_group": "Group {i}",
        "dedup_keep": "Keep",
        "dedup_sharpest": "★sharpest",
        "dedup_blur": "blur",
        "dedup_execute": "Move unchecked to trash",
        "dedup_moving": "Moving…",
        "dedup_moved": "Moved {n} images to {dir}",
        "dedup_rescan": "Rescan",
        "dedup_confirm": "Move {n} images to a trash subfolder (nothing is deleted). Continue?",
        "dedup_none_selected": "Nothing to clean up (every group must keep at least one image)",
        "review_title": "Review & Rate",
        "review_pos": "{i} / {n}",
        "review_loading": "Reading metadata… {n}/{total}",
        "review_rating": "Rating",
        "review_keywords": "Keywords",
        "review_title_lbl": "Title",
        "review_save": "Save",
        "review_saved": "Saved",
        "review_save_failed": "Write failed: {err}",
        "review_filter": "Filter",
        "review_min_rating": "Min rating",
        "review_filter_kw": "Keyword contains",
        "review_apply_filter": "Apply",
        "review_clear_filter": "Clear",
        "review_empty": "No matching images",
        "review_no_piexif": "⚠️ piexif not installed: view only (pip install photo-s-tools[exif])",
        "review_prev": "◀ Prev",
        "review_next": "Next ▶",
        "review_none": "Add images first",
        "analyze_title": "Exposure Stats",
        "analyze_none": "Select an image in the file list first",
        "analyze_err": "Cannot read that image",
        "analyze_luminance": "Mean luminance",
        "analyze_over": "Overexposed (≥250)",
        "analyze_under": "Underexposed (≤5)",
        "analyze_blur": "Blur score",
        "analyze_histogram": "Luminance histogram",
        # Settings dialog (MCP + optional deps)
        "settings": "Settings",
        "settings_title": "Settings",
        "set_mcp": "MCP Server",
        "set_mcp_desc": "Let MCP clients (Claude Desktop, agents) call PhotoS tools",
        "mcp_installed": "Installed",
        "mcp_missing": "Not installed",
        "mcp_install_hint": "Install: pip install 'photo-s-tools[mcp]'",
        "mcp_launch": "Launch command",
        "mcp_claude_config": "Claude Desktop config",
        "mcp_claude_snippet": (
            "{\n  \"mcpServers\": {\n    \"photo-s\": {\n"
            "      \"command\": \"photo-s\",\n      \"args\": [\"mcp\"]\n"
            "    }\n  }\n}"
        ),
        "copy": "Copy",
        "copied": "Copied",
        "set_deps": "Optional dependencies",
        "dep_install": "Install",
        "dep_installing": "Installing…",
        "set_plugins_link": "Open Plugin Manager",
        # Watermark
        "sec_watermark": "Watermark",
        "wm_text": "Text",
        "wm_image": "Image",
        "wm_position": "Position",
        "wm_opacity": "Opacity",
        # Multi-size
        "sec_sizes": "Multi-size",
        "sizes_hint": "format: label:WxH, e.g. thumb:480x,screen:1920x1080",
        # Adjust
        "sec_adjust": "Adjust",
        "brightness": "Brightness",
        "contrast": "Contrast",
        "saturation": "Saturation",
        "gamma": "Gamma",
        "sharpen": "Sharpen",
        "grayscale": "Grayscale",
        "sepia": "Sepia",
        # Composition
        "sec_composition": "Composition",
        "crop": "Crop",
        "crop_hint": "format: WxH+X+Y, e.g. 800x600+100+50",
        "crop_ratio": "Crop ratio",
        "rotate": "Rotate°",
        "rotate_bg": "Rotate fill",
        "flip": "Flip",
        "flip_hint": "h = horizontal, v = vertical",
        "pad": "Pad ratio",
        "pad_bg": "Pad bg",
        "pad_hint": "e.g. 16:9, 1:1 (blank = no padding)",
        # Correction (exposure / LOG / denoise / straighten)
        "sec_correction": "Correction",
        "ev": "Exposure (EV)",
        "ev_hint": "EV stops, 2^EV gain (0 = unchanged)",
        "auto_exposure": "Auto-exposure target (0-1)",
        "auto_exposure_hint": "Normalize mean luminance (blank = off)",
        "log_curve": "LOG recovery",
        "log_curve_hint": "SLOG3/CLOG3/LOGC3/DLOG/VLOG/HLG (blank = off)",
        "denoise": "Denoise strength (0-20)",
        "denoise_hint": "NLM denoise (blank = off; needs photo-s-tools[enhance] or SCUNet plugin)",
        "auto_straighten": "Auto-straighten horizon",
        "max_straighten_angle": "Max straighten angle°",
        # White balance / color / evaluation
        "wb_temp": "White balance temp (K)",
        "wb_temp_hint": "e.g. 5600; blank = off",
        "wb_reference": "WB reference image",
        "wb_reference_hint": "gray-card path; blank = no sampling",
        "browse_ref": "Browse…",
        "auto_levels": "Auto levels (histogram stretch)",
        "srgb": "Convert to sRGB",
        "flatten_cmyk": "Flatten CMYK → RGB",
        "evaluate": "Compute SSIM score",
        "blur_score": "Compute blur score",
        "resume": "Resume (skip already-processed files)",
        "print_size": "Print size",
        "print_size_hint": "e.g. 8x10@300dpi; blank = no crop",
        # Metadata
        "sec_metadata": "Metadata",
        "date_shift": "EXIF date shift",
        "date_shift_hint": "e.g. -5h30m; blank = off",
        "sync_date": "Output mtime ← EXIF datetime",
        "scrub": "Strip ALL metadata (EXIF+ICC+GPS)",
        "gpx_trace": "GPX track file",
        "gpx_trace_hint": "interpolate GPS from timestamps; blank = off",
        "browse_gpx": "Browse…",
        "cmp_no_result": "No comparison",
        "cmp_no_result_body": "This file was not processed yet (or failed).\nProcess it first to compare before/after.",
        # About
        "about_title": "About PhotoS",
        "about_desc": "Batch image compression & format conversion tool (CLI + GUI)",
        "about_features": "Features",
        "about_feature_list": (
            "· Batch compress JPEG / PNG / WebP / TIFF / BMP / HEIC / AVIF\n"
            "· Camera RAW support (requires rawpy)\n"
            "· Target-size auto-tuning, resizing, smart renaming\n"
            "· Parallel processing, EXIF preservation, subfolder organization"
        ),
        "about_env": "Environment",
        "about_deps": "Optional Components",
        "dep_installed": "installed",
        "dep_missing": "not installed",
        "about_license": "License: MIT License",
    },
}


# ── Flat button (renders colors correctly on macOS Aqua) ─────────────────────

class FlatButton(tk.Canvas):
    """A flat, rounded-pill button that honors colors on every platform.

    tk.Button on macOS Aqua ignores custom colors entirely, so the button is
    drawn on a Canvas: a rounded rectangle (polygon with smooth corners)
    plus centered text. Hover swaps the fill, a disabled state greys the
    button and blocks clicks. ``configure(text=..., bg=..., fg=...,
    state=...)`` keeps the classic widget API so callers (e.g. the
    copy-flash in the settings dialog) need no changes.
    """

    def __init__(self, master, text, command, bg, fg="white",
                 hover_bg=None, font=None, padx=16, pady=7,
                 border_color=None):
        self._command = command
        self._bg = bg
        self._fg = fg
        self._hover_bg = hover_bg or bg
        self._border = border_color
        self._font = font or FONT_BUTTON
        self._padx, self._pady = padx, pady
        self._state = "normal"
        self._text = text
        self._fill = bg  # current rendered fill (hover-aware)
        try:
            super().__init__(
                master, bg=master.cget("bg"), highlightthickness=0, bd=0,
                cursor="pointinghand",
            )
        except Exception:
            # Some environments (e.g. headless Xvfb) lack the 'pointinghand'
            # cursor; degrade to the default cursor instead of failing.
            super().__init__(
                master, bg=master.cget("bg"), highlightthickness=0, bd=0,
            )
        self._measure_and_redraw()
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

    # ── internals ─────────────────────────────────────────────────────────

    def _measure_and_redraw(self):
        """Size the canvas to the text, then (re)draw the pill + label."""
        f = tkfont.Font(font=self._font)
        w = f.measure(self._text) + 2 * self._padx + 4
        h = f.metrics("linespace") + 2 * self._pady
        # bypass the FlatButton.configure override (avoid recursion)
        tk.Canvas.configure(self, width=w, height=h)
        self.delete("all")
        radius = h // 2  # full pill
        pts = [radius, 1, w - radius, 1, w - 1, 1, w - 1, radius,
               w - 1, h - radius, w - 1, h - 1, w - radius, h - 1,
               radius, h - 1, 1, h - 1, 1, h - radius, 1, radius, 1, 1]
        fill = COLORS["border"] if self._state == "disabled" else self._fill
        outline = self._border or fill
        self.create_polygon(pts, smooth=True, fill=fill, outline=outline)
        text_color = (COLORS["text_secondary"] if self._state == "disabled"
                      else self._fg)
        self.create_text(w / 2, h / 2, text=self._text, fill=text_color,
                         font=self._font)

    def configure(self, cnf=None, **kw):
        if isinstance(cnf, dict):
            kw.update(cnf)
        changed = bool(kw)
        old_bg, old_hover = self._bg, self._hover_bg
        for key in ("text", "bg", "fg", "hover_bg", "border_color"):
            if key in kw:
                setattr(self, "_" + key, kw.pop(key))
        # keep the rendered fill in sync with new colors
        if self._fill == old_bg:
            self._fill = self._bg  # idle → follow the new base color
        if self._fill == old_hover:
            self._fill = self._hover_bg  # hovering → new hover color
        if "state" in kw:
            self._state = kw.pop("state")
        if kw:
            tk.Canvas.configure(self, **kw)
        if changed:
            self._measure_and_redraw()

    config = configure

    def cget(self, key):
        if key == "state":
            return self._state
        if key == "text":
            return self._text
        if key == "bg":
            return self._fill
        if key == "fg":
            return self._fg
        return super().cget(key)

    def _is_enabled(self):
        return self._state != "disabled"

    def _on_enter(self, _event):
        if self._is_enabled() and self._fill != self._hover_bg:
            self._fill = self._hover_bg
            self._measure_and_redraw()

    def _on_leave(self, _event):
        if self._fill != self._bg:
            self._fill = self._bg
            self._measure_and_redraw()

    def _on_click(self, _event):
        if self._is_enabled() and self._command:
            self._command()


def _open_image_safe(path):
    """Open a PhotoS-supported image for GUI display (PIL cannot open
    RAW — falls back to the engine loader which handles rawpy/HEIC
    with fallbacks). Raises on anything unreadable; callers catch."""
    from PIL import Image
    try:
        return Image.open(path)
    except Exception:
        from .engine import _get_image
        return _get_image(path)


def canvas_unbind_safe(widget):
    """Drop any leftover global mousewheel binding from a destroyed panel.

    bind_all is interp-global: destroying the settings card does not remove
    its handler, and a stale one would target a destroyed canvas. Called at
    the top of every settings-panel build.
    """
    try:
        widget.unbind_all("<MouseWheel>")
    except Exception:
        pass


# ── Main Application ────────────────────────────────────────────────────────

class PhotoSApp:
    """Main application window."""

    def __init__(self, root):
        self.root = root
        self.lang = DEFAULT_LANG
        self.dark_mode = _system_dark_mode()
        # COLORS is module-global and may be left flipped by a previous
        # app instance (e.g. tests, or embedding PhotoSApp twice in one
        # process) — re-apply the palette so the build always matches
        # THIS instance's dark_mode.
        _apply_palette(self.dark_mode)
        self.root.title(self._t("window_title"))
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.root.minsize(MIN_WIDTH, MIN_HEIGHT)
        self.root.configure(bg=COLORS["bg"])

        # State
        self.files: List[str] = []
        # Checked subset of self.files (first Treeview column). All
        # workflow actions — process / review / dedup / gallery — operate
        # on the checked files, not on the row selection (which stays an
        # ephemeral multi-select for remove/analyze). New files are
        # checked by default. Survives language/theme rebuilds.
        self._checked: set = set()
        # Ephemeral row selection (highlight) for remove/analyze/compare.
        # Distinct from _checked on purpose: checks define the action
        # scope, selection is a temporary multi-mark like the old
        # Treeview selection.
        self._selected_rows: set = set()
        self.processing = False
        self.cancel_requested = False
        self.output_dir = tk.StringVar(value="")
        self.prefix = tk.StringVar(value="")
        self.suffix = tk.StringVar(value="_compressed")
        self.quality = tk.IntVar(value=85)
        self.output_format = tk.StringVar(value="JPEG")
        self.scale_percent = tk.StringVar(value="")
        self.max_width = tk.StringVar(value="")
        self.max_height = tk.StringVar(value="")
        self.preserve_exif = tk.BooleanVar(value=True)
        self.optimize = tk.BooleanVar(value=True)
        self.progressive = tk.BooleanVar(value=False)
        self.overwrite = tk.BooleanVar(value=False)
        self.target_size_mode = tk.BooleanVar(value=False)
        self.target_size_value = tk.StringVar(value="500")
        self.target_size_unit = tk.StringVar(value="KB")
        self.raw_half_size = tk.BooleanVar(value=False)
        self.raw_auto_bright = tk.BooleanVar(value=True)
        self.auto_rotate = tk.BooleanVar(value=True)
        self.remove_original = tk.BooleanVar(value=False)
        self.strip_gps = tk.BooleanVar(value=False)
        self.keep_mtime = tk.BooleanVar(value=False)
        self.max_pixels = tk.StringVar(value="")  # longest-side cap (downscale only)
        # Watermark
        self.watermark_text = tk.StringVar(value="")
        self.watermark_image = tk.StringVar(value="")
        self.watermark_position = tk.StringVar(value="BOTTOM_RIGHT")
        self.watermark_opacity = tk.IntVar(value=50)
        # Multi-size
        self.output_sizes = tk.StringVar(value="")
        # Adjust (tone & color)
        self.brightness = tk.DoubleVar(value=1.0)
        self.contrast = tk.DoubleVar(value=1.0)
        self.saturation = tk.DoubleVar(value=1.0)
        self.gamma = tk.DoubleVar(value=1.0)
        self.sharpen = tk.DoubleVar(value=1.0)
        self.grayscale = tk.BooleanVar(value=False)
        self.sepia = tk.BooleanVar(value=False)
        # Correction (exposure / LOG / denoise / straighten)
        self.ev = tk.DoubleVar(value=0.0)
        self.auto_exposure = tk.StringVar(value="")
        self.log_curve = tk.StringVar(value="")
        self.denoise = tk.StringVar(value="")
        self.auto_straighten = tk.BooleanVar(value=False)
        self.max_straighten_angle = tk.StringVar(value="10")
        # White balance / color / evaluation
        self.wb_temp = tk.StringVar(value="")
        self.wb_reference = tk.StringVar(value="")
        self.auto_levels = tk.BooleanVar(value=False)
        self.srgb = tk.BooleanVar(value=False)
        self.flatten_cmyk = tk.BooleanVar(value=False)
        self.evaluate = tk.BooleanVar(value=False)
        self.blur_score = tk.BooleanVar(value=False)
        self.resume = tk.BooleanVar(value=False)
        self.print_size = tk.StringVar(value="")
        # Metadata
        self.date_shift = tk.StringVar(value="")
        self.sync_date = tk.BooleanVar(value=False)
        self.scrub = tk.BooleanVar(value=False)
        self.gpx_trace = tk.StringVar(value="")
        # Composition
        self.crop = tk.StringVar(value="")
        self.crop_ratio = tk.StringVar(value="")
        self.rotate = tk.StringVar(value="")
        self.rotate_bg = tk.StringVar(value="")
        self.flip = tk.StringVar(value="")
        self.pad_ratio = tk.StringVar(value="")
        self.pad_bg = tk.StringVar(value="#000000")
        # Queue + comparison state
        self._queued_files: List[str] = []
        self._last_result = None
        # (path, size, mtime) -> "WxH" cache for the file list; opening every
        # image on each refresh freezes the UI on RAW files
        self._dims_cache: dict = {}
        self.rename_pattern = tk.StringVar(value="")
        self.folder_pattern = tk.StringVar(value="")
        self.jobs = tk.StringVar(value="4")  # parallel workers

        self._configure_ttk_styles()

        # Build UI
        self._build_ui()
        self._bind_global_shortcuts()

        # Periodic update for progress polling
        self._progress_lock = threading.Lock()
        self._progress_current = 0
        self._progress_total = 0
        self._progress_path = ""
        self._progress_status = ""
        self._batch_result = None
        self._batch_error = None
        self._after_id = None

    # ── Localization ────────────────────────────────────────────────────────

    def _t(self, key, **kwargs):
        """Look up a UI string in the current language."""
        text = STRINGS[self.lang].get(key) or STRINGS[DEFAULT_LANG].get(key) or key
        return text.format(**kwargs) if kwargs else text

    def _set_language(self, lang):
        """Switch UI language by rebuilding the interface.

        All user state lives in tk Variables and self.files, so a rebuild
        loses nothing. The language combobox is disabled while processing
        (via _toggle_settings), so a rebuild can never interrupt a batch.
        """
        if lang == self.lang:
            return
        self.lang = lang
        self.root.title(self._t("window_title"))

        for child in self.root.winfo_children():
            child.destroy()
        self._build_ui()

        # Re-apply dynamic state to the freshly built widgets
        self._refresh_file_list()
        self._on_mode_change()
        self._update_stats()
        if not self.processing:
            self.progress_label.config(
                text=self._t("ready"), fg=COLORS["text_secondary"])

    def _bind_global_shortcuts(self):
        """App-wide accelerator keys (Cmd on macOS / Ctrl elsewhere —
        both bound since Tk accepts either). Modifier chords never
        collide with typing in entries. Review/dedup/gallery/start are
        locked out during processing (the toolbar buttons are too);
        add-file/add-folder stay available for queueing. Root bindings
        survive language/theme rebuilds (the root is never destroyed)."""

        def wrap(fn, allow_during_processing=False):
            def handler(event=None):
                if self.processing and not allow_during_processing:
                    return
                fn()
            return handler

        binds = [
            ("<Command-o>", self._add_files, True),
            ("<Control-o>", self._add_files, True),
            ("<Command-O>", self._add_folder, True),
            ("<Control-O>", self._add_folder, True),
            ("<Command-r>", lambda: self._start_processing(), False),
            ("<Control-r>", lambda: self._start_processing(), False),
            ("<Command-p>", self._preview, False),
            ("<Control-p>", self._preview, False),
            ("<Command-e>", self._show_review, False),
            ("<Control-e>", self._show_review, False),
            ("<Command-d>", self._show_dedup, False),
            ("<Control-d>", self._show_dedup, False),
            ("<Command-g>", self._show_gallery_export, False),
            ("<Control-g>", self._show_gallery_export, False),
        ]
        for seq, fn, allow in binds:
            self.root.bind(seq, wrap(fn, allow))
        self.root.bind("<Escape>", self._on_global_escape)

    def _on_global_escape(self, event=None):
        """Esc cancels a running batch from the main window. Events in
        Toplevels never reach the root binding, so dialog-level Escape
        handlers keep working."""
        if self.processing:
            self._cancel_processing()

    def _toggle_theme(self):
        """Flip between dark and light palette (manual override of the
        system appearance). Rebuilds the UI like _set_language — all state
        lives in tk Variables, so nothing is lost."""
        self.dark_mode = not self.dark_mode
        _apply_palette(self.dark_mode)
        self._configure_ttk_styles()  # styles persist — must follow the palette
        self.root.configure(bg=COLORS["bg"])
        for child in self.root.winfo_children():
            child.destroy()
        self._build_ui()
        self._refresh_file_list()
        self._on_mode_change()
        self._update_stats()
        if not self.processing:
            self.progress_label.config(
                text=self._t("ready"), fg=COLORS["text_secondary"])

    def _on_language_selected(self, _event=None):
        display = self.lang_combo.get()
        self._set_language("zh" if display == "中文" else "en")

    def _configure_ttk_styles(self):
        """Tune ttk widget appearance for a cleaner look.

        Runs at startup AND after every theme switch — ttk styles persist
        across widget rebuilds, so stale style colors would leave widgets
        (entries, sliders, comboboxes, treeview) stuck on the previous
        palette. Also switches to the 'clam' theme: the macOS-native
        'aqua' theme draws most ttk widgets with native controls that
        follow the OS appearance and ignore style colors entirely.
        """
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass  # clam ships with every Tk; never fail on it
        style.configure("Treeview", rowheight=26, font=FONT_BODY,
                        fieldbackground=COLORS["card"],
                        background=COLORS["card"],
                        foreground=COLORS["text"],
                        relief="flat", borderwidth=0)
        style.configure("Treeview.Heading", font=FONT_SMALL, padding=(4, 5),
                        background=COLORS["card"], foreground=COLORS["text"],
                        relief="flat")
        style.map("Treeview", background=[("selected", COLORS["accent"])],
                  foreground=[("selected", "white")])
        style.configure("TCombobox", padding=2, fieldbackground=COLORS["card"],
                        background=COLORS["card"], foreground=COLORS["text"],
                        arrowcolor=COLORS["text_secondary"],
                        bordercolor=COLORS["border"])
        style.map("TCombobox",
                  fieldbackground=[("readonly", COLORS["card"])],
                  selectbackground=[("readonly", COLORS["accent"])],
                  selectforeground=[("readonly", "white")])
        style.configure("TEntry", fieldbackground=COLORS["card"],
                        foreground=COLORS["text"],
                        insertcolor=COLORS["text"],
                        bordercolor=COLORS["border"],
                        lightcolor=COLORS["border"],
                        darkcolor=COLORS["border"])
        style.configure("TScale", background=COLORS["accent"],
                        troughcolor=COLORS["divider"])
        style.configure("TCheckbutton", background=COLORS["card"],
                        foreground=COLORS["text"], focuscolor=COLORS["card"])
        style.configure("TRadiobutton", background=COLORS["card"],
                        foreground=COLORS["text"], focuscolor=COLORS["card"])
        style.configure("TProgressbar", background=COLORS["accent"],
                        troughcolor=COLORS["progress_bg"],
                        bordercolor=COLORS["progress_bg"],
                        lightcolor=COLORS["accent"],
                        darkcolor=COLORS["accent"])
        # Arrow-less slim scrollbars (modern look): redefine the clam layout
        # to trough + thumb only.
        for orient in ("Vertical", "Horizontal"):
            style.layout(
                orient + ".TScrollbar",
                [(orient + ".Scrollbar.trough",
                  {"children": [(orient + ".Scrollbar.thumb",
                                 {"expand": "1", "sticky": "nswe"})],
                   "sticky": "ns" if orient == "Vertical" else "we"})])
            style.configure(
                orient + ".TScrollbar", background=COLORS["border"],
                troughcolor=COLORS["card"],
                arrowcolor=COLORS["text_secondary"],
                bordercolor=COLORS["card"], lightcolor=COLORS["card"],
                darkcolor=COLORS["card"])

    # ── UI Construction ─────────────────────────────────────────────────────

    def _build_ui(self):
        """Build the entire UI layout."""
        # ── Title bar ───────────────────────────────────────────────────────
        title_frame = tk.Frame(self.root, bg=COLORS["bg"])
        title_frame.pack(fill="x", padx=22, pady=(18, 0))

        title_label = tk.Label(
            title_frame, text=APP_NAME,
            font=FONT_TITLE, fg=COLORS["text"], bg=COLORS["bg"],
        )
        title_label.pack(side="left")

        version_label = tk.Label(
            title_frame, text=f"v{APP_VERSION}",
            font=FONT_SMALL, fg=COLORS["text_secondary"], bg=COLORS["bg"],
        )
        version_label.pack(side="left", padx=(8, 0), pady=(8, 0))

        subtitle_label = tk.Label(
            title_frame, text=self._t("subtitle"),
            font=FONT_SMALL, fg=COLORS["text_secondary"], bg=COLORS["bg"],
        )
        subtitle_label.pack(side="left", padx=(16, 0), pady=(8, 0))

        # About button (right side)
        about_btn = FlatButton(
            title_frame, text=self._t("about"), command=self._show_about,
            bg=COLORS["bg"], fg=COLORS["text_secondary"],
            hover_bg=COLORS["divider"], font=FONT_SMALL, padx=10, pady=4,
        )
        about_btn.pack(side="right", pady=(6, 0))

        # Plugins button (right side, next to About)
        plugins_btn = FlatButton(
            title_frame, text=self._t("plugins"), command=self._show_plugin_manager,
            bg=COLORS["bg"], fg=COLORS["text_secondary"],
            hover_bg=COLORS["divider"], font=FONT_SMALL, padx=10, pady=4,
        )
        plugins_btn.pack(side="right", pady=(6, 0))

        # Settings button (right side)
        settings_btn = FlatButton(
            title_frame, text=self._t("settings"), command=self._show_settings,
            bg=COLORS["bg"], fg=COLORS["text_secondary"],
            hover_bg=COLORS["divider"], font=FONT_SMALL, padx=10, pady=4,
        )
        settings_btn.pack(side="right", pady=(6, 0))

        # Language selector (right side)
        self.lang_combo = ttk.Combobox(
            title_frame, values=["中文", "English"], state="readonly",
            font=FONT_SMALL, width=8,
        )
        self.lang_combo.current(0 if self.lang == "zh" else 1)
        self.lang_combo.bind("<<ComboboxSelected>>", self._on_language_selected)
        self.lang_combo.pack(side="right", padx=(0, 8), pady=(6, 0))

        # Theme toggle (right side, before language)
        theme_icon = "☀️" if self.dark_mode else "🌙"
        theme_btn = FlatButton(
            title_frame, text=theme_icon, command=self._toggle_theme,
            bg=COLORS["bg"], fg=COLORS["text_secondary"],
            hover_bg=COLORS["divider"], font=FONT_SMALL, padx=8, pady=4,
        )
        theme_btn.pack(side="right", padx=(0, 4), pady=(6, 0))

        # ── Main content area (two columns) ─────────────────────────────────
        main_frame = tk.Frame(self.root, bg=COLORS["bg"])
        main_frame.pack(fill="both", expand=True, padx=22, pady=14)

        # Right column: settings — packed FIRST so its fixed width is always
        # honored; the file list gets whatever space remains
        right_frame = tk.Frame(main_frame, bg=COLORS["bg"], width=SETTINGS_WIDTH)
        right_frame.pack(side="right", fill="y", padx=(8, 0))
        right_frame.pack_propagate(False)

        self._build_settings_panel(right_frame)

        # Left column: file list
        left_frame = tk.Frame(main_frame, bg=COLORS["bg"])
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 8))

        self._build_file_panel(left_frame)

        # ── Bottom: progress and actions ────────────────────────────────────
        bottom_frame = tk.Frame(self.root, bg=COLORS["bg"])
        bottom_frame.pack(fill="x", padx=22, pady=(0, 18))

        self._build_bottom_panel(bottom_frame)

    def _build_file_panel(self, parent):
        """Build the left-side file list panel."""
        # Card container
        card = tk.Frame(parent, bg=COLORS["card"], bd=0, highlightthickness=0)
        card.pack(fill="both", expand=True)

        # Toolbar
        toolbar = tk.Frame(card, bg=COLORS["card"])
        toolbar.pack(fill="x", padx=14, pady=(14, 0))

        self.add_files_btn = FlatButton(
            toolbar, text=self._t("add_images"), command=self._add_files,
            bg=COLORS["accent"], hover_bg=COLORS["accent_hover"],
        )
        self.add_files_btn.pack(side="left")

        self.add_folder_btn = FlatButton(
            toolbar, text=self._t("add_folder"), command=self._add_folder,
            bg=COLORS["card"], fg=COLORS["accent"], hover_bg=COLORS["bg"],
            border_color=COLORS["border"],
        )
        self.add_folder_btn.pack(side="left", padx=(8, 0))

        remove_btn = FlatButton(
            toolbar, text=self._t("remove"), command=self._remove_selected,
            bg=COLORS["card"], fg=COLORS["danger"], hover_bg=COLORS["bg"],
            border_color=COLORS["border"],
        )
        remove_btn.pack(side="left", padx=(8, 0))

        FlatButton(
            toolbar, text=self._t("check_toggle_all"),
            command=self._toggle_all_checks,
            bg=COLORS["card"], fg=COLORS["text"], hover_bg=COLORS["bg"],
            border_color=COLORS["border"], font=FONT_SMALL,
        ).pack(side="left", padx=(8, 0))

        clear_btn = FlatButton(
            toolbar, text=self._t("clear"), command=self._clear_files,
            bg=COLORS["card"], fg=COLORS["text_secondary"], hover_bg=COLORS["bg"],
            border_color=COLORS["border"],
        )
        clear_btn.pack(side="right")

        analyze_btn = FlatButton(
            toolbar, text=self._t("analyze"), command=self._show_analysis,
            bg=COLORS["card"], fg=COLORS["text"], hover_bg=COLORS["bg"],
            border_color=COLORS["border"],
        )
        analyze_btn.pack(side="left", padx=(8, 0))

        # Workflow toolbar (review / dedup / gallery). Gallery is exempted
        # from the processing lockout (read-only export); review/dedup are
        # auto-disabled during a batch (in-place EXIF writes / file moves
        # would race the pipeline).
        wf = tk.Frame(card, bg=COLORS["card"])
        wf.pack(fill="x", padx=14, pady=(8, 0))

        self.review_btn = FlatButton(
            wf, text=self._t("review_btn"), command=self._show_review,
            bg=COLORS["accent"], hover_bg=COLORS["accent_hover"],
            font=FONT_SMALL,
        )
        self.review_btn.pack(side="left")

        self.dedup_btn = FlatButton(
            wf, text=self._t("dedup_btn"), command=self._show_dedup,
            bg=COLORS["card"], fg=COLORS["text"], hover_bg=COLORS["bg"],
            border_color=COLORS["border"], font=FONT_SMALL,
        )
        self.dedup_btn.pack(side="left", padx=(8, 0))

        self.gallery_btn = FlatButton(
            wf, text=self._t("gallery_btn"), command=self._show_gallery_export,
            bg=COLORS["card"], fg=COLORS["text"], hover_bg=COLORS["bg"],
            border_color=COLORS["border"], font=FONT_SMALL,
        )
        self.gallery_btn.pack(side="left", padx=(8, 0))

        self.file_count_label = tk.Label(
            toolbar, text=self._t("files_count", n=0), font=FONT_SMALL,
            fg=COLORS["text_secondary"], bg=COLORS["card"],
        )
        self.file_count_label.pack(side="right", padx=(0, 12))

        # File list: scrollable rows with real ttk.Checkbuttons — the
        # same widget as the settings panel. (Treeview cells cannot host
        # widgets, and its per-item image column proved unreliable, so
        # the list is a canvas of row frames instead.)
        list_frame = tk.Frame(card, bg=COLORS["card"])
        list_frame.pack(fill="both", expand=True, padx=14, pady=12)

        self.file_list_canvas = tk.Canvas(
            list_frame, bg=COLORS["card"], highlightthickness=0,
            borderwidth=0)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical",
                                  command=self.file_list_canvas.yview)
        self.file_list_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.file_list_canvas.pack(side="left", fill="both", expand=True)

        self.file_rows_frame = tk.Frame(self.file_list_canvas,
                                        bg=COLORS["card"])
        self._rows_win = self.file_list_canvas.create_window(
            (0, 0), window=self.file_rows_frame, anchor="nw")

        def _sync_width(event=None):
            self.file_list_canvas.itemconfigure(
                self._rows_win,
                width=self.file_list_canvas.winfo_width())

        self.file_list_canvas.bind("<Configure>", _sync_width)

        def _sync_scroll(event=None):
            self.file_list_canvas.configure(
                scrollregion=self.file_list_canvas.bbox("all"))

        self.file_rows_frame.bind("<Configure>", _sync_scroll)

        # Mousewheel: same pattern as the settings panel (card-scoped
        # bind_all + boundary snapping + momentum debounce)
        _last_boundary = [0.0]

        def _on_mousewheel(event):
            delta = event.delta
            amount = -delta if abs(delta) < 10 else -delta / 120
            if time.monotonic() - _last_boundary[0] < 0.15:
                return  # momentum tail right after a boundary hit
            top, bottom = self.file_list_canvas.yview()
            if amount > 0:
                if bottom >= 1.0 - 1e-9:
                    _last_boundary[0] = time.monotonic()
                    self.file_list_canvas.yview_moveto(1.0)
                    return
            elif amount < 0:
                if top <= 1e-9:
                    _last_boundary[0] = time.monotonic()
                    self.file_list_canvas.yview_moveto(0.0)
                    return
            self.file_list_canvas.yview_scroll(amount, "units")

        def _bind_scroll(event):
            self.file_list_canvas.bind_all("<MouseWheel>", _on_mousewheel)

        def _unbind_scroll(event):
            self.file_list_canvas.unbind_all("<MouseWheel>")

        for w in (list_frame, self.file_list_canvas):
            w.bind("<Enter>", _bind_scroll)
            w.bind("<Leave>", _unbind_scroll)

        # Register drag-and-drop targets (requires tkinterdnd2 AND a TkinterDnD
        # root; with a plain tk.Tk() root — e.g. headless smoke tests — the
        # tkdnd Tcl commands aren't loaded, so degrade gracefully)
        if DND_AVAILABLE:
            try:
                for widget in (card, self.file_list_canvas,
                               self.file_rows_frame):
                    widget.drop_target_register(DND_FILES)
                    widget.dnd_bind("<<Drop>>", self._on_drop)
            except Exception:
                pass

        # File list hint
        hint_text = self._t("hint_dnd" if DND_AVAILABLE else "hint_no_dnd")
        drop_hint = tk.Label(
            card, text=hint_text,
            font=FONT_TINY, fg=COLORS["text_secondary"], bg=COLORS["card"],
        )
        drop_hint.pack(fill="x", padx=14, pady=(0, 10))

    def _build_settings_panel(self, parent):
        """Build the right-side settings panel."""
        # Defensive: a rebuild (theme/language) destroys the old card while
        # its Enter/Leave handlers are gone, but any bind_all left behind by
        # the old panel would target a destroyed canvas. Clear it first.
        canvas_unbind_safe(parent)

        # Card container
        card = tk.Frame(parent, bg=COLORS["card"], bd=0, highlightthickness=0)
        card.pack(fill="both", expand=True)

        # Scrollable settings area
        canvas = tk.Canvas(card, bg=COLORS["card"], highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(card, orient="vertical", command=canvas.yview)
        settings_frame = tk.Frame(canvas, bg=COLORS["card"])
        settings_frame.columnconfigure(0, weight=1)

        canvas_window = canvas.create_window((0, 0), window=settings_frame, anchor="nw")

        def _on_frame_configure(_event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(event):
            # Keep the inner frame exactly as wide as the visible canvas so
            # settings are never clipped on the right edge
            canvas.itemconfigure(canvas_window, width=event.width)

        settings_frame.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", _on_canvas_configure)
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Mousewheel scrolling: active while the pointer is anywhere over the
        # settings CARD (canvas, scrollbar, or any widget inside the panel).
        # Binding on the card instead of the canvas keeps the handler alive
        # over child widgets — the old canvas-only Enter/Leave unbound on
        # every child crossing, so scrolling stuttered/jumped near the bottom
        # where the pointer sits between widgets. The handler clamps at the
        # boundaries and re-snaps for a beat after hitting one, so trackpad
        # momentum — which can reverse direction for a few frames — can't
        # wobble the view off the edge.
        _last_boundary = [0.0]

        def _on_mousewheel(event):
            # macOS: event.delta is ±1; Windows/Linux: event.delta is ±120
            delta = event.delta
            amount = -delta if abs(delta) < 10 else -delta / 120
            if time.monotonic() - _last_boundary[0] < 0.15:
                return  # momentum tail right after a boundary hit — drop it
            top, bottom = canvas.yview()
            if amount > 0:
                if bottom >= 1.0 - 1e-9:
                    _last_boundary[0] = time.monotonic()
                    canvas.yview_moveto(1.0)  # snap exactly to the bottom
                    return
            elif amount < 0:
                if top <= 1e-9:
                    _last_boundary[0] = time.monotonic()
                    canvas.yview_moveto(0.0)
                    return
            # Pass the raw (possibly fractional) amount through so Windows
            # high-resolution wheels (delta=±30/±60) scroll smoothly too.
            canvas.yview_scroll(amount, "units")

        def _bind_scroll(event):
            canvas.bind_all("<MouseWheel>", _on_mousewheel)

        def _unbind_scroll(event):
            canvas.unbind_all("<MouseWheel>")

        card.bind("<Enter>", _bind_scroll)
        card.bind("<Leave>", _unbind_scroll)

        pad = {"padx": 18, "pady": 4}

        # ── Output Format ────────────────────────────────────────────────────
        self._add_section_label(settings_frame, self._t("sec_format"), row=0)

        fmt_frame = tk.Frame(settings_frame, bg=COLORS["card"])
        fmt_frame.grid(row=1, sticky="ew", **pad)
        fmt_frame.columnconfigure(0, weight=1)

        self.format_combo = ttk.Combobox(
            fmt_frame, textvariable=self.output_format,
            values=list(SUPPORTED_FORMATS.keys()), state="readonly",
            font=FONT_BODY,
        )
        self.format_combo.pack(fill="x")

        # ── Quality / Target Size ────────────────────────────────────────────
        self._add_section_label(settings_frame, self._t("sec_mode"), row=2)

        # Mode toggle: radio buttons
        mode_frame = tk.Frame(settings_frame, bg=COLORS["card"])
        mode_frame.grid(row=4, sticky="ew", **pad)

        self.manual_radio = ttk.Radiobutton(
            mode_frame, text=self._t("manual_quality"), variable=self.target_size_mode,
            value=False, command=self._on_mode_change,
        )
        self.manual_radio.pack(anchor="w")

        self.target_radio = ttk.Radiobutton(
            mode_frame, text=self._t("target_size_mode"), variable=self.target_size_mode,
            value=True, command=self._on_mode_change,
        )
        self.target_radio.pack(anchor="w", pady=(4, 0))

        # ── Quality slider (shown in manual mode; ceiling in target mode) ────
        self.quality_section_frame = tk.Frame(settings_frame, bg=COLORS["card"])
        self.quality_section_frame.grid(row=5, sticky="ew", **pad)

        self.quality_section_label = tk.Label(
            self.quality_section_frame, text=self._t("quality"),
            font=FONT_SMALL, fg=COLORS["text_secondary"], bg=COLORS["card"],
        )
        self.quality_section_label.pack(anchor="w")

        quality_row = tk.Frame(self.quality_section_frame, bg=COLORS["card"])
        quality_row.pack(fill="x", pady=(4, 0))

        self.quality_label = tk.Label(
            quality_row, text=str(self.quality.get()),
            font=(PLATFORM_FONTS["body"], 14, "bold"),
            fg=COLORS["accent"], bg=COLORS["card"], width=4,
        )
        self.quality_label.pack(side="right")

        self.quality_slider = ttk.Scale(
            quality_row, from_=1, to=100, variable=self.quality,
            orient="horizontal", command=self._on_quality_change,
        )
        self.quality_slider.pack(side="left", fill="x", expand=True, padx=(0, 8))

        # ── Target size input (shown in target mode) ─────────────────────────
        self.target_section_frame = tk.Frame(settings_frame, bg=COLORS["card"])
        self.target_section_frame.grid(row=6, sticky="ew", **pad)

        tk.Label(self.target_section_frame, text=self._t("target_size"),
                 font=FONT_SMALL, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).pack(anchor="w")

        target_row = tk.Frame(self.target_section_frame, bg=COLORS["card"])
        target_row.pack(fill="x", pady=(4, 0))

        self.target_entry = ttk.Entry(
            target_row, textvariable=self.target_size_value,
            font=FONT_BODY, width=8,
        )
        self.target_entry.pack(side="left")

        self.target_unit_combo = ttk.Combobox(
            target_row, textvariable=self.target_size_unit,
            values=["KB", "MB"], state="readonly",
            font=FONT_BODY, width=5,
        )
        self.target_unit_combo.pack(side="left", padx=(8, 0))

        tk.Label(target_row, text=self._t("autotune_hint"),
                 font=FONT_TINY, fg=COLORS["text_secondary"], justify="left",
                 bg=COLORS["card"]).pack(side="left", padx=(8, 0))

        # Hide target section initially (manual mode default)
        self.target_section_frame.grid_remove()

        # ── Resize ──────────────────────────────────────────────────────────
        self._add_section_label(settings_frame, self._t("sec_resize"), row=7)

        resize_frame = tk.Frame(settings_frame, bg=COLORS["card"])
        resize_frame.grid(row=9, sticky="ew", **pad)
        resize_frame.columnconfigure(1, weight=1)
        resize_frame.columnconfigure(3, weight=1)

        tk.Label(resize_frame, text=self._t("width"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=0, column=0, sticky="e", padx=(0, 4))
        w_entry = ttk.Entry(resize_frame, textvariable=self.max_width,
                            font=FONT_BODY, width=7)
        w_entry.grid(row=0, column=1, sticky="w")

        tk.Label(resize_frame, text=self._t("height"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=0, column=2, sticky="e", padx=(12, 4))
        h_entry = ttk.Entry(resize_frame, textvariable=self.max_height,
                            font=FONT_BODY, width=7)
        h_entry.grid(row=0, column=3, sticky="w")

        tk.Label(resize_frame, text=self._t("pixels_hint"),
                 font=FONT_TINY, fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(4, 0))

        # Max pixels on the longest side (downscale only)
        tk.Label(resize_frame, text=self._t("max_pixels"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        px_entry = ttk.Entry(resize_frame, textvariable=self.max_pixels,
                             font=FONT_BODY, width=7)
        px_entry.grid(row=2, column=2, columnspan=2, sticky="w",
                      padx=(8, 0), pady=(8, 0))
        tk.Label(resize_frame, text=self._t("max_pixels_hint"),
                 font=FONT_TINY, fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=3, column=0, columnspan=4, sticky="w", pady=(2, 0))

        # Scale percentage
        scale_frame = tk.Frame(settings_frame, bg=COLORS["card"])
        scale_frame.grid(row=10, sticky="ew", **pad)

        tk.Label(scale_frame, text=self._t("scale"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).pack(side="left")

        scale_entry = ttk.Entry(scale_frame, textvariable=self.scale_percent,
                                font=FONT_BODY, width=7)
        scale_entry.pack(side="left", padx=(8, 0))

        # ── Output Location ─────────────────────────────────────────────────
        self._add_section_label(settings_frame, self._t("sec_output"), row=11)

        out_frame = tk.Frame(settings_frame, bg=COLORS["card"])
        out_frame.grid(row=13, sticky="ew", **pad)
        out_frame.columnconfigure(0, weight=1)

        out_entry = ttk.Entry(out_frame, textvariable=self.output_dir,
                              font=FONT_SMALL)
        out_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        browse_btn = FlatButton(
            out_frame, text=self._t("browse"), command=self._browse_output_dir,
            bg=COLORS["bg"], fg=COLORS["text"], hover_bg=COLORS["border"],
            font=FONT_SMALL, padx=10, pady=4, border_color=COLORS["border"],
        )
        browse_btn.grid(row=0, column=1)

        # Print size (blank = off)
        tk.Label(out_frame, text=self._t("print_size"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(out_frame, textvariable=self.print_size,
                  font=FONT_BODY, width=10).grid(
            row=1, column=1, sticky="w", padx=(8, 0), pady=(10, 0))
        tk.Label(out_frame, text=self._t("print_size_hint"),
                 font=FONT_TINY, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(2, 0))

        # ── Naming ──────────────────────────────────────────────────────────
        self._add_section_label(settings_frame, self._t("sec_naming"), row=14)

        naming_frame = tk.Frame(settings_frame, bg=COLORS["card"])
        naming_frame.grid(row=16, sticky="ew", **pad)

        tk.Label(naming_frame, text=self._t("prefix"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=0, column=0, sticky="w")
        ttk.Entry(naming_frame, textvariable=self.prefix,
                  font=FONT_BODY, width=10).grid(
            row=0, column=1, sticky="ew", padx=(8, 0))

        tk.Label(naming_frame, text=self._t("suffix"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(naming_frame, textvariable=self.suffix,
                  font=FONT_BODY, width=10).grid(
            row=1, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))

        tk.Label(naming_frame, text=self._t("smart_rename"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"], justify="left").grid(
            row=2, column=0, sticky="w", pady=(12, 0))
        self.rename_entry = ttk.Entry(
            naming_frame, textvariable=self.rename_pattern,
            font=FONT_SMALL, width=20,
        )
        self.rename_entry.grid(
            row=2, column=1, sticky="ew", padx=(8, 0), pady=(12, 0))
        tk.Label(naming_frame, text=self._t("rename_vars"),
                 font=FONT_TINY, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(2, 0), padx=(0, 8))

        naming_frame.columnconfigure(1, weight=1)

        # ── Folder Organization ─────────────────────────────────────────────
        self._add_section_label(settings_frame, self._t("sec_subfolder"), row=17)

        folder_frame = tk.Frame(settings_frame, bg=COLORS["card"])
        folder_frame.grid(row=19, sticky="ew", **pad)
        folder_frame.columnconfigure(1, weight=1)

        tk.Label(folder_frame, text=self._t("template"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=0, column=0, sticky="w")

        # Preset list is localized; index maps to an internal value
        self._folder_preset_keys = [
            "preset_flat", "preset_date", "preset_camera",
            "preset_date_camera", "preset_custom",
        ]
        # Internal value per preset index; None = custom template
        self._folder_preset_values = ["", "date", "camera", "date-camera", None]

        self.folder_combo = ttk.Combobox(
            folder_frame, font=FONT_BODY, state="readonly",
            values=[self._t(k) for k in self._folder_preset_keys],
        )
        self.folder_combo.current(0)
        self.folder_combo.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self.folder_combo.bind("<<ComboboxSelected>>", self._on_folder_preset_change)

        tk.Label(folder_frame, text=self._t("custom"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=1, column=0, sticky="w", pady=(8, 0))

        self.folder_custom_entry = ttk.Entry(
            folder_frame, textvariable=self.folder_pattern,
            font=FONT_SMALL,
        )
        self.folder_custom_entry.grid(
            row=1, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))

        tk.Label(folder_frame, text=self._t("folder_vars"),
                 font=FONT_TINY, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(2, 0), padx=(0, 8))

        # ── Options ─────────────────────────────────────────────────────────
        self._add_section_label(settings_frame, self._t("sec_options"), row=20)

        opts_frame = tk.Frame(settings_frame, bg=COLORS["card"])
        opts_frame.grid(row=22, sticky="ew", **pad)

        self._add_checkbox(opts_frame, self._t("preserve_exif"),
                           self.preserve_exif, row=0)
        self._add_checkbox(opts_frame, self._t("optimize"),
                           self.optimize, row=1)
        self._add_checkbox(opts_frame, self._t("progressive"),
                           self.progressive, row=2)
        self._add_checkbox(opts_frame, self._t("overwrite"),
                           self.overwrite, row=3)
        self._add_checkbox(opts_frame, self._t("auto_rotate"),
                           self.auto_rotate, row=4)
        self._add_checkbox(opts_frame, self._t("raw_half_size"),
                           self.raw_half_size, row=5)
        self._add_checkbox(opts_frame, self._t("raw_auto_bright"),
                           self.raw_auto_bright, row=6)
        self._add_checkbox(opts_frame, self._t("delete_original"),
                           self.remove_original, row=7)
        self._add_checkbox(opts_frame, self._t("strip_gps"),
                           self.strip_gps, row=8)
        self._add_checkbox(opts_frame, self._t("keep_mtime"),
                           self.keep_mtime, row=9)

        # Parallel workers
        tk.Label(opts_frame, text=self._t("jobs"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=10, column=0, sticky="w", pady=(10, 0))
        jobs_entry = ttk.Entry(opts_frame, textvariable=self.jobs,
                               font=FONT_BODY, width=5)
        jobs_entry.grid(row=10, column=1, sticky="w", padx=(8, 0), pady=(10, 0))

        # Spacer
        spacer = tk.Frame(settings_frame, bg=COLORS["card"], height=16)
        spacer.grid(row=23, sticky="ew")

        # ── Watermark ────────────────────────────────────────────────────────
        self._add_section_label(settings_frame, self._t("sec_watermark"), row=24)
        wm_frame = tk.Frame(settings_frame, bg=COLORS["card"])
        wm_frame.grid(row=26, sticky="ew", **pad)
        wm_frame.columnconfigure(1, weight=1)

        tk.Label(wm_frame, text=self._t("wm_text"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=0, column=0, sticky="w")
        wm_text_entry = ttk.Entry(wm_frame, textvariable=self.watermark_text,
                                  font=FONT_BODY)
        wm_text_entry.grid(row=0, column=1, columnspan=2, sticky="ew",
                           padx=(8, 0))

        tk.Label(wm_frame, text=self._t("wm_image"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=1, column=0, sticky="w", pady=(8, 0))
        wm_image_entry = ttk.Entry(wm_frame, textvariable=self.watermark_image,
                                   font=FONT_SMALL)
        wm_image_entry.grid(row=1, column=1, sticky="ew", padx=(8, 0),
                            pady=(8, 0))
        wm_browse = FlatButton(
            wm_frame, self._t("browse"),
            lambda: self._browse_watermark_image(),
            COLORS["accent"], fg="white")
        wm_browse.grid(row=1, column=2, sticky="e", padx=(6, 0), pady=(8, 0))

        tk.Label(wm_frame, text=self._t("wm_position"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=2, column=0, sticky="w", pady=(8, 0))
        wm_pos_combo = ttk.Combobox(
            wm_frame, textvariable=self.watermark_position, state="readonly",
            font=FONT_SMALL, width=14,
            values=list(watermark.POSITIONS.keys()))
        wm_pos_combo.grid(row=2, column=1, sticky="w", padx=(8, 0), pady=(8, 0))

        tk.Label(wm_frame, text=self._t("wm_opacity"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=3, column=0, sticky="w", pady=(8, 0))
        wm_opacity_scale = ttk.Scale(
            wm_frame, from_=0, to=100, variable=self.watermark_opacity,
            command=lambda v: wm_opacity_lbl.config(
                text=f"{int(float(v))}%"))
        wm_opacity_scale.grid(row=3, column=1, sticky="ew", padx=(8, 0),
                              pady=(8, 0))
        wm_opacity_lbl = tk.Label(wm_frame, text="50%", font=FONT_SMALL,
                                  fg=COLORS["text_secondary"],
                                  bg=COLORS["card"], width=4)
        wm_opacity_lbl.grid(row=3, column=2, sticky="e", pady=(8, 0))

        # ── Multi-size output ─────────────────────────────────────────────────
        self._add_section_label(settings_frame, self._t("sec_sizes"), row=27)
        sizes_frame = tk.Frame(settings_frame, bg=COLORS["card"])
        sizes_frame.grid(row=29, sticky="ew", **pad)
        sizes_frame.columnconfigure(0, weight=1)

        sizes_entry = ttk.Entry(sizes_frame, textvariable=self.output_sizes,
                                font=FONT_BODY)
        sizes_entry.grid(row=0, column=0, sticky="ew")
        tk.Label(sizes_frame, text=self._t("sizes_hint"),
                 font=FONT_TINY, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).grid(
            row=1, column=0, sticky="w", pady=(4, 0))

        # ── Adjust (tone & color) ────────────────────────────────────────────
        self._add_section_label(settings_frame, self._t("sec_adjust"), row=30)
        adj_frame = tk.Frame(settings_frame, bg=COLORS["card"])
        adj_frame.grid(row=32, sticky="ew", **pad)
        adj_frame.columnconfigure(1, weight=1)

        adj_specs = [
            ("brightness", self.brightness, 0.0, 2.0, 0.05, "{:.2f}"),
            ("contrast", self.contrast, 0.0, 2.0, 0.05, "{:.2f}"),
            ("saturation", self.saturation, 0.0, 2.0, 0.05, "{:.2f}"),
            ("gamma", self.gamma, 0.1, 3.0, 0.05, "{:.2f}"),
            ("sharpen", self.sharpen, 0.0, 3.0, 0.05, "{:.2f}"),
        ]
        for i, (key, var, lo, hi, step, fmt) in enumerate(adj_specs):
            tk.Label(adj_frame, text=self._t(key), font=FONT_SMALL,
                     fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
                row=i, column=0, sticky="w")
            val_lbl = tk.Label(adj_frame, text=fmt.format(var.get()),
                               font=FONT_SMALL, fg=COLORS["text_secondary"],
                               bg=COLORS["card"], width=5)
            val_lbl.grid(row=i, column=2, sticky="e")
            ttk.Scale(adj_frame, from_=lo, to=hi, variable=var,
                      command=lambda v, lbl=val_lbl, f=fmt: lbl.config(
                          text=f.format(float(v)))).grid(
                row=i, column=1, sticky="ew", padx=(8, 0))

        self._add_checkbox(adj_frame, self._t("grayscale"),
                           self.grayscale, row=5)
        self._add_checkbox(adj_frame, self._t("sepia"),
                           self.sepia, row=6)

        # ── Composition (crop / rotate / flip / pad) ─────────────────────────
        self._add_section_label(settings_frame, self._t("sec_composition"),
                                row=33)
        comp_frame = tk.Frame(settings_frame, bg=COLORS["card"])
        comp_frame.grid(row=35, sticky="ew", **pad)
        comp_frame.columnconfigure(1, weight=1)

        comp_specs = [
            ("crop", self.crop, None),
            ("crop_ratio", self.crop_ratio, None),
            ("rotate", self.rotate, None),
            ("rotate_bg", self.rotate_bg, None),
            ("pad", self.pad_ratio, None),
            ("pad_bg", self.pad_bg, None),
        ]
        for i, (key, var, _) in enumerate(comp_specs):
            tk.Label(comp_frame, text=self._t(key), font=FONT_SMALL,
                     fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
                row=i, column=0, sticky="w")
            ttk.Entry(comp_frame, textvariable=var, font=FONT_BODY).grid(
                row=i, column=1, sticky="ew", padx=(8, 0))

        tk.Label(comp_frame, text=self._t("flip"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=6, column=0, sticky="w", pady=(8, 0))
        flip_combo = ttk.Combobox(
            comp_frame, textvariable=self.flip, state="readonly",
            font=FONT_SMALL, width=6, values=["", "h", "v"])
        flip_combo.grid(row=6, column=1, sticky="w", padx=(8, 0), pady=(8, 0))

        tk.Label(comp_frame, text=self._t("crop_hint"),
                 font=FONT_TINY, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).grid(
            row=7, column=0, columnspan=2, sticky="w", pady=(4, 0))
        tk.Label(comp_frame, text=self._t("pad_hint"),
                 font=FONT_TINY, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).grid(
            row=8, column=0, columnspan=2, sticky="w", pady=(2, 0))

        # ── Correction (exposure / LOG / denoise / straighten) ───────────────
        self._add_section_label(settings_frame, self._t("sec_correction"),
                                row=36)
        corr_frame = tk.Frame(settings_frame, bg=COLORS["card"])
        corr_frame.grid(row=38, sticky="ew", **pad)
        corr_frame.columnconfigure(1, weight=1)

        # EV exposure slider (-2..+2 stops)
        tk.Label(corr_frame, text=self._t("ev"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=0, column=0, sticky="w")
        ev_lbl = tk.Label(corr_frame, text="{:+.2f}".format(self.ev.get()),
                          font=FONT_SMALL, fg=COLORS["text_secondary"],
                          bg=COLORS["card"], width=5)
        ev_lbl.grid(row=0, column=2, sticky="e")
        ttk.Scale(corr_frame, from_=-2.0, to=2.0, variable=self.ev,
                  command=lambda v, lbl=ev_lbl: lbl.config(
                      text="{:+.2f}".format(float(v)))).grid(
            row=0, column=1, sticky="ew", padx=(8, 0))
        tk.Label(corr_frame, text=self._t("ev_hint"),
                 font=FONT_TINY, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(2, 0))

        # Auto-exposure target (blank = off)
        tk.Label(corr_frame, text=self._t("auto_exposure"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=2, column=0, sticky="w")
        ttk.Entry(corr_frame, textvariable=self.auto_exposure,
                  font=FONT_BODY, width=8).grid(
            row=2, column=1, sticky="w", padx=(8, 0))
        tk.Label(corr_frame, text=self._t("auto_exposure_hint"),
                 font=FONT_TINY, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(2, 0))

        # LOG recovery curve (blank = off)
        tk.Label(corr_frame, text=self._t("log_curve"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=4, column=0, sticky="w")
        log_combo = ttk.Combobox(
            corr_frame, textvariable=self.log_curve, state="readonly",
            font=FONT_SMALL, width=8,
            values=["", "SLOG3", "CLOG3", "LOGC3", "DLOG", "VLOG", "HLG"])
        log_combo.grid(row=4, column=1, sticky="w", padx=(8, 0))
        tk.Label(corr_frame, text=self._t("log_curve_hint"),
                 font=FONT_TINY, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(2, 0))

        # Denoise strength (blank = off)
        tk.Label(corr_frame, text=self._t("denoise"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=6, column=0, sticky="w")
        ttk.Entry(corr_frame, textvariable=self.denoise,
                  font=FONT_BODY, width=8).grid(
            row=6, column=1, sticky="w", padx=(8, 0))
        tk.Label(corr_frame, text=self._t("denoise_hint"),
                 font=FONT_TINY, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).grid(
            row=7, column=0, columnspan=3, sticky="w", pady=(2, 0))

        # Auto-straighten + max angle
        self._add_checkbox(corr_frame, self._t("auto_straighten"),
                           self.auto_straighten, row=8)
        tk.Label(corr_frame, text=self._t("max_straighten_angle"),
                 font=FONT_SMALL, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).grid(
            row=9, column=0, sticky="w")
        ttk.Entry(corr_frame, textvariable=self.max_straighten_angle,
                  font=FONT_BODY, width=8).grid(
            row=9, column=1, sticky="w", padx=(8, 0))

        # ── White balance / color / evaluation (row 10+) ─────────────────────
        # WB temperature (blank = off)
        tk.Label(corr_frame, text=self._t("wb_temp"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=10, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(corr_frame, textvariable=self.wb_temp,
                  font=FONT_BODY, width=8).grid(
            row=10, column=1, sticky="w", padx=(8, 0), pady=(10, 0))
        tk.Label(corr_frame, text=self._t("wb_temp_hint"),
                 font=FONT_TINY, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).grid(
            row=11, column=0, columnspan=3, sticky="w", pady=(2, 0))

        # WB reference image (blank = off)
        tk.Label(corr_frame, text=self._t("wb_reference"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=12, column=0, sticky="w")
        ref_entry = ttk.Entry(corr_frame, textvariable=self.wb_reference,
                              font=FONT_SMALL)
        ref_entry.grid(row=12, column=1, sticky="ew", padx=(8, 0))
        FlatButton(corr_frame, text=self._t("browse_ref"),
                   command=self._browse_wb_reference,
                   bg=COLORS["bg"], fg=COLORS["text"],
                   hover_bg=COLORS["border"], font=FONT_SMALL,
                   padx=8, pady=2, border_color=COLORS["border"]).grid(
            row=12, column=2, sticky="e", padx=(4, 0))
        tk.Label(corr_frame, text=self._t("wb_reference_hint"),
                 font=FONT_TINY, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).grid(
            row=13, column=0, columnspan=3, sticky="w", pady=(2, 0))

        # Checkboxes: auto levels / color / evaluation
        self._add_checkbox(corr_frame, self._t("auto_levels"),
                           self.auto_levels, row=14)
        self._add_checkbox(corr_frame, self._t("srgb"),
                           self.srgb, row=15)
        self._add_checkbox(corr_frame, self._t("flatten_cmyk"),
                           self.flatten_cmyk, row=16)
        self._add_checkbox(corr_frame, self._t("evaluate"),
                           self.evaluate, row=17)
        self._add_checkbox(corr_frame, self._t("blur_score"),
                           self.blur_score, row=18)
        self._add_checkbox(corr_frame, self._t("resume"),
                           self.resume, row=19)

        # ── Metadata section ──────────────────────────────────────────────────
        self._add_section_label(settings_frame, self._t("sec_metadata"), row=39)
        meta_frame = tk.Frame(settings_frame, bg=COLORS["card"])
        meta_frame.grid(row=41, sticky="ew", **pad)
        meta_frame.columnconfigure(1, weight=1)

        # EXIF date shift (blank = off)
        tk.Label(meta_frame, text=self._t("date_shift"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=0, column=0, sticky="w")
        ttk.Entry(meta_frame, textvariable=self.date_shift,
                  font=FONT_BODY, width=8).grid(
            row=0, column=1, sticky="w", padx=(8, 0))
        tk.Label(meta_frame, text=self._t("date_shift_hint"),
                 font=FONT_TINY, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(2, 0))

        # GPX track (blank = off)
        tk.Label(meta_frame, text=self._t("gpx_trace"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["card"]).grid(
            row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(meta_frame, textvariable=self.gpx_trace,
                  font=FONT_SMALL).grid(
            row=2, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        FlatButton(meta_frame, text=self._t("browse_gpx"),
                   command=self._browse_gpx,
                   bg=COLORS["bg"], fg=COLORS["text"],
                   hover_bg=COLORS["border"], font=FONT_SMALL,
                   padx=8, pady=2, border_color=COLORS["border"]).grid(
            row=2, column=2, sticky="e", padx=(4, 0), pady=(8, 0))
        tk.Label(meta_frame, text=self._t("gpx_trace_hint"),
                 font=FONT_TINY, fg=COLORS["text_secondary"],
                 bg=COLORS["card"]).grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(2, 0))

        self._add_checkbox(meta_frame, self._t("sync_date"),
                           self.sync_date, row=4)
        self._add_checkbox(meta_frame, self._t("scrub"),
                           self.scrub, row=5)

    def _browse_wb_reference(self):
        """Pick a white-balance reference image (gray card)."""
        if self._dlg_cooldown_active():
            return
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title=self._t("wb_reference"),
            filetypes=[("图片 Images", "*.jpg *.jpeg *.png *.webp *.tif *.tiff")])
        self._after_file_dialog()
        if path:
            self.wb_reference.set(path)

    def _browse_gpx(self):
        """Pick a GPX track file."""
        if self._dlg_cooldown_active():
            return
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title=self._t("gpx_trace"),
            filetypes=[("GPX", "*.gpx"), ("All Files", "*.*")])
        self._after_file_dialog()
        if path:
            self.gpx_trace.set(path)

    def _browse_watermark_image(self):
        """Pick a watermark overlay image via file dialog."""
        if self._dlg_cooldown_active():
            return
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title=self._t("wm_image"),
            filetypes=[("图片 Images", "*.png *.jpg *.jpeg *.webp"),
                       ("All files", "*.*")])
        self._after_file_dialog()
        if path:
            self.watermark_image.set(path)

    def _build_bottom_panel(self, parent):
        """Build bottom progress and action bar."""
        # Card container
        card = tk.Frame(parent, bg=COLORS["card"], bd=0, highlightthickness=0)
        card.pack(fill="x")

        inner = tk.Frame(card, bg=COLORS["card"])
        inner.pack(fill="x", padx=18, pady=14)

        # Progress label
        self.progress_label = tk.Label(
            inner, text=self._t("ready"),
            font=FONT_BODY, fg=COLORS["text_secondary"], bg=COLORS["card"],
            anchor="w",
        )
        self.progress_label.pack(fill="x")

        # Progress bar
        self.progress_bar = ttk.Progressbar(
            inner, mode="determinate", length=400,
        )
        self.progress_bar.pack(fill="x", pady=(8, 10))

        # Stats row
        stats_frame = tk.Frame(inner, bg=COLORS["card"])
        stats_frame.pack(fill="x")

        self.stats_label = tk.Label(
            stats_frame, text="",
            font=FONT_SMALL, fg=COLORS["text_secondary"], bg=COLORS["card"],
        )
        self.stats_label.pack(side="left")

        # Action buttons
        btn_frame = tk.Frame(inner, bg=COLORS["card"])
        btn_frame.pack(fill="x", pady=(10, 0))

        self.preview_btn = FlatButton(
            btn_frame, text=self._t("preview"), command=self._preview,
            bg=COLORS["card"], fg=COLORS["text"], hover_bg=COLORS["bg"],
            font=FONT_BUTTON, padx=20, pady=8, border_color=COLORS["border"],
        )
        self.preview_btn.pack(side="left")

        self.start_btn = FlatButton(
            btn_frame, text=self._t("start"), command=self._start_processing,
            bg=COLORS["accent"], hover_bg=COLORS["accent_hover"],
            font=FONT_BUTTON_LG, padx=24, pady=8,
        )
        self.start_btn.pack(side="right")

        # Cancel button (hidden by default)
        self.cancel_btn = FlatButton(
            btn_frame, text=self._t("cancel"), command=self._cancel_processing,
            bg=COLORS["danger"], hover_bg=COLORS["danger_hover"],
            font=FONT_BUTTON_LG, padx=24, pady=8,
        )
        # Start hidden

    # ── UI Helper Methods ────────────────────────────────────────────────────

    def _add_section_label(self, parent, text, row):
        """Add a section header label."""
        # Thin separator
        if row > 0:
            sep = tk.Frame(parent, bg=COLORS["divider"], height=1)
            sep.grid(row=row, sticky="ew", padx=18, pady=(12, 8), columnspan=2)

        label = tk.Label(
            parent, text=text, font=FONT_SECTION,
            fg=COLORS["text"], bg=COLORS["card"], anchor="w",
        )
        label.grid(row=row + (1 if row > 0 else 0), sticky="ew", padx=18,
                   pady=(14 if row == 0 else 0, 4))

    def _add_checkbox(self, parent, text, variable, row):
        """Add a native-styled checkbox."""
        cb = ttk.Checkbutton(parent, text=text, variable=variable)
        cb.grid(row=row, sticky="w", pady=2)

    def _on_quality_change(self, value):
        """Update quality label when slider moves."""
        self.quality_label.config(text=str(int(float(value))))

    def _on_mode_change(self):
        """Toggle between manual quality mode and target size mode."""
        if self.target_size_mode.get():
            # Target size mode: quality becomes ceiling
            self.quality_section_label.config(text=self._t("max_quality"))
            self.target_section_frame.grid()
            # Default to 95 as ceiling in target mode
            if self.quality.get() == 85:
                self.quality.set(95)
                self.quality_label.config(text="95")
        else:
            # Manual quality mode
            self.quality_section_label.config(text=self._t("quality"))
            self.target_section_frame.grid_remove()

    # ── About ───────────────────────────────────────────────────────────────

    def _show_about(self):
        """Show the About dialog with version, features and environment info."""
        import platform
        import importlib.util
        import PIL

        win = tk.Toplevel(self.root)
        win.title(self._t("about_title"))
        win.resizable(False, False)
        win.configure(bg=COLORS["bg"])
        win.transient(self.root)

        inner = tk.Frame(win, bg=COLORS["bg"])
        inner.pack(padx=28, pady=24)

        tk.Label(inner, text=APP_NAME, font=FONT_TITLE,
                 fg=COLORS["text"], bg=COLORS["bg"]).pack(anchor="w")
        tk.Label(inner, text=f"v{APP_VERSION}  ·  {self._t('about_desc')}",
                 font=FONT_SMALL, fg=COLORS["text_secondary"],
                 bg=COLORS["bg"]).pack(anchor="w", pady=(2, 14))

        def section(title):
            tk.Label(inner, text=title, font=FONT_SECTION,
                     fg=COLORS["text"], bg=COLORS["bg"]).pack(anchor="w", pady=(10, 2))

        section(self._t("about_features"))
        tk.Label(inner, text=self._t("about_feature_list"),
                 font=FONT_SMALL, fg=COLORS["text_secondary"], justify="left",
                 bg=COLORS["bg"]).pack(anchor="w")

        section(self._t("about_env"))
        tk.Label(inner, text=f"Python {platform.python_version()}  ·  Pillow {PIL.__version__}",
                 font=FONT_SMALL, fg=COLORS["text_secondary"],
                 bg=COLORS["bg"]).pack(anchor="w")

        section(self._t("about_deps"))
        deps = [
            ("tkinterdnd2", DND_AVAILABLE, "GUI drag & drop"),
            ("rawpy", importlib.util.find_spec("rawpy") is not None, "RAW"),
            ("pillow-heif", importlib.util.find_spec("pillow_heif") is not None, "HEIC"),
            ("pillow-avif-plugin", importlib.util.find_spec("pillow_avif") is not None, "AVIF"),
            ("piexif", importlib.util.find_spec("piexif") is not None, "EXIF"),
            ("watchdog", importlib.util.find_spec("watchdog") is not None, "watch"),
        ]
        for name, installed, purpose in deps:
            row = tk.Frame(inner, bg=COLORS["bg"])
            row.pack(anchor="w", fill="x")
            status = self._t("dep_installed" if installed else "dep_missing")
            color = COLORS["success"] if installed else COLORS["text_secondary"]
            tk.Label(row, text=f"{name} ({purpose})", font=FONT_SMALL,
                     fg=COLORS["text"], bg=COLORS["bg"]).pack(side="left")
            tk.Label(row, text=status, font=FONT_SMALL,
                     fg=color, bg=COLORS["bg"]).pack(side="left", padx=(8, 0))

        section(self._t("about_shortcuts"))
        tk.Label(inner, text=self._t("shortcuts_text"),
                 font=FONT_SMALL, fg=COLORS["text_secondary"], justify="left",
                 bg=COLORS["bg"]).pack(anchor="w")

        tk.Label(inner, text=self._t("about_license"),
                 font=FONT_TINY, fg=COLORS["text_secondary"],
                 bg=COLORS["bg"]).pack(anchor="w", pady=(16, 12))

        FlatButton(inner, text=self._t("close"), command=win.destroy,
                   bg=COLORS["accent"], hover_bg=COLORS["accent_hover"],
                   font=FONT_BUTTON, padx=24, pady=6).pack()

    # ── Plugin Manager ──────────────────────────────────────────────────────

    def _show_plugin_manager(self):
        """Dialog to manage official plugins: list installed + available,
        install / uninstall / pre-fetch weights. Uses the same logic as the
        `photo-s plugin` CLI (photo_s.plugincmd)."""
        from .registry import OFFICIAL_PLUGINS, to_dict
        from .plugincmd import _pip_run, _installed_version
        from .plugin import discover_plugins

        win = tk.Toplevel(self.root)
        win.title(self._t("plugins_title"))
        win.configure(bg=COLORS["bg"])
        win.transient(self.root)
        win.geometry("560x520")

        status_lbl = tk.Label(win, text="", font=FONT_SMALL,
                              fg=COLORS["text_secondary"], bg=COLORS["bg"],
                              wraplength=520, justify="left")
        status_lbl.pack(fill="x", padx=18, pady=(12, 4))

        body = tk.Frame(win, bg=COLORS["bg"])
        body.pack(fill="both", expand=True, padx=18, pady=(0, 10))

        def _section_title(text):
            tk.Label(body, text=text, font=FONT_SECTION,
                     fg=COLORS["text"], bg=COLORS["bg"]).pack(anchor="w",
                                                              pady=(10, 2))

        def _set_status(text, is_err=False):
            status_lbl.config(text=text,
                              fg=COLORS["danger"] if is_err
                              else COLORS["text_secondary"])

        def _row(text, right_text="", right_color=None):
            """One label row with an optional right-aligned status."""
            row = tk.Frame(body, bg=COLORS["bg"])
            row.pack(anchor="w", fill="x")
            tk.Label(row, text=text, font=FONT_SMALL,
                     fg=COLORS["text"], bg=COLORS["bg"]).pack(side="left")
            if right_text:
                tk.Label(row, text=right_text, font=FONT_SMALL,
                         fg=right_color or COLORS["text_secondary"],
                         bg=COLORS["bg"]).pack(side="right")

        def _button_row(plugin_name, dist, installed):
            """Action buttons for one official plugin."""
            row = tk.Frame(body, bg=COLORS["bg"])
            row.pack(anchor="e", fill="x", pady=(0, 6))

            def _run(verb):
                # pip runs in a background thread (it blocks for seconds
                # on real installs — freezing the UI otherwise); Tk updates
                # go back through win.after.
                _set_status(self._t("plugins_ok", verb))

                def worker():
                    try:
                        if verb == "install":
                            proc = _pip_run(["install", "--quiet", dist])
                        else:
                            proc = _pip_run(["uninstall", "-y", dist])
                        ok = proc.returncode == 0
                        detail = (proc.stderr or "").strip()[-200:]
                    except FileNotFoundError:
                        ok, detail = False, "pip not available"

                    def finish():
                        if not win.winfo_exists():
                            return
                        if ok:
                            _set_status(self._t(
                                "plugins_ok", f"{plugin_name} {verb}"))
                        else:
                            _set_status(self._t("plugins_err", detail),
                                        is_err=True)
                        win.after(600, _refresh)
                    win.after(0, finish)

                threading.Thread(target=worker, daemon=True).start()

            if installed:
                FlatButton(row, text=self._t("plugins_uninstall"),
                           command=lambda: _run("uninstall"),
                           bg=COLORS["danger"], hover_bg=COLORS["danger_hover"],
                           font=FONT_SMALL, padx=12, pady=4).pack(side="right")
            else:
                FlatButton(row, text=self._t("plugins_install"),
                           command=lambda: _run("install"),
                           bg=COLORS["accent"], hover_bg=COLORS["accent_hover"],
                           font=FONT_SMALL, padx=12, pady=4).pack(side="right")

        def _refresh():
            for child in body.winfo_children():
                child.destroy()
            _set_status("")
            installed_names = {p.name for p in discover_plugins()}

            _section_title(self._t("plugins_installed"))
            if installed_names:
                for p in discover_plugins():
                    ver = _installed_version("photo-s-plugin-" + p.name)
                    ver_str = " (v{})".format(ver) if ver else ""
                    provides = ", ".join(getattr(p, "provides", ())) or "-"
                    _row("{}  [{}]{}".format(p.name, provides, ver_str))
            else:
                _row(self._t("plugins_none"), right_text="")

            _section_title(self._t("plugins_available"))
            for name in sorted(OFFICIAL_PLUGINS):
                entry = to_dict(OFFICIAL_PLUGINS[name])
                installed = name in installed_names
                _row("{}  —  {}".format(name, entry["description"]),
                     right_text="✅" if installed else "")
                _button_row(name, entry["pypi_distribution"], installed)

        refresh_btn = FlatButton(win, text=self._t("plugins_refresh"),
                                 command=_refresh,
                                 bg=COLORS["bg"], fg=COLORS["text"],
                                 hover_bg=COLORS["border"],
                                 font=FONT_SMALL, padx=12, pady=4,
                                 border_color=COLORS["border"])
        refresh_btn.pack(side="left", padx=(18, 0), pady=(0, 12))
        FlatButton(win, text=self._t("close"), command=win.destroy,
                   bg=COLORS["accent"], hover_bg=COLORS["accent_hover"],
                   font=FONT_BUTTON, padx=20, pady=6).pack(side="right",
                                                           padx=18,
                                                           pady=(0, 12))

        _refresh()

    # ── Settings (MCP + optional deps) ──────────────────────────────────────

    def _show_settings(self):
        """Settings dialog: MCP server status + launch/config, optional
        dependency installs, and a link to the plugin manager."""
        import importlib.util
        from .plugincmd import _pip_run

        win = tk.Toplevel(self.root)
        win.title(self._t("settings_title"))
        win.configure(bg=COLORS["bg"])
        win.transient(self.root)
        win.geometry("620x580")

        inner = tk.Frame(win, bg=COLORS["bg"])
        inner.pack(fill="both", expand=True, padx=24, pady=18)

        def section_title(text):
            tk.Label(inner, text=text, font=FONT_SECTION,
                     fg=COLORS["text"], bg=COLORS["bg"]).pack(anchor="w",
                                                              pady=(8, 2))

        def _status_lbl(parent, text, color):
            return tk.Label(parent, text=text, font=FONT_SMALL, fg=color,
                            bg=COLORS["bg"])

        # ── MCP section ─────────────────────────────────────────────────────
        section_title(self._t("set_mcp"))
        tk.Label(inner, text=self._t("set_mcp_desc"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["bg"],
                 wraplength=560, justify="left").pack(anchor="w", pady=(0, 6))

        mcp_row = tk.Frame(inner, bg=COLORS["bg"])
        mcp_row.pack(anchor="w", fill="x")
        mcp_ok = importlib.util.find_spec("mcp") is not None
        mcp_status = _status_lbl(
            mcp_row,
            ("✅ " + self._t("mcp_installed")) if mcp_ok
            else ("❌ " + self._t("mcp_missing")),
            COLORS["success"] if mcp_ok else COLORS["danger"])
        mcp_status.pack(side="left")

        install_btns = []
        if not mcp_ok:
            def _install_mcp():
                self._run_dep_install(win, "mcp>=1.20,<2", mcp_install_btn,
                                      mcp_status,
                                      lambda: "✅ " + self._t("mcp_installed"))
            mcp_install_btn = FlatButton(
                mcp_row, text=self._t("dep_install"),
                command=_install_mcp,
                bg=COLORS["accent"], hover_bg=COLORS["accent_hover"],
                font=FONT_SMALL, padx=10, pady=3)
            mcp_install_btn.pack(side="left", padx=(10, 0))
            install_btns.append(mcp_install_btn)

        # Launch command + copy
        tk.Label(inner, text=self._t("mcp_launch"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["bg"]).pack(anchor="w",
                                                                    pady=(10, 2))
        launch_row = tk.Frame(inner, bg=COLORS["bg"])
        launch_row.pack(anchor="w", fill="x")
        launch_entry = ttk.Entry(launch_row, font=FONT_SMALL)
        launch_entry.insert(0, "photo-s mcp")
        launch_entry.configure(state="readonly")
        launch_entry.pack(side="left", fill="x", expand=True)
        copy_launch = FlatButton(
            launch_row, text=self._t("copy"),
            command=lambda: self._copy_text(win, "photo-s mcp",
                                            copy_launch),
            bg=COLORS["bg"], fg=COLORS["text"], hover_bg=COLORS["border"],
            font=FONT_SMALL, padx=10, pady=3, border_color=COLORS["border"])
        copy_launch.pack(side="left", padx=(8, 0))

        # Claude Desktop config snippet
        tk.Label(inner, text=self._t("mcp_claude_config"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["bg"]).pack(anchor="w",
                                                                    pady=(10, 2))
        cfg_row = tk.Frame(inner, bg=COLORS["bg"])
        cfg_row.pack(anchor="w", fill="x")
        snippet = self._t("mcp_claude_snippet")
        cfg_text = tk.Text(cfg_row, height=7, font=("Menlo", 10),
                           bg=COLORS["card"], fg=COLORS["text"],
                           relief="flat", borderwidth=0, wrap="none")
        cfg_text.insert("1.0", snippet)
        cfg_text.configure(state="disabled")
        cfg_text.pack(side="left", fill="both", expand=True)
        copy_cfg = FlatButton(
            cfg_row, text=self._t("copy"),
            command=lambda: self._copy_text(win, snippet, copy_cfg),
            bg=COLORS["bg"], fg=COLORS["text"], hover_bg=COLORS["border"],
            font=FONT_SMALL, padx=10, pady=3, border_color=COLORS["border"])
        copy_cfg.pack(side="left", padx=(8, 0), fill="y")

        # ── Optional dependencies ────────────────────────────────────────────
        section_title(self._t("set_deps"))
        deps = [
            ("rawpy", "rawpy", "RAW"),
            ("piexif", "piexif", "EXIF"),
            ("watchdog", "watchdog", "watch"),
            ("opencv-python-headless", "cv2", "enhance"),
            ("mcp", "mcp", "MCP"),
        ]
        for dist, mod, purpose in deps:
            row = tk.Frame(inner, bg=COLORS["bg"])
            row.pack(anchor="w", fill="x", pady=1)
            tk.Label(row, text=f"{dist} ({purpose})", font=FONT_SMALL,
                     fg=COLORS["text"], bg=COLORS["bg"],
                     width=30, anchor="w").pack(side="left")
            installed = importlib.util.find_spec(mod) is not None
            status = _status_lbl(
                row, ("✅ " + self._t("mcp_installed")) if installed
                else ("· " + self._t("mcp_missing")),
                COLORS["success"] if installed else COLORS["text_secondary"])
            status.pack(side="left")
            if not installed:
                btn = FlatButton(
                    row, text=self._t("dep_install"),
                    command=lambda d=dist, s=status, b=None:
                        self._run_dep_install(
                            win, d, b, s,
                            lambda: "✅ " + self._t("mcp_installed")),
                    bg=COLORS["accent"], hover_bg=COLORS["accent_hover"],
                    font=FONT_SMALL, padx=8, pady=2)
                btn.pack(side="left", padx=(8, 0))
                install_btns.append(btn)

        # ── Plugin manager link ──────────────────────────────────────────────
        FlatButton(inner, text=self._t("set_plugins_link"),
                   command=lambda: (win.destroy(), self._show_plugin_manager()),
                   bg=COLORS["bg"], fg=COLORS["text"],
                   hover_bg=COLORS["border"], font=FONT_SMALL, padx=12, pady=4,
                   border_color=COLORS["border"]).pack(anchor="w", pady=(14, 0))

        self._settings_install_btns = install_btns

        FlatButton(inner, text=self._t("close"), command=win.destroy,
                   bg=COLORS["accent"], hover_bg=COLORS["accent_hover"],
                   font=FONT_BUTTON, padx=20, pady=6).pack(pady=(16, 0))

    def _copy_text(self, win, text, btn):
        """Copy text to the clipboard and flash the button label."""
        win.clipboard_clear()
        win.clipboard_append(text)
        old = btn.cget("text")
        btn.configure(text=self._t("copied"))

        def _restore():
            # The dialog may have been closed within the 1.2s — the widget
            # is gone then, and Tk's after is interp-global (destroying the
            # widget does NOT cancel it), so guard before touching it.
            if btn.winfo_exists():
                btn.configure(text=old)
        win.after(1200, _restore)

    def _run_dep_install(self, win, dist, btn, status_lbl, ok_text):
        """Install an optional dependency in a background thread.

        pip is subprocess-based (thread-safe); Tk must only be touched from
        the main thread, so all UI updates go through win.after(). All
        install buttons are disabled during the run (pip holds a global
        lock — concurrent installs would wedge).
        """
        for b in getattr(self, "_settings_install_btns", []):
            if b is not None:
                b.configure(state="disabled")
        status_lbl.config(text=self._t("dep_installing"))

        def worker():
            try:
                from .plugincmd import _pip_run
                proc = _pip_run(["install", "--quiet", dist])
                ok = proc.returncode == 0
                detail = (proc.stderr or "").strip()[-200:]
            except FileNotFoundError:
                ok, detail = False, "pip not available"

            def finish():
                # The dialog may have been closed while pip ran (after is
                # interp-global — not cancelled by widget destruction).
                if not win.winfo_exists():
                    return
                for b in getattr(self, "_settings_install_btns", []):
                    if b is not None:
                        b.configure(state="normal")
                if ok:
                    status_lbl.config(text=ok_text(),
                                      fg=COLORS["success"])
                else:
                    status_lbl.config(
                        text="❌ " + (detail or self._t("mcp_missing")),
                        fg=COLORS["danger"])
            win.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    # ── Exposure Analysis ───────────────────────────────────────────────────

    def _show_analysis(self):
        """Dialog showing exposure / sharpness stats + luminance histogram
        for the currently selected file (via photo_s.metrics)."""
        from .metrics import compute_exposure_stats, compute_blur_score

        selected = list(self._selected_rows)
        if not selected:
            messagebox.showwarning(self._t("analyze_title"),
                                   self._t("analyze_none"))
            return
        path = selected[0]

        stats = compute_exposure_stats(path)
        if not stats.get("ok"):
            messagebox.showerror(self._t("analyze_title"),
                                 self._t("analyze_err"))
            return

        win = tk.Toplevel(self.root)
        win.title("{} — {}".format(self._t("analyze_title"),
                                   os.path.basename(path)))
        win.configure(bg=COLORS["bg"])
        win.transient(self.root)
        win.resizable(False, False)

        inner = tk.Frame(win, bg=COLORS["bg"])
        inner.pack(padx=24, pady=20)

        def stat_row(label, value, color=None):
            row = tk.Frame(inner, bg=COLORS["bg"])
            row.pack(anchor="w", fill="x", pady=1)
            tk.Label(row, text=label, font=FONT_SMALL,
                     fg=COLORS["text_secondary"], bg=COLORS["bg"],
                     width=22, anchor="w").pack(side="left")
            tk.Label(row, text=value, font=FONT_SMALL,
                     fg=color or COLORS["text"], bg=COLORS["bg"]).pack(side="left")

        stat_row(self._t("analyze_luminance"),
                 "{:.3f}".format(stats["luminance"]))
        stat_row(self._t("analyze_over"),
                 "{:.2f}%".format(stats["overexposed_pct"]),
                 COLORS["danger"] if stats["overexposed_pct"] > 0
                 else COLORS["text"])
        stat_row(self._t("analyze_under"),
                 "{:.2f}%".format(stats["underexposed_pct"]),
                 COLORS["warning"] if stats["underexposed_pct"] > 0
                 else COLORS["text"])
        try:
            blur = compute_blur_score(path)
            stat_row(self._t("analyze_blur"), "{:.1f}".format(blur))
        except Exception:
            pass

        # Luminance histogram (from the same grayscale sample)
        tk.Label(inner, text=self._t("analyze_histogram"),
                 font=FONT_SECTION, fg=COLORS["text"],
                 bg=COLORS["bg"]).pack(anchor="w", pady=(14, 6))
        canvas = tk.Canvas(inner, width=360, height=120, bg=COLORS["card"],
                           highlightthickness=0, bd=0)
        canvas.pack()

        from PIL import Image
        img = _open_image_safe(path)
        sample = img.convert("L").copy()
        sample.thumbnail((256, 256))
        hist = sample.histogram()  # 256 bins

        max_bin = max(hist) or 1
        bins = 64  # aggregate into 64 bars
        bar_w = 360 / bins
        for i in range(bins):
            lo = i * 4
            hi = lo + 4
            h = sum(hist[lo:hi]) / max_bin
            h = max(h * 100, 1.0)  # min visible bar
            color = COLORS["accent"] if 30 <= lo <= 225 else COLORS["border"]
            canvas.create_rectangle(i * bar_w, 120 - h,
                                    (i + 1) * bar_w, 120,
                                    fill=color, outline="")

        FlatButton(inner, text=self._t("close"), command=win.destroy,
                   bg=COLORS["accent"], hover_bg=COLORS["accent_hover"],
                   font=FONT_BUTTON, padx=24, pady=6).pack(pady=(16, 0))

    # ── File Management ─────────────────────────────────────────────────────

    def _gallery_build(self, paths, out_dir, title="PhotoS Gallery",
                       thumb_size=360):
        """Sync: build the HTML gallery (thin wrapper so tests can call it
        without touching Tk)."""
        from .gallery import build_gallery
        return build_gallery(list(paths), out_dir, title=title,
                             thumb_size=thumb_size)

    def _show_gallery_export(self):
        """Gallery export dialog: title + thumb size + output dir, then
        build the HTML gallery in a background thread (thumbnail
        rendering can take a while)."""
        if not self.files:
            messagebox.showinfo(self._t("gallery_title"),
                                self._t("gallery_need_files"))
            return
        files = self._checked_files()
        if not files:
            messagebox.showinfo(self._t("gallery_title"),
                                self._t("check_none"))
            return

        win = tk.Toplevel(self.root)
        win.title(self._t("gallery_title"))
        win.geometry("480x360")
        win.configure(bg=COLORS["bg"])
        win.transient(self.root)

        body = tk.Frame(win, bg=COLORS["bg"])
        body.pack(fill="both", expand=True, padx=20, pady=16)
        body.columnconfigure(0, weight=1)

        tk.Label(body, text=self._t("gallery_name"), font=FONT_BODY,
                 fg=COLORS["text"], bg=COLORS["bg"]).grid(
            row=0, column=0, sticky="w", pady=(0, 2))
        title_var = tk.StringVar(value="PhotoS Gallery")
        ttk.Entry(body, textvariable=title_var, font=FONT_BODY).grid(
            row=1, column=0, sticky="ew", pady=(0, 10))

        tk.Label(body, text=self._t("gallery_thumb"), font=FONT_BODY,
                 fg=COLORS["text"], bg=COLORS["bg"]).grid(
            row=2, column=0, sticky="w", pady=(0, 2))
        thumb_combo = ttk.Combobox(
            body, values=("240", "360", "480", "600"),
            state="readonly", font=FONT_BODY, width=8)
        thumb_combo.set("360")
        thumb_combo.grid(row=3, column=0, sticky="w", pady=(0, 10))

        tk.Label(body, text=self._t("gallery_out"), font=FONT_BODY,
                 fg=COLORS["text"], bg=COLORS["bg"]).grid(
            row=4, column=0, sticky="w", pady=(0, 2))
        out_row = tk.Frame(body, bg=COLORS["bg"])
        out_row.grid(row=5, column=0, sticky="ew", pady=(0, 10))
        out_var = tk.StringVar(value=self.output_dir.get())
        ttk.Entry(out_row, textvariable=out_var, font=FONT_BODY).pack(
            side="left", fill="x", expand=True)

        def _browse_out():
            if self._dlg_cooldown_active():
                return
            picked = filedialog.askdirectory(title=self._t("gallery_out"))
            self._after_file_dialog()
            if picked:
                out_var.set(picked)

        FlatButton(
            out_row, text=self._t("browse"), command=_browse_out,
            bg=COLORS["bg"], fg=COLORS["text"], hover_bg=COLORS["border"],
            font=FONT_SMALL, padx=10, pady=3,
            border_color=COLORS["border"]).pack(side="left", padx=(8, 0))

        status_lbl = tk.Label(body, text="", font=FONT_SMALL,
                              fg=COLORS["text_secondary"], bg=COLORS["bg"])
        status_lbl.grid(row=6, column=0, sticky="w", pady=(0, 8))

        btns = tk.Frame(body, bg=COLORS["bg"])
        btns.grid(row=7, column=0, sticky="w")
        state = {"output": None}

        # Worker threads must never touch Tk directly: they put UI
        # callbacks on a queue and a main-thread after-loop drains it
        # (win.after from a worker raises "main thread is not in main
        # loop" whenever the mainloop is not running).
        q = queue.Queue()

        def schedule(fn):
            q.put(fn)

        def drain():
            try:
                while True:
                    q.get_nowait()()
            except queue.Empty:
                pass
            if win.winfo_exists():
                win.after(80, drain)

        win.after(80, drain)

        def set_status(text, color=None):
            if win.winfo_exists():
                status_lbl.configure(
                    text=text, fg=color or COLORS["text_secondary"])

        def run():
            out_dir = out_var.get().strip()
            if not out_dir:
                schedule(lambda: set_status(
                    self._t("gallery_need_dir"), COLORS["danger"]))
                return
            schedule(lambda: (
                generate_btn.configure(state="disabled"),
                set_status(self._t("gallery_generating"))))
            try:
                res = self._gallery_build(
                    list(files), out_dir,
                    title=title_var.get().strip() or "PhotoS Gallery",
                    thumb_size=int(thumb_combo.get()))
            except Exception as e:
                schedule(lambda: _failed(str(e)))
            else:
                schedule(lambda: _done(res))

        def _failed(err):
            if not win.winfo_exists():
                return
            generate_btn.configure(state="normal")
            set_status(self._t("gallery_error", err=err), COLORS["danger"])

        def _done(res):
            if not win.winfo_exists():
                return
            state["output"] = res["output"]
            generate_btn.configure(state="normal")
            set_status(self._t("gallery_done", count=res["count"],
                               path=res["output"]), COLORS["accent"])
            open_btn.pack(side="left", padx=(8, 0))

        generate_btn = FlatButton(
            btns, text=self._t("gallery_generate"),
            command=lambda: threading.Thread(target=run, daemon=True).start(),
            bg=COLORS["accent"])
        generate_btn.pack(side="left")
        open_btn = FlatButton(
            btns, text=self._t("gallery_open"),
            command=lambda: state["output"]
            and webbrowser.open("file://" + state["output"]),
            bg=COLORS["bg"], fg=COLORS["text"], hover_bg=COLORS["border"],
            border_color=COLORS["border"])

    # ── Duplicate viewer ────────────────────────────────────────────────────

    def _dedup_scan(self, paths, threshold=5, progress_cb=None):
        """Sync: find duplicate groups + per-image blur scores.

        Returns (groups, scores): groups is a list of path-lists (each
        >= 2 members), scores maps path -> blur score (0.0 on error).
        Tk-free so tests can call it directly.
        """
        from .dedup import find_duplicates
        from .metrics import compute_blur_score

        dup_groups = find_duplicates(list(paths), threshold=threshold,
                                     progress_callback=progress_cb)
        groups = [list(g) for g in dup_groups.values() if len(g) >= 2]
        scores = {}
        for group in groups:
            for p in group:
                try:
                    scores[p] = compute_blur_score(p)
                except Exception:
                    scores[p] = 0.0
        return groups, scores

    def _dedup_trash_path(self, path, trash_dir):
        """Trash destination: trash_dir/basename with a numeric suffix if
        the name is taken (mirrors dedup.py move collision logic)."""
        dest = os.path.join(trash_dir, os.path.basename(path))
        stem, ext = os.path.splitext(dest)
        n = 1
        while os.path.exists(dest):
            dest = "{}_{}{}".format(stem, n, ext)
            n += 1
        return dest

    def _dedup_move_to_trash(self, paths, trash_dir, progress_cb=None):
        """Sync: move ``paths`` into ``trash_dir`` (created if needed).
        Returns (moved, failed). Tk-free so tests can call it directly."""
        moved, failed = 0, 0
        try:
            os.makedirs(trash_dir, exist_ok=True)
        except OSError:
            return 0, len(paths)
        for i, p in enumerate(paths):
            try:
                os.rename(p, self._dedup_trash_path(p, trash_dir))
                moved += 1
            except OSError:
                failed += 1
            if progress_cb:
                progress_cb(i + 1, len(paths))
        return moved, failed

    def _show_dedup(self):
        """Duplicate viewer: scan in a background thread, render groups
        with per-image keep-checkboxes (sharpest pre-checked), move the
        unchecked ones into a ``_duplicates_trash`` subfolder."""
        if not self.files:
            messagebox.showinfo(self._t("dedup_title"),
                                self._t("gallery_need_files"))
            return
        files = self._checked_files()
        if not files:
            messagebox.showinfo(self._t("dedup_title"),
                                self._t("check_none"))
            return

        win = tk.Toplevel(self.root)
        win.title(self._t("dedup_title"))
        win.geometry("980x660")
        win.configure(bg=COLORS["bg"])
        win.transient(self.root)
        canvas_unbind_safe(win)

        header = tk.Frame(win, bg=COLORS["bg"])
        header.pack(fill="x", padx=20, pady=(16, 4))
        tk.Label(header, text=self._t("dedup_title"),
                 font=(PLATFORM_FONTS["title"], 14, "bold"),
                 fg=COLORS["text"], bg=COLORS["bg"]).pack(side="left")
        status_lbl = tk.Label(header, text="", font=FONT_SMALL,
                              fg=COLORS["text_secondary"], bg=COLORS["bg"])
        status_lbl.pack(side="left", padx=(16, 0))

        # Scrollable group area
        holder = tk.Frame(win, bg=COLORS["bg"])
        holder.pack(fill="both", expand=True, padx=20, pady=8)
        canvas = tk.Canvas(holder, bg=COLORS["bg"], highlightthickness=0,
                           borderwidth=0)
        sb = ttk.Scrollbar(holder, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=COLORS["bg"])
        canvas.create_window((0, 0), window=inner, anchor="nw")

        def _sync_scroll(event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        inner.bind("<Configure>", _sync_scroll)

        def _on_mw(event):
            if inner.winfo_reqheight() > canvas.winfo_height():
                canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

        canvas.bind("<Enter>",
                    lambda e: canvas.bind_all("<MouseWheel>", _on_mw))
        canvas.bind("<Leave>",
                    lambda e: canvas.unbind_all("<MouseWheel>"))

        footer = tk.Frame(win, bg=COLORS["bg"])
        footer.pack(fill="x", padx=20, pady=(4, 16))

        state = {"groups": [], "scores": {}, "checks": [], "sharp": set()}

        # Worker→UI marshalling queue (see gallery dialog for rationale)
        q = queue.Queue()

        def schedule(fn):
            q.put(fn)

        def drain():
            try:
                while True:
                    q.get_nowait()()
            except queue.Empty:
                pass
            if win.winfo_exists():
                win.after(80, drain)

        win.after(80, drain)

        def render():
            for w in inner.winfo_children():
                w.destroy()
            state["checks"] = []
            state["sharp"] = set()
            groups, scores = state["groups"], state["scores"]
            if not groups:
                tk.Label(inner, text=self._t("dedup_none"), font=FONT_BODY,
                         fg=COLORS["text_secondary"],
                         bg=COLORS["bg"]).pack(pady=40)
                execute_btn.configure(state="disabled")
                return
            from PIL import Image, ImageTk
            for gi, group in enumerate(groups):
                card = tk.Frame(inner, bg=COLORS["card"], bd=0,
                                highlightthickness=0)
                card.pack(fill="x", padx=2, pady=(0, 10))
                head = tk.Frame(card, bg=COLORS["card"])
                head.pack(fill="x", padx=12, pady=(10, 4))
                tk.Label(head, text=self._t("dedup_group", i=gi + 1),
                         font=(PLATFORM_FONTS["body"], 12, "bold"),
                         fg=COLORS["text"], bg=COLORS["card"]).pack(
                    side="left")
                tk.Label(head, text="· {}".format(
                    self._t("files_count", n=len(group))), font=FONT_SMALL,
                    fg=COLORS["text_secondary"], bg=COLORS["card"]).pack(
                    side="left", padx=(8, 0))
                row = tk.Frame(card, bg=COLORS["card"])
                row.pack(fill="x", padx=12, pady=(0, 12))
                sharpest = max(group,
                               key=lambda p: scores.get(p, 0.0))
                state["sharp"].add(sharpest)
                for p in group:
                    cell = tk.Frame(row, bg=COLORS["card"])
                    cell.pack(side="left", padx=6)
                    try:
                        img = _open_image_safe(p).convert("RGB")
                        img.thumbnail((150, 150), Image.LANCZOS)
                        photo = ImageTk.PhotoImage(img)
                        lbl = tk.Label(cell, image=photo, bg=COLORS["bg"],
                                       bd=0, highlightthickness=0)
                        lbl.image = photo  # keep the reference alive
                        lbl.pack()
                    except Exception:
                        tk.Label(cell, text="?", width=12, height=6,
                                 bg=COLORS["bg"],
                                 fg=COLORS["text_secondary"]).pack()
                    cap = os.path.basename(p)
                    if len(cap) > 16:
                        cap = cap[:15] + "…"
                    star = " " + self._t("dedup_sharpest") \
                        if p == sharpest else ""
                    tk.Label(cell, text=cap + star, font=FONT_TINY,
                             fg=COLORS["text_secondary"],
                             bg=COLORS["card"]).pack()
                    tk.Label(cell, text="{} {:.1f}".format(
                        self._t("dedup_blur"), scores.get(p, 0.0)),
                        font=FONT_TINY, fg=COLORS["text_secondary"],
                        bg=COLORS["card"]).pack()
                    var = tk.BooleanVar(value=(p == sharpest))
                    ttk.Checkbutton(cell, text=self._t("dedup_keep"),
                                    variable=var).pack(pady=(2, 0))
                    state["checks"].append((p, var))
            execute_btn.configure(state="normal")

        def scan_thread():
            try:
                def cb(cur, total):
                    schedule(lambda: status_lbl.configure(
                        text=self._t("dedup_scanning", n=cur, total=total)))

                groups, scores = self._dedup_scan(list(files),
                                                  progress_cb=cb)
            except Exception as e:
                schedule(lambda: _scan_failed(str(e)))
                return
            schedule(lambda: _scanned(groups, scores))

        def _scan_failed(err):
            if not win.winfo_exists():
                return
            status_lbl.configure(text=self._t("op_failed", err=err),
                                 fg=COLORS["danger"])

        def _scanned(groups, scores):
            if not win.winfo_exists():
                return
            state["groups"], state["scores"] = groups, scores
            status_lbl.configure(text="")
            render()

        def execute():
            unchecked = [p for p, var in state["checks"] if not var.get()]
            if not unchecked:
                messagebox.showinfo(self._t("dedup_title"),
                                    self._t("dedup_none_selected"))
                return
            if not messagebox.askyesno(
                    self._t("dedup_title"),
                    self._t("dedup_confirm", n=len(unchecked))):
                return
            # single trash dir next to the first file's folder
            trash_dir = os.path.join(os.path.dirname(files[0]),
                                     "_duplicates_trash")
            execute_btn.configure(state="disabled")

            def move_thread():
                try:
                    def cb(cur, total):
                        schedule(lambda: status_lbl.configure(
                            text="{} {}/{}".format(self._t("dedup_moving"),
                                                   cur, total)))

                    moved, failed = self._dedup_move_to_trash(
                        unchecked, trash_dir, progress_cb=cb)
                except Exception as e:
                    schedule(lambda: _scan_failed(str(e)))
                    return
                schedule(lambda: _moved(moved, failed, unchecked, trash_dir))

            def _moved(moved, failed, unchecked, trash_dir):
                if not win.winfo_exists():
                    return
                moved_set = set(unchecked)
                self.files = [f for f in self.files if f not in moved_set]
                self._checked -= moved_set
                self._refresh_file_list()
                self._update_stats()
                state["groups"] = [
                    [p for p in g if p not in moved_set]
                    for g in state["groups"]]
                state["groups"] = [g for g in state["groups"]
                                   if len(g) >= 2]
                state["scores"] = {p: s for p, s in state["scores"].items()
                                   if p not in moved_set}
                msg = self._t("dedup_moved", n=moved, dir=trash_dir)
                if failed:
                    msg += "（{} 失败）".format(failed)
                status_lbl.configure(text=msg, fg=COLORS["accent"])
                render()

            threading.Thread(target=move_thread, daemon=True).start()

        execute_btn = FlatButton(
            footer, text=self._t("dedup_execute"), command=execute,
            bg=COLORS["accent"])
        execute_btn.configure(state="disabled")
        execute_btn.pack(side="left")
        FlatButton(
            footer, text=self._t("dedup_rescan"),
            command=lambda: threading.Thread(target=scan_thread,
                                             daemon=True).start(),
            bg=COLORS["bg"], fg=COLORS["text"], hover_bg=COLORS["border"],
            border_color=COLORS["border"]).pack(side="left", padx=(8, 0))
        FlatButton(
            footer, text=self._t("close"), command=win.destroy,
            bg=COLORS["bg"], fg=COLORS["text"], hover_bg=COLORS["border"],
            border_color=COLORS["border"]).pack(side="right")

        threading.Thread(target=scan_thread, daemon=True).start()

    # ── Review & rate dialog ────────────────────────────────────────────────

    def _review_scan(self, paths, progress_cb=None):
        """Sync: read EXIF metadata for all paths. Returns {path: meta}.
        Tk-free so tests can call it directly."""
        from .engine import read_exif_metadata
        meta = {}
        total = len(paths)
        for i, p in enumerate(paths):
            try:
                meta[p] = read_exif_metadata(p)
            except Exception:
                meta[p] = {"rating": None, "keywords": [], "title": "",
                           "caption": ""}
            if progress_cb:
                progress_cb(i + 1, total)
        return meta

    def _review_save(self, path, rating=None, keywords=None, title=None):
        """Sync: write rating/keywords/title diffs into ``path``'s EXIF
        (PhotoS: UserComment segment; only changed fields are touched).
        Returns (ok, message). Tk-free so tests can call it directly."""
        from .engine import apply_exif_tags, read_exif_metadata

        m = read_exif_metadata(path)
        tags = {}
        if rating is not None and rating != m.get("rating"):
            tags["rating"] = rating
        kw = (keywords or "").strip()
        if kw != ",".join(m.get("keywords") or []):
            tags["keywords"] = kw
        tl = (title or "").strip()
        if tl != (m.get("title") or ""):
            tags["title"] = tl
        if not tags:
            return True, ""
        try:
            msg = apply_exif_tags(path, tags)
        except Exception as e:
            return False, self._t("review_save_failed", err=str(e))
        if msg.startswith("⚠️"):
            return False, msg
        return True, msg

    def _show_review(self):
        """Lightbox review dialog: navigate, rate 0-5, tag keywords/title,
        filter by rating/keywords. EXIF writes go through the engine's
        PhotoS: UserComment segment; partial updates preserve other tags.
        Operates on the tree selection, or all files when none selected."""
        import importlib.util

        if not self.files:
            messagebox.showinfo(self._t("review_title"),
                                self._t("review_none"))
            return
        all_paths = self._checked_files()
        if not all_paths:
            messagebox.showinfo(self._t("review_title"),
                                self._t("check_none"))
            return

        has_piexif = importlib.util.find_spec("piexif") is not None

        win = tk.Toplevel(self.root)
        win.title(self._t("review_title"))
        win.geometry("1000x720")
        win.configure(bg=COLORS["bg"])
        win.transient(self.root)

        state = {"seq": [], "meta": {}, "idx": 0, "rating": None,
                 "photo": None}

        header = tk.Frame(win, bg=COLORS["bg"])
        header.pack(fill="x", padx=20, pady=(14, 4))
        tk.Label(header, text=self._t("review_title"),
                 font=(PLATFORM_FONTS["title"], 14, "bold"),
                 fg=COLORS["text"], bg=COLORS["bg"]).pack(side="left")
        pos_lbl = tk.Label(header, text="", font=FONT_BODY,
                           fg=COLORS["text_secondary"], bg=COLORS["bg"])
        pos_lbl.pack(side="left", padx=(16, 0))
        status_lbl = tk.Label(header, text="", font=FONT_SMALL,
                              fg=COLORS["text_secondary"], bg=COLORS["bg"])
        status_lbl.pack(side="right")

        if not has_piexif:
            tk.Label(win, text=self._t("review_no_piexif"), font=FONT_SMALL,
                     fg=COLORS["danger"], bg=COLORS["bg"]).pack(
                anchor="w", padx=20)

        # Image area + shooting-info line
        img_lbl = tk.Label(win, bg=COLORS["bg"])
        img_lbl.pack(fill="both", expand=True, padx=20, pady=8)
        info_lbl = tk.Label(win, text="", font=FONT_SMALL,
                            fg=COLORS["text_secondary"], bg=COLORS["bg"])
        info_lbl.pack(fill="x", padx=20, pady=(0, 2))

        # Nav + rating row
        ctrl = tk.Frame(win, bg=COLORS["bg"])
        ctrl.pack(fill="x", padx=20, pady=(0, 6))
        nav = tk.Frame(ctrl, bg=COLORS["bg"])
        nav.pack(side="left")
        prev_btn = FlatButton(
            nav, text=self._t("review_prev"), command=lambda: go(-1),
            bg=COLORS["card"], fg=COLORS["text"], hover_bg=COLORS["bg"],
            border_color=COLORS["border"], font=FONT_SMALL)
        prev_btn.pack(side="left")
        next_btn = FlatButton(
            nav, text=self._t("review_next"), command=lambda: go(1),
            bg=COLORS["card"], fg=COLORS["text"], hover_bg=COLORS["bg"],
            border_color=COLORS["border"], font=FONT_SMALL)
        next_btn.pack(side="left", padx=(8, 0))

        rating_box = tk.Frame(ctrl, bg=COLORS["bg"])
        rating_box.pack(side="left", padx=(20, 0))
        tk.Label(rating_box, text=self._t("review_rating"), font=FONT_BODY,
                 fg=COLORS["text"], bg=COLORS["bg"]).pack(
            side="left", padx=(0, 6))
        rating_btns = {}
        for n in range(6):
            btn = FlatButton(
                rating_box, text="{}★".format(n),
                command=lambda n=n: set_rating(n),
                bg=COLORS["card"], fg=COLORS["text"],
                hover_bg=COLORS["bg"], border_color=COLORS["border"],
                font=FONT_SMALL, padx=10, pady=3)
            btn.pack(side="left", padx=(4, 0))
            rating_btns[n] = btn

        # Keywords + title row
        fields = tk.Frame(win, bg=COLORS["bg"])
        fields.pack(fill="x", padx=20, pady=(0, 4))
        tk.Label(fields, text=self._t("review_keywords"), font=FONT_BODY,
                 fg=COLORS["text"], bg=COLORS["bg"]).pack(side="left")
        keywords_var = tk.StringVar()
        ttk.Entry(fields, textvariable=keywords_var, font=FONT_BODY).pack(
            side="left", fill="x", expand=True, padx=(8, 16))
        tk.Label(fields, text=self._t("review_title_lbl"), font=FONT_BODY,
                 fg=COLORS["text"], bg=COLORS["bg"]).pack(side="left")
        title_var = tk.StringVar()
        ttk.Entry(fields, textvariable=title_var, font=FONT_BODY).pack(
            side="left", fill="x", expand=True, padx=(8, 0))
        save_btn = FlatButton(
            fields, text=self._t("review_save"),
            command=lambda: save_current(),
            bg=COLORS["card"], fg=COLORS["text"], hover_bg=COLORS["bg"],
            border_color=COLORS["border"], font=FONT_SMALL, padx=10, pady=3)
        save_btn.pack(side="left", padx=(8, 0))

        # Filter row
        filt = tk.Frame(win, bg=COLORS["bg"])
        filt.pack(fill="x", padx=20, pady=(0, 14))
        tk.Label(filt, text=self._t("review_filter"), font=FONT_BODY,
                 fg=COLORS["text_secondary"], bg=COLORS["bg"]).pack(
            side="left")
        tk.Label(filt, text=self._t("review_min_rating"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["bg"]).pack(
            side="left", padx=(10, 4))
        min_rating_var = tk.StringVar(value="0")
        ttk.Combobox(filt, values=("0", "1", "2", "3", "4", "5"),
                     textvariable=min_rating_var, state="readonly",
                     width=3, font=FONT_SMALL).pack(side="left")
        tk.Label(filt, text=self._t("review_filter_kw"), font=FONT_SMALL,
                 fg=COLORS["text_secondary"], bg=COLORS["bg"]).pack(
            side="left", padx=(10, 4))
        filter_var = tk.StringVar()
        ttk.Entry(filt, textvariable=filter_var, font=FONT_SMALL,
                  width=16).pack(side="left")
        FlatButton(
            filt, text=self._t("review_apply_filter"),
            command=lambda: apply_filter(),
            bg=COLORS["card"], fg=COLORS["text"], hover_bg=COLORS["bg"],
            border_color=COLORS["border"], font=FONT_SMALL,
            padx=10, pady=3).pack(side="left", padx=(8, 0))
        FlatButton(
            filt, text=self._t("review_clear_filter"),
            command=lambda: clear_filter(),
            bg=COLORS["card"], fg=COLORS["text"], hover_bg=COLORS["bg"],
            border_color=COLORS["border"], font=FONT_SMALL,
            padx=10, pady=3).pack(side="left", padx=(8, 0))
        FlatButton(
            filt, text=self._t("close"), command=lambda: on_close(),
            bg=COLORS["card"], fg=COLORS["text"], hover_bg=COLORS["bg"],
            border_color=COLORS["border"], font=FONT_SMALL,
            padx=10, pady=3).pack(side="right")

        # Worker→UI marshalling queue (see gallery dialog for rationale)
        q = queue.Queue()

        def schedule(fn):
            q.put(fn)

        def drain():
            try:
                while True:
                    q.get_nowait()()
            except queue.Empty:
                pass
            if win.winfo_exists():
                win.after(80, drain)

        win.after(80, drain)

        def set_status(text, color=None):
            status_lbl.configure(text=text,
                                 fg=color or COLORS["text_secondary"])

        def save_current():
            """Write rating/keywords/title diffs for the current image."""
            if not state["seq"]:
                return True
            p = state["seq"][state["idx"]]
            ok, msg = self._review_save(
                p, rating=state["rating"],
                keywords=keywords_var.get(),
                title=title_var.get())
            if not ok:
                set_status(msg, COLORS["danger"])
                return False
            m = state["meta"].get(p, {})
            m["rating"] = state["rating"]
            m["keywords"] = [k for k
                             in keywords_var.get().strip().split(",")
                             if k.strip()]
            m["title"] = title_var.get().strip()
            if msg:
                set_status(self._t("review_saved") + " · " + msg,
                           COLORS["accent"])
            return True

        def _restyle_rating():
            for n, btn in rating_btns.items():
                active = (state["rating"] is not None
                          and n == state["rating"])
                btn.configure(
                    bg=COLORS["accent"] if active else COLORS["card"],
                    fg="white" if active else COLORS["text"],
                    border_color=COLORS["accent"] if active
                    else COLORS["border"])

        def show():
            if not state["seq"]:
                img_lbl.configure(image="", text=self._t("review_empty"))
                info_lbl.configure(text="")
                pos_lbl.configure(text="0 / 0")
                prev_btn.configure(state="disabled")
                next_btn.configure(state="disabled")
                return
            idx = state["idx"]
            p = state["seq"][idx]
            m = state["meta"].get(p, {})
            state["rating"] = m.get("rating")
            keywords_var.set(",".join(m.get("keywords") or []))
            title_var.set(m.get("title") or "")
            pos_lbl.configure(text=self._t("review_pos", i=idx + 1,
                                           n=len(state["seq"])))
            parts = []
            if m.get("date"):
                parts.append(m["date"])
            if m.get("camera"):
                parts.append(m["camera"])
            if m.get("iso"):
                parts.append("ISO " + str(m["iso"]))
            if m.get("focal"):
                parts.append(str(m["focal"]))
            info_lbl.configure(text="  |  ".join(parts))
            prev_btn.configure(
                state="normal" if idx > 0 else "disabled")
            next_btn.configure(
                state="normal" if idx < len(state["seq"]) - 1
                else "disabled")
            _restyle_rating()
            state["photo"] = None
            try:
                from PIL import Image, ImageTk
                img = _open_image_safe(p).convert("RGB")
                img.thumbnail((900, 540), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                img_lbl.configure(image=photo, text="")
                state["photo"] = photo  # keep the reference alive
            except Exception as e:
                img_lbl.configure(image="",
                                  text=os.path.basename(p) + "\n" + str(e))

        def set_rating(n):
            if not state["seq"]:
                return
            state["rating"] = n
            _restyle_rating()
            save_current()

        def go(delta):
            if not state["seq"]:
                return
            save_current()
            new_idx = state["idx"] + delta
            if 0 <= new_idx < len(state["seq"]):
                state["idx"] = new_idx
                show()

        def apply_filter():
            save_current()
            min_r = int(min_rating_var.get() or 0)
            kw = filter_var.get().strip().lower()
            seq = []
            for p in all_paths:
                m = state["meta"].get(p, {})
                if (m.get("rating") or 0) < min_r:
                    continue
                if kw:
                    kws = [k.lower() for k in (m.get("keywords") or [])]
                    if not any(kw in k for k in kws):
                        continue
                seq.append(p)
            state["seq"] = seq
            state["idx"] = 0
            show()

        def clear_filter():
            filter_var.set("")
            min_rating_var.set("0")
            state["seq"] = list(all_paths)
            state["idx"] = 0
            show()

        def on_close():
            save_current()
            win.destroy()

        def _focus_in_input():
            w = win.focus_get()
            return isinstance(w, (ttk.Entry, ttk.Combobox, tk.Entry))

        win.bind("<Left>", lambda e: go(-1) if not _focus_in_input() else None)
        win.bind("<Right>", lambda e: go(1) if not _focus_in_input() else None)
        for n in range(6):
            win.bind(str(n), lambda e, n=n: (
                set_rating(n) if not _focus_in_input() else None))
        win.bind("<Escape>", lambda e: on_close())

        def scan_thread():
            try:
                def cb(cur, total):
                    schedule(lambda: set_status(
                        self._t("review_loading", n=cur, total=total)))

                meta = self._review_scan(all_paths, progress_cb=cb)
            except Exception as e:
                schedule(lambda: set_status(
                    self._t("op_failed", err=str(e)), COLORS["danger"]))
                return
            schedule(lambda: _scanned(meta))

        def _scanned(meta):
            if not win.winfo_exists():
                return
            state["meta"] = meta
            state["seq"] = list(all_paths)
            state["idx"] = 0
            set_status("")
            show()

        win.protocol("WM_DELETE_WINDOW", on_close)
        threading.Thread(target=scan_thread, daemon=True).start()

    def _after_file_dialog(self, btn=None):
        """Work around the macOS Tk native-file-dialog focus bug: after
        the dialog closes, Tk can re-deliver the closing click into the
        window (re-opening the dialog on the next click anywhere) and
        leaves the button stuck in its hover fill (the Leave event was
        eaten by the dialog). Reset the hover look and gate dialog
        re-entry for a short cooldown."""
        if btn is not None:
            btn._on_leave(None)
        self._dlg_guard_until = time.monotonic() + 0.4

    def _dlg_cooldown_active(self) -> bool:
        return time.monotonic() < getattr(self, "_dlg_guard_until", 0.0)

    def _add_files(self):
        """Open file dialog to add image files."""
        if self._dlg_cooldown_active():
            return
        extensions = []
        for ext in sorted(INPUT_EXTENSIONS):
            extensions.append(f"*{ext}")
            extensions.append(f"*{ext.upper()}")

        filetypes = [
            ("All Images", extensions),
            ("All Images + RAW", extensions + ["*.cr2", "*.CR2", "*.nef",
             "*.NEF", "*.arw", "*.ARW", "*.dng", "*.DNG", "*.orf", "*.ORF",
             "*.rw2", "*.RW2", "*.raf", "*.RAF", "*.pef", "*.PEF"]),
            ("JPEG", "*.jpg *.jpeg *.JPG *.JPEG"),
            ("PNG", "*.png *.PNG"),
            ("WebP", "*.webp *.WEBP"),
            ("HEIC", "*.heic *.heif *.HEIC *.HEIF"),
            ("RAW", "*.cr2 *.CR2 *.nef *.NEF *.arw *.ARW *.dng *.DNG *.orf *.ORF *.rw2 *.RW2 *.raf *.RAF"),
            ("All Files", "*.*"),
        ]

        paths = filedialog.askopenfilenames(
            title=self._t("add_images"),
            filetypes=filetypes,
        )
        self._after_file_dialog(self.add_files_btn)

        if paths:
            added = self._append_files(list(paths))
            if added == 0 and self._last_skipped:
                messagebox.showinfo(
                    self._t("dlg_no_images_title"),
                    self._t("dlg_no_supported", m=self._last_skipped))
            elif self._last_skipped:
                messagebox.showinfo(
                    self._t("dlg_added_title"),
                    self._t("dlg_skipped", n=added, m=self._last_skipped))

    def _add_folder(self):
        """Open folder dialog and scan for images (recursively)."""
        if self._dlg_cooldown_active():
            return
        folder = filedialog.askdirectory(title=self._t("add_folder"))
        self._after_file_dialog(self.add_folder_btn)
        if folder:
            images = scan_directory(folder, recursive=True)
            skipped = self._count_unsupported(folder)
            if not images:
                if skipped:
                    messagebox.showinfo(
                        self._t("dlg_no_images_title"),
                        self._t("dlg_no_supported", m=skipped))
                else:
                    messagebox.showinfo(
                        self._t("dlg_no_images_title"),
                        self._t("dlg_no_images"))
                return
            added = self._append_files(images)
            if added == 0:
                messagebox.showinfo(
                    self._t("dlg_no_images_title"),
                    self._t("dlg_no_images"))
                return
            if skipped:
                messagebox.showinfo(
                    self._t("dlg_added_title"),
                    self._t("dlg_skipped", n=added, m=skipped))
            else:
                messagebox.showinfo(
                    self._t("dlg_added_title"),
                    self._t("dlg_added", n=added))

    def _total_size(self) -> int:
        """Total size of listed files, ignoring files that no longer exist."""
        total = 0
        for f in self.files:
            try:
                total += os.path.getsize(f)
            except OSError:
                pass
        return total

    def _checked_files(self) -> List[str]:
        """Checked files in list order (the set all workflow actions use)."""
        return [p for p in self.files if p in self._checked]

    def _update_count_label(self):
        """File-count label in the toolbar (shows the checked subset
        when only some files are checked)."""
        if self._checked and len(self._checked) < len(self.files):
            self.file_count_label.config(text=self._t(
                "files_count_checked", n=len(self.files),
                m=len(self._checked)))
        else:
            self.file_count_label.config(
                text=self._t("files_count", n=len(self.files)))

    def _make_check_cb(self, path):
        """Checkbutton command: keep self._checked in sync with the
        clicked checkbox (Tk flips the variable before the command)."""

        def on_toggle():
            if self._row_vars[path].get():
                self._checked.add(path)
            else:
                self._checked.discard(path)
            self._update_count_label()

        return on_toggle

    def _toggle_check(self, path):
        """Toggle the checkbox for one row (programmatic / test seam).
        Syncs the row's variable in place — no full re-render."""
        if path in self._checked:
            self._checked.discard(path)
        else:
            self._checked.add(path)
        var = self._row_vars.get(path)
        if var is not None:
            var.set(path in self._checked)
        self._update_count_label()

    def _toggle_all_checks(self):
        """Uncheck all when everything is checked, else check all."""
        if self._checked and len(self._checked) == len(self.files):
            self._checked.clear()
        else:
            self._checked = set(self.files)
        self._refresh_file_list()

    def _select_row(self, path):
        """Click on a row toggles its ephemeral selection highlight
        (remove/analyze/compare scope — distinct from the checkbox)."""
        if path in self._selected_rows:
            self._selected_rows.discard(path)
        else:
            self._selected_rows.add(path)
        self._highlight_row(path)

    def _highlight_row(self, path):
        """Apply/clear the selection highlight for one row."""
        w = self._row_widgets.get(path)
        if not w:
            return
        on = path in self._selected_rows
        bg = COLORS["accent"] if on else w["base_bg"]
        w["row"].configure(bg=bg)
        for lbl, base_fg in w["labels"]:
            lbl.configure(bg=bg, fg="white" if on else base_fg)

    def _remove_selected(self):
        """Remove the selected rows from the list (exact by full path,
        so same-name files in different folders never collide)."""
        selected = list(self._selected_rows)
        if not selected:
            return

        remove_paths = set(selected)
        self._selected_rows -= remove_paths
        self.files = [f for f in self.files if f not in remove_paths]
        self._checked -= remove_paths
        self._refresh_file_list()
        self._update_stats()

    def _count_unsupported(self, directory) -> int:
        """Count non-hidden files under ``directory`` that PhotoS cannot
        read (anything outside engine.ALL_INPUT_EXTENSIONS)."""
        count = 0
        for root, dirs, files in os.walk(directory):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in files:
                if f.startswith("."):
                    continue
                if os.path.splitext(f)[1].lower() not in ALL_INPUT_EXTENSIONS:
                    count += 1
        return count

    def _append_files(self, new_paths: List[str]) -> int:
        """Dedupe-append paths to the file list (queued when processing).

        Unsupported files are skipped (counted into ``self._last_skipped``
        for the caller to notify). Returns the number of newly added paths.
        """
        self._last_skipped = 0
        added = 0
        fresh = []
        for p in new_paths:
            if os.path.isdir(p):
                # recursive: a folder may hold the photos in subfolders
                self._last_skipped += self._count_unsupported(p)
                for img in scan_directory(p, recursive=True):
                    if img not in self.files:
                        self.files.append(img)
                        fresh.append(img)
                        added += 1
            elif os.path.isfile(p):
                if os.path.splitext(p)[1].lower() not in ALL_INPUT_EXTENSIONS:
                    self._last_skipped += 1
                    continue
                if p not in self.files:
                    self.files.append(p)
                    fresh.append(p)
                    added += 1

        if fresh:
            # new files start checked (default: process everything added)
            self._checked.update(fresh)
        if added:
            self._refresh_file_list()
            self._update_stats()
            if self.processing:
                # Batch in flight: queue fresh files for an automatic follow-up
                for p in fresh:
                    if p not in self._queued_files:
                        self._queued_files.append(p)
        return added
        return added

    def _on_drop(self, event):
        """Handle drag-and-drop of files/folders onto the file list."""
        try:
            paths = self.root.tk.splitlist(event.data)
        except Exception:
            paths = event.data.split()

        if paths:
            added = self._append_files(list(paths))
            if added == 0:
                if self._last_skipped:
                    messagebox.showinfo(
                        self._t("dlg_no_images_title"),
                        self._t("dlg_no_supported", m=self._last_skipped))
                else:
                    messagebox.showinfo(
                        self._t("dlg_no_images_title"),
                        self._t("dlg_drop_none"))
            elif self._last_skipped:
                messagebox.showinfo(
                    self._t("dlg_added_title"),
                    self._t("dlg_skipped", n=added, m=self._last_skipped))

    def _clear_files(self):
        """Clear all files from the list."""
        if self.files and messagebox.askyesno(
            self._t("dlg_confirm_clear_title"),
            self._t("dlg_confirm_clear", n=len(self.files)),
        ):
            self.files.clear()
            self._checked.clear()
            self._refresh_file_list()
            self._update_stats()

    def _refresh_file_list(self):
        """Refresh the file list (rebuilds all rows from self.files).
        Checkbox state comes from self._checked — the tk.Variables are
        recreated per build, so language/theme rebuilds keep the checks.
        """
        # Clear existing rows
        for w in self.file_rows_frame.winfo_children():
            w.destroy()
        self._row_vars = {}
        self._row_widgets = {}

        for i, path in enumerate(self.files):
            name = os.path.basename(path)
            try:
                st = os.stat(path)
                size = format_size(st.st_size)
                cache_key = (path, st.st_size, st.st_mtime)
                dims = self._dims_cache.get(cache_key)
                if dims is None:
                    from PIL import Image
                    if Path(path).suffix.lower() in RAW_EXTENSIONS:
                        # header-only read — decoding every RAW for a
                        # dims column would freeze the list
                        import rawpy
                        with rawpy.imread(path) as raw:
                            dims = (f"{raw.sizes.width}"
                                    f"×{raw.sizes.height}")
                    else:
                        with Image.open(path) as img:
                            dims = f"{img.width}×{img.height}"
                    self._dims_cache[cache_key] = dims
            except OSError:
                size, dims = "N/A", "—"
            except Exception:
                size, dims = "N/A", "—"
            fmt = Path(path).suffix.upper().lstrip(".")
            base_bg = COLORS["row_alt"] if i % 2 else COLORS["card"]

            row = tk.Frame(self.file_rows_frame, bg=base_bg, bd=0,
                           highlightthickness=0)
            row.pack(fill="x")
            row.pack_propagate(True)

            var = tk.BooleanVar(value=path in self._checked)
            cb = ttk.Checkbutton(row, variable=var,
                                 command=self._make_check_cb(path))
            cb.pack(side="left", padx=(10, 8), pady=3)

            name_lbl = tk.Label(row, text=name, anchor="w", font=FONT_BODY,
                                fg=COLORS["text"], bg=base_bg)
            name_lbl.pack(side="left", fill="x", expand=True)
            labels = [(name_lbl, COLORS["text"])]
            for text, width in ((size, 10), (fmt, 6), (dims, 12)):
                lbl = tk.Label(row, text=text, width=width, anchor="e",
                               font=FONT_SMALL,
                               fg=COLORS["text_secondary"], bg=base_bg)
                lbl.pack(side="left", padx=(8, 0))
                labels.append((lbl, COLORS["text_secondary"]))

            # interactions: click selects, double-click compares,
            # BackSpace/Delete removes the selected rows
            for w in (row, name_lbl):
                w.bind("<Button-1>", lambda e, p=path: self._select_row(p))
                w.bind("<Double-1>", lambda e, p=path: self._open_compare(p))
                w.bind("<BackSpace>", lambda e: self._remove_selected())
                w.bind("<Delete>", lambda e: self._remove_selected())

            self._row_vars[path] = var
            self._row_widgets[path] = {"row": row, "labels": labels,
                                       "base_bg": base_bg}

        self._update_count_label()

    def _browse_output_dir(self):
        """Browse for output directory."""
        if self._dlg_cooldown_active():
            return
        folder = filedialog.askdirectory(title=self._t("sec_output"))
        self._after_file_dialog()
        if folder:
            self.output_dir.set(folder)

    # ── Processing ───────────────────────────────────────────────────────────

    def _on_folder_preset_change(self, event=None):
        """When a folder preset is selected from the combobox."""
        idx = self.folder_combo.current()
        if idx < 0 or idx >= len(self._folder_preset_values):
            return
        value = self._folder_preset_values[idx]
        if value is None:  # custom template
            self.folder_pattern.set("")
            self.folder_custom_entry.focus_set()
        else:
            self.folder_pattern.set(value)

    def _build_options(self) -> ProcessOptions:
        """Build ProcessOptions from current UI state."""
        try:
            max_w = int(self.max_width.get()) if self.max_width.get().strip() else None
        except (ValueError, TypeError):
            max_w = None
        try:
            max_h = int(self.max_height.get()) if self.max_height.get().strip() else None
        except (ValueError, TypeError):
            max_h = None
        try:
            scale = int(self.scale_percent.get()) if self.scale_percent.get().strip() else None
        except (ValueError, TypeError):
            scale = None
        try:
            max_pixels = int(self.max_pixels.get()) if self.max_pixels.get().strip() else None
        except (ValueError, TypeError):
            max_pixels = None

        # Parse target size if in target size mode
        target_bytes = None
        if self.target_size_mode.get():
            try:
                val = float(self.target_size_value.get())
                unit = self.target_size_unit.get()
                multiplier = 1024 if unit == "KB" else 1024**2
                target_bytes = int(val * multiplier)
            except ValueError:
                pass  # Invalid input → ignore target size

        # Parse jobs (parallel workers): clamp to >= 1
        jobs_str = self.jobs.get().strip()
        try:
            jobs = max(1, int(jobs_str))
        except ValueError:
            jobs = 1

        def _to_float(value, default):
            try:
                return float(value)
            except (ValueError, TypeError):
                return default

        from .cli import _parse_sizes  # lazy: cli imports engine only

        return ProcessOptions(
            quality=self.quality.get(),
            output_format=self.output_format.get(),
            output_dir=self.output_dir.get() if self.output_dir.get().strip() else None,
            max_width=max_w,
            max_height=max_h,
            scale_percent=scale,
            preserve_exif=self.preserve_exif.get(),
            optimize=self.optimize.get(),
            progressive=self.progressive.get(),
            overwrite=self.overwrite.get(),
            prefix=self.prefix.get(),
            suffix=self.suffix.get(),
            target_size_bytes=target_bytes,
            raw_half_size=self.raw_half_size.get(),
            raw_auto_bright=self.raw_auto_bright.get(),
            auto_rotate=self.auto_rotate.get(),
            remove_original=self.remove_original.get(),
            strip_gps=self.strip_gps.get(),
            keep_mtime=self.keep_mtime.get(),
            max_pixels=max_pixels,
            brightness=_to_float(self.brightness.get(), 1.0),
            contrast=_to_float(self.contrast.get(), 1.0),
            saturation=_to_float(self.saturation.get(), 1.0),
            gamma=_to_float(self.gamma.get(), 1.0),
            sharpen=_to_float(self.sharpen.get(), 1.0),
            grayscale=self.grayscale.get(),
            sepia=self.sepia.get(),
            ev=_to_float(self.ev.get(), 0.0),
            auto_exposure=_to_float(self.auto_exposure.get(), 0.0)
            if self.auto_exposure.get().strip() else None,
            log_curve=self.log_curve.get() or None,
            denoise=_to_float(self.denoise.get(), 0.0)
            if self.denoise.get().strip() else None,
            auto_straighten=self.auto_straighten.get(),
            wb_temp=_to_float(self.wb_temp.get(), 0.0)
            if self.wb_temp.get().strip() else None,
            wb_reference=self.wb_reference.get().strip() or None,
            auto_levels=self.auto_levels.get(),
            srgb=self.srgb.get(),
            flatten_cmyk=self.flatten_cmyk.get(),
            evaluate=self.evaluate.get(),
            blur_score=self.blur_score.get(),
            resume=self.resume.get(),
            print_size=self.print_size.get().strip() or None,
            date_shift=self.date_shift.get().strip() or None,
            sync_date=self.sync_date.get(),
            scrub=self.scrub.get(),
            gpx_trace=self.gpx_trace.get().strip() or None,
            max_straighten_angle=_to_float(self.max_straighten_angle.get(), 10.0),
            crop=self.crop.get().strip() or None,
            crop_ratio=self.crop_ratio.get().strip() or None,
            rotate_degrees=_to_float(self.rotate.get(), 0.0),
            rotate_bg=self.rotate_bg.get().strip() or None,
            flip=self.flip.get() or None,
            pad_ratio=self.pad_ratio.get().strip() or None,
            pad_bg=self.pad_bg.get().strip() or "#000000",
            watermark_text=self.watermark_text.get().strip(),
            watermark_image=self.watermark_image.get().strip(),
            watermark_position=self.watermark_position.get() or "BOTTOM_RIGHT",
            watermark_opacity=int(self.watermark_opacity.get()),
            output_sizes=_parse_sizes(self.output_sizes.get().strip() or None),
            rename_pattern=self.rename_pattern.get(),
            folder_pattern=_resolve_folder_pattern(self.folder_pattern.get()),
            jobs=jobs,
        )

    def _preview(self):
        """Preview what would happen without processing."""
        files = self._checked_files()
        if not files:
            if not self.files:
                messagebox.showwarning(self._t("dlg_no_files_title"),
                                       self._t("dlg_no_files"))
            else:
                messagebox.showwarning(self._t("dlg_no_files_title"),
                                       self._t("check_none"))
            return

        options = self._build_options()
        yes, no = self._t("yes"), self._t("no")
        yn = lambda b: yes if b else no

        lines = [self._t("preview_header"), "=" * 40, ""]
        lines.append(self._t("pv_files", n=len(files)))
        lines.append(self._t("pv_format", fmt=options.output_format))
        if options.target_size_bytes:
            lines.append(self._t("pv_target", size=format_size(options.target_size_bytes)))
            lines.append(self._t("pv_qmax", q=options.quality))
        else:
            lines.append(self._t("pv_quality", q=options.quality))

        if options.max_width or options.max_height:
            w = options.max_width or self._t("auto")
            h = options.max_height or self._t("auto")
            lines.append(self._t("pv_maxsize", w=w, h=h))

        if options.scale_percent:
            lines.append(self._t("pv_scale", s=options.scale_percent))

        lines.append(self._t("pv_exif", yn=yn(options.preserve_exif)))
        lines.append(self._t("pv_optimize", yn=yn(options.optimize)))
        lines.append(self._t("pv_progressive", yn=yn(options.progressive)))
        lines.append(self._t("pv_overwrite", yn=yn(options.overwrite)))
        outdir = options.output_dir or self._t("pv_outdir_same")
        lines.append(self._t("pv_outdir", d=outdir))
        if options.folder_pattern:
            lines.append(self._t("pv_subfolder", p=options.folder_pattern))
        lines.append(self._t("pv_prefix", p=options.prefix))
        lines.append(self._t("pv_suffix", s=options.suffix))
        lines.append("")
        lines.append(self._t("pv_total", size=format_size(self._total_size())))

        messagebox.showinfo(self._t("preview_title"), "\n".join(lines))

    def _start_processing(self, file_list=None, confirm_delete=True):
        """Start batch processing in a background thread.

        Args:
            file_list: Files to process (default: the checked files).
            confirm_delete: Skip the remove-original confirmation on
                            automatic queue follow-up runs.
        """
        if file_list is not None:
            files = list(file_list)
        else:
            # interactive start: process the checked files only
            files = self._checked_files()
            if not files:
                if not self.files:
                    messagebox.showwarning(self._t("dlg_no_files_title"),
                                           self._t("dlg_no_files"))
                else:
                    messagebox.showwarning(self._t("dlg_no_files_title"),
                                           self._t("check_none"))
                return

        if self.processing:
            return

        # Safety check for remove-original
        if confirm_delete and self.remove_original.get():
            if not messagebox.askyesno(
                self._t("dlg_confirm_delete_title"),
                self._t("dlg_confirm_delete", n=len(files)),
            ):
                return

        self.processing = True
        self.cancel_requested = False
        self._batch_result = None
        self._batch_error = None

        options = self._build_options()

        # Update UI to processing state
        self.start_btn.pack_forget()
        self.preview_btn.pack_forget()
        self.cancel_btn.pack(side="right")
        self.progress_bar["value"] = 0
        self.progress_label.config(text=self._t("processing"), fg=COLORS["text"])

        # Disable settings during processing (add buttons stay enabled → queue)
        self._toggle_settings(False)

        # Start background thread
        thread = threading.Thread(
            target=self._process_thread,
            args=(files.copy(), options),
            daemon=True,
        )
        thread.start()

        # Start progress polling via after()
        self._poll_progress()

    def _cancel_processing(self):
        """Request cancellation of processing."""
        self.cancel_requested = True
        self.progress_label.config(text=self._t("cancelling"), fg=COLORS["warning"])

    def _process_thread(self, files, options):
        """Background thread for batch processing."""
        def progress_callback(current, total, path, status=""):
            if self.cancel_requested:
                return  # Stop progress updates once cancelled
            with self._progress_lock:
                self._progress_current = current
                self._progress_total = total
                self._progress_path = path
                self._progress_status = status

        try:
            result = batch_process(
                files, options,
                progress_callback=progress_callback,
                cancel_checker=lambda: self.cancel_requested,
            )
            with self._progress_lock:
                self._batch_result = result
        except Exception as e:
            with self._progress_lock:
                self._batch_result = BatchResult(
                    results=[], total_input_size=0, total_output_size=0,
                    success_count=0, fail_count=1,
                )
                self._batch_error = str(e)

    def _poll_progress(self):
        """Poll progress from background thread and update UI."""
        if not self.processing:
            return

        with self._progress_lock:
            current = self._progress_current
            total = self._progress_total
            path = self._progress_path
            status = self._progress_status
            result = self._batch_result

        if result is not None:
            # Processing complete
            self._on_processing_done(result)
            return

        if total > 0:
            self.progress_bar["value"] = (current / total) * 100
            if path:
                name = os.path.basename(path) if path else ""
                action = self._t("tuning") if status == "tuning" else ""
                self.progress_label.config(
                    text=self._t("processing_item", cur=current, total=total, name=name)
                         + ("  " + action if action else "")
                )

        # Schedule next poll
        self._after_id = self.root.after(100, self._poll_progress)

    def _on_processing_done(self, result: BatchResult):
        """Handle processing completion."""
        self.processing = False
        self._last_result = result  # for double-click before/after comparison
        was_cancelled = self.cancel_requested
        self.cancel_requested = False

        # Restore UI
        self.cancel_btn.pack_forget()
        self.preview_btn.pack(side="left")
        self.start_btn.pack(side="right")
        self.progress_bar["value"] = 0 if was_cancelled else 100

        # Re-enable settings
        self._toggle_settings(True)

        # Drop files that no longer exist (e.g. deleted by remove_original),
        # then refresh so sizes/dimensions shown are current
        self.files = [f for f in self.files if os.path.exists(f)]
        self._refresh_file_list()

        # Update stats
        if was_cancelled:
            self.progress_label.config(
                text=self._t("cancelled_status",
                             ok=result.success_count, fail=result.fail_count),
                fg=COLORS["warning"],
            )
        elif self._batch_error:
            self.progress_label.config(
                text=self._t("failed_status"),
                fg=COLORS["danger"],
            )
            messagebox.showerror(
                self._t("dlg_error_title"),
                self._t("dlg_error", err=self._batch_error),
            )
            self._batch_error = None
            self._update_stats()
            return
        elif result.success_count > 0:
            savings = format_size(result.savings_bytes)
            self.progress_label.config(
                text=self._t("done_status", ok=result.success_count,
                             total=len(result.results), savings=savings,
                             pct=f"{result.savings_percent:.1f}"),
                fg=COLORS["success"],
            )
        else:
            self.progress_label.config(
                text=self._t("failed_status"),
                fg=COLORS["danger"],
            )

        self._update_stats(result)

        # Show summary dialog
        if result.success_count > 0 or result.fail_count > 0:
            self._show_summary(result)

        # Auto-run queued files (added while processing)
        pending = [f for f in self._queued_files if os.path.exists(f)]
        self._queued_files = []
        if pending and not was_cancelled and not self._batch_error:
            # defer so the summary dialog can render first; skip the
            # remove-original confirmation on automatic follow-up runs
            self.root.after(200,
                            lambda: self._start_processing(pending,
                                                           confirm_delete=False))

    def _show_summary(self, result: BatchResult):
        """Show processing summary in a scrollable dialog.

        A plain messagebox truncates long per-file error lists; the
        readonly Text widget keeps every failure visible.
        """
        lines = [self._t("sum_header"), "=" * 40, ""]
        lines.append(f"{self._t('sum_success')}: {result.success_count}")
        lines.append(f"{self._t('sum_failed')}: {result.fail_count}")
        lines.append("")
        lines.append(f"{self._t('sum_original')}: {format_size(result.total_input_size)}")
        lines.append(f"{self._t('sum_compressed')}: {format_size(result.total_output_size)}")
        lines.append(f"{self._t('sum_saved')}: {format_size(result.savings_bytes)} "
                     f"({result.savings_percent:.1f}%)")
        lines.append("")

        # Show individual failures
        for r in result.results:
            if not r.success:
                lines.append(f"{self._t('sum_failed')}: {os.path.basename(r.input_path)}"
                             f"\n  → {r.error}")

        msg = "\n".join(lines)

        win = tk.Toplevel(self.root)
        win.title(self._t("summary_title"))
        win.geometry("600x480")
        win.configure(bg=COLORS["bg"])
        win.transient(self.root)

        tk.Label(win, text=self._t("summary_title"),
                 font=(PLATFORM_FONTS["title"], 14, "bold"),
                 fg=COLORS["text"], bg=COLORS["bg"]).pack(pady=(16, 4))

        text = tk.Text(win, wrap="word", font=FONT_BODY,
                       bg=COLORS["card"], fg=COLORS["text"],
                       relief="flat", borderwidth=0,
                       padx=14, pady=10, highlightthickness=0)
        text.insert("1.0", msg)
        text.configure(state="disabled")
        text.pack(fill="both", expand=True, padx=20, pady=(4, 8))

        btns = tk.Frame(win, bg=COLORS["bg"])
        btns.pack(pady=(0, 16))
        if result.success_count > 0:
            FlatButton(
                btns, text=self._t("sum_view_compare"),
                command=lambda: (win.destroy(), self._show_comparison(result)),
                bg=COLORS["accent"]).pack(side="left", padx=6)
        FlatButton(
            btns, text=self._t("close"), command=win.destroy,
            bg=COLORS["bg"], fg=COLORS["text"], hover_bg=COLORS["border"],
            border_color=COLORS["border"]).pack(side="left", padx=6)

    def _show_comparison(self, result: BatchResult):
        """Open a before/after comparison window for the first successful result."""
        first = next((r for r in result.results if r.success), None)
        if first:
            self._show_comparison_for(first)

    def _show_comparison_for(self, r):
        """Open a before/after comparison window for one ProcessResult."""
        from PIL import Image, ImageTk

        win = tk.Toplevel(self.root)
        win.title(self._t("compare_title"))
        win.geometry("900x500")
        win.configure(bg=COLORS["bg"])

        tk.Label(win, text=self._t("compare_header"),
                 font=(PLATFORM_FONTS["title"], 14, "bold"),
                 fg=COLORS["text"], bg=COLORS["bg"]).pack(pady=(16, 4))

        # Info row
        if r.input_size > 0:
            saved_pct = (r.input_size - r.output_size) / r.input_size * 100
        else:
            saved_pct = 0.0
        info = (f"{self._t('before')}: {format_size(r.input_size)}  |  "
                f"{self._t('after')}: {format_size(r.output_size)}  |  "
                f"{self._t('saved')}: {saved_pct:.1f}%  |  "
                f"{self._t('quality_lbl')}: {r.achieved_quality}")
        tk.Label(win, text=info, font=FONT_BODY,
                 fg=COLORS["text_secondary"], bg=COLORS["bg"]).pack(pady=(0, 12))

        # Images row
        img_frame = tk.Frame(win, bg=COLORS["bg"])
        img_frame.pack(fill="both", expand=True, padx=20)

        # Load and display images (fit within ~400×320 px box)
        max_w, max_h = 400, 320
        for label, path in [(self._t("before"), r.input_path),
                            (self._t("after"), r.output_path)]:
            col = tk.Frame(img_frame, bg=COLORS["card"], bd=0, highlightthickness=0)
            col.pack(side="left", fill="both", expand=True, padx=8)

            tk.Label(col, text=label, font=(PLATFORM_FONTS["body"], 11, "bold"),
                     fg=COLORS["text"], bg=COLORS["card"]).pack(pady=(8, 0))

            try:
                img = _open_image_safe(path).convert("RGB")
                w, h = img.size
                ratio = min(max_w / w, max_h / h, 1.0)
                img = img.resize((max(1, int(w * ratio)), max(1, int(h * ratio))),
                                 Image.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                img_label = tk.Label(col, image=photo, bg=COLORS["card"])
                img_label.image = photo  # keep reference
                img_label.pack(padx=12, pady=12)
            except Exception:
                tk.Label(col, text=self._t("cannot_load"), font=FONT_SMALL,
                         fg=COLORS["danger"], bg=COLORS["card"]).pack(padx=12, pady=40)

            tk.Label(col, text=f"{r.input_dims[0]}x{r.input_dims[1]}"
                     if label == self._t("before")
                     else f"{r.output_dims[0]}x{r.output_dims[1]}",
                     font=FONT_TINY, fg=COLORS["text_secondary"],
                     bg=COLORS["card"]).pack(pady=(0, 8))

        # Close button
        FlatButton(win, text=self._t("close"), command=win.destroy,
                   bg=COLORS["accent"], hover_bg=COLORS["accent_hover"],
                   font=FONT_BUTTON, padx=24, pady=6).pack(pady=12)

    def _open_compare(self, path):
        """Double-click a file row → before/after comparison for that file."""
        if self._last_result is None:
            messagebox.showinfo(self._t("cmp_no_result"),
                                self._t("cmp_no_result_body"))
            return
        for r in self._last_result.results:
            if r.input_path == path and r.success:
                self._show_comparison_for(r)
                return
        messagebox.showinfo(self._t("cmp_no_result"),
                            self._t("cmp_no_result_body"))

    def _update_stats(self, result: BatchResult = None):
        """Update stats label at the bottom."""
        if result:
            self.stats_label.config(
                text=self._t("stats_result",
                             sin=format_size(result.total_input_size),
                             sout=format_size(result.total_output_size),
                             pct=f"{result.savings_percent:.1f}")
            )
        else:
            total = self._total_size()
            if total > 0:
                self.stats_label.config(
                    text=self._t("stats_files", n=len(self.files),
                                 size=format_size(total))
                )
            else:
                if self.files:
                    # Files listed but unreadable (e.g. moved away)
                    self.stats_label.config(
                        text=self._t("stats_files_only", n=len(self.files)))
                else:
                    self.stats_label.config(text="")

    def _toggle_settings(self, enabled: bool):
        """Enable or disable settings controls during processing."""
        state = "normal" if enabled else "disabled"
        # Toggle major controls
        for widget in self.root.winfo_children():
            self._set_state_recursive(widget, state)

    def _set_state_recursive(self, widget, state):
        """Recursively set widget state."""
        try:
            # Keep cancel/preview/start and the file-add buttons enabled:
            # files can be added to the queue while a batch is processing.
            # Gallery export is read-only on the originals, so it stays up
            # too; review/dedup mutate files and are locked out.
            if widget in (self.cancel_btn, self.start_btn, self.preview_btn,
                          self.add_files_btn, self.add_folder_btn,
                          self.gallery_btn):
                return
            if isinstance(widget, (FlatButton, ttk.Combobox, ttk.Scale,
                                   ttk.Entry, ttk.Checkbutton, ttk.Radiobutton)):
                widget.configure(state=state)
        except Exception:
            pass
        for child in widget.winfo_children():
            if child in (self.file_rows_frame, self.file_list_canvas,
                         self.progress_bar, self.progress_label):
                continue
            self._set_state_recursive(child, state)


# ── Entry Point ─────────────────────────────────────────────────────────────

def run_gui():
    """Launch the PhotoS GUI application."""
    # Use TkinterDnD root window when available so drag-and-drop works
    if DND_AVAILABLE:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()

    root.title(STRINGS[DEFAULT_LANG]["window_title"])
    root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
    root.minsize(MIN_WIDTH, MIN_HEIGHT)
    root.configure(bg=COLORS["bg"])

    app = PhotoSApp(root)

    # Center window on screen (clamped so it never opens off-screen)
    root.update_idletasks()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    x = max(0, (sw - WINDOW_WIDTH) // 2)
    y = max(0, (sh - WINDOW_HEIGHT) // 2)
    root.geometry(f"+{x}+{y}")

    root.mainloop()


if __name__ == "__main__":
    run_gui()
