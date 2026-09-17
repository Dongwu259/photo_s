"""v2.6 P1/P2 tests: smart suggest · Library facet filters + semantic
search · color labels · export audit.

Same conventions as test_gui_v26.py: hermetic HOME, zh pinned (status
assertions), real display or skip, bus delivery drained by hand (no
mainloop in tests).
"""

import os
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
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


def _img(path, seed=1, size=(96, 64), color=None):
    import numpy as np
    from PIL import Image
    if color is not None:
        Image.new("RGB", size, color).save(path)
        return
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 256, (size[1], size[0], 3), dtype=np.uint8)
    Image.fromarray(arr, "RGB").save(path)


def _poll(root, pred, seconds=30.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        root.update()
        if pred():
            return True
        time.sleep(0.05)
    return False


def _drain_suggest(app, timeout=5.0):
    """Wait for the suggest worker + dev-bus delivery (no mainloop)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        app._dev_bus.drain_pending()
        if not getattr(app, "_dev_suggest_busy", False):
            return True
        time.sleep(0.02)
    app._dev_bus.drain_pending()
    return not getattr(app, "_dev_suggest_busy", False)


@pytest.fixture
def lib_app(tmp_path):
    """App on the Library module with two JPEGs + one PNG."""
    root, app = _make_app()
    paths = []
    for i in range(2):
        p = str(tmp_path / "photo{}.jpg".format(i))
        _img(p, seed=i + 1)
        paths.append(p)
    png = str(tmp_path / "extra.png")
    _img(png, seed=9)
    import PIL.Image as _I
    _I.new("RGB", (64, 64), (10, 200, 30)).save(png, "PNG")
    paths.append(png)
    app.files = list(paths)
    app._checked = set(paths)
    app._show_module("library")
    app._refresh_file_list()
    yield root, app, paths
    try:
        app._on_main_close()
    except Exception:
        pass
    try:
        root.destroy()
    except Exception:
        pass


# ── P1b: Develop smart suggest ───────────────────────────────────────────────

class TestSuggest:
    @pytest.fixture
    def dev_app(self, tmp_path):
        root, app = _make_app()
        p = str(tmp_path / "dev.jpg")
        _img(p, seed=3)
        app.files = [p]
        app._checked = {p}
        app._show_module("develop")
        app._refresh_file_list()
        app._dev_select(p)
        yield root, app, p
        try:
            app._on_main_close()
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass

    def _res(self, suggested):
        return {"ok": True, "path": "", "suggested": suggested,
                "reasons": [], "neutral": not suggested}

    def test_apply_writes_overlay_and_undo(self, dev_app):
        root, app, p = dev_app
        assert p not in app._photo_adjust
        app._dev_suggest_apply(p, self._res({"ev": 0.3, "contrast": 1.05}), None)
        ov = app._photo_adjust[p]
        assert ov["ev"] == pytest.approx(0.3)
        assert ov["contrast"] == pytest.approx(1.05)
        assert app._dev_undo_available()
        assert float(app.ev.get()) == pytest.approx(0.3)  # sliders follow
        app._dev_undo()
        assert app._photo_adjust[p].get("ev") != pytest.approx(0.3)

    def test_only_dev_fields_taken(self, dev_app):
        root, app, p = dev_app
        app._dev_suggest_apply(
            p, self._res({"ev": 0.2, "bogus_key": 1}), None)
        assert app._photo_adjust[p]["ev"] == pytest.approx(0.2)
        assert "bogus_key" not in app._photo_adjust[p]

    def test_neutral_and_error_paths(self, dev_app):
        root, app, p = dev_app
        app._dev_suggest_apply(p, self._res({}), None)
        assert p not in app._photo_adjust
        assert "均衡" in app._dev_status_lbl.cget("text")
        app._dev_suggest_apply(p, {"ok": False, "error": "boom"}, None)
        assert "boom" in app._dev_status_lbl.cget("text")

    def test_button_to_overlay_e2e(self, dev_app, monkeypatch):
        import photo_s.suggest as suggest_mod
        monkeypatch.setattr(
            suggest_mod, "suggest_file",
            lambda path, **kw: self._res({"ev": -0.4, "vibrance": 0.12}))
        root, app, p = dev_app
        app._dev_suggest()
        assert _drain_suggest(app)
        ov = app._photo_adjust[p]
        assert ov["ev"] == pytest.approx(-0.4)
        assert ov["vibrance"] == pytest.approx(0.12)

    def test_need_photo_guard(self, dev_app):
        root, app, p = dev_app
        app._dev_selected = None
        app._dev_suggest()
        assert "选择" in app._dev_status_lbl.cget("text") \
            or "照片" in app._dev_status_lbl.cget("text")


# ── P1a: Library facet filters ──────────────────────────────────────────────

class TestFacetFilters:
    def test_name_filter_still_works(self, lib_app):
        root, app, paths = lib_app
        app.filter_var.set("photo1")
        vis = app._visible_files()
        assert vis == [paths[1]]

    def test_edited_filter(self, lib_app):
        root, app, paths = lib_app
        app._photo_adjust[paths[0]] = {"ev": 0.1}
        app._filter_edited_combo.current(1)   # 仅已调
        assert app._visible_files() == [paths[0]]
        app._filter_edited_combo.current(2)   # 未调
        assert paths[0] not in app._visible_files()
        app._filter_edited_combo.current(0)

    def test_format_filter_rebuild(self, lib_app):
        root, app, paths = lib_app
        fmts = app._lib_filter_fmts
        assert "jpg" in fmts and "png" in fmts
        app._filter_format_combo.current(fmts.index("png") + 1)
        assert app._visible_files() == [paths[2]]
        # selection survives a rebuild while still valid
        app._refresh_file_list()
        assert app._lib_filter_format() == "png"
        app._filter_format_combo.current(0)

    def test_rating_filter(self, lib_app):
        pytest.importorskip("piexif")
        root, app, paths = lib_app
        app._review_save(paths[0], rating=4)
        app._lib_rating_cache = {}  # drop stale zeros from the draw pass
        app._filter_rating_combo.current(4)    # ≥4★
        assert app._visible_files() == [paths[0]]
        app._filter_rating_combo.current(3)    # ≥3★ → same photo
        assert app._visible_files() == [paths[0]]
        app._filter_rating_combo.current(0)

    def test_label_filter(self, lib_app):
        pytest.importorskip("piexif")
        root, app, paths = lib_app
        app._selected_rows = {paths[0]}
        app._lib_set_label("Red")
        app._filter_label_combo.current(1)     # 红
        assert app._visible_files() == [paths[0]]
        app._filter_label_combo.current(6)     # 无标签
        vis = app._visible_files()
        assert paths[0] not in vis and len(vis) == 2
        app._filter_label_combo.current(0)


# ── P1a: semantic search ────────────────────────────────────────────────────

class TestSemanticSearch:
    def test_need_index_hint(self, lib_app):
        root, app, paths = lib_app
        app._lib_semantic_var.set("海边日落")
        app._lib_semantic_search()
        assert app._lib_semantic_hits is None
        assert "index" in app._semantic_hint_lbl.cget("text")

    def test_hist84_no_text_encoder_hint(self, lib_app):
        import photo_s.search as search
        # extractor forced to the zero-dep built-in — on dev machines with
        # the auto-tone plugin the default resolves to SigLIP (which CAN
        # embed text and loads torch), so never rely on the default here
        search.build_index([lib_app[2][0], lib_app[2][1]],
                           extractor_name=search.HIST_NAME)
        root, app, paths = lib_app
        app._lib_semantic_var.set("海边")
        app._lib_semantic_search()
        assert app._lib_semantic_busy
        assert _poll(root, lambda: not app._lib_semantic_busy)
        app._lib_bus.drain_pending()
        assert app._lib_semantic_hits is None  # hint, not a crash
        assert "text encoder" in app._semantic_hint_lbl.cget("text")

    def test_hits_filter_the_list(self, lib_app):
        root, app, paths = lib_app
        app._lib_semantic_apply({paths[1]}, None)
        assert app._visible_files() == [paths[1]]
        assert "1" in app._semantic_hint_lbl.cget("text")
        app._lib_semantic_var.set("")
        app._lib_semantic_search()             # empty query clears
        assert app._lib_semantic_hits is None
        assert len(app._visible_files()) == 3


# ── P2: color labels ────────────────────────────────────────────────────────

class TestColorLabels:
    def test_engine_roundtrip(self, tmp_path):
        pytest.importorskip("piexif")
        from photo_s.engine import apply_exif_tags, read_exif_metadata
        p = str(tmp_path / "l.jpg")
        _img(p, seed=5)
        apply_exif_tags(p, {"rating": 4, "label": "Red",
                            "title": "My Title"})
        m = read_exif_metadata(p)
        assert m["label"] == "Red" and m["rating"] == 4
        assert m["title"] == "My Title"
        apply_exif_tags(p, {"label": ""})      # clear keeps the rest
        m = read_exif_metadata(p)
        assert m["label"] == "" and m["rating"] == 4
        assert m["title"] == "My Title"

    def test_lib_set_and_read(self, lib_app):
        pytest.importorskip("piexif")
        root, app, paths = lib_app
        app._selected_rows = {paths[0]}
        app._lib_set_label("Green")
        from photo_s.engine import read_exif_metadata
        assert read_exif_metadata(paths[0])["label"] == "Green"
        assert app._lib_label(paths[0]) == "Green"
        app._selected_rows = {paths[0]}
        app._lib_set_label("")                 # keyboard 0 clears
        assert read_exif_metadata(paths[0])["label"] == ""

    def test_key_label_without_selection_noop(self, lib_app):
        pytest.importorskip("piexif")
        root, app, paths = lib_app
        app._selected_rows = set()
        app._lib_key_label("Red")              # must not raise
        from photo_s.engine import read_exif_metadata
        assert read_exif_metadata(paths[0])["label"] == ""

    def test_lightbox_set_label(self, lib_app):
        pytest.importorskip("piexif")
        from photo_s.engine import read_exif_metadata
        root, app, paths = lib_app
        app._show_review()
        ctl = app._lib_lightbox_ctl
        assert ctl is not None
        # the lightbox scans EXIF asynchronously — set_label is a no-op
        # until the scan delivers, so retry until the write sticks
        def _labeled():
            ctl["set_label"]("Purple")
            return read_exif_metadata(paths[0])["label"] == "Purple"
        assert _poll(root, _labeled)
        app._exit_library_lightbox()

    def test_label_flows_into_xmp_write_back(self, lib_app):
        pytest.importorskip("piexif")
        from photo_s.engine import ProcessOptions
        from photo_s.gui import workflows
        from photo_s.lrxmp import read_embedded_xmp
        root, app, paths = lib_app
        app._selected_rows = {paths[0]}
        app._lib_set_label("Red")
        app._selected_rows = {paths[1]}
        app._lib_set_label("Blue")
        workflows.xmp_write_back(paths[0], ProcessOptions())
        text = read_embedded_xmp(paths[0]) or ""
        assert 'Label="Red"' in text
        workflows.xmp_write_back(paths[1], ProcessOptions())
        assert 'Label="Blue"' in (read_embedded_xmp(paths[1]) or "")


# ── P2: export audit ───────────────────────────────────────────────────────

class TestExportAudit:
    def _fake_result(self, paths):
        from photo_s.engine import BatchResult
        rs = [SimpleNamespace(success=True, output_path=p, input_path=p)
              for p in paths]
        return BatchResult(results=rs, total_input_size=1,
                           total_output_size=1, success_count=len(rs),
                           fail_count=0)

    def test_audit_outputs_report(self, tmp_path):
        good = str(tmp_path / "good.jpg")
        _img(good, seed=7)                     # sharp + balanced → passes
        blown = str(tmp_path / "blown.jpg")
        _img(blown, color=(255, 255, 255))     # clipped → fails
        missing = str(tmp_path / "missing.jpg")
        root, app = _make_app()
        rep = app._audit_outputs(self._fake_result([good, blown, missing]))
        assert rep["total"] == 3
        assert rep["passed"] >= 1
        kinds = {os.path.basename(f["path"]) for f in rep["failed"]}
        assert "blown.jpg" in kinds and "missing.jpg" in kinds
        assert all(f["reason"] for f in rep["failed"])
        try:
            app._on_main_close()
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass

    def test_summary_shows_audit_and_output_dir(self, tmp_path):
        from photo_s.engine import BatchResult
        out = str(tmp_path / "out.jpg")
        _img(out, seed=2)
        root, app = _make_app()
        app._audit_report = {"total": 2, "passed": 1,
                             "failed": [{"path": out, "reason": "overexposed"}]}
        result = BatchResult(
            results=[SimpleNamespace(success=True, output_path=out,
                                     input_path=out)],
            total_input_size=1, total_output_size=1,
            success_count=1, fail_count=0)
        app._show_summary(result)
        import tkinter as tk
        tops = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
        assert tops, "summary dialog opened"
        body = ""
        for w in tops:
            widgets = list(w.winfo_children())
            for c in widgets:
                if isinstance(c, tk.Text):
                    body = c.get("1.0", "end")
                widgets.extend(getattr(c, "winfo_children", lambda: [])())
        assert "质量检查" in body and "1/2" in body
        assert "overexposed" in body and "out.jpg" in body
        for w in tops:
            w.destroy()
        try:
            app._on_main_close()
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass
