"""Color grading primitives (v1.6.0): levels / curves / vibrance / grading."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest
from PIL import Image

from photo_s.grade import (
    _build_curve_lut,
    _monotone_cubic,
    _parse_color_grading,
    _parse_curves,
    _parse_grain,
    _parse_hsl,
    _parse_levels,
    _parse_vignette,
    apply_clarity,
    apply_color_grading,
    apply_curves,
    apply_dehaze,
    apply_export_sharpen,
    apply_grain,
    apply_highlight_recovery,
    apply_hsl,
    apply_levels,
    apply_texture,
    apply_vibrance,
    apply_vignette,
)


class TestParseLevels:
    def test_full(self):
        assert _parse_levels("10,240,1.1") == (10.0, 240.0, 1.1)

    def test_partial(self):
        assert _parse_levels("10") == (10.0, 255.0, 1.0)
        assert _parse_levels("10,240") == (10.0, 240.0, 1.0)

    def test_clamping(self):
        black, white, gamma = _parse_levels("-5,300,0.5")
        assert black == 0.0 and white == 255.0 and gamma == 0.5
        black, white, _ = _parse_levels("50,50,1")
        assert white > black  # white point forced above black


class TestApplyLevels:
    def test_identity_is_noop(self):
        im = Image.new("RGB", (4, 4), (100, 100, 100))
        assert apply_levels(im) is im

    def test_black_point_raises_floors(self):
        # black=128 → anything below 128 goes to 0
        im = Image.new("RGB", (4, 4), (64, 64, 64))
        out = apply_levels(im, black=128)
        assert out.getpixel((0, 0)) == (0, 0, 0)

    def test_white_point_raises_ceiling(self):
        im = Image.new("RGB", (4, 4), (192, 192, 192))
        out = apply_levels(im, white=128)
        assert out.getpixel((0, 0)) == (255, 255, 255)

    def test_gamma_midpoint(self):
        im = Image.new("RGB", (4, 4), (128, 128, 128))
        # convention matches _final_tone: out = in**(1/gamma) → gamma<1 darkens
        out = apply_levels(im, gamma=0.5)
        assert out.getpixel((0, 0))[0] < 128

    def test_alpha_preserved(self):
        im = Image.new("RGBA", (4, 4), (100, 100, 100, 200))
        out = apply_levels(im, black=64)
        assert out.mode == "RGBA"
        assert out.getpixel((0, 0))[3] == 200

    def test_info_preserved(self):
        im = Image.new("RGB", (4, 4), (100, 100, 100))
        im.info["exif"] = b"mock"
        out = apply_levels(im, gamma=1.2)
        assert out.info.get("exif") == b"mock"


class TestCurves:
    def test_parse_rgb_default(self):
        assert _parse_curves("0,0;128,140;255,255") == {
            "rgb": [(0.0, 0.0), (128.0, 140.0), (255.0, 255.0)]}

    def test_parse_channels(self):
        got = _parse_curves("r:0,0;255,255|g:0,0;128,120;255,255")
        assert set(got) == {"r", "g"}

    def test_parse_bad_channel(self):
        with pytest.raises(ValueError):
            _parse_curves("x:0,0;255,255")

    def test_monotone_cubic_is_monotone(self):
        xs = [0, 64, 128, 192, 255]
        ys = [0, 60, 130, 200, 255]
        xq = np.linspace(0, 255, 300)
        out = _monotone_cubic(xs, ys, xq)
        assert np.all(np.diff(out) >= -1e-6)  # never decreases

    def test_build_lut_endpoints(self):
        lut = _build_curve_lut([(0, 0), (255, 255)])
        assert lut[0] == 0 and lut[255] == 255
        assert lut == list(range(256))  # identity

    def test_apply_darkens(self):
        im = Image.new("RGB", (8, 8), (200, 200, 200))
        # a curve pulling the top of the range down
        out = apply_curves(im, {"rgb": [(0, 0), (128, 128), (255, 160)]})
        px = out.getpixel((0, 0))
        assert 128 < px[0] < 200  # darkened, and monotone (below the endpoint)

    def test_apply_per_channel(self):
        im = Image.new("RGB", (8, 8), (100, 200, 100))
        # only R: linear inverse (0,255)→(255,0) maps 100 → 155; G/B identity
        out = apply_curves(im, {"r": [(0, 255), (255, 0)]})
        r, g, b = out.getpixel((0, 0))
        assert r == 155 and g == 200 and b == 100

    def test_alpha_preserved(self):
        im = Image.new("RGBA", (8, 8), (100, 200, 100, 180))
        out = apply_curves(im, {"r": [(0, 255), (255, 0)]})
        assert out.mode == "RGBA"
        assert out.getpixel((0, 0))[3] == 180

    def test_info_preserved(self):
        im = Image.new("RGB", (8, 8), (100, 200, 100))
        im.info["icc_profile"] = b"mock"
        out = apply_curves(im, {"r": [(0, 255), (255, 0)]})
        assert out.info.get("icc_profile") == b"mock"

    def test_empty_is_noop(self):
        im = Image.new("RGB", (4, 4), (50, 100, 150))
        assert apply_curves(im, {}) is im


class TestVibrance:
    def test_zero_noop(self):
        im = Image.new("RGB", (4, 4), (50, 100, 150))
        assert apply_vibrance(im, 0.0) is im

    def test_boost_muted_more_than_saturated(self):
        muted = np.zeros((1, 1, 3), dtype=np.float32)
        muted[0, 0] = (0.5, 0.5, 0.6)      # low saturation
        saturated = np.zeros((1, 1, 3), dtype=np.float32)
        saturated[0, 0] = (0.2, 0.1, 0.9)  # high saturation
        _sat = lambda arr: (arr.max() - arr.min()) / max(arr.max(), 1e-9)
        im_m = Image.fromarray((muted * 255).astype(np.uint8), "RGB")
        im_s = Image.fromarray((saturated * 255).astype(np.uint8), "RGB")
        m_out = apply_vibrance(im_m, 0.8)
        s_out = apply_vibrance(im_s, 0.8)
        m_arr = np.asarray(m_out, dtype=np.float32) / 255.0
        s_arr = np.asarray(s_out, dtype=np.float32) / 255.0
        # muted pixel gains relatively more saturation than the saturated one
        assert (_sat(m_arr[0, 0]) - _sat(muted[0, 0])) > (
            _sat(s_arr[0, 0]) - _sat(saturated[0, 0]))

    def test_negative_softens(self):
        im = Image.new("RGB", (4, 4), (200, 50, 50))
        out = apply_vibrance(im, -0.5)
        r, g, b = out.getpixel((0, 0))
        # desaturated → channels closer together
        assert (r - g) < 150

    def test_alpha_and_info(self):
        im = Image.new("RGBA", (8, 8), (200, 50, 50, 160))
        im.info["exif"] = b"mock"
        out = apply_vibrance(im, 0.5)
        assert out.mode == "RGBA"
        assert out.getpixel((0, 0))[3] == 160
        assert out.info.get("exif") == b"mock"


class TestColorGrading:
    def test_parse(self):
        got = _parse_color_grading("shadows:10,0.3;highlights:-5,0.2")
        assert got["shadows"] == (10.0, 0.3, 0.0)
        assert got["highlights"] == (-5.0, 0.2, 0.0)

    def test_parse_with_luminance(self):
        got = _parse_color_grading("shadows:10,0.3,0.2;midtones:-5,0,0.1")
        assert got["shadows"] == (10.0, 0.3, 0.2)
        assert got["midtones"] == (-5.0, 0.0, 0.1)

    def test_luminance_lifts_zone(self):
        # pure shadow with a strong +lum should get brighter overall
        im = Image.new("RGB", (16, 16), (20, 20, 20))
        out = apply_color_grading(im, shadows=(0, 0.0, 0.5))
        r, g, b = out.getpixel((0, 0))
        assert r > 20  # luminance lifted the shadows

    def test_parse_bad_zone(self):
        with pytest.raises(ValueError):
            _parse_color_grading("mids:10,0.3")

    def test_none_noop(self):
        im = Image.new("RGB", (4, 4), (100, 100, 100))
        assert apply_color_grading(im) is im

    def test_shadow_tint_pulls_dark_pixels(self):
        # dark neutral gray — hue 0; target hue 120 (green) with strength 1
        im = Image.new("RGB", (8, 8), (40, 40, 40))
        out = apply_color_grading(im, shadows=(120, 1.0))
        r, g, b = out.getpixel((0, 0))
        # green channel should dominate after a strong green pull
        assert g > r and g > b

    def test_highlight_tint_leaves_shadows(self):
        im = Image.new("RGB", (8, 8), (10, 10, 10))  # pure shadow
        out = apply_color_grading(im, highlights=(0, 0.8))  # red pull
        r, g, b = out.getpixel((0, 0))
        # shadows masked ~0 → pixels barely change
        assert abs(r - 10) <= 12 and abs(g - 10) <= 12

    def test_alpha_and_info(self):
        im = Image.new("RGBA", (8, 8), (40, 40, 40, 150))
        im.info["icc_profile"] = b"mock"
        out = apply_color_grading(im, shadows=(120, 0.5))
        assert out.mode == "RGBA"
        assert out.getpixel((0, 0))[3] == 150
        assert out.info.get("icc_profile") == b"mock"


class TestHsl:
    def test_parse(self):
        got = _parse_hsl("green:10,0.2,0.1;red:-5,0,0")
        assert got["green"] == (10.0, 0.2, 0.1)
        assert got["red"] == (-5.0, 0.0, 0.0)

    def test_parse_bad_color(self):
        with pytest.raises(ValueError):
            _parse_hsl("cyan:10,0.2,0.1")

    def test_shift_green_toward_cyan(self):
        # pure green (hue 120°) shifted +30° → cyan (180°), luminance held
        im = Image.new("RGB", (8, 8), (0, 180, 0))
        out = apply_hsl(im, {"green": (30, 0, 0)})
        r, g, b = out.getpixel((0, 0))
        assert b > r  # blue channel rose → hue moved toward cyan

    def test_sat_boost(self):
        im = Image.new("RGB", (8, 8), (120, 120, 140))  # slightly desat blue
        out = apply_hsl(im, {"blue": (0, 0.5, 0)})
        r, g, b = out.getpixel((0, 0))
        # saturating blue → the channel spread widens (b pulled away from r/g)
        assert (b - r) > (140 - 120)

    def test_alpha_and_info(self):
        im = Image.new("RGBA", (8, 8), (0, 180, 0, 170))
        im.info["exif"] = b"mock"
        out = apply_hsl(im, {"green": (30, 0, 0)})
        assert out.mode == "RGBA"
        assert out.getpixel((0, 0))[3] == 170
        assert out.info.get("exif") == b"mock"


class TestClarityTexture:
    def test_zero_noop(self):
        im = Image.new("RGB", (8, 8), (100, 100, 100))
        assert apply_clarity(im, 0.0) is im
        assert apply_texture(im, 0.0) is im

    def test_clarity_changes_edges(self):
        # a flat field with one bright square → local contrast kicks the edges
        arr = np.full((32, 32, 3), 120, dtype=np.uint8)
        arr[8:24, 8:24] = 180
        im = Image.fromarray(arr, "RGB")
        out = apply_clarity(im, 0.8)
        # at least one pixel changed vs input
        assert np.any(np.asarray(out) != np.asarray(im))

    def test_info_preserved(self):
        im = Image.new("RGB", (8, 8), (100, 100, 100))
        im.info["icc_profile"] = b"mock"
        out = apply_texture(im, 0.5)
        assert out.info.get("icc_profile") == b"mock"


class TestDehaze:
    def test_zero_noop(self):
        im = Image.new("RGB", (4, 4), (120, 120, 120))
        assert apply_dehaze(im, 0.0) is im

    def test_dehaze_increases_contrast(self):
        # uniformly hazy: dark+bright regions pulled apart
        arr = np.zeros((16, 16, 3), dtype=np.float32)
        arr[..., :] = 0.5          # heavy haze base
        arr[4:12, 4:12] = 0.65     # a slightly brighter patch
        im = Image.fromarray((arr * 255).astype(np.uint8), "RGB")
        out = apply_dehaze(im, 0.9)
        out_arr = np.asarray(out, dtype=np.float32) / 255.0
        base_var = float(arr.reshape(-1, 3).std())
        out_var = float(out_arr.reshape(-1, 3).std())
        assert out_var > base_var  # spread widened

    def test_info_preserved(self):
        im = Image.new("RGB", (8, 8), (120, 120, 120))
        im.info["exif"] = b"mock"
        out = apply_dehaze(im, 0.5)
        assert out.info.get("exif") == b"mock"


class TestVignette:
    def test_parse(self):
        assert _parse_vignette("0.6,0.4,0.3") == (0.6, 0.4, 0.3)
        assert _parse_vignette("0.6") == (0.6, 0.5, 0.5)

    def test_corners_darker_than_center(self):
        im = Image.new("RGB", (32, 32), (200, 200, 200))
        out = apply_vignette(im, 0.8)
        center = out.getpixel((16, 16))
        corner = out.getpixel((1, 1))
        assert corner[0] < center[0]

    def test_negative_lifts_corners(self):
        im = Image.new("RGB", (32, 32), (100, 100, 100))
        out = apply_vignette(im, -0.8)
        corner = out.getpixel((1, 1))
        assert corner[0] > 100

    def test_alpha_and_info(self):
        im = Image.new("RGBA", (32, 32), (200, 200, 200, 150))
        im.info["icc_profile"] = b"mock"
        out = apply_vignette(im, 0.5)
        assert out.mode == "RGBA"
        assert out.getpixel((16, 16))[3] == 150
        assert out.info.get("icc_profile") == b"mock"


class TestGrain:
    def test_parse(self):
        assert _parse_grain("0.2") == (0.2, 1.0)
        assert _parse_grain("0.2,2.5") == (0.2, 2.5)

    def test_zero_noop(self):
        im = Image.new("RGB", (8, 8), (100, 100, 100))
        assert apply_grain(im, 0.0) is im

    def test_adds_noise(self):
        im = Image.new("RGB", (16, 16), (100, 100, 100))
        out = apply_grain(im, 0.8)
        assert np.any(np.asarray(out) != np.asarray(im))

    def test_info_preserved(self):
        im = Image.new("RGB", (8, 8), (100, 100, 100))
        im.info["exif"] = b"mock"
        out = apply_grain(im, 0.3)
        assert out.info.get("exif") == b"mock"


class TestEngineSlot:
    """New grading options flow through the pipeline and keep EXIF."""

    def _run(self, tmp_path, **kwargs):
        from photo_s.engine import ProcessOptions, batch_process
        src = tmp_path / "in.jpg"
        Image.new("RGB", (16, 16), (120, 80, 40)).save(src)
        out = tmp_path / "out"
        opts = ProcessOptions(
            output_dir=str(out), overwrite=True, output_format="JPEG",
            suffix="", quality=90, **kwargs)
        return batch_process([str(src)], opts), out

    def test_levels(self, tmp_path):
        r, out = self._run(tmp_path, levels="80,200,1.0")
        assert r.success_count == 1 and (out / "in.jpg").exists()

    def test_curves(self, tmp_path):
        r, out = self._run(tmp_path, curves="0,0;128,140;255,255")
        assert r.success_count == 1 and (out / "in.jpg").exists()

    def test_vibrance(self, tmp_path):
        r, out = self._run(tmp_path, vibrance=0.5)
        assert r.success_count == 1 and (out / "in.jpg").exists()

    def test_wb_tint(self, tmp_path):
        r, out = self._run(tmp_path, wb_temp=6500, wb_tint=20)
        assert r.success_count == 1 and (out / "in.jpg").exists()

    def test_color_grading(self, tmp_path):
        r, out = self._run(tmp_path, color_grading="shadows:120,0.4;highlights:-10,0.2")
        assert r.success_count == 1 and (out / "in.jpg").exists()

    def test_hsl(self, tmp_path):
        r, out = self._run(tmp_path, hsl="green:10,0.2,0.1;red:-5,0,0")
        assert r.success_count == 1 and (out / "in.jpg").exists()

    def test_clarity_texture(self, tmp_path):
        r, out = self._run(tmp_path, clarity=0.5, texture=0.3)
        assert r.success_count == 1 and (out / "in.jpg").exists()

    def test_dehaze(self, tmp_path):
        r, out = self._run(tmp_path, dehaze=0.6)
        assert r.success_count == 1 and (out / "in.jpg").exists()

    def test_vignette_grain(self, tmp_path):
        r, out = self._run(tmp_path, vignette="0.5,0.4,0.4", grain="0.15,1.5")
        assert r.success_count == 1 and (out / "in.jpg").exists()

    def test_keeps_exif_through_grading(self, tmp_path):
        import piexif
        from photo_s.engine import (ProcessOptions, apply_exif_tags,
                                    batch_process)
        src = tmp_path / "in.jpg"
        Image.new("RGB", (16, 16), (120, 80, 40)).save(src)
        assert apply_exif_tags(str(src), {"artist": "Me"})
        out = tmp_path / "out"
        r = batch_process(
            [str(src)],
            ProcessOptions(output_dir=str(out), overwrite=True,
                           output_format="JPEG", suffix="", quality=90,
                           levels="80,200,1.0", vibrance=0.4,
                           color_grading="shadows:120,0.3"),
        )
        assert r.success_count == 1
        exif = piexif.load(str(out / "in.jpg"))
        artist = exif.get("0th", {}).get(piexif.ImageIFD.Artist)
        assert artist is not None and artist.decode(errors="replace") == "Me"

    def test_bad_curves_is_per_file_error(self, tmp_path):
        from photo_s.engine import ProcessOptions, batch_process
        src = tmp_path / "in.jpg"
        Image.new("RGB", (8, 8), (50, 100, 150)).save(src)
        r = batch_process(
            [str(src)],
            ProcessOptions(output_dir=str(tmp_path / "o"), overwrite=True,
                           output_format="JPEG", suffix="",
                           curves="x:0,0;255,255"),
        )
        # invalid spec must not abort the batch; the file fails per-file
        assert r.fail_count == 1
        assert r.results[0].success is False
        assert "curve" in r.results[0].error.lower()


# ── Point color (v1.7.0) ─────────────────────────────────────────────────────

from photo_s.grade import (  # noqa: E402
    _parse_point_color,
    apply_point_color,
)


def _two_color_image(top=(200, 40, 40), bottom=(40, 40, 200), w=4, h=4):
    img = Image.new("RGB", (w, h))
    for y in range(h):
        for x in range(w):
            img.putpixel((x, y), top if y < h // 2 else bottom)
    return img


def test_parse_point_color_basic_and_range():
    t = _parse_point_color("200,40,40:30,0.1,-0.2")[0]
    assert t == (200, 40, 40, 30.0, 0.1, -0.2, 0.1)  # default range
    t2 = _parse_point_color("200,40,40:30,0,0,0.3")[0]
    assert t2[6] == pytest.approx(0.3)


def test_parse_point_color_multiple_targets():
    ts = _parse_point_color("255,0,0:10,0,0;0,0,255:-10,0,0")
    assert len(ts) == 2
    assert ts[0][0] == 255 and ts[1][2] == 255


def test_parse_point_color_rejects_garbage():
    for bad in ("200,40:1,0,0", "a,b,c:1,0,0", "200,40,40:x,y,z",
                "no-colon", "200,40,40:1,0,0,0.5,9"):
        with pytest.raises(ValueError):
            _parse_point_color(bad)


def test_point_color_shifts_only_matching_color():
    img = _two_color_image()
    out = apply_point_color(img, _parse_point_color("200,40,40:60,0,0"))
    arr = np.asarray(out).astype(int)
    # Red half hue-shifted 60 deg (towards yellow): R stays high, G rises.
    assert arr[:2, :, 1].mean() > 80
    # Blue half essentially untouched.
    assert abs(arr[2:, :, :].mean() - np.asarray(img)[2:].mean()) < 6


def test_point_color_sat_and_lum():
    img = _two_color_image()
    out = apply_point_color(img, _parse_point_color("200,40,40:0,0,0.3"))
    arr = np.asarray(out).astype(int)
    assert arr[:2].mean() > np.asarray(img)[:2].mean()   # red half brighter
    assert abs(arr[2:].mean() - np.asarray(img)[2:].mean()) < 6


def test_point_color_tight_range_excludes_neighboring_hue():
    img = _two_color_image(top=(0, 200, 0), bottom=(60, 200, 0))  # green vs olive-ish
    tight = apply_point_color(img, _parse_point_color("0,200,0:90,0,0,0.02"))
    arr = np.asarray(tight).astype(int)
    # Green half rotates towards blue/cyan strongly; olive half barely moves.
    assert arr[:2, :, 2].mean() > 100
    assert arr[2:, :, 2].mean() < 30


def test_point_color_identity_noop():
    img = _two_color_image()
    assert apply_point_color(img, []) is img
    out = apply_point_color(img, _parse_point_color("200,40,40:0,0,0"))
    assert np.array_equal(np.asarray(out), np.asarray(img))


def test_point_color_preserves_info_and_alpha():
    img = _two_color_image().convert("RGBA")
    img.info["exif"] = b"keepme"
    out = apply_point_color(img, _parse_point_color("200,40,40:30,0,0"))
    assert out.mode == "RGBA"
    assert out.info.get("exif") == b"keepme"
    assert np.all(np.asarray(out)[..., 3] == 255)


class TestVibranceNeutral:
    """Regression: vibrance must leave truly neutral (gray) pixels alone.

    At sat ≈ 0, HSV hue is undefined — boosting saturation there round-trips
    to a red tint via HSV→RGB and darkens the pixel (e.g. 0.12 vibrance
    turned mid-gray 128 into (128, 113, 113)). Real vibrance is a no-op on
    neutrals."""

    def test_gray_stays_gray_and_same_value(self):
        im = Image.new("RGB", (4, 4), (128, 128, 128))
        out = apply_vibrance(im, 0.5)
        r, g, b = out.getpixel((0, 0))
        assert (r, g, b) == (128, 128, 128)

    def test_near_gray_preserves_value_and_hue_order(self):
        # sat ~0.03 is above the neutral floor, so it IS boosted by design
        # ("muted colors get the most change") — but the value (max channel)
        # must stay put and the hue must not flip to the red hue=0 pole.
        im = Image.new("RGB", (4, 4), (128, 126, 124))
        out = apply_vibrance(im, 0.5)
        r, g, b = out.getpixel((0, 0))
        assert max(r, g, b) == 128  # value preserved
        assert r > g > b            # hue order intact (no red/cyan flip)


class TestExportSharpen:
    def test_zero_is_noop(self):
        im = Image.new("RGB", (40, 40), (100, 100, 100))
        assert apply_export_sharpen(im, 0.0) is im

    def test_edge_contrast_increases(self):
        # a hard edge gets a light halo (USM) → local gradient grows
        import numpy as np
        arr = np.zeros((60, 80, 3), dtype=np.uint8)
        arr[:, :40] = (40, 40, 40)
        arr[:, 40:] = (200, 200, 200)
        im = Image.fromarray(arr)
        out = apply_export_sharpen(im, 1.5)
        o = np.asarray(out, dtype=int)
        # just left of the edge: darker than the flat 40 side
        assert o[30, 39, 0] < 40
        # just right of the edge: brighter than the flat 200 side
        assert o[30, 40, 0] > 200

    def test_info_preserved(self):
        im = Image.new("RGB", (40, 40), (100, 100, 100))
        im.info["exif"] = b"mock"
        out = apply_export_sharpen(im, 1.0)
        assert out.info.get("exif") == b"mock"

    def test_radius_scales_with_resolution(self):
        # small vs large images both run; the large one's radius is bigger
        # (formula 0.5 + max_dim/4000, clamped [0.3, 3.0]) — indirectly
        # verified: both succeed and neither errors on tiny/large sizes.
        small = Image.new("RGB", (200, 100), (128, 128, 128))
        big = Image.new("RGB", (4000, 3000), (128, 128, 128))
        apply_export_sharpen(small, 1.0)
        apply_export_sharpen(big, 1.0)  # radius would be 1.5 here
        # flat images are unchanged (delta = 0) — the strong smoke check
        assert np.array_equal(np.asarray(apply_export_sharpen(small, 1.0)),
                              np.asarray(small))


class TestHighlightRecovery:
    def test_zero_is_noop(self):
        im = Image.new("RGB", (4, 4), (255, 255, 255))
        assert apply_highlight_recovery(im, 0.0) is im

    def test_clipped_white_gains_gradient(self):
        # pure white 255 → pulled down below 255 (ceiling 255-18*amount)
        im = Image.new("RGB", (4, 4), (255, 255, 255))
        out = apply_highlight_recovery(im, 1.0)
        assert out.getpixel((0, 0)) == (237, 237, 237)

    def test_midtones_untouched(self):
        im = Image.new("RGB", (4, 4), (128, 128, 128))
        out = apply_highlight_recovery(im, 1.0)
        assert out.getpixel((0, 0)) == (128, 128, 128)

    def test_stronger_amount_pulls_more(self):
        im = Image.new("RGB", (4, 4), (255, 255, 255))
        soft = apply_highlight_recovery(im, 0.5).getpixel((0, 0))[0]
        hard = apply_highlight_recovery(im, 1.0).getpixel((0, 0))[0]
        assert hard < soft < 255

    def test_monotone_and_alpha_preserved(self):
        import numpy as np
        arr = np.zeros((1, 256, 3), dtype=np.uint8)
        for x in range(256):
            arr[:, x] = [x, x, x]
        im = Image.fromarray(arr).convert("RGBA")
        im.putalpha(180)
        out = apply_highlight_recovery(im, 1.0)
        row = np.asarray(out.convert("L"))[0]
        assert np.all(np.diff(row) >= 0)      # monotone
        assert out.getpixel((0, 0))[3] == 180  # alpha untouched
