"""Interactive grading widgets (v1.6.x): CurveEditor / ColorWheel / HSLPanel."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk

import pytest

pytest.importorskip("tkinter")

from photo_s.gui_widgets import (
    ColorWheel,
    CurveEditor,
    HSLPanel,
    HSL_COLORS,
    rgb_to_hex,
)


@pytest.fixture(scope="module")
def root():
    r = tk.Tk()
    r.withdraw()
    yield r
    r.destroy()


class TestCurveEditor:
    def test_set_get_roundtrip(self, root):
        ed = CurveEditor(root)
        ed.set_points([(0, 0), (128, 140), (255, 255)])
        assert ed.get_points() == [(0.0, 0.0), (128.0, 140.0), (255.0, 255.0)]

    def test_endpoints_always_present(self, root):
        ed = CurveEditor(root)
        ed.set_points([(100, 120)])
        pts = ed.get_points()
        assert pts[0] == (0.0, 0.0) and pts[-1] == (255.0, 255.0)
        assert len(pts) >= 2

    def test_to_spec(self, root):
        ed = CurveEditor(root, channel="r")
        ed.set_points([(0, 0), (128, 140), (255, 255)])
        assert ed.to_spec() == "r:0,0;128,140;255,255"

    def test_is_identity(self, root):
        ed = CurveEditor(root)
        assert CurveEditor.is_identity(ed.get_points())
        ed.set_points([(0, 0), (128, 140), (255, 255)])
        assert not CurveEditor.is_identity(ed.get_points())

    def test_coord_roundtrip(self, root):
        ed = CurveEditor(root)
        for x, y in [(0, 0), (255, 255), (128, 64), (200, 10)]:
            cx, cy = ed.data_to_canvas(x, y)
            bx, by = ed.canvas_to_data(cx, cy)
            assert abs(bx - x) < 2 and abs(by - y) < 2

    def test_click_on_curve_adds_point_and_drags(self, root):
        # Lightroom interaction: clicking the curve (not a control point)
        # inserts a point on the curve and starts dragging it.
        ed = CurveEditor(root)
        assert len(ed.get_points()) == 2
        cx, cy = ed.data_to_canvas(100, 100)  # middle of the diagonal
        ed._on_press(type("E", (), {"x": cx, "y": cy})())
        pts = ed.get_points()
        assert len(pts) == 3
        # the new point sits on the curve (diagonal → x == y) and is grabbed
        added = [p for p in pts if 99 < p[0] < 101]
        assert added and abs(added[0][0] - added[0][1]) < 0.5
        assert ed._drag_idx is not None
        # drag it off the diagonal
        nx, ny = ed.data_to_canvas(150, 60)
        ed._on_drag(type("E", (), {"x": nx, "y": ny})())
        moved = [p for p in ed.get_points() if 149 < p[0] < 151]
        assert moved and moved[0][1] < 100  # pulled off the line

    def test_px_falls_back_before_layout(self, root):
        # Before the canvas is mapped winfo_width()==1 — the geometry must
        # fall back to the requested size or the curve is drawn ~10px wide
        # and the points are un-hittable (the "squeezed curve" bug).
        ed = CurveEditor(root, width=280, height=200)
        assert ed._px() == 280 - 2 * ed.MARGIN
        assert ed._py() == 200 - 2 * ed.MARGIN

    def test_engine_accepts_spec(self, root):
        from PIL import Image
        from photo_s.grade import _parse_curves, apply_curves
        ed = CurveEditor(root)
        # a curve pulling the upper range down: 200 → below 200
        ed.set_points([(0, 0), (128, 120), (255, 255)])
        im = Image.new("RGB", (8, 8), (200, 200, 200))
        out = apply_curves(im, _parse_curves(ed.to_spec("rgb")))
        assert out.getpixel((0, 0))[0] < 200


class TestColorWheel:
    def test_pick_center_is_zero_sat(self, root):
        w = ColorWheel(root)
        _hue, sat = w._pick_from_pos(w.center, w.center)
        assert sat == 0.0

    def test_pick_edge_sat_one(self, root):
        w = ColorWheel(root)
        _hue, sat = w._pick_from_pos(w.center + w.radius, w.center)
        assert sat == 1.0

    def test_pick_hue_angle(self, root):
        w = ColorWheel(root)
        hue, _ = w._pick_from_pos(w.center + w.radius, w.center)  # right → 0
        assert abs(hue - 0.0) < 1 or abs(hue - 360.0) < 1
        hue2, _ = w._pick_from_pos(w.center, w.center + w.radius)  # down → 90
        assert abs(hue2 - 90.0) < 1

    def test_set_get(self, root):
        w = ColorWheel(root)
        w.set_value(120, 0.5)
        h, s = w.get_value()
        assert abs(h - 120) < 1 and abs(s - 0.5) < 1e-6

    def test_sat_clamped(self, root):
        w = ColorWheel(root)
        w.set_value(30, 3.0)
        assert w.get_value()[1] == 1.0


class TestHslPanel:
    def test_set_get(self, root):
        p = HSLPanel(root)
        p.set_adjustments({"green": (10, 0.2, 0.1)})
        assert p.get_adjustments()["green"] == (10.0, 0.2, 0.1)

    def test_load_dump_roundtrip(self, root):
        p = HSLPanel(root)
        p.load("green:10,0.2,0.1;red:-5,0,0")
        out = p.dump()
        assert "green:10,0.2,0.1" in out
        assert "red:-5,0,0" in out

    def test_dump_skips_zero(self, root):
        p = HSLPanel(root)
        p.set_adjustments({"green": (0, 0, 0), "blue": (10, 0, 0)})
        assert p.dump() == "blue:10,0,0"

    def test_engine_accepts_dump(self, root):
        from PIL import Image
        from photo_s.grade import _parse_hsl, apply_hsl
        p = HSLPanel(root)
        p.set_adjustments({"green": (10, 0.2, 0.1)})
        im = Image.new("RGB", (8, 8), (0, 180, 0))
        out = apply_hsl(im, _parse_hsl(p.dump()))
        assert out is not None

    def test_rgb_to_hex(self):
        assert rgb_to_hex((255, 0, 0)) == "#ff0000"
        assert rgb_to_hex((52, 199, 89)) == "#34c759"


class TestDialogSerializers:
    """The editor dialogs' OK handlers must write the right specs back."""

    def _stub_win(self):
        class _W:
            def destroy(self):
                pass
        return _W()

    def test_curve_reset_restores_identity(self, root):
        from tests.test_gui_app import _make_app
        _r, app = _make_app()
        editors = {}
        for ch in ("rgb", "r", "g", "b"):
            ed = CurveEditor(root, channel=ch)
            ed.set_points([(0, 0), (128, 140), (255, 255)])
            editors[ch] = ed
        app._reset_curves(editors)
        for ed in editors.values():
            assert CurveEditor.is_identity(ed.get_points())
        _r.destroy()

    def test_curve_ok_sets_spec(self, root):
        from tests.test_gui_app import _make_app
        _r, app = _make_app()
        editors = {}
        for ch in ("rgb", "r", "g", "b"):
            ed = CurveEditor(root, channel=ch)
            if ch == "rgb":
                ed.set_points([(0, 0), (128, 140), (255, 255)])
            editors[ch] = ed
        app._curve_editor_ok(self._stub_win(), editors)
        assert app.curves.get() == "rgb:0,0;128,140;255,255"
        # only rgb edited → channels stay identity → single spec
        assert "|" not in app.curves.get()
        _r.destroy()

    def test_wheels_ok_skips_center(self, root):
        from tests.test_gui_app import _make_app
        _r, app = _make_app()
        wheels = {}
        for zone in ("shadows", "midtones", "highlights"):
            w = ColorWheel(root)
            wheels[zone] = w
        wheels["shadows"].set_value(120, 0.5)   # set
        wheels["midtones"].set_value(30, 0.0)   # centre → skipped
        app._wheels_ok(self._stub_win(), wheels)
        assert app.color_grading.get() == "shadows:120,0.50"
        _r.destroy()

    def test_wheels_ok_with_luminance(self, root):
        from tests.test_gui_app import _make_app
        _r, app = _make_app()

        class _V:
            def __init__(self, v):
                self._v = v
            def get(self):
                return self._v

        wheels, lums = {}, {}
        for zone in ("shadows", "midtones", "highlights"):
            wheels[zone] = ColorWheel(root)
        wheels["shadows"].set_value(120, 0.5)
        lums["shadows"] = _V(20.0)     # lum +0.20 → 3-value spec
        lums["midtones"] = _V(0.0)     # zero lum, wheel centre → skipped
        app._wheels_ok(self._stub_win(), wheels, lums)
        assert app.color_grading.get() == "shadows:120,0.50,0.20"
        _r.destroy()

    def test_hsl_ok_sets_spec(self, root):
        from tests.test_gui_app import _make_app
        _r, app = _make_app()
        panel = HSLPanel(root)
        panel.set_adjustments({"green": (10, 0.2, 0.1)})
        app._hsl_ok(self._stub_win(), panel)
        assert app.hsl.get() == "green:10,0.2,0.1"
        _r.destroy()
