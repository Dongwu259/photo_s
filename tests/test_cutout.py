"""Cutout (background removal) — spec parsing + color-key math + apply.

Parser and color-key are hermetic (pure numpy/PIL). AI kinds (subject/
person/object) delegate to ``mask.render_mask`` → ``segmask`` and are
covered by the engine-integration tests in this file's sibling tests
(mock segment), mirroring test_segmask.py's hermetic-by-default rule.
"""

import numpy as np
import pytest
from PIL import Image

from photo_s.cutout import (
    CutoutError, CutoutSpec, apply_cutout, cutout_mask, parse_cutout,
)


def _img(w=8, h=8, mode="RGB", fill=(0, 0, 0)):
    """Solid-color test image."""
    return Image.new(mode, (w, h), fill)


def _block_img(block, rest, w=8, h=8):
    """Image with a 2x2 block in the top-left corner of color `block`,
    the rest colored `rest`."""
    arr = np.empty((h, w, 3), dtype=np.uint8)
    arr[:, :] = rest
    arr[:2, :2] = block
    return Image.fromarray(arr)


# ── parser ──────────────────────────────────────────────────────────────

class TestParseBareKinds:
    def test_subject_roundtrip(self):
        spec = parse_cutout("subject")
        assert spec.kind == "subject"
        assert spec.label is None and spec.rgb is None
        assert spec.to_string() == "subject"

    def test_person_roundtrip(self):
        spec = parse_cutout("person")
        assert spec.kind == "person"
        assert spec.to_string() == "person"

    def test_whitespace_tolerated(self):
        assert parse_cutout("  subject ").kind == "subject"

    def test_stray_params_rejected(self):
        for bad in ("subject,x", "person:5", "subject:tol=3"):
            with pytest.raises(CutoutError, match="no params"):
                parse_cutout(bad)


class TestParseObject:
    def test_object_label(self):
        spec = parse_cutout("object:car")
        assert spec.kind == "object"
        assert spec.label == "car"
        assert spec.to_string() == "object:car"

    def test_label_case_and_spaces(self):
        assert parse_cutout("object:Traffic Light").label == "traffic light"
        assert parse_cutout("object:stop sign").label == "stop sign"

    def test_empty_label_rejected(self):
        with pytest.raises(CutoutError, match="COCO label"):
            parse_cutout("object:")

    def test_bad_chars_rejected(self):
        for bad in ("object:car;x", "object:ca:r", "object:car,feather=1",
                    "object:a=b"):
            with pytest.raises(CutoutError, match="COCO label"):
                parse_cutout(bad)


class TestParseColor:
    def test_defaults(self):
        spec = parse_cutout("color:255,0,128")
        assert spec.kind == "color"
        assert spec.rgb == (255, 0, 128)
        assert spec.tol == 30.0
        assert spec.feather == 0.0
        assert not spec.invert
        assert spec.to_string() == "color:255,0,128"  # defaults not echoed

    def test_kwargs_order_any(self):
        spec = parse_cutout("color:10,20,30,tol=5,feather=2,invert")
        assert spec.rgb == (10, 20, 30)
        assert spec.tol == 5.0
        assert spec.feather == 2.0
        assert spec.invert
        assert spec.to_string() == "color:10,20,30,tol=5,feather=2,invert"
        # keywords can precede positionals
        assert parse_cutout("color:tol=5,10,20,30").tol == 5.0

    def test_rgb_clamped(self):
        assert parse_cutout("color:300,-5,128.6").rgb == (255, 0, 129)

    def test_tol_clamped(self):
        assert parse_cutout("color:0,0,0,tol=-10").tol == 0.0
        assert parse_cutout("color:0,0,0,tol=9999").tol == 255.0

    def test_bad_color_rejected(self):
        for bad in ("color:", "color:1,2", "color:1,2,3,4", "color:1,x,3",
                    "color:1,2,3,tol=abc", "color:1,2,3,feather="):
            with pytest.raises(CutoutError):
                parse_cutout(bad)

    def test_nan_inf_rejected(self):
        with pytest.raises(CutoutError, match="finite"):
            parse_cutout("color:1,2,3,tol=nan")
        with pytest.raises(CutoutError, match="finite"):
            parse_cutout("color:1,2,3,feather=inf")


