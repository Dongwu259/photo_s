# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for PhotoS **lite** — the CLI/MCP build without the GUI.

Same pipeline as photo-s.spec, but the GUI module and tkinter are excluded
at build level, so the bundle is smaller and never touches a display:
ideal for headless servers and agent-spawned processes:

    dist/photo-s-lite/photo-s-lite serve --port 0 --token auto --ready-file x.json
    dist/photo-s-lite/photo-s-lite mcp

Build:
    pip install pyinstaller
    pyinstaller --noconfirm photo-s-lite.spec
(or `python packaging/build.py --lite`)

CLI behavior in this build: no args prints help, `gui` exits 1 with a
hint, `--version` carries a "(lite)" suffix (see photo_s.cli.main).
"""

import os

from PyInstaller.utils.hooks import collect_submodules

# Optional runtime deps — bundled when installed at build time.
# (tkinterdnd2 deliberately absent: no GUI in this build.)
hiddenimports = []
for mod in ("piexif", "tomli", "pillow_heif", "pillow_avif_plugin",
            "rawpy", "watchdog"):
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
    # The whole point of the lite build: no GUI code, no Tk runtime libs.
    # photo_s.gui is a package since v2.0 — the parent exclude covers it
    # (nothing else imports the submodules); they are listed explicitly
    # so a future direct import can't smuggle GUI code into lite.
    excludes=["pytest", "tests", "photo_s.gui",
              "photo_s.gui.app", "photo_s.gui.strings", "photo_s.gui.theme",
              "photo_s.gui.state", "photo_s.gui.workflows",
              "photo_s.gui.widgets",
              "tkinter", "_tkinter", "tkinterdnd2"],
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
    name="photo-s-lite",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
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
    name="photo-s-lite",
)
