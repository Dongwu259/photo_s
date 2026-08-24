#!/usr/bin/env python3
"""
PhotoS — Batch Photo Toolkit
       批量照片处理工具箱（压缩/转换/调色/EXIF/RAW/去重/选片）

Usage:
    photo-s gui            Launch graphical user interface
    photo-s <command> ...  Run command-line operations

    If no arguments are given, the GUI is launched automatically.
    If arguments are given, CLI mode is used.

Examples:
    python main.py                              # Launch GUI
    python main.py compress *.jpg -q 80         # CLI: compress JPEGs
    python main.py batch ~/Pictures/ -r -q 70   # CLI: batch process directory
    python main.py info                         # CLI: show supported formats
"""

import sys
import os

# Ensure the photo_s package (repo root) is importable when running as
# `python main.py` without an installed copy.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from photo_s.cli import main

if __name__ == "__main__":
    sys.exit(main())
