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
            "rawpy", "watchdog", "tkinterdnd2",
            # lazy imports the AST scan can't see (mcp_server imports these
            # inside functions; without them the packaged `photo-s mcp`
            # dies on startup)
            "cv2", "tifffile", "onnxruntime"):
    try:
        __import__(mod)
        hiddenimports.append(mod)
    except ImportError:
        pass
# mcp is imported lazily inside functions (py3.9 support) — bundle the
# whole package when the extra is installed, or `photo-s mcp` breaks.
# mcp.cli (the standalone `mcp` dev CLI) hard-imports typer, which newer
# mcp releases moved to the mcp[cli] extra — collect with on_error
# ignore and drop mcp.cli*: the server never imports it.
try:
    __import__("mcp")
    hiddenimports += [
        m for m in collect_submodules("mcp", on_error="ignore")
        if not m.startswith("mcp.cli")
    ]
except Exception:
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
