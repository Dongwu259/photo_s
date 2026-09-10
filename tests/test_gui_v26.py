"""v2.6 tests: XMP roundtrip GUI (develop write-back + export checkbox +
autoload).

Covers the three GUI entry points that reuse photo_s.lrxmp through the
Tk-free seams in gui.workflows:
* Develop「写回 XMP」button — busy guard, no-photo hint, confirm-once
  dialog for JPEG embeds, status for done/warned/failed, real-file e2e
* Export「同时写 XMP」checkbox — outputs carry the recipe (JPEG embedded,
  TIFF sidecar next to the output); unchecked writes nothing
* Develop autoload — photos carrying XMP pick up their adjustments into
  the overlay (undoable, badge-lit); local edits always win; no-XMP
  photos stay untouched
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    # 状态文案断言基于中文，显式钉 zh，任何 runner 上确定
    monkeypatch.setenv("PHOTO_S_LANG", "zh")


def _make_app():
    import tkinter as tk
    from photo_s.gui import PhotoSApp
    try:
        root = tk.Tk()
    except Exception as e:
        pytest.skip("no display: {}".format(e))
    app = PhotoSApp(root)
    root.update_idletasks()
    return root, app


def _img(path, seed=1, size=(96, 64)):
    import numpy as np
    from PIL import Image
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 256, (size[1], size[0], 3), dtype=np.uint8)
    Image.fromarray(arr, "RGB").save(path, "JPEG")


def _poll(root, pred, seconds=45.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        root.update()
        if pred():
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def app_with_photos(tmp_path):
    root, app = _make_app()
    paths = []
    for i in range(2):
        p = str(tmp_path / "photo{}.jpg".format(i))
        _img(p, seed=i + 1)
        paths.append(p)
    app.files = list(paths)
    app._checked = set(paths)
    app._refresh_file_list()
    app._show_module("develop")
    yield root, app, paths
    try:
        app._on_main_close()
    except Exception:
        pass
    try:
        root.destroy()
    except Exception:
        pass


def _drain_xmp(app, timeout=5.0):
    """Wait for the write-back worker + bus delivery (no mainloop)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        app._dev_bus.drain_pending()
        if not app._dev_xmp_busy:
            return True
        time.sleep(0.02)
    app._dev_bus.drain_pending()
    return not app._dev_xmp_busy


def _status(app):
    return str(app._dev_status_lbl.cget("text"))


