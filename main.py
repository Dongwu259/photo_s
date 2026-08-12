#!/usr/bin/env python3
"""
PhotoS — Batch Image Compression & Format Conversion Tool
       批量图片压缩与格式转换工具

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

# Ensure src package is importable when running as `python main.py`
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from photo_s.cli import main

if __name__ == "__main__":
    sys.exit(main())
