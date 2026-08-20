"""Lens correction (v1.7.0): distortion / vignette removal / CA fix."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest
from PIL import Image

from photo_s.lens import (
    LensError,
    apply_ca_fix,
    apply_distortion,
    apply_vignette_fix,
    parse_ca,
    parse_vignette_fix,
)


def _checker(size=32, cell=8):
    """Checkerboard image - geometry shifts are easy to detect."""
    img = Image.new("RGB", (size, size))
    for y in range(size):
        for x in range(size):
            v = 255 if ((x // cell) + (y // cell)) % 2 == 0 else 0
            img.putpixel((x, y), (v, v, v))
    return img


def _center_dot(size=32, radius=2):
    img = Image.new("RGB", (size, size), (0, 0, 0))
    c = size // 2
    for y in range(size):
        for x in range(size):
            if (x - c) ** 2 + (y - c) ** 2 <= radius ** 2:
                img.putpixel((x, y), (255, 255, 255))
    return img


# ── Distortion ───────────────────────────────────────────────────────────────

def test_distortion_identity():
    img = _checker()
    assert apply_distortion(img, 0.0) is img


def test_distortion_moves_edges_not_center():
    img = _center_dot(32, 3)   # white dot exactly at centre
    out = apply_distortion(img, 0.3)
    arr = np.asarray(out)
    # Centre stays white (scale ~1 at r=0).
    assert arr[16, 16, 0] > 200
    # Corner content came from outside the original frame (black) ->
    # a black ring appears at the very corners.
    assert arr[0, 0, 0] == 0 or arr[1, 1, 0] < 100


def test_distortion_positive_pulls_content_outward():
    # White background, black centre dot: with k1 > 0 the output samples
    # further out at the edges, so the centre dot must appear SMALLER.
    img = _center_dot(40, 8)
    out = apply_distortion(img, 0.5)
    count_in = np.asarray(img)[..., 0].sum() / 255
    count_out = np.asarray(out)[..., 0].sum() / 255
    assert count_out < count_in  # dot shrank (edge replicate keeps bg white)


def test_distortion_negative_pushes_content_inward():
    img = _center_dot(40, 8)
    out = apply_distortion(img, -0.3)
    count_in = np.asarray(img)[..., 0].sum() / 255
    count_out = np.asarray(out)[..., 0].sum() / 255
    assert count_out > count_in  # dot grew (sampling inward)


def test_distortion_preserves_info_and_alpha():
    img = _checker(16, 4).convert("RGBA")
    img.info["exif"] = b"keep"
    out = apply_distortion(img, 0.2)
    assert out.mode == "RGBA"
    assert out.info.get("exif") == b"keep"
    assert out.size == img.size


# ── Vignette fix ─────────────────────────────────────────────────────────────

def test_vignette_fix_brightens_corners_only():
    img = Image.new("RGB", (64, 64), (100, 100, 100))
    out = apply_vignette_fix(img, 0.5, 0.1)
    arr = np.asarray(out).astype(int)
    assert arr[32, 32, 0] == 100               # centre untouched
    assert arr[0, 0, 0] > 130                  # corner lifted ~1.5x
    assert arr[0, 32, 0] > 100                 # edge partially lifted


def test_vignette_fix_negative_darkens():
    img = Image.new("RGB", (64, 64), (100, 100, 100))
    out = apply_vignette_fix(img, -0.5, 0.1)
    arr = np.asarray(out).astype(int)
    assert arr[32, 32, 0] == 100
    assert arr[0, 0, 0] < 70


def test_parse_vignette_fix():
    assert parse_vignette_fix("0.3") == (0.3, 0.5)
    assert parse_vignette_fix("0.3,0.8") == (0.3, 0.8)
    with pytest.raises(LensError):
        parse_vignette_fix("a,b")
    with pytest.raises(LensError):
        parse_vignette_fix("0.1,0.2,0.3")


# ── CA fix ───────────────────────────────────────────────────────────────────

def test_ca_fix_identity():
    img = _checker(16, 4)
    assert apply_ca_fix(img, 1.0, 1.0) is img


def test_ca_fix_rescales_red_channel():
    # Red square filling the image; shrinking the R channel pulls in black
    # from... no - edge replicate keeps it red. Use a red circle instead.
    size = 32
    img = Image.new("RGB", (size, size), (0, 255, 0))
    c = size // 2
    for y in range(size):
        for x in range(size):
            if (x - c) ** 2 + (y - c) ** 2 <= 10 ** 2:
                img.putpixel((x, y), (255, 0, 0))
    out = apply_ca_fix(img, 2.0, 1.0)   # R samples outward -> red shrinks
    arr = np.asarray(out).astype(int)
    # R content shrank: fewer red-dominant pixels at the old radius.
    red_before = (np.asarray(img)[..., 0] > 200).sum()
    red_after = (arr[..., 0] > 200).sum()
    assert red_after < red_before
    # Green untouched everywhere outside the circle.
    assert arr[0, 0, 1] == 255


def test_parse_ca():
    assert parse_ca("") == (1.0, 1.0)
    assert parse_ca("0.999") == (0.999, 1.0)
    assert parse_ca("0.999,1.001") == (0.999, 1.001)
    with pytest.raises(LensError):
        parse_ca("x,y")
    with pytest.raises(LensError):
        parse_ca("1,2,3")


# ── Engine pipeline ──────────────────────────────────────────────────────────

def _process(src, out_dir, **kwargs):
    from photo_s.engine import ProcessOptions, process_image
    opts = ProcessOptions(output_dir=str(out_dir), suffix="_l",
                          output_format="PNG", **kwargs)
    return process_image(str(src), opts)


def test_engine_lens_vignette_pipeline(tmp_path):
    src = tmp_path / "a.png"
    Image.new("RGB", (32, 32), (100, 100, 100)).save(src)
    res = _process(src, tmp_path / "out", lens_vignette="0.5,0.1")
    assert res.success
    arr = np.asarray(Image.open(res.output_path)).astype(int)
    assert arr[16, 16, 0] == 100
    assert arr[0, 0, 0] > 130


def test_engine_lens_distort_pipeline(tmp_path):
    src = tmp_path / "a.png"
    _center_dot(32, 4).save(src)
    res = _process(src, tmp_path / "out", lens_distort=0.4)
    assert res.success
    # Output written and centre still white-ish (bilinear on flat dot).
    arr = np.asarray(Image.open(res.output_path))
    assert arr[16, 16, 0] > 200


def test_engine_lens_bad_spec_is_per_file_error(tmp_path):
    src = tmp_path / "a.png"
    Image.new("RGB", (8, 8), (10, 10, 10)).save(src)
    res = _process(src, tmp_path / "out", lens_vignette="bogus")
    assert res.success is False
    assert res.error