class TestDevWriteXmpButton:

    def test_need_photo_hint(self, tmp_path):
        root, app = _make_app()
        app._dev_selected = ""
        app._dev_write_xmp()
        assert "先在胶片条选择" in _status(app)
        root.destroy()

    def test_busy_guard_blocks_reentry(self, app_with_photos):
        root, app, paths = app_with_photos
        app._dev_selected = paths[0]
        app._dev_xmp_busy = True
        app._dev_write_xmp()  # must be a no-op, not a second thread
        assert app._dev_xmp_busy
        app._dev_xmp_busy = False

    def test_embed_confirm_once_per_session(self, app_with_photos,
                                            monkeypatch):
        root, app, paths = app_with_photos
        import photo_s.gui as gui_mod
        asked = []

        def fake_ask(title, msg, **kw):
            asked.append(title)
            return False

        monkeypatch.setattr(gui_mod.messagebox, "askyesno", fake_ask)
        app._dev_selected = paths[0]
        app._dev_write_xmp()
        assert asked, "first JPEG write-back must confirm"
        assert not app._dev_xmp_busy, "declined → no write started"
        # decline leaves the session flag untouched — next click asks again
        app._dev_write_xmp()
        assert len(asked) == 2
        # a RAW-style sidecar target never asks (sidecar adds a file only)
        asked.clear()
        app._dev_selected = paths[0].rsplit(".", 1)[0] + ".cr2"
        calls = []
        import photo_s.gui.workflows as wf
        monkeypatch.setattr(
            wf, "xmp_write_back",
            lambda *a, **k: calls.append(a) or {"target": a[0],
                                                "warnings": []})
        app._dev_write_xmp()
        assert calls and not asked, "non-JPEG target must not confirm"

    def test_done_with_warning_status(self, app_with_photos, monkeypatch):
        root, app, paths = app_with_photos
        import photo_s.gui.workflows as wf
        monkeypatch.setattr(wf, "xmp_write_back", lambda *a, **k: {
            "target": paths[0], "warnings": ["mask 'b'（brush）无 LR 几何等价"]})
        app._dev_selected = paths[0]
        app._xmp_embed_confirmed = True
        app._dev_write_xmp()
        assert _poll(root, lambda: not app._dev_xmp_busy)
        assert "警告" in _status(app) and "brush" in _status(app)

    def test_failed_status(self, app_with_photos, monkeypatch):
        root, app, paths = app_with_photos
        import photo_s.gui.workflows as wf

        def boom(*a, **k):
            raise RuntimeError("disk full")

        monkeypatch.setattr(wf, "xmp_write_back", boom)
        app._dev_selected = paths[0]
        app._xmp_embed_confirmed = True
        app._dev_write_xmp()
        assert _poll(root, lambda: not app._dev_xmp_busy)
        assert "XMP 写入失败" in _status(app) and "disk full" in _status(app)

    def test_real_jpeg_roundtrip(self, app_with_photos):
        root, app, paths = app_with_photos
        from photo_s.lrxmp import parse_xmp_sidecar, read_embedded_xmp
        app._photo_adjust[paths[0]] = {"ev": 0.4, "contrast": 1.25}
        app._dev_selected = paths[0]
        app._xmp_embed_confirmed = True
        app._dev_write_xmp()
        assert _poll(root, lambda: not app._dev_xmp_busy)
        assert "XMP 已写入" in _status(app)
        settings = parse_xmp_sidecar(read_embedded_xmp(paths[0]))
        assert float(settings["Exposure2012"]) == 0.4


class TestExportWriteXmp:

    def _run_batch(self, root, app):
        app._start_processing(confirm_delete=False)
        assert _poll(root, lambda: not app.processing), "batch must finish"

    def test_outputs_carry_xmp(self, app_with_photos, tmp_path):
        root, app, paths = app_with_photos
        out = tmp_path / "out"
        out.mkdir()
        app.output_dir.set(str(out))
        app.suffix.set("")
        app.ev.set(0.35)
        app.write_xmp.set(True)
        self._run_batch(root, app)
        from photo_s.lrxmp import parse_xmp_sidecar, read_embedded_xmp
        for r in app._last_result.results:
            assert r.success
            settings = parse_xmp_sidecar(read_embedded_xmp(r.output_path))
            assert float(settings["Exposure2012"]) == 0.35
        assert "XMP 已写 2 个" in str(app.progress_label.cget("text"))

    def test_disabled_writes_nothing(self, app_with_photos, tmp_path):
        root, app, paths = app_with_photos
        out = tmp_path / "out"
        out.mkdir()
        app.output_dir.set(str(out))
        app.suffix.set("")
        app.write_xmp.set(False)
        self._run_batch(root, app)
        from photo_s.lrxmp import read_embedded_xmp
        for r in app._last_result.results:
            assert read_embedded_xmp(r.output_path) is None
        assert "XMP 已写" not in str(app.progress_label.cget("text"))

    def test_tiff_output_gets_sidecar(self, tmp_path):
        root, app = _make_app()
        src = str(tmp_path / "src.jpg")
        _img(src)
        out = tmp_path / "out"
        out.mkdir()
        app.files = [src]
        app._checked = {src}
        app._refresh_file_list()
        app.output_dir.set(str(out))
        app.suffix.set("")
        app.output_format.set("TIFF")
        app.ev.set(0.2)
        app.write_xmp.set(True)
        self._run_batch(root, app)
        r = app._last_result.results[0]
        sidecar = r.output_path.rsplit(".", 1)[0] + ".xmp"
        assert os.path.exists(sidecar), "non-JPEG output gets a sidecar"
        try:
            app._on_main_close()
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass


