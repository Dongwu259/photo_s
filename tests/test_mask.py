"""Local-adjustment masks (v1.7.0): parse / render / combine / apply_local."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest
from PIL import Image

from photo_s.mask import (
    ADJUST_KEYS,
    MaskError,
    apply_local,
    combine,
    parse_mask_adjust,
    parse_masks,
    render_all,
    render_mask,
)


def _solid(w=8, h=8, color=(128, 64, 32)):
    img = Image.new("RGB", (w, h), color)
    return img


# ── Parsing ──────────────────────────────────────────────────────────────────

def test_parse_linear_with_name_and_feather():
    specs = parse_masks("sky:linear:0.5,0,0.5,1,feather=0.3")
    assert len(specs) == 1
    s = specs[0]
    assert s.name == "sky"
    assert s.kind == "linear"
    assert s.params == (0.5, 0.0, 0.5, 1.0)
    assert s.feather == pytest.approx(0.3)
    assert s.invert is False


def test_parse_unnamed_gets_sequential_name():
    specs = parse_masks("linear:0,0,0,1;radial:0.5,0.5,0.2,0.2")
    assert [s.name for s in specs] == ["1", "2"]


def test_parse_radial_positional_feather_and_invert():
    s = parse_masks("radial:0.5,0.5,0.3,0.4,0.2,invert")[0]
    assert s.feather == pytest.approx(0.2)
    assert s.invert is True
    assert s.params == (0.5, 0.5, 0.3, 0.4)


def test_parse_color_defaults_and_tol_kw():
    s = parse_masks("face:color:255,200,180")[0]
    assert s.kind == "color"
    assert s.params == (255, 200, 180, 0.15)  # default tol
    s2 = parse_masks("face:color:255,200,180,tol=0.4")[0]
    assert s2.params[3] == pytest.approx(0.4)


def test_parse_rejects_bad_type():
    with pytest.raises(MaskError, match="unknown mask type"):
        parse_masks("linearx:0,0,0,1")
    with pytest.raises(MaskError, match="unknown mask type"):
        parse_masks("gradient:0,0,1,0")


def test_v18_types_parse():
    # v1.8 types now parse (AI/brush/combo); params are validated per type.
    assert parse_masks("main:subject")[0].kind == "subject"
    assert parse_masks("people:person")[0].kind == "person"
    assert parse_masks("car:object:car")[0].params == ("car",)
    b = parse_masks("stroke:brush:0.5,0.5,0.05|0.6,0.5,0.05")[0]
    assert b.kind == "brush" and len(b.params) == 2
    c = parse_masks("both:combo:a&b")[0]
    assert c.kind == "combo" and c.params == ("a", "&", "b")
    d = parse_masks("diff:combo:a-b")[0]
    assert d.params == ("a", "-", "b")
    # invalid params per type still raise
    with pytest.raises(MaskError, match="takes no params"):
        parse_masks("subject:x")
    with pytest.raises(MaskError, match="COCO label"):
        parse_masks("object:")
    with pytest.raises(MaskError, match="needs at least one dot"):
        parse_masks("brush:")
    with pytest.raises(MaskError, match="needs 'A&B' or 'A-B'"):
        parse_masks("combo:abc")


def test_parse_rejects_missing_params():
    with pytest.raises(MaskError):
        parse_masks("linear:0,0,0")           # needs 4 coords
    with pytest.raises(MaskError):
        parse_masks("radial:0.5,0.5,0,0.2")   # rx must be > 0
    with pytest.raises(MaskError):
        parse_masks("color:255,200")          # needs r,g,b
    with pytest.raises(MaskError):
        parse_masks("linear:0.5,0.5,0.5,0.5")  # zero-length axis


def test_parse_rejects_duplicate_names():
    with pytest.raises(MaskError, match="duplicate"):
        parse_masks("a:linear:0,0,0,1;a:linear:0,1,1,1")


def test_to_string_roundtrips():
    for spec in ("sky:linear:0.5,0,0.5,1,feather=0.3",
                 "radial:0.5,0.5,0.3,0.4,invert",
                 "face:color:255,200,180,tol=0.2",
                 "linear:0,0,0,1"):
        s = parse_masks(spec)[0]
        again = parse_masks(s.to_string())[0]
        assert again.kind == s.kind
        assert np.allclose(again.params, s.params, atol=1e-4)
        assert again.feather == pytest.approx(s.feather, abs=1e-4)
        assert again.invert == s.invert
        assert again.name == s.name


# ── Rendering ────────────────────────────────────────────────────────────────

def test_linear_mask_ramps_top_to_bottom():
    m = render_mask(parse_masks("linear:0.5,0,0.5,1")[0], 4, 4)
    assert m.shape == (4, 4)
    # Same value on every row pixel; rows ramp 0 -> 1 downwards.
    assert np.allclose(m[0], 0.0)
    assert np.allclose(m[3], 1.0)
    assert m[1, 0] < m[2, 0]
    assert np.allclose(m, m[:, :1])  # uniform within each row


def test_radial_mask_center_full_edge_empty():
    m = render_mask(parse_masks("radial:0.5,0.5,0.4,0.4")[0], 9, 9)
    assert m[4, 4] > 0.9          # center inside
    assert m[0, 0] == 0.0         # corner outside the ellipse


def test_radial_invert_flips():
    spec = parse_masks("radial:0.5,0.5,0.4,0.4,invert")[0]
    m = render_mask(spec, 9, 9)
    assert m[4, 4] == pytest.approx(0.0, abs=1e-6)
    assert m[0, 0] == pytest.approx(1.0, abs=1e-6)


def test_color_mask_selects_matching_pixels():
    img = Image.new("RGB", (4, 2))
    for x in range(4):
        img.putpixel((x, 0), (200, 30, 30))   # red row
        img.putpixel((x, 1), (30, 30, 200))   # blue row
    m = render_mask(parse_masks("r:color:200,30,30,tol=0.1")[0], 4, 2, img=img)
    assert m[0].mean() > 0.8   # red row selected
    assert m[1].mean() < 0.2   # blue row rejected


def test_color_mask_ignores_gray_for_saturated_target():
    img = Image.new("RGB", (2, 1))
    img.putpixel((0, 0), (128, 128, 128))  # gray
    img.putpixel((1, 0), (10, 200, 10))    # green
    m = render_mask(parse_masks("g:color:10,200,10,tol=0.3")[0], 2, 1, img=img)
    assert m[0, 0] < 0.1
    assert m[0, 1] > 0.8


def test_color_mask_without_image_raises():
    with pytest.raises(MaskError, match="needs the image"):
        render_mask(parse_masks("c:color:1,2,3")[0], 4, 4)


def test_feather_softens_hard_edge():
    hard = render_mask(parse_masks("linear:0,0,0,1")[0], 64, 64)
    soft = render_mask(parse_masks("linear:0,0,0,1,feather=0.5")[0], 64, 64)
    # Feathering must not change the extremes but must lift the floor.
    assert soft.min() > hard.min()
    assert abs(soft[-1].mean() - hard[-1].mean()) < 0.1


def test_render_all_returns_named_dict():
    specs = parse_masks("sky:linear:0.5,0,0.5,1;spot:radial:0.5,0.5,0.2,0.2")
    out = render_all(specs, 8, 8)
    assert set(out) == {"sky", "spot"}
    assert out["sky"].shape == (8, 8)


def test_combine_is_union():
    a = np.zeros((4, 4), dtype=np.float32)
    a[0, 0] = 1.0
    b = np.zeros((4, 4), dtype=np.float32)
    b[1, 1] = 0.5
    c = combine([a, b])
    assert c[0, 0] == 1.0
    assert c[1, 1] == 0.5
    assert c[2, 2] == 0.0


# ── mask_adjust parsing ──────────────────────────────────────────────────────

def test_parse_mask_adjust():
    out = parse_mask_adjust("sky:exposure=-0.7,saturation=0.2;face:blur=4")
    assert out == {"sky": {"exposure": -0.7, "saturation": 0.2},
                   "face": {"blur": 4.0}}


def test_parse_mask_adjust_rejects_unknown_key():
    with pytest.raises(MaskError, match="unknown mask adjustment"):
        parse_mask_adjust("a:exposur=0.5")   # typo
    with pytest.raises(MaskError, match="numeric"):
        parse_mask_adjust("a:exposure=lots")
    with pytest.raises(MaskError):
        parse_mask_adjust("no-colon-here")


# ── apply_local ──────────────────────────────────────────────────────────────

def test_apply_local_brightens_only_masked_half():
    img = Image.new("RGB", (4, 4), (100, 100, 100))
    mask = np.zeros((4, 4), dtype=np.float32)
    mask[2:, :] = 1.0  # bottom half
    out = apply_local(img, mask, {"brightness": 0.5})
    arr = np.asarray(out)
    assert np.allclose(arr[:2], 100)          # top untouched
    assert arr[2:].mean() > 110               # bottom brightened
    assert out.size == img.size


def test_apply_local_empty_mask_is_identity():
    img = _solid()
    mask = np.zeros((8, 8), dtype=np.float32)
    out = apply_local(img, mask, {"exposure": 1.0})
    assert out is img  # fast path, no work


def test_apply_local_preserves_info_and_mode():
    img = _solid(4, 4)
    img.info["exif"] = b"dummy"
    mask = np.ones((4, 4), dtype=np.float32)
    out = apply_local(img, mask, {"contrast": 0.2})
    assert out.mode == "RGB"
    assert out.info.get("exif") == b"dummy"


def test_apply_local_blur_softens_inside_mask():
    img = Image.new("RGB", (16, 16), (0, 0, 0))
    for x in range(16):  # vertical stripes -> blur mixes them
        for y in range(16):
            img.putpixel((x, y), (255, 255, 255) if x % 2 else (0, 0, 0))
    mask = np.ones((16, 16), dtype=np.float32)
    out = apply_local(img, mask, {"blur": 2.0})
    arr = np.asarray(out).astype(float)
    assert arr.std() < np.asarray(img).astype(float).std()


def test_apply_local_partial_mask_blends():
    img = Image.new("RGB", (2, 1), (100, 100, 100))
    mask = np.array([[0.0, 0.5]], dtype=np.float32)
    out = apply_local(img, mask, {"brightness": 1.0})  # 100 -> 200, half-blended
    arr = np.asarray(out)
    assert tuple(arr[0, 0]) == (100, 100, 100)
    assert 140 < arr[0, 1, 0] < 160  # ~150 half-way blend


def test_apply_local_shape_mismatch_raises():
    img = _solid(4, 4)
    mask = np.zeros((8, 8), dtype=np.float32)
    with pytest.raises(MaskError, match="does not match"):
        apply_local(img, mask, {"exposure": 1.0})


def test_adjust_keys_cover_documented_set():
    assert set(ADJUST_KEYS) == {
        "exposure", "brightness", "contrast", "saturation", "vibrance",
        "clarity", "texture", "sharpen", "temp", "tint", "blur"}


# ── v1.8: brush / combo / string adjustments ─────────────────────────────────

def test_brush_renders_stroke_union():
    spec = parse_masks("stroke:brush:0.5,0.5,0.05|0.6,0.5,0.05")[0]
    m = render_mask(spec, 100, 100)
    assert m.shape == (100, 100)
    assert m[50, 50] > 0.9       # first dot center
    assert m[50, 55] > 0.9       # second dot center
    assert m[50, 52] > 0.3       # capsule between dots
    assert m[5, 5] < 0.05        # far away


def test_brush_bad_dot_raises():
    with pytest.raises(MaskError, match="must be 'x,y,r'"):
        parse_masks("brush:0.5,0.5")
    with pytest.raises(MaskError, match="radius must be in"):
        parse_masks("brush:0.5,0.5,0.9")
    with pytest.raises(MaskError, match="out of range"):
        parse_masks("brush:1.5,0.5,0.05")


def test_combo_intersection_and_difference():
    specs = parse_masks("a:linear:0,0,1,0; b:linear:0,1,1,1; both:combo:a&b")
    refs = {s.name: s for s in specs}
    a = render_mask(refs["a"], 50, 50, refs=refs)
    b = render_mask(refs["b"], 50, 50, refs=refs)
    both = render_mask(refs["both"], 50, 50, refs=refs)
    assert both[25, 25] == pytest.approx(min(a[25, 25], b[25, 25]))
    diff = parse_masks("d:combo:a-b")
    d = render_mask(diff[0], 50, 50, refs={**refs, "d": diff[0]})
    assert d[25, 25] == pytest.approx(max(a[25, 25] - b[25, 25], 0.0))


def test_combo_unknown_reference_raises():
    specs = parse_masks("both:combo:a&b; x:linear:0,0,1,0")
    refs = {s.name: s for s in specs if s.name == "x"}
    with pytest.raises(MaskError, match="unknown mask"):
        render_mask(specs[0], 10, 10, refs=refs)


def test_v18_to_string_roundtrip():
    for s in ("main:subject", "people:person", "car:object:car",
              "stroke:brush:0.5,0.5,0.05|0.6,0.5,0.05",
              "both:combo:a&b", "diff:combo:a-b"):
        spec = parse_masks(s)[0]
        assert parse_masks(spec.to_string())[0].to_string() == spec.to_string()


def test_mask_adjust_string_values():
    d = parse_mask_adjust(
        "sky:curves={r:0,0;128,140;255,255},hsl={red:0.1,0.2,0.0}")
    assert d["sky"]["curves"] == "r:0,0;128,140;255,255"
    assert d["sky"]["hsl"] == "red:0.1,0.2,0.0"
    # plain scalars still work alongside
    d2 = parse_mask_adjust("sky:exposure=-0.5,curves={r:0,0;255,255}")
    assert d2["sky"]["exposure"] == -0.5
    assert d2["sky"]["curves"] == "r:0,0;255,255"
    # missing braces: ';' inside value would split - reject as unknown key
    with pytest.raises(MaskError):
        parse_mask_adjust("sky:curves=r:0,0;128,140")


def test_apply_local_curves_under_mask():
    img = _solid(8, 8)
    mask = np.full((8, 8), 1.0, dtype=np.float32)
    # curves pushing highlights down: 120 -> darker under full mask
    out = apply_local(img, mask, {"curves": "r:0,0;200,100;255,255"})
    assert np.asarray(out)[0, 0, 0] < 110


# ── Engine pipeline integration ──────────────────────────────────────────────

def _process(src, out_dir, **kwargs):
    from photo_s.engine import ProcessOptions, process_image
    opts = ProcessOptions(output_dir=str(out_dir), suffix="_m",
                          output_format="PNG", **kwargs)
    return process_image(str(src), opts)


def test_engine_pipeline_local_adjustment(tmp_path):
    src = tmp_path / "a.png"
    Image.new("RGB", (20, 20), (120, 120, 120)).save(src)
    res = _process(
        src, tmp_path / "out",
        masks="bottom:linear:0.5,0.5,0.5,1",
        mask_adjust="bottom:brightness=0.5")
    out = Image.open(res.output_path).convert("RGB")
    arr = np.asarray(out)
    assert arr[:10].mean() == pytest.approx(120, abs=3)   # top untouched
    assert arr[10:].mean() > 150                          # bottom brightened


def test_engine_pipeline_color_mask_adjustment(tmp_path):
    src = tmp_path / "a.png"
    img = Image.new("RGB", (8, 8))
    for y in range(8):
        for x in range(8):
            img.putpixel((x, y), (200, 40, 40) if y < 4 else (40, 40, 200))
    img.save(src)
    res = _process(
        src, tmp_path / "out",
        masks="reds:color:200,40,40,tol=0.1",
        mask_adjust="reds:brightness=0.5")
    out = np.asarray(Image.open(res.output_path).convert("RGB"))
    assert out[:4].mean() > out[4:].mean() + 30   # red half brightened
    assert out[4:].mean() == pytest.approx(93.3, abs=2)  # blue half untouched


def test_engine_pipeline_unknown_mask_reference_fails(tmp_path):
    src = tmp_path / "a.png"
    Image.new("RGB", (4, 4), (10, 10, 10)).save(src)
    res = _process(src, tmp_path / "out",
                   masks="sky:linear:0,0,0,1",
                   mask_adjust="nosuch:brightness=0.5")
    assert res.success is False
    assert "unknown mask" in (res.error or "")


def test_engine_pipeline_bad_mask_spec_fails(tmp_path):
    src = tmp_path / "a.png"
    Image.new("RGB", (4, 4), (10, 10, 10)).save(src)
    res = _process(src, tmp_path / "out",
                   masks="sky:warp:0,0",
                   mask_adjust="sky:brightness=0.5")
    assert res.success is False
    assert res.error
