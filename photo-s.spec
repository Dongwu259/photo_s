# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for PhotoS.

Build (one-dir by default — faster startup, ideal for agent-spawned serve):
    pip install pyinstaller
    pyinstaller --noconfirm photo-s.spec

Artifacts land in dist/photo-s/ (photo-s.exe on Windows, photo-s on macOS/Linux).
Optional extras detected at build time are bundled automatically; install
`piexif pillow-heif rawpy watchdog` first to include those features.

For agent products: spawn the bundled binary with an absolute path, no PATH
or environment variables required:
    dist/photo-s/photo-s.exe serve --port 0 --token auto --ready-file x.json
"""

import os

from PyInstaller.utils.hooks import collect_submodules

# Optional runtime deps — bundled when installed at build time.
hiddenimports = []
for mod in ("piexif", "tomli", "pillow_heif", "pillow_avif_plugin",
            "rawpy", "watchdog", "tkinterdnd2"):
    try:
        __import__(mod)
        hiddenimports.append(mod)
    except ImportError:
        pass
# Pillow plugins are loaded via entry points / dynamic registration
hiddenimports += collect_submodules("PIL")

a = Analysis(
    ["packaging/launcher.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "tests"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="photo-s",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # CLI tool: keep the console (also needed for serve output)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="photo-s",
)