class TestDevAutoload:

    def test_loads_overlay_masks_and_status(self, app_with_photos):
        root, app, paths = app_with_photos
        from photo_s.engine import ProcessOptions
        from photo_s.gui import workflows
        # photo1 carries LR settings + a mask in its embedded XMP
        workflows.xmp_write_back(paths[1], ProcessOptions(
            ev=0.45, contrast=1.1,
            masks="m1:linear:0.1,0.1,0.9,0.9", mask_adjust="m1:exposure=0.45"))
        app._dev_select(paths[1])
        assert _poll(root, lambda: paths[1] in app._photo_adjust)
        assert app._photo_adjust[paths[1]]["ev"] == 0.45
        assert app._photo_masks[paths[1]]["masks"].startswith("m1:linear:")
        assert "已从 XMP 载入" in _status(app)
        assert paths[1] in app._dev_history, "undo baseline must be seeded"

    def test_local_edits_win(self, app_with_photos):
        root, app, paths = app_with_photos
        from photo_s.engine import ProcessOptions
        from photo_s.gui import workflows
        workflows.xmp_write_back(paths[1], ProcessOptions(ev=0.45))
        app._photo_adjust[paths[1]] = {"ev": -0.2}
        app._dev_select(paths[1])
        deadline = time.time() + 1.0
        while time.time() < deadline:
            root.update()
            app._dev_bus.drain_pending()
            time.sleep(0.02)
        assert app._photo_adjust[paths[1]] == {"ev": -0.2}, \
            "an existing overlay must never be replaced by XMP"

    def test_plain_photo_stays_untouched(self, app_with_photos):
        root, app, paths = app_with_photos
        app._dev_select(paths[0])
        deadline = time.time() + 1.0
        while time.time() < deadline:
            root.update()
            app._dev_bus.drain_pending()
            time.sleep(0.02)
        assert paths[0] not in app._photo_adjust
        assert paths[0] not in app._photo_masks


def _dark_img(path, fill=70, size=(160, 160)):
    """test_autopilot 同款合成图：噪声过 blur 检测，暗填充驱动 suggest 补偿。"""
    import numpy as np
    from PIL import Image
    rng = np.random.default_rng(7)
    arr = np.full((*size, 3), fill, dtype=np.int16)
    arr += rng.integers(-20, 21, arr.shape)
    Image.fromarray(arr.clip(0, 255).astype("uint8")).save(str(path),
                                                           quality=95)
    return str(path)


def _walk(widget, pred, out=None):
    if out is None:
        out = []
    for c in widget.winfo_children():
        try:
            if pred(c):
                out.append(c)
        except Exception:
            pass
        _walk(c, pred, out)
    return out


def _open_watch(app):
    import tkinter as tk
    app._show_watch()
    wins = [w for w in app.root.winfo_children()
            if isinstance(w, tk.Toplevel)]
    return wins[-1]


