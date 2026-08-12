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
import sys
import threading
import tkinter as tk
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
APP_VERSION = "1.0.0"
WINDOW_WIDTH = 1120
WINDOW_HEIGHT = 720
MIN_WIDTH = 980
MIN_HEIGHT = 640
SETTINGS_WIDTH = 400

# Color scheme (light mode, macOS-friendly)
COLORS = {
    "bg": "#f5f5f7",
    "card": "#ffffff",
    "border": "#d2d2d7",
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
        # Toolbar / file list
        "add_images": "添加图片",
        "add_folder": "添加文件夹",
        "remove": "移除",
        "clear": "清除全部",
        "files_count": "{n} 个文件",
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
        "compare_title": "压缩对比",
        "compare_header": "压缩前后对比",
        "before": "原始",
        "after": "压缩后",
        "saved": "节省",
        "quality_lbl": "质量",
        "cannot_load": "无法加载",
        "close": "关闭",
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
        "denoise_hint": "NLM 降噪（空 = 关闭；需 photo-s[enhance] 或 SCUNet 插件）",
        "auto_straighten": "自动扶正地平线",
        "max_straighten_angle": "最大扶正角°",
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
        # Toolbar / file list
        "add_images": "Add Images",
        "add_folder": "Add Folder",
        "remove": "Remove",
        "clear": "Clear All",
        "files_count": "{n} files",
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
        "compare_title": "Comparison",
        "compare_header": "Before & After",
        "before": "Original",
        "after": "Compressed",
        "saved": "Saved",
        "quality_lbl": "Quality",
        "cannot_load": "Cannot load",
        "close": "Close",
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
        "denoise_hint": "NLM denoise (blank = off; needs photo-s[enhance] or SCUNet plugin)",
        "auto_straighten": "Auto-straighten horizon",
        "max_straighten_angle": "Max straighten angle°",
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

class FlatButton(tk.Label):
    """A flat button that honors bg/fg colors on every platform.

    tk.Button on macOS Aqua ignores custom colors entirely (white text on
    a light native button becomes unreadable), so a Label-based button is
    used instead. Supports hover feedback and a disabled state that both
    greys the text and blocks clicks.
    """

    def __init__(self, master, text, command, bg, fg="white",
                 hover_bg=None, font=None, padx=16, pady=7,
                 border_color=None):
        self._command = command
        self._bg = bg
        self._hover_bg = hover_bg or bg
        extra = {}
        if border_color:
            extra = {"highlightthickness": 1, "highlightbackground": border_color}
        try:
            super().__init__(
                master, text=text, font=font or FONT_BUTTON, bg=bg, fg=fg,
                padx=padx, pady=pady, cursor="pointinghand", **extra,
            )
        except Exception:
            # Some environments (e.g. headless Xvfb) lack the 'pointinghand'
            # cursor; degrade to the default cursor instead of failing.
            super().__init__(
                master, text=text, font=font or FONT_BUTTON, bg=bg, fg=fg,
                padx=padx, pady=pady, **extra,
            )
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

    def _is_enabled(self):
        return str(self.cget("state")) != "disabled"

    def _on_enter(self, _event):
        if self._is_enabled():
            self.configure(bg=self._hover_bg)

    def _on_leave(self, _event):
        self.configure(bg=self._bg)

    def _on_click(self, _event):
        if self._is_enabled() and self._command:
            self._command()


# ── Main Application ────────────────────────────────────────────────────────

class PhotoSApp:
    """Main application window."""

    def __init__(self, root):
        self.root = root
        self.lang = DEFAULT_LANG
        self.root.title(self._t("window_title"))
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.root.minsize(MIN_WIDTH, MIN_HEIGHT)
        self.root.configure(bg=COLORS["bg"])

        # State
        self.files: List[str] = []
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
        self.rename_pattern = tk.StringVar(value="")
        self.folder_pattern = tk.StringVar(value="")
        self.jobs = tk.StringVar(value="4")  # parallel workers

        self._configure_ttk_styles()

        # Build UI
        self._build_ui()

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

    def _on_language_selected(self, _event=None):
        display = self.lang_combo.get()
        self._set_language("zh" if display == "中文" else "en")

    def _configure_ttk_styles(self):
        """Tune ttk widget appearance for a cleaner look."""
        style = ttk.Style(self.root)
        style.configure("Treeview", rowheight=26, font=FONT_BODY,
                        fieldbackground=COLORS["card"])
        style.configure("Treeview.Heading", font=FONT_SMALL, padding=(4, 5))
        style.map("Treeview", background=[("selected", COLORS["accent"])],
                  foreground=[("selected", "white")])
        style.configure("TCombobox", padding=2)
        style.configure("TCheckbutton", background=COLORS["card"])
        style.configure("TRadiobutton", background=COLORS["card"])

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
            bg=COLORS["bg"], fg=COLORS["text_secondary"], hover_bg=COLORS["border"],
            font=FONT_SMALL, padx=10, pady=4, border_color=COLORS["border"],
        )
        about_btn.pack(side="right", pady=(6, 0))

        # Language selector (right side)
        self.lang_combo = ttk.Combobox(
            title_frame, values=["中文", "English"], state="readonly",
            font=FONT_SMALL, width=8,
        )
        self.lang_combo.current(0 if self.lang == "zh" else 1)
        self.lang_combo.bind("<<ComboboxSelected>>", self._on_language_selected)
        self.lang_combo.pack(side="right", padx=(0, 8), pady=(6, 0))

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
        card = tk.Frame(parent, bg=COLORS["card"], highlightbackground=COLORS["border"],
                        highlightthickness=1, bd=0)
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

        clear_btn = FlatButton(
            toolbar, text=self._t("clear"), command=self._clear_files,
            bg=COLORS["card"], fg=COLORS["text_secondary"], hover_bg=COLORS["bg"],
            border_color=COLORS["border"],
        )
        clear_btn.pack(side="right")

        self.file_count_label = tk.Label(
            toolbar, text=self._t("files_count", n=0), font=FONT_SMALL,
            fg=COLORS["text_secondary"], bg=COLORS["card"],
        )
        self.file_count_label.pack(side="right", padx=(0, 12))

        # File list (Treeview)
        list_frame = tk.Frame(card, bg=COLORS["card"])
        list_frame.pack(fill="both", expand=True, padx=14, pady=12)

        columns = ("name", "size", "format", "dims")
        self.file_tree = ttk.Treeview(
            list_frame, columns=columns, show="headings",
            selectmode="extended", height=12,
        )

        self.file_tree.heading("name", text=self._t("col_name"))
        self.file_tree.heading("size", text=self._t("col_size"))
        self.file_tree.heading("format", text=self._t("col_format"))
        self.file_tree.heading("dims", text=self._t("col_dims"))

        self.file_tree.column("name", width=300, minwidth=140)
        self.file_tree.column("size", width=100, minwidth=80, anchor="center")
        self.file_tree.column("format", width=80, minwidth=60, anchor="center")
        self.file_tree.column("dims", width=140, minwidth=90, anchor="center")

        # Zebra striping for readability
        self.file_tree.tag_configure("even", background=COLORS["row_alt"])

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.file_tree.yview)
        self.file_tree.configure(yscrollcommand=scrollbar.set)

        self.file_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Bind delete key
        self.file_tree.bind("<BackSpace>", lambda e: self._remove_selected())
        self.file_tree.bind("<Delete>", lambda e: self._remove_selected())

        # Double-click a row → before/after comparison for that file
        self.file_tree.bind("<Double-1>", self._on_tree_double_click)

        # Register drag-and-drop targets (requires tkinterdnd2 AND a TkinterDnD
        # root; with a plain tk.Tk() root — e.g. headless smoke tests — the
        # tkdnd Tcl commands aren't loaded, so degrade gracefully)
        if DND_AVAILABLE:
            try:
                for widget in (card, self.file_tree):
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
        # Card container
        card = tk.Frame(parent, bg=COLORS["card"], highlightbackground=COLORS["border"],
                        highlightthickness=1, bd=0)
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

        # Bind mousewheel for scrolling (only when mouse is over the canvas)
        def _on_mousewheel(event):
            # macOS: event.delta is ±1; Windows/Linux: event.delta is ±120
            delta = event.delta
            if abs(delta) < 10:  # macOS trackpad/mouse
                canvas.yview_scroll(int(-delta), "units")
            else:  # Windows/Linux
                canvas.yview_scroll(int(-delta / 120), "units")

        def _bind_scroll(event):
            canvas.bind_all("<MouseWheel>", _on_mousewheel)

        def _unbind_scroll(event):
            canvas.unbind_all("<MouseWheel>")

        canvas.bind("<Enter>", _bind_scroll)
        canvas.bind("<Leave>", _unbind_scroll)

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

    def _browse_watermark_image(self):
        """Pick a watermark overlay image via file dialog."""
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title=self._t("wm_image"),
            filetypes=[("图片 Images", "*.png *.jpg *.jpeg *.webp"),
                       ("All files", "*.*")])
        if path:
            self.watermark_image.set(path)

    def _build_bottom_panel(self, parent):
        """Build bottom progress and action bar."""
        # Card container
        card = tk.Frame(parent, bg=COLORS["card"], highlightbackground=COLORS["border"],
                        highlightthickness=1, bd=0)
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
            sep = tk.Frame(parent, bg=COLORS["border"], height=1)
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

        tk.Label(inner, text=self._t("about_license"),
                 font=FONT_TINY, fg=COLORS["text_secondary"],
                 bg=COLORS["bg"]).pack(anchor="w", pady=(16, 12))

        FlatButton(inner, text=self._t("close"), command=win.destroy,
                   bg=COLORS["accent"], hover_bg=COLORS["accent_hover"],
                   font=FONT_BUTTON, padx=24, pady=6).pack()

    # ── File Management ─────────────────────────────────────────────────────

    def _add_files(self):
        """Open file dialog to add image files."""
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

        if paths:
            self._append_files(list(paths))

    def _add_folder(self):
        """Open folder dialog and scan for images."""
        folder = filedialog.askdirectory(title=self._t("add_folder"))
        if folder:
            images = scan_directory(folder, recursive=False)
            if not images:
                messagebox.showinfo(
                    self._t("dlg_no_images_title"),
                    self._t("dlg_no_images"),
                )
                return
            added = self._append_files(images)
            if added == 0:
                messagebox.showinfo(
                    self._t("dlg_added_title"),
                    self._t("dlg_added", n=len(images)),
                )

    def _total_size(self) -> int:
        """Total size of listed files, ignoring files that no longer exist."""
        total = 0
        for f in self.files:
            try:
                total += os.path.getsize(f)
            except OSError:
                pass
        return total

    def _remove_selected(self):
        """Remove selected files from the list.

        Treeview item IDs are the full file paths, so removal is exact
        even when two folders contain files with the same name.
        """
        selected = self.file_tree.selection()
        if not selected:
            return

        remove_paths = set(selected)
        self.files = [f for f in self.files if f not in remove_paths]
        self._refresh_file_list()
        self._update_stats()

    def _append_files(self, new_paths: List[str]) -> int:
        """Dedupe-append paths to the file list (queued when processing).

        Returns the number of newly added paths.
        """
        added = 0
        fresh = []
        for p in new_paths:
            if os.path.isdir(p):
                for img in scan_directory(p, recursive=False):
                    if img not in self.files:
                        self.files.append(img)
                        fresh.append(img)
                        added += 1
            elif os.path.isfile(p) and p not in self.files:
                self.files.append(p)
                fresh.append(p)
                added += 1

        if added:
            self._refresh_file_list()
            self._update_stats()
            if self.processing:
                # Batch in flight: queue fresh files for an automatic follow-up
                for p in fresh:
                    if p not in self._queued_files:
                        self._queued_files.append(p)
        return added

    def _on_drop(self, event):
        """Handle drag-and-drop of files/folders onto the file list."""
        try:
            paths = self.root.tk.splitlist(event.data)
        except Exception:
            paths = event.data.split()

        if paths:
            if not self._append_files(list(paths)):
                messagebox.showinfo(
                    self._t("dlg_no_images_title"),
                    self._t("dlg_drop_none"),
                )

    def _clear_files(self):
        """Clear all files from the list."""
        if self.files and messagebox.askyesno(
            self._t("dlg_confirm_clear_title"),
            self._t("dlg_confirm_clear", n=len(self.files)),
        ):
            self.files.clear()
            self._refresh_file_list()
            self._update_stats()

    def _refresh_file_list(self):
        """Refresh the file treeview."""
        # Clear existing items
        for item in self.file_tree.get_children():
            self.file_tree.delete(item)

        # Add files
        for i, path in enumerate(self.files):
            name = os.path.basename(path)
            try:
                size = format_size(os.path.getsize(path))
            except OSError:
                size = "N/A"
            fmt = Path(path).suffix.upper().lstrip(".")
            try:
                from PIL import Image
                with Image.open(path) as img:
                    dims = f"{img.width}×{img.height}"
            except Exception:
                dims = "—"
            tag = "even" if i % 2 else ""
            self.file_tree.insert("", "end", iid=path, values=(name, size, fmt, dims),
                                  tags=(tag,) if tag else ())

        self.file_count_label.config(text=self._t("files_count", n=len(self.files)))

    def _browse_output_dir(self):
        """Browse for output directory."""
        folder = filedialog.askdirectory(title=self._t("sec_output"))
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
        if not self.files:
            messagebox.showwarning(self._t("dlg_no_files_title"),
                                   self._t("dlg_no_files"))
            return

        options = self._build_options()
        yes, no = self._t("yes"), self._t("no")
        yn = lambda b: yes if b else no

        lines = [self._t("preview_header"), "=" * 40, ""]
        lines.append(self._t("pv_files", n=len(self.files)))
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
            file_list: Files to process (default: the whole file list).
            confirm_delete: Skip the remove-original confirmation on
                            automatic queue follow-up runs.
        """
        files = file_list if file_list is not None else self.files
        if not files:
            messagebox.showwarning(self._t("dlg_no_files_title"),
                                   self._t("dlg_no_files"))
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
                             total=len(self.files), savings=savings,
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
        """Show processing summary dialog."""
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

        # Show summary. If successful files exist, offer comparison view
        if result.success_count > 0:
            if messagebox.askyesno(self._t("summary_title"),
                                   msg + "\n\n" + self._t("sum_ask_compare")):
                self._show_comparison(result)
        else:
            messagebox.showinfo(self._t("summary_title"), msg)

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
            col = tk.Frame(img_frame, bg=COLORS["card"], highlightbackground=COLORS["border"],
                           highlightthickness=1)
            col.pack(side="left", fill="both", expand=True, padx=8)

            tk.Label(col, text=label, font=(PLATFORM_FONTS["body"], 11, "bold"),
                     fg=COLORS["text"], bg=COLORS["card"]).pack(pady=(8, 0))

            try:
                img = Image.open(path)
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

    def _on_tree_double_click(self, event):
        """Double-click a file row → before/after comparison for that file."""
        iid = self.file_tree.identify_row(event.y)
        if not iid:
            return
        if self._last_result is None:
            messagebox.showinfo(self._t("cmp_no_result"),
                                self._t("cmp_no_result_body"))
            return
        for r in self._last_result.results:
            if r.input_path == iid and r.success:
                self._show_comparison_for(r)
                return
        if iid:
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
            # files can be added to the queue while a batch is processing
            if widget in (self.cancel_btn, self.start_btn, self.preview_btn,
                          self.add_files_btn, self.add_folder_btn):
                return
            if isinstance(widget, (FlatButton, ttk.Combobox, ttk.Scale,
                                   ttk.Entry, ttk.Checkbutton, ttk.Radiobutton)):
                widget.configure(state=state)
        except Exception:
            pass
        for child in widget.winfo_children():
            if child in (self.file_tree, self.progress_bar, self.progress_label):
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