class TestParseErrors:
    def test_empty_spec(self):
        for bad in ("", "   "):
            with pytest.raises(CutoutError, match="empty"):
                parse_cutout(bad)

    def test_unknown_kind(self):
        for bad in ("nope", "car", "background"):
            with pytest.raises(CutoutError, match="unknown kind"):
                parse_cutout(bad)

    def test_error_quotes_spec(self):
        with pytest.raises(CutoutError, match="'car'"):
            parse_cutout("car")


# ── color-key math (cutout_mask / apply_cutout) ─────────────────────────

class TestColorKey:
    def test_hard_threshold(self):
        img = _block_img((255, 0, 0), (0, 255, 0), w=4, h=4)  # red on green
        spec = parse_cutout("color:255,0,0,tol=1")
        mask = cutout_mask(spec, img)
        assert mask.dtype == np.float32 and mask.shape == (4, 4)
        assert mask[:2, :2].min() == 0.0   # red block -> background
        assert mask[2:, 2:].max() == 1.0   # green -> foreground

    def test_tol_boundary(self):
        # target white, tol=3: dist==2 kept, dist==4 dropped (dist<=tol -> bg)
        arr = np.zeros((1, 2, 3), dtype=np.uint8)
        arr[0, 0] = (253, 255, 255)  # dist 2
        arr[0, 1] = (251, 255, 255)  # dist 4
        img = Image.fromarray(arr)
        mask = cutout_mask(parse_cutout("color:255,255,255,tol=3"), img)
        assert mask[0, 0] == 0.0
        assert mask[0, 1] == 1.0

    def test_feather_soft_edge(self):
        w = h = 32
        arr = np.zeros((h, w, 3), dtype=np.uint8)
        arr[:, w // 2:] = (255, 255, 255)  # right half white bg
        img = Image.fromarray(arr)
        mask = cutout_mask(parse_cutout("color:255,255,255,tol=1,feather=3"),
                           img)
        alphas = mask * 255.0
        assert alphas[h // 2, 4] == 255.0          # deep black -> opaque
        assert alphas[h // 2, w - 4] == 0.0        # deep white -> transparent
        band = alphas[h // 2, :]                   # row across the edge
        assert (0.0 < band).any() and (band < 255.0).any()  # soft edge
        assert (np.diff(band) <= 1e-6).all()       # monotonic 1 -> 0

    def test_invert_flips_selection(self):
        img = _block_img((255, 0, 0), (0, 255, 0), w=4, h=4)
        mask = cutout_mask(parse_cutout("color:255,0,0,tol=1,invert"), img)
        assert mask[:2, :2].max() == 1.0
        assert mask[2:, 2:].min() == 0.0

    def test_apply_cutout_alpha(self):
        img = _block_img((255, 0, 0), (0, 255, 0), w=4, h=4)
        out = apply_cutout(img, parse_cutout("color:255,0,0,tol=1"))
        assert out.mode == "RGBA"
        assert out.getpixel((0, 0))[3] == 0      # red block transparent
        assert out.getpixel((3, 3))[3] == 255    # green opaque
        assert out.info == img.info              # info copied

    def test_source_alpha_replaced(self):
        src = Image.new("RGBA", (4, 4), (0, 0, 0, 0))  # fully transparent src
        out = apply_cutout(src, parse_cutout("color:0,0,0,tol=1,invert"))
        assert out.getpixel((0, 0))[3] == 255    # black now opaque

    def test_rgb_input_returns_rgba(self):
        out = apply_cutout(_img(4, 4, fill=(10, 10, 10)),
                           parse_cutout("color:0,0,0,tol=1"))
        assert out.mode == "RGBA"
