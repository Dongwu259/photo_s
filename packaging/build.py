#!/usr/bin/env python3
"""Build the PhotoS bundled executable with PyInstaller.

Usage:
    python packaging/build.py            # one-dir build (default)
    python packaging/build.py --onefile  # single .exe (slower first start)

Prereqs:
    pip install pyinstaller
    # optional, to include features in the bundle:
    pip install piexif pillow-heif pillow-avif-plugin rawpy watchdog
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(description="Build bundled PhotoS")
    parser.add_argument("--onefile", action="store_true",
                        help="single-file build (slower startup)")
    args = parser.parse_args()

    if shutil.which("pyinstaller") is None:
        print("❌ PyInstaller 未安装 Not installed: pip install pyinstaller")
        return 1

    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm",
           str(ROOT / "photo-s.spec")]
    if args.onefile:
        cmd.append("--onefile")

    print("🚀 Building PhotoS bundle ...")
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        print("❌ Build failed")
        return result.returncode

    ext = ".exe" if os.name == "nt" else ""
    if args.onefile:
        out = ROOT / "dist" / f"photo-s{ext}"
    else:
        out = ROOT / "dist" / "photo-s" / f"photo-s{ext}"
    print(f"✅ 构建完成 Built: {out}")
    print(f"   Windows 打包场景 Windows bundling: 用绝对路径拉起子进程，"
          f"不依赖 PATH/环境变量:")
    print(f"   {out} serve --port 0 --token auto --ready-file x.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
