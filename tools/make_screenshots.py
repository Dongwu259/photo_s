#!/usr/bin/env python3
"""PhotoS 演示截图生成器。

以脚本方式驱动 GUI 到指定状态，再按 **窗口 ID** 精确截图（不受其他窗口遮挡）。

用法：
    python3 tools/make_screenshots.py [输出目录]

素材目录可用环境变量 PS_DEMO_PHOTOS 覆盖（默认 /tmp/ps_demo/photos）。
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

PHOTOS = Path(os.environ.get("PS_DEMO_PHOTOS", "/tmp/ps_demo/photos"))
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else REPO / "demo" / "screenshots")
OUT.mkdir(parents=True, exist_ok=True)

WINDOW_W, WINDOW_H = 1600, 1000


def log(msg: str) -> None:
    print(f"[shot] {msg}", flush=True)


# ── macOS 窗口 ID 枚举（ctypes 调 CoreGraphics，零第三方依赖） ──────────────

_cg_cache: dict = {}


def _load_cg():
    if _cg_cache:
        return _cg_cache
    cg_path = (ctypes.util.find_library("CoreGraphics")
               or "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    cf_path = (ctypes.util.find_library("CoreFoundation")
               or "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    cg, cf = ctypes.CDLL(cg_path), ctypes.CDLL(cf_path)

    cg.CGWindowListCopyWindowInfo.restype = ctypes.c_void_p
    cg.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    cf.CFArrayGetCount.restype = ctypes.c_long
    cf.CFArrayGetCount.argtypes = [ctypes.c_void_p]
    cf.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
    cf.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]
    cf.CFDictionaryGetValue.restype = ctypes.c_void_p
    cf.CFDictionaryGetValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    cf.CFStringCreateWithCString.restype = ctypes.c_void_p
    cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
    cf.CFNumberGetValue.restype = ctypes.c_bool
    cf.CFNumberGetValue.argtypes = [ctypes.c_void_p, ctypes.c_long, ctypes.c_void_p]
    cf.CFStringGetCString.restype = ctypes.c_bool
    cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]

    keys = {k: cf.CFStringCreateWithCString(None, k.encode(), 0x08000100)
            for k in ("kCGWindowOwnerName", "kCGWindowName", "kCGWindowNumber")}
    _cg_cache.update(cg=cg, cf=cf, keys=keys)
    return _cg_cache


def _cfstr(cf, val) -> str:
    if not val:
        return ""
    buf = ctypes.create_string_buffer(512)
    return (buf.value.decode("utf-8", "replace")
            if cf.CFStringGetCString(val, buf, 512, 0x08000100) else "")


def find_window_id(title_substr: str):
    """返回标题/属主包含 title_substr 的最前层窗口 ID，找不到返回 None。"""
    c = _load_cg()
    cg, cf, keys = c["cg"], c["cf"], c["keys"]
    arr = cg.CGWindowListCopyWindowInfo(1 | 16, 0)  # OnScreenOnly | ExcludeDesktopElements
    for i in range(cf.CFArrayGetCount(arr)):
        d = cf.CFArrayGetValueAtIndex(arr, i)
        num = ctypes.c_long(0)
        cf.CFNumberGetValue(cf.CFDictionaryGetValue(d, keys["kCGWindowNumber"]),
                            10, ctypes.byref(num))
        name = _cfstr(cf, cf.CFDictionaryGetValue(d, keys["kCGWindowName"]))
        owner = _cfstr(cf, cf.CFDictionaryGetValue(d, keys["kCGWindowOwnerName"]))
        if title_substr in name or title_substr in owner:
            return num.value
    return None


# ── 事件泵与截图 ────────────────────────────────────────────────────────────

def pump(root: tk.Tk, seconds: float) -> None:
    """保持事件循环运转指定秒数（让异步缩略图/预览完成）。"""
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.03)


def capture(root: tk.Tk, name: str, title: str = "PhotoS") -> Path | None:
    # 必须把窗口提到最前：macOS 下 screencapture -l 对未前置的 Tk 窗口
    # 可能抓到未合成的空 backing store（Canvas 内容会整片丢失）。
    try:
        root.attributes("-topmost", True)
    except tk.TclError:
        pass
    root.lift()
    pump(root, 1.2)
    wid = find_window_id(title)
    path = OUT / f"{name}.png"
    if wid is None:
        log(f"!! 找不到窗口「{title}」，跳过 {name}")
        return None
    r = subprocess.run(["screencapture", "-x", "-o", "-l", str(wid), str(path)],
                       capture_output=True, text=True)
    if r.returncode != 0 or not path.exists():
        log(f"!! 截图失败 {name}: {r.stderr.strip()}")
        return None
    log(f"{name} -> {path.name} (window {wid}, {path.stat().st_size // 1024} KB)")
    return path


def main() -> int:
    from photo_s import gui

    photos = sorted(str(p) for p in PHOTOS.glob("*.jpg"))
    if not photos:
        log(f"没有找到素材：{PHOTOS}")
        return 1
    log(f"素材 {len(photos)} 张，输出到 {OUT}")

    root = tk.Tk()
    app = gui.PhotoSApp(root)
    # 覆盖启动几何：给截图更大的画布
    root.geometry(f"{WINDOW_W}x{WINDOW_H}+60+60")
    root.update_idletasks()
    root.geometry(f"{WINDOW_W}x{WINDOW_H}+60+60")

    app._first_run_done = True
    app._show_first_run_guide = lambda: None

    # 走真实入口注入素材（直接赋值 self.files 会绕过 Library 列表模型）
    added = app._append_files(list(photos))
    log(f"_append_files 注入 {added} 张")
    # 窗口必须在布局完成后才能算出 VirtualGrid 的可视区；此时再逼一次重绘
    pump(root, 2.0)
    for fn in ("_refresh_file_list", "_lib_draw", "_update_count_label", "_update_stats"):
        try:
            getattr(app, fn)()
        except Exception as e:  # noqa: BLE001
            log(f"{fn} 失败: {e}")
    pump(root, 4.0)
    try:
        c = app.file_list_canvas
        log(f"file_list_canvas: {c.winfo_width()}x{c.winfo_height()}, items={len(c.find_all())}")
    except Exception as e:  # noqa: BLE001
        log(f"canvas 探测失败: {e}")

    shots = []

    # 1) Library（抖一次滚动，逼 VirtualGrid 物化可见行）
    app._show_module("library")
    pump(root, 2.5)
    try:
        app.file_list_canvas.yview_moveto(0.002)
        pump(root, 0.8)
        app.file_list_canvas.yview_moveto(0.0)
    except Exception as e:  # noqa: BLE001
        log(f"滚动激励跳过: {e}")
    pump(root, 2.0)
    shots.append(capture(root, "01-library"))

    # 2) Develop（选中一张，等真实管线渲染 + 直方图）
    app._show_module("develop")
    pump(root, 2.0)
    try:
        app._dev_select(photos[1] if len(photos) > 1 else photos[0])
    except Exception as e:  # noqa: BLE001
        log(f"_dev_select 失败: {e}")
    pump(root, 6.0)
    shots.append(capture(root, "02-develop"))

    # 3) Develop —— 拉上克制的调整参数（证明滑杆真的驱动预览）
    try:
        app.ev.set(0.12)
        app.contrast.set(1.06)
        app.vibrance.set("0.08")
        app.clarity.set("0.04")
    except Exception as e:  # noqa: BLE001
        log(f"设置调整参数失败: {e}")
    pump(root, 6.0)
    shots.append(capture(root, "03-develop-adjusted"))

    # 4) 并排 before/after（LR 式对比）
    try:
        app._dev_compare_toggle()
        pump(root, 5.0)
        shots.append(capture(root, "04-develop-before-after"))
        app._dev_compare_toggle()
        pump(root, 2.0)
    except Exception as e:  # noqa: BLE001
        log(f"对比视图跳过: {e}")

    # 5) Export
    app._show_module("export")
    pump(root, 2.5)
    shots.append(capture(root, "05-export"))

    # 6) Tools
    app._show_module("tools")
    pump(root, 2.0)
    shots.append(capture(root, "06-tools"))

    root.destroy()
    ok = [s for s in shots if s]
    log(f"完成：{len(ok)}/{len(shots)} 张")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
