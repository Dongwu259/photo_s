"""Regression tests for the gui.py audit fix batch.

Covers: worker exception-lambda binding (PEP 3110), plugin manager i18n
kwargs + drain queue + cache invalidation, _build_options sizes fallback,
_start_processing ordering, preview staleness signature, dialog close
protocol on language/theme rebuild, cull threshold parsing, auto_exposure
parse fallback, and dedup partial-move UI consistency.

Tk tests skip headless; the STRINGS/source guards are pure.
"""

import os
import re
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path, monkeypatch):
    """Hermetic gui_state: the app restores geometry/thumb-size/active
    module from ~/.photos/gui_state.json — a polluted real file once
    flipped the startup module, made the Develop panel auto-render in
    unrelated tests (its lazy tempdir then tripped other files'
    mkdtemp-tracking assertions) and leaked live Tk roots that cascaded
    into focus-event storms on later tests."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))


def _gui_sources():
    """All v2.0 GUI package sources (app.py + theme/strings/workflows/
    widgets/*) — the audit below scans every module, not one file."""
    gui_dir = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "photo_s", "gui")
    paths = [os.path.join(gui_dir, f) for f in sorted(os.listdir(gui_dir))
             if f.endswith(".py") and f != "__init__.py"]
    wdir = os.path.join(gui_dir, "widgets")
    paths += [os.path.join(wdir, f) for f in sorted(os.listdir(wdir))
              if f.endswith(".py") and f != "__init__.py"]
    return paths


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


def _img(path, seed=1, size=(64, 48), color=None):
    from PIL import Image
    if color is not None:
        Image.new("RGB", size, color).save(str(path))
        return str(path)
    import numpy as np
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 256, (size[1], size[0], 3), dtype=np.uint8)
    Image.fromarray(arr).save(str(path), quality=95)
    return str(path)


def _walk(widget):
    for c in widget.winfo_children():
        yield c
        yield from _walk(c)


def _find_text(widget, needle):
    import tkinter as tk
    for w in _walk(widget):
        try:
            if isinstance(w, tk.Label) and needle in str(w.cget("text")):
                return True
        except Exception:
            pass
    return False


def _poll(root, pred, seconds=20.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        root.update()
        if pred():
            return True
        time.sleep(0.05)
    return False


def _flat_button(widget, text):
    from photo_s.gui import FlatButton
    for w in _walk(widget):
        try:
            if isinstance(w, FlatButton) and str(w.cget("text")) == text:
                return w
        except Exception:
            pass
    return None


def _toplevels(root):
    import tkinter as tk
    return [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]


class _SyncThread:
    """threading.Thread stand-in that runs the target inline on start()
    (tests drive tk from the main thread only)."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)


class TestWorkerExceptionBinding:
    def test_no_scheduled_lambda_captures_except_var(self):
        """PEP 3110: `except Exception as e` deletes ``e`` when the block
        ends — a plain ``lambda: ... str(e)`` scheduled onto the drain
        queue raises NameError when drained and kills the drain loop.
        Every such lambda must bind ``err=str(e)`` as a default arg."""
        src = "".join(open(p, encoding="utf-8").read()
                      for p in _gui_sources())
        bad = re.findall(r"schedule\(lambda: [^\n]*str\(e\)", src)
        assert bad == [], \
            "scheduled lambdas capturing the except var: " + "; ".join(bad)
        assert src.count("lambda err=str(e):") >= 8, \
            "all 8 audited worker lambdas must bind err=str(e)"

    def test_gallery_failure_reaches_status(self, tmp_path, monkeypatch):
        """A failing gallery worker must surface its error in the dialog
        (with the old lambda the drain loop died on NameError first)."""
        from photo_s import gui as gui_mod
        root, app = _make_app()
        a = _img(tmp_path / "a.jpg")
        app._append_files([a])
        app.output_dir.set(str(tmp_path / "gal"))

        def boom(*args, **kwargs):
            raise RuntimeError("boom-gallery")
        monkeypatch.setattr(app, "_gallery_build", boom)
        # run workers inline: background threads must not touch tk Vars in
        # a test (no running mainloop); the queue/drain path is unchanged
        monkeypatch.setattr(gui_mod.threading, "Thread", _SyncThread)
        app._show_gallery_export()
        win = _toplevels(root)[0]
        btn = _flat_button(win, app._t("gallery_generate"))
        assert btn is not None
        btn._on_click(None)
        assert _poll(root, lambda: _find_text(win, "boom-gallery")), \
            "worker failure must reach the dialog status label"
        root.destroy()


class TestPluginStrings:
    def test_plugins_strings_named_placeholders(self):
        """plugins_ok/plugins_err take kwargs — positional ``{}`` raised
        TypeError via _t(key, **kwargs) and broke install/uninstall."""
        from photo_s.gui import STRINGS
        for lang in ("zh", "en"):
            assert STRINGS[lang]["plugins_ok"].format(what="x") == "✅ x"
            assert STRINGS[lang]["plugins_err"].format(detail="d") == "❌ d"

    def test_strings_key_parity(self):
        from photo_s.gui import STRINGS
        assert set(STRINGS["zh"]) == set(STRINGS["en"])


class TestPluginManager:
    def test_install_flow_drains_and_clears_cache(self, monkeypatch):
        """Install click → pip worker → drain-queue finish → status shows
        ✅ and the plugin entry-point cache is dropped (a freshly installed
        plugin must not still list as uninstalled)."""
        import types
        import photo_s.plugin as plugin_mod
        import photo_s.plugincmd as plugincmd_mod
        cleared = []
        monkeypatch.setattr(plugin_mod, "discover_plugins", lambda: [])
        monkeypatch.setattr(plugin_mod, "clear_cache",
                            lambda: cleared.append(1))
        monkeypatch.setattr(
            plugincmd_mod, "_pip_run",
            lambda args: types.SimpleNamespace(returncode=0, stderr=""))
        root, app = _make_app()
        app._show_plugin_manager()
        win = _toplevels(root)[0]
        btn = _flat_button(win, app._t("plugins_install"))
        assert btn is not None, "no install button rendered"
        btn._on_click(None)
        assert _poll(root, lambda: cleared), \
            "successful pip run must clear the plugin cache"
        assert _find_text(win, "✅"), "install result must reach the status"
        root.destroy()

    def test_uninstall_flow_clears_cache(self, monkeypatch):
        import types
        import photo_s.plugin as plugin_mod
        import photo_s.plugincmd as plugincmd_mod

        class FakePlugin:
            name = "scunet"
            provides = ("denoise",)
        cleared = []
        monkeypatch.setattr(plugin_mod, "discover_plugins",
                            lambda: [FakePlugin()])
        monkeypatch.setattr(plugin_mod, "clear_cache",
                            lambda: cleared.append(1))
        monkeypatch.setattr(
            plugincmd_mod, "_pip_run",
            lambda args: types.SimpleNamespace(returncode=0, stderr=""))
        monkeypatch.setattr(plugincmd_mod, "_installed_version",
                            lambda dist: "1.0")
        root, app = _make_app()
        app._show_plugin_manager()
        win = _toplevels(root)[0]
        btn = _flat_button(win, app._t("plugins_uninstall"))
        assert btn is not None, "no uninstall button for an installed plugin"
        btn._on_click(None)
        assert _poll(root, lambda: cleared), \
            "successful uninstall must clear the plugin cache"
        root.destroy()


class TestBuildOptionsSizes:
    def test_invalid_sizes_degrade_to_none(self):
        """Garbage in the sizes field must not raise — _build_options runs
        on every preview drain tick, so a ValueError killed the drain."""
        root, app = _make_app()
        app.output_sizes.set("thumb:abcxdef")
        opts = app._build_options()
        assert opts.output_sizes is None
        root.destroy()

    def test_valid_sizes_still_parse(self):
        root, app = _make_app()
        app.output_sizes.set("thumb:480x,full:1920x1080")
        opts = app._build_options()
        assert opts.output_sizes == [("thumb", 480, None),
                                     ("full", 1920, 1080)]
        root.destroy()

    def test_apply_options_serializes_none_dim_blank(self):
        """None dims must serialize as empty ('thumb:480x'), never the
        literal 'None' ('thumb:480xNone' was unparseable on reload)."""
        from photo_s.cli import _parse_sizes
        from photo_s.engine import ProcessOptions
        root, app = _make_app()
        opts = ProcessOptions(output_sizes=[("thumb", 480, None)])
        app._apply_options_to_ui(opts)
        val = app.output_sizes.get()
        assert "None" not in val
        assert val == "thumb:480x"
        assert _parse_sizes(val) == [("thumb", 480, None)]
        root.destroy()

    def test_start_processing_builds_options_before_locking(
            self, tmp_path, monkeypatch):
        """A failing options build must never leave the app wedged in
        processing=True."""
        root, app = _make_app()
        a = _img(tmp_path / "a.jpg")
        app._append_files([a])

        def boom():
            raise ValueError("bad options")
        monkeypatch.setattr(app, "_build_options", boom)
        with pytest.raises(ValueError):
            app._start_processing()
        assert not app.processing
        root.destroy()


class TestAutoExposureFallback:
    def test_unparseable_auto_exposure_is_none(self):
        """Unparseable input must map to None (disabled) — the engine
        treats 0.0 as enabled and drags the batch to near-black."""
        root, app = _make_app()
        app.auto_exposure.set("abc")
        assert app._build_options().auto_exposure is None
        app.auto_exposure.set("0.45")
        assert app._build_options().auto_exposure == 0.45
        app.auto_exposure.set("")
        assert app._build_options().auto_exposure is None
        root.destroy()


class TestRebuildClosesDialogs:
    def test_language_switch_runs_close_protocol(self):
        """Rebuilding the UI must close Toplevels via their WM_DELETE
        protocol (watch observer shutdown / rating save), not bare-destroy
        them."""
        import tkinter as tk
        root, app = _make_app()
        win = tk.Toplevel(root)
        closed = []
        win.protocol("WM_DELETE_WINDOW",
                     lambda: (closed.append(1), win.destroy()))
        app._set_language("en" if app.lang == "zh" else "zh")
        assert closed == [1], "close protocol must run before the rebuild"
        assert not win.winfo_exists()
        root.destroy()

    def test_theme_toggle_runs_close_protocol(self):
        import tkinter as tk
        root, app = _make_app()
        win = tk.Toplevel(root)
        closed = []
        win.protocol("WM_DELETE_WINDOW",
                     lambda: (closed.append(1), win.destroy()))
        app._toggle_theme()
        assert closed == [1]
        assert not win.winfo_exists()
        app._toggle_theme()   # restore the palette for later tests
        root.destroy()


class TestCullThresholds:
    def test_non_numeric_threshold_does_not_wedge_scan(self, tmp_path):
        """A non-numeric threshold used to raise ValueError AFTER the scan
        button was disabled — leaving it dead. Invalid input now degrades
        to 'no threshold' and the scan completes."""
        from tkinter import ttk
        root, app = _make_app()
        a = _img(tmp_path / "a.png", seed=3)
        app._append_files([a])
        app._show_cull()
        win = _toplevels(root)[0]
        for w in _walk(win):
            if isinstance(w, ttk.Entry):
                w.delete(0, "end")
                w.insert(0, "abc")
        btn = _flat_button(win, app._t("cull_scan"))
        assert btn is not None
        btn._on_click(None)
        assert _poll(root, lambda: str(btn.cget("state")) == "normal"), \
            "scan button must be re-enabled after the scan"
        assert _find_text(win, app._t("cull_kept", kept=1, total=1)), \
            "invalid thresholds count as unset → the file is kept"
        root.destroy()


class TestDedupPartialMove:
    def test_failed_moves_stay_in_ui(self, tmp_path, monkeypatch):
        """Files whose move to trash failed must keep their rows — the old
        code removed every requested file (set(unchecked)) instead of the
        actually moved ones (set(moved_map))."""
        from photo_s import gui as gui_mod
        root, app = _make_app()
        a = _img(tmp_path / "a.jpg")
        b = _img(tmp_path / "b.jpg")               # identical → duplicates
        # a FILE where the trash dir would go: makedirs fails, so every
        # move reports failure and moved_map comes back empty
        (tmp_path / "_duplicates_trash").write_bytes(b"blocked")
        app._append_files([a, b])
        monkeypatch.setattr(gui_mod.messagebox, "askyesno",
                            lambda *a, **k: True)
        monkeypatch.setattr(gui_mod.messagebox, "showinfo",
                            lambda *a, **k: None)
        app._show_dedup()
        win = _toplevels(root)[0]
        from tkinter import ttk

        def scanned():
            return any(isinstance(w, ttk.Checkbutton) for w in _walk(win))
        assert _poll(root, scanned), "dedup scan must render the group"
        # mark every file for removal
        for w in _walk(win):
            if isinstance(w, ttk.Checkbutton) and w.instate(["selected"]):
                w.invoke()
        btn = _flat_button(win, app._t("dedup_execute"))
        assert btn is not None
        btn._on_click(None)
        assert _poll(root, lambda: _find_text(win, "失败")), \
            "the failed moves must be reported"
        assert app.files == [a, b], \
            "files that never moved must stay in the list"
        assert os.path.exists(a) and os.path.exists(b)
        root.destroy()


class TestPreviewStaleness:
    def test_stale_render_discarded_after_nav(self, tmp_path, monkeypatch):
        """Navigate while a slow render is in flight: when the old render
        lands it must be dropped, never applied to the new file's panel.
        (The old signature compared ProcessOptions by value only, and _nav
        force-cleared inflight, so the stale render compared equal and was
        applied.) Renders are gated so the landing order is deterministic:
        A lands while B is still gated — if A is stale-applied, the red
        image sticks on the processed panel."""
        from photo_s.engine import ProcessResult
        from photo_s import gui as gui_mod
        root, app = _make_app()
        a = _img(tmp_path / "a.png", seed=1)
        b = _img(tmp_path / "b.png", seed=2)
        out_a = _img(tmp_path / "out_a.png", color=(255, 0, 0), size=(30, 30))
        out_b = _img(tmp_path / "out_b.png", color=(0, 255, 0), size=(30, 30))
        app._append_files([a, b])

        # track the preview temp dir so the test can leave it cleaned up
        created = []
        real_mkdtemp = gui_mod.tempfile.mkdtemp

        def tracking_mkdtemp(*args, **kwargs):
            d = real_mkdtemp(*args, **kwargs)
            created.append(d)
            return d
        monkeypatch.setattr(gui_mod.tempfile, "mkdtemp", tracking_mkdtemp)

        gate_a, gate_b = threading.Event(), threading.Event()
        calls = []

        def fake_render(path, opts):
            calls.append(path)
            (gate_a if path == a else gate_b).wait(5)
            return ProcessResult(
                input_path=path,
                output_path=out_a if path == a else out_b,
                input_size=100, output_size=100,
                input_format="PNG", output_format="PNG",
                input_dims=(64, 48), output_dims=(30, 30),
                success=True, error=None)
        monkeypatch.setattr(app, "_preview_render", fake_render)

        app._preview()
        win = [w for w in _toplevels(root)
               if w.title() == app._t("preview_title")][0]
        assert _poll(root, lambda: a in calls), \
            "the first render must launch for the first file"
        nav = _flat_button(win, "›")
        assert nav is not None
        nav._on_click(None)
        gate_a.set()   # the in-flight render of the previous file lands now
        # let the drain absorb it and (fixed behavior) launch B
        deadline = time.time() + 4
        while time.time() < deadline:
            root.update()
            time.sleep(0.05)
        assert b in calls, \
            "after the stale render is discarded, the new file must render"
        assert not self._proc_is(win, "red"), \
            "the stale render must not be applied to the new file's panel"
        gate_b.set()
        assert _poll(root, lambda: self._proc_is(win, "green"), seconds=20), \
            "the new file's own render must be applied"
        for _ in range(10):   # settle: no late callback may flip it back
            root.update()
            time.sleep(0.05)
        assert self._proc_is(win, "green")
        assert not self._proc_is(win, "red")
        win.destroy()
        assert _poll(root, lambda: not os.path.exists(created[-1]),
                     seconds=15), "preview temp dir must be cleaned up"
        root.destroy()

    def test_no_relaunch_on_unchanged_options(self, tmp_path, monkeypatch):
        """Regression: after a preview render lands, the drain loop must NOT
        relaunch with the same unchanged options.

        Bug: `_done` cleared `inflight` but left `stable >= 5`, so the next
        drain tick re-entered the launch branch → infinite re-render of the
        same file. Fix: `_done` resets `stable` to 0 (an options change also
        resets it via the `cur != sig` branch, so debounce still works).
        """
        import glob
        from photo_s.engine import ProcessResult
        from photo_s import gui as gui_mod
        root, app = _make_app()
        img = _img(tmp_path / "a.png", seed=1)
        out = _img(tmp_path / "out.png", color=(0, 255, 0), size=(30, 30))
        app._append_files([img])

        calls = []

        def fake_render(path, opts):
            calls.append(path)
            return ProcessResult(
                input_path=path, output_path=out,
                input_size=100, output_size=100,
                input_format="PNG", output_format="PNG",
                input_dims=(64, 48), output_dims=(30, 30),
                success=True, error=None)
        monkeypatch.setattr(app, "_preview_render", fake_render)

        created = []
        real_mkdtemp = gui_mod.tempfile.mkdtemp

        def tracking_mkdtemp(*args, **kwargs):
            d = real_mkdtemp(*args, **kwargs)
            created.append(d)
            return d
        monkeypatch.setattr(gui_mod.tempfile, "mkdtemp", tracking_mkdtemp)

        app._preview()
        win = [w for w in _toplevels(root)
               if w.title() == app._t("preview_title")][0]
        # wait for the first render to complete AND for the drain loop to
        # have ticked several times afterward (which is what would relaunch)
        assert _poll(root, lambda: len(calls) == 1, seconds=20), \
            "first render must launch exactly once"
        for _ in range(15):  # let the drain loop run; bug would relaunch here
            root.update()
            time.sleep(0.05)
        assert len(calls) == 1, \
            "preview must not re-render with unchanged options (got {})" \
            .format(len(calls))
        win.destroy()
        # wait for the drain loop to rmtree the preview temp dir, so this
        # test doesn't leak a photos_preview_* dir that would break the
        # cleanup-glob assertions in test_gui_workflows (same-suite order).
        deadline = time.time() + 15
        while time.time() < deadline:
            root.update()
            if created and not os.path.exists(created[-1]):
                break
            time.sleep(0.05)
        assert created and not os.path.exists(created[-1]), \
            "preview temp dir must be cleaned up"
        root.destroy()

    @staticmethod
    def _proc_is(win, color):
        """Pixel-check the image last applied to the processed panel (the
        label with the rendering placeholder text that carries an image
        reference — the status label shares the text but never an image)."""
        import tkinter as tk
        for w in _walk(win):
            if not isinstance(w, tk.Label):
                continue
            try:
                text = str(w.cget("text")).lower()
                # en placeholder is "Rendering preview…" — case-insensitive
                # match ("render" alone missed the capital R and skipped the
                # panel entirely on en-locale runs)
                if "render" not in text and "渲染" not in text:
                    continue
            except Exception:
                continue
            photo = getattr(w, "image", None)
            if photo is None:
                continue   # status label — same placeholder text, no image
            nums = [int(v) for v in re.findall(
                r"\d+", str(w.tk.call(str(photo), "get", 8, 8)))][:3]
            r, g, b = nums
            if max(nums) > 255:   # some Tk builds report 16-bit samples
                r, g, b = r >> 8, g >> 8, b >> 8
            if color == "red":
                return r > 200 and g < 100 and b < 100
            return g > 200 and r < 100 and b < 100
        return False