class TestWatchAutopilot:

    def test_mode_switch_toggles_controls(self):
        root, app = _make_app()
        win = _open_watch(app)
        import tkinter.ttk as ttk
        boxes = _walk(win, lambda w: isinstance(w, ttk.Combobox))
        mode_box = next(b for b in boxes
                        if app._t("watch_mode_suggest") in b.cget("values"))
        strength_box = next(b for b in boxes
                            if "0.8" in b.cget("values")
                            and app._t("watch_mode_suggest")
                            not in b.cget("values"))
        cbs = _walk(win, lambda w: isinstance(w, ttk.Checkbutton))
        rm = next(c for c in cbs
                  if app._t("watch_remove_original") in str(c.cget("text")))
        scan = next(c for c in cbs
                    if app._t("watch_scan_existing") in str(c.cget("text")))
        ap_xmp = next(c for c in cbs
                      if app._t("watch_ap_write_xmp") in str(c.cget("text")))

        def _mode(m):
            mode_box.set(app._t("watch_mode_" + m))
            mode_box.event_generate("<<ComboboxSelected>>")
            root.update()

        assert str(rm.cget("state")) == "normal", "basic default keeps rm_orig"
        assert str(strength_box.cget("state")) == "disabled"
        _mode("suggest")
        assert str(strength_box.cget("state")) == "disabled", "suggest no AI"
        assert str(scan.cget("state")) == "normal"
        assert str(rm.cget("state")) == "disabled", "autopilot never deletes"
        _mode("auto_tone")
        assert str(strength_box.cget("state")) == "readonly"
        _mode("basic")
        assert str(rm.cget("state")) == "normal"
        assert str(ap_xmp.cget("state")) == "disabled"
        win.destroy()
        root.destroy()

    def test_suggest_e2e_routes_passed(self, tmp_path):
        root, app = _make_app()
        watch = tmp_path / "watch"
        watch.mkdir()
        _dark_img(watch / "dark.jpg")
        win = _open_watch(app)
        import tkinter.ttk as ttk
        entries = _walk(win, lambda w: isinstance(w, ttk.Entry))
        entries[0].delete(0, "end")
        entries[0].insert(0, str(watch))
        boxes = _walk(win, lambda w: isinstance(w, ttk.Combobox))
        mode_box = next(b for b in boxes
                        if app._t("watch_mode_suggest") in b.cget("values"))
        # mode FIRST — ap controls stay disabled in basic mode, so an
        # invoke() there is a silent no-op (found the hard way)
        mode_box.set(app._t("watch_mode_suggest"))
        mode_box.event_generate("<<ComboboxSelected>>")
        root.update()
        cbs = _walk(win, lambda w: isinstance(w, ttk.Checkbutton))
        scan = next(c for c in cbs
                    if app._t("watch_scan_existing") in str(c.cget("text")))
        scan.invoke()
        assert scan.instate(["selected"]), \
            "scan_existing on — deterministic, no FS timing"
        start = next(b for b in _walk(win, lambda w: hasattr(w, "_command"))
                     if getattr(b, "_text", "") == app._t("watch_start"))
        stop = next(b for b in _walk(win, lambda w: hasattr(w, "_command"))
                    if getattr(b, "_text", "") == app._t("watch_stop"))
        try:
            start._command()

            passed_dir = watch / "photo-s-out" / "passed"
            ok = _poll(root, lambda: passed_dir.exists()
                       and any(passed_dir.iterdir()))
            assert ok, "dark image must be routed into passed/"
            assert _poll(root, lambda: _find_status(app, win, "✅"))
            assert (watch / "photo-s-out" / "autopilot.jsonl").exists()
        finally:
            stop._command()

            def _worker_dead():
                import threading
                return not any(t.name == "autopilot-worker"
                               for t in threading.enumerate())
            _poll(root, _worker_dead, seconds=20)
            win.destroy()
            root.destroy()

    def test_auto_tone_without_plugin_fails_loud(self, tmp_path,
                                                 monkeypatch):
        import photo_s.plugin as plugin_mod
        monkeypatch.setattr(plugin_mod, "find_provider", lambda op: None)
        root, app = _make_app()
        watch = tmp_path / "watch"
        watch.mkdir()
        win = _open_watch(app)
        import tkinter.ttk as ttk
        entries = _walk(win, lambda w: isinstance(w, ttk.Entry))
        entries[0].delete(0, "end")
        entries[0].insert(0, str(watch))
        boxes = _walk(win, lambda w: isinstance(w, ttk.Combobox))
        mode_box = next(b for b in boxes
                        if app._t("watch_mode_suggest") in b.cget("values"))
        mode_box.set(app._t("watch_mode_auto_tone"))
        mode_box.event_generate("<<ComboboxSelected>>")
        start = next(b for b in _walk(win, lambda w: hasattr(w, "_command"))
                     if getattr(b, "_text", "") == app._t("watch_start"))
        start._command()
        assert _poll(root, lambda: _find_status(app, win, "启动失败"))
        assert _poll(root, lambda: start._state == "normal"), \
            "buttons restored after a failed start"
        win.destroy()
        root.destroy()


def _find_status(app, win, needle):
    return any(needle in str(w.cget("text"))
               for w in _walk(win, lambda w: w.winfo_class() == "Label"))
