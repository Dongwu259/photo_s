"""Tests for Sprint-2 engine features: EXIF privacy, max-pixels, keep-mtime, SSIM."""

import os
import sys

# Ensure src package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

from photo_s.engine import process_image, ProcessOptions


def _process(src, out_dir, fmt="JPEG", suffix="_out", **kwargs):
    opts = ProcessOptions(output_dir=str(out_dir), suffix=suffix,
                          output_format=fmt, **kwargs)
    return process_image(str(src), opts)


def _make_image(path, size=(400, 300), color=(120, 200, 60)):
    Image.new("RGB", size, color).save(path, quality=95)
    return str(path)


def _make_jpeg_with_gps(path):
    """Create a JPEG with GPS + Make EXIF so we can verify GPS stripping."""
    import piexif

    exif_dict = {
        "0th": {piexif.ImageIFD.Make: b"TestCam", piexif.ImageIFD.Orientation: 1},
        "GPS": {
            piexif.GPSIFD.GPSLatitude: ((42, 1), (6, 1), (0, 1)),
            piexif.GPSIFD.GPSLatitudeRef: b"N",
        },
        "Exif": {},
        "1st": {},
        "thumbnail": None,
    }
    exif_bytes = piexif.dump(exif_dict)
    img = Image.new("RGB", (60, 40), (10, 90, 200))
    img.save(path, quality=92, exif=exif_bytes)
    return str(path)


def _load_exif(path):
    import piexif
    with open(path, "rb") as f:
        return piexif.load(f.read())


class TestStripGps:
    def test_strip_gps_removes_gps_keeps_make(self, tmp_path):
        src = _make_jpeg_with_gps(tmp_path / "gps.jpg")
        out_dir = tmp_path / "out"
        result = _process(src, out_dir, strip_gps=True, preserve_exif=True)
        assert result.success
        out = result.output_path
        # sanity: source has GPS
        assert _load_exif(src)["GPS"] != {}
        # GPS emptied (piexif always writes an empty GPS segment on dump)
        assert _load_exif(out)["GPS"] == {}
        # other EXIF preserved
        import piexif
        assert _load_exif(out)["0th"].get(piexif.ImageIFD.Make) == b"TestCam"

    def test_no_strip_gps_keeps_gps(self, tmp_path):
        src = _make_jpeg_with_gps(tmp_path / "gps2.jpg")
        result = _process(src, tmp_path / "out", preserve_exif=True)
        assert result.success
        assert _load_exif(result.output_path)["GPS"] != {}


class TestWebpExif:
    def test_exif_preserved_on_webp(self, tmp_path):
        src = _make_jpeg_with_gps(tmp_path / "src.jpg")
        result = _process(src, tmp_path / "out", fmt="WebP", preserve_exif=True)
        assert result.success
        import piexif
        d = _load_exif(result.output_path)
        assert d["0th"].get(piexif.ImageIFD.Make) == b"TestCam"


class TestOrientationNormalize:
    def test_auto_rotate_sets_orientation_one(self, tmp_path):
        import piexif

        # landscape JPEG carrying Orientation=6 (rotate 90 CW)
        exif_bytes = piexif.dump({
            "0th": {piexif.ImageIFD.Orientation: 6},
            "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None,
        })
        img = Image.new("RGB", (100, 50), (30, 30, 200))
        src = str(tmp_path / "rot.jpg")
        img.save(src, quality=95, exif=exif_bytes)

        result = _process(src, tmp_path / "out", auto_rotate=True)
        assert result.success
        # transposed: 100x50 → 50x100
        assert result.output_dims == (50, 100)
        d = _load_exif(result.output_path)
        # orientation normalized to 1 so no second rotation on view
        assert d["0th"].get(piexif.ImageIFD.Orientation) == 1

    def test_auto_rotate_normalizes_without_piexif(self, tmp_path, monkeypatch):
        # regression: without piexif the normalize step was skipped entirely,
        # leaving a stale Orientation that double-rotated downstream viewers
        import piexif
        import photo_s.engine as eng

        exif_bytes = piexif.dump({
            "0th": {piexif.ImageIFD.Orientation: 6},
            "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None,
        })
        src = str(tmp_path / "rot_nopx.jpg")
        Image.new("RGB", (100, 50), (30, 30, 200)).save(
            src, quality=95, exif=exif_bytes)

        monkeypatch.setattr(eng, "_HAS_PIEXIF", False)
        result = _process(src, tmp_path / "out", auto_rotate=True)
        assert result.success
        assert result.output_dims == (50, 100)  # pixels rotated
        # Orientation normalized via the PIL fallback (getexif + tobytes)
        with Image.open(result.output_path) as out:
            assert out.getexif().get(0x0112) == 1


class TestMaxPixels:
    def test_downscales_long_side(self, tmp_path):
        src = _make_image(tmp_path / "big.jpg", size=(4000, 2000))
        result = _process(src, tmp_path / "out", max_pixels=800)
        assert result.success
        assert result.output_dims == (800, 400)

    def test_smaller_image_not_upscaled(self, tmp_path):
        src = _make_image(tmp_path / "small.jpg", size=(300, 200))
        result = _process(src, tmp_path / "out", max_pixels=800)
        assert result.success
        assert result.output_dims == (300, 200)

    def test_combines_with_max_width(self, tmp_path):
        # 4000x2000: max_pixels=800 → 800x400; max_width=400 → 400x200 (smaller wins)
        src = _make_image(tmp_path / "big2.jpg", size=(4000, 2000))
        result = _process(src, tmp_path / "out", max_pixels=800, max_width=400)
        assert result.success
        assert result.output_dims == (400, 200)


class TestKeepMtime:
    def test_preserves_mtime(self, tmp_path):
        src = _make_image(tmp_path / "src.jpg")
        old = 1577851200  # 2020-01-01
        os.utime(src, (old, old))
        result = _process(src, tmp_path / "out", keep_mtime=True)
        assert result.success
        assert int(os.stat(result.output_path).st_mtime) == old

    def test_default_mtime_not_preserved(self, tmp_path):
        src = _make_image(tmp_path / "src2.jpg")
        old = 1577851200
        os.utime(src, (old, old))
        result = _process(src, tmp_path / "out")
        assert result.success
        assert int(os.stat(result.output_path).st_mtime) != old


class TestExifMetaDateExtraction:
    def test_datetimeoriginal_from_exif_sub_ifd(self, tmp_path):
        # regression: _extract_exif_metadata must read DateTimeOriginal from
        # the Exif sub-IFD (PIL getexif() only surfaces the 0th IFD)
        from photo_s.engine import _extract_exif_metadata
        import piexif
        exif_bytes = piexif.dump({
            "0th": {},
            "Exif": {piexif.ExifIFD.DateTimeOriginal: b"2024:07:30 14:30:00"},
            "GPS": {}, "1st": {}, "thumbnail": None,
        })
        p = tmp_path / "dated.jpg"
        Image.new("RGB", (20, 20), (1, 2, 3)).save(p, quality=92, exif=exif_bytes)
        with Image.open(p) as img:
            meta = _extract_exif_metadata(img, str(p))
        assert meta["date"] == "2024-07-30"
        assert meta["time"] == "14-30-00"
        assert meta["year"] == "2024" and meta["month"] == "07" and meta["day"] == "30"

    def test_iso_focal_from_exif_sub_ifd(self, tmp_path):
        # regression: ISO/FocalLength were read from the 0th IFD, but the
        # EXIF spec stores them in the Exif sub-IFD (like DateTimeOriginal)
        from photo_s.engine import _extract_exif_metadata
        import piexif
        exif_bytes = piexif.dump({
            "0th": {},
            "Exif": {piexif.ExifIFD.ISOSpeedRatings: 400,
                     piexif.ExifIFD.FocalLength: (50, 1)},
            "GPS": {}, "1st": {}, "thumbnail": None,
        })
        p = tmp_path / "exif.jpg"
        Image.new("RGB", (20, 20), (1, 2, 3)).save(p, quality=92, exif=exif_bytes)
        with Image.open(p) as img:
            meta = _extract_exif_metadata(img, str(p))
        assert meta["iso"] == "400"
        assert meta["focal"] == "50mm"

    def test_iso_focal_rename_variables(self, tmp_path):
        # end-to-end: {iso}/{focal} must be usable in rename patterns
        import piexif
        exif_bytes = piexif.dump({
            "0th": {},
            "Exif": {piexif.ExifIFD.ISOSpeedRatings: 200,
                     piexif.ExifIFD.FocalLength: (35, 1)},
            "GPS": {}, "1st": {}, "thumbnail": None,
        })
        src = str(tmp_path / "shot.jpg")
        Image.new("RGB", (20, 20)).save(src, quality=92, exif=exif_bytes)
        result = _process(src, tmp_path / "out",
                          rename_pattern="{iso}_{focal}_{original}")
        assert result.success
        assert os.path.basename(result.output_path) == "200_35mm_shot.jpg"


class TestPerFileOptions:
    def test_per_file_masks_injected(self, tmp_path):
        """GUI per-photo masks: hook replaces masks per path before output
        path reservation (fields consistent with preassigned paths)."""
        from photo_s.engine import batch_process, ProcessOptions
        from dataclasses import replace
        a = _make_image(tmp_path / "a.jpg")
        b = _make_image(tmp_path / "b.jpg")
        out = str(tmp_path / "out")
        base = ProcessOptions(output_dir=out, suffix="_m",
                              output_format="PNG", jobs=1)
        per_photo = {
            a: ("sky:linear:0,0,1,0", "sky:brightness=0.5"),
            b: ("fg:radial:0.5,0.5,0.4,0.4", "fg:brightness=0.5"),
        }

        def hook(path, opts):
            masks, adjust = per_photo[path]
            return replace(opts, masks=masks, mask_adjust=adjust)

        result = batch_process([a, b], base, per_file_options=hook)
        assert result.success_count == 2
        # masks actually applied: top half of a gets brightness -> lighter
        import numpy as np
        from PIL import Image
        out_a = np.asarray(Image.open(os.path.join(out, "a_m.png"))
                           .convert("RGB"))
        plain_a = np.asarray(Image.open(a).convert("RGB"))
        assert out_a.shape == plain_a.shape
        # injected mask (brightness=0.5) changed pixels vs no-mask baseline
        assert not np.allclose(out_a, plain_a)

    def test_hook_not_called_without_it(self, tmp_path):
        from photo_s.engine import batch_process, ProcessOptions
        a = _make_image(tmp_path / "a.jpg")
        result = batch_process([a], ProcessOptions(
            output_dir=str(tmp_path / "o"), suffix="_x", jobs=1))
        assert result.success_count == 1

    def test_no_masks_photo_does_not_inherit_previous(self, tmp_path):
        """照片 A 有蒙版、B 无条目 → B 必须用全局 options（防泄漏）。"""
        from photo_s.engine import batch_process, ProcessOptions
        from dataclasses import replace
        import numpy as np
        from PIL import Image
        a = _make_image(tmp_path / "a.jpg")
        b = _make_image(tmp_path / "b.jpg")
        out = str(tmp_path / "out")
        base = ProcessOptions(output_dir=out, suffix="_m",
                              output_format="PNG", jobs=1)

        def hook(path, opts):
            if path == a:
                return replace(opts, masks="sky:linear:0,0,1,0",
                               mask_adjust="sky:brightness=0.5")
            return opts  # B 无蒙版：原样返回

        result = batch_process([a, b], base, per_file_options=hook)
        assert result.success_count == 2
        # B 的输出必须等于无钩子批处理的结果（未被 A 的蒙版污染）
        out_plain = str(tmp_path / "out_plain")
        result_plain = batch_process(
            [b], ProcessOptions(output_dir=out_plain, suffix="_m",
                                output_format="PNG", jobs=1))
        assert result_plain.success_count == 1
        img_b = np.asarray(Image.open(os.path.join(out, "b_m.png"))
                           .convert("RGB"))
        img_b_plain = np.asarray(
            Image.open(os.path.join(out_plain, "b_m.png")).convert("RGB"))
        assert np.allclose(img_b, img_b_plain)


class TestResume:
    def test_skips_existing_outputs(self, tmp_path):
        from photo_s.engine import batch_process, ProcessOptions
        a = _make_image(tmp_path / "a.jpg")
        b = _make_image(tmp_path / "b.jpg")
        out = str(tmp_path / "out")
        options = ProcessOptions(output_dir=out, suffix="_out", jobs=1)

        first = batch_process([a, b], options)
        assert first.success_count == 2

        second = batch_process([a, b], ProcessOptions(
            output_dir=out, suffix="_out", jobs=1, resume=True))
        # both outputs already exist → nothing processed
        assert second.success_count == 0
        assert len(second.results) == 0

    def test_partial_resume(self, tmp_path):
        from photo_s.engine import batch_process, ProcessOptions
        a = _make_image(tmp_path / "a.jpg")
        b = _make_image(tmp_path / "b.jpg")
        out = str(tmp_path / "out")
        options = ProcessOptions(output_dir=out, suffix="_out", jobs=1)

        # pre-create only a's output
        from pathlib import Path
        Path(out).mkdir(exist_ok=True)
        Path(out, "a_out.jpg").write_bytes(b"fake")

        result = batch_process([a, b], ProcessOptions(
            output_dir=out, suffix="_out", jobs=1, resume=True))
        # only b processed
        assert result.success_count == 1
        assert os.path.basename(result.results[0].input_path) == "b.jpg"

    def test_folder_pattern_resume_warns_and_processes(self, tmp_path, capsys):
        # regression: the resume pre-pass called _get_output_path without
        # exif_meta, so with folder_pattern its prediction never matched the
        # real (subfolder) output — resume silently misfired and piled up
        # _1 copies. Now it warns and ignores resume, like --rename.
        from photo_s.engine import batch_process, ProcessOptions
        a = _make_image(tmp_path / "fp.jpg")
        out = str(tmp_path / "out")
        opts = dict(output_dir=out, suffix="_out", folder_pattern="date")
        first = batch_process([a], ProcessOptions(**opts))
        assert first.success_count == 1
        second = batch_process([a], ProcessOptions(resume=True, **opts))
        assert second.success_count == 1  # still processed (resume ignored)
        err = capsys.readouterr().err
        assert "resume" in err
        assert "--organize" in err


class TestEvaluate:
    def test_ssim_present_when_evaluate(self, tmp_path):
        src = _make_image(tmp_path / "flat.jpg")
        result = _process(src, tmp_path / "out", evaluate=True)
        assert result.success
        assert result.ssim is not None
        assert 0.0 <= result.ssim <= 1.0

    def test_ssim_none_when_not_evaluate(self, tmp_path):
        src = _make_image(tmp_path / "flat2.jpg")
        result = _process(src, tmp_path / "out")
        assert result.success
        assert result.ssim is None

    def test_to_dict_includes_ssim(self, tmp_path):
        src = _make_image(tmp_path / "flat3.jpg")
        result = _process(src, tmp_path / "out", evaluate=True)
        d = result.to_dict()
        assert "ssim" in d


class TestToneAndComposition:
    def test_rotate_90_swaps_dims(self, tmp_path):
        src = _make_image(tmp_path / "r.jpg", size=(100, 50))
        result = _process(src, tmp_path / "out", rotate_degrees=90)
        assert result.success
        assert result.output_dims == (50, 100)

    def test_pad_square(self, tmp_path):
        src = _make_image(tmp_path / "p.jpg", size=(400, 300))
        result = _process(src, tmp_path / "out", pad_ratio="1:1")
        assert result.success
        assert result.output_dims == (400, 400)

    def test_crop_absolute(self, tmp_path):
        src = _make_image(tmp_path / "c.jpg", size=(100, 80))
        result = _process(src, tmp_path / "out", crop="40x30+10+20")
        assert result.success
        assert result.output_dims == (40, 30)

    def test_crop_ratio(self, tmp_path):
        src = _make_image(tmp_path / "cr.jpg", size=(400, 300))
        result = _process(src, tmp_path / "out", crop_ratio="16:9")
        assert result.success
        assert result.output_dims == (400, 225)

    def test_crop_ratio_square(self, tmp_path):
        # 1:1 on a 4:3 image center-crops to a square (300x300)
        src = _make_image(tmp_path / "cr_sq.jpg", size=(400, 300))
        result = _process(src, tmp_path / "out", crop_ratio="1:1")
        assert result.success
        assert result.output_dims == (300, 300)

    def test_crop_ratio_with_crop(self, tmp_path):
        # explicit --crop then ratio: ratio applies to the already-cropped
        # pixels (200x200 stays 200x200 under 1:1) — no conflict
        src = _make_image(tmp_path / "cr_both.jpg", size=(400, 300))
        result = _process(src, tmp_path / "out",
                          crop="200x200+0+0", crop_ratio="1:1")
        assert result.success
        assert result.output_dims == (200, 200)

    def test_grayscale_output(self, tmp_path):
        src = _make_image(tmp_path / "g.jpg", color=(120, 200, 60))
        result = _process(src, tmp_path / "out", grayscale=True)
        assert result.success
        with Image.open(result.output_path) as out:
            r, g, b = out.convert("RGB").getpixel((10, 10))
            assert r == g == b

    def test_sepia_output(self, tmp_path):
        src = _make_image(tmp_path / "s.jpg", color=(120, 120, 120))
        result = _process(src, tmp_path / "out", sepia=True)
        assert result.success
        with Image.open(result.output_path) as out:
            r, g, b = out.convert("RGB").getpixel((10, 10))
            assert r > b  # sepia warms the image

    def test_flip_horizontal(self, tmp_path):
        src = _make_image(tmp_path / "f.jpg", size=(100, 50))
        result = _process(src, tmp_path / "out", flip="h")
        assert result.success
        assert result.output_dims == (100, 50)

    def test_brightness_batch_site_a(self, tmp_path):
        # Site A parity: fields must survive the per-image copy in batch mode
        from photo_s.engine import batch_process, ProcessOptions
        a = _make_image(tmp_path / "a.jpg", size=(100, 50))
        b = _make_image(tmp_path / "b.jpg", size=(80, 40))
        options = ProcessOptions(
            output_dir=str(tmp_path / "out"), jobs=2, overwrite=True,
            rotate_degrees=90, crop="20x20+5+5", brightness=1.5,
        )
        result = batch_process([a, b], options)
        assert result.success_count == 2
        for r in result.results:
            assert r.output_dims == (20, 20)  # crop applied after rotate


class TestDateShift:
    def _jpeg_with_date(self, tmp_path, name="dated.jpg"):
        import piexif
        exif_bytes = piexif.dump({
            "0th": {piexif.ImageIFD.Make: b"TestCam"},
            "Exif": {piexif.ExifIFD.DateTimeOriginal: b"2024:07:30 14:30:00"},
            "GPS": {}, "1st": {}, "thumbnail": None,
        })
        img = Image.new("RGB", (30, 20), (10, 90, 200))
        p = tmp_path / name
        img.save(p, quality=92, exif=exif_bytes)
        return str(p)

    def test_shift_plus_2h(self, tmp_path):
        src = self._jpeg_with_date(tmp_path)
        result = _process(src, tmp_path / "out", date_shift="+2h")
        assert result.success
        import piexif
        d = _load_exif(result.output_path)
        assert d["Exif"][piexif.ExifIFD.DateTimeOriginal] == b"2024:07:30 16:30:00"

    def test_shift_minus_5h30m(self, tmp_path):
        src = self._jpeg_with_date(tmp_path)
        result = _process(src, tmp_path / "out", date_shift="-5h30m")
        assert result.success
        import piexif
        d = _load_exif(result.output_path)
        assert d["Exif"][piexif.ExifIFD.DateTimeOriginal] == b"2024:07:30 09:00:00"


class TestRgbaJpegExif:
    def test_exif_survives_alpha_flatten(self, tmp_path):
        # regression: RGBA→JPEG used to drop EXIF because the flatten
        # background was created with an empty info dict
        import piexif
        exif_bytes = piexif.dump({
            "0th": {piexif.ImageIFD.Make: b"TestCam"},
            "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None,
        })
        src = str(tmp_path / "rgba.png")
        Image.new("RGBA", (30, 20), (10, 90, 200, 128)).save(
            src, exif=exif_bytes)

        result = _process(src, tmp_path / "out", fmt="JPEG")
        assert result.success
        d = _load_exif(result.output_path)
        assert d["0th"].get(piexif.ImageIFD.Make) == b"TestCam"


class TestScrub:
    def test_scrub_removes_all_metadata(self, tmp_path):
        import piexif
        exif_bytes = piexif.dump({
            "0th": {piexif.ImageIFD.Make: b"TestCam"},
            "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None,
        })
        img = Image.new("RGB", (30, 20), (10, 90, 200))
        src = str(tmp_path / "scrub.jpg")
        img.save(src, quality=92, exif=exif_bytes, icc_profile=b"fake-icc")

        result = _process(src, tmp_path / "out", scrub=True, preserve_exif=True)
        assert result.success
        with Image.open(result.output_path) as out:
            assert "exif" not in out.info
            assert "icc_profile" not in out.info
        d = _load_exif(result.output_path)
        assert not d["0th"].get(piexif.ImageIFD.Make)


class TestSyncDate:
    def _jpeg_with_date(self, tmp_path, ts_str=b"2020:01:02 03:04:05"):
        import piexif
        exif_bytes = piexif.dump({
            "0th": {},
            "Exif": {piexif.ExifIFD.DateTimeOriginal: ts_str},
            "GPS": {}, "1st": {}, "thumbnail": None,
        })
        img = Image.new("RGB", (30, 20), (10, 90, 200))
        p = tmp_path / "dated.jpg"
        img.save(p, quality=92, exif=exif_bytes)
        return str(p)

    def test_mtime_from_exif(self, tmp_path):
        import datetime
        src = self._jpeg_with_date(tmp_path)
        result = _process(src, tmp_path / "out", sync_date=True)
        assert result.success
        expect = datetime.datetime(2020, 1, 2, 3, 4, 5).timestamp()
        assert abs(os.stat(result.output_path).st_mtime - expect) < 2

    def test_sync_date_wins_over_keep_mtime(self, tmp_path):
        src = self._jpeg_with_date(tmp_path)
        old = 1577851200
        os.utime(src, (old, old))
        result = _process(src, tmp_path / "out", sync_date=True, keep_mtime=True)
        assert result.success
        import datetime
        expect = datetime.datetime(2020, 1, 2, 3, 4, 5).timestamp()
        assert abs(os.stat(result.output_path).st_mtime - expect) < 2

    def test_no_exif_falls_back_to_keep_mtime(self, tmp_path):
        src = _make_image(tmp_path / "plain.jpg")
        old = 1577851200
        os.utime(src, (old, old))
        result = _process(src, tmp_path / "out", sync_date=True, keep_mtime=True)
        assert result.success
        assert int(os.stat(result.output_path).st_mtime) == old


class TestBlurScore:
    def test_flat_image_scores_zero(self, tmp_path):
        src = _make_image(tmp_path / "flat.jpg")
        result = _process(src, tmp_path / "out", blur_score=True)
        assert result.success
        assert result.blur_score == 0.0

    def test_score_in_to_dict(self, tmp_path):
        src = _make_image(tmp_path / "flat2.jpg")
        result = _process(src, tmp_path / "out", blur_score=True)
        assert "blur_score" in result.to_dict()

    def test_none_when_flag_off(self, tmp_path):
        src = _make_image(tmp_path / "flat3.jpg")
        result = _process(src, tmp_path / "out")
        assert result.blur_score is None


class TestColorManagement:
    def test_srgb_output_has_profile(self, tmp_path):
        src = _make_image(tmp_path / "c.jpg")
        result = _process(src, tmp_path / "out", srgb=True)
        assert result.success
        with Image.open(result.output_path) as out:
            assert out.info.get("icc_profile")

    def test_flatten_cmyk_input(self, tmp_path):
        src = str(tmp_path / "cmyk.tiff")
        Image.new("CMYK", (30, 20), (0, 0, 0, 0)).save(src)
        result = _process(src, tmp_path / "out", flatten_cmyk=True)
        assert result.success


class TestLowTempWhiteBalance:
    """Regression: wb_temp <= ~1900K failed every file (float division by zero)."""

    def test_low_kelvin_batch_succeeds(self, tmp_path):
        src = _make_image(tmp_path / "candle.jpg")
        result = _process(src, tmp_path / "out", wb_temp=1800)
        assert result.success
        assert os.path.exists(result.output_path)

    def test_low_kelvin_output_warmer_than_neutral(self, tmp_path):
        src = _make_image(tmp_path / "candle2.jpg", color=(128, 128, 128))
        result = _process(src, tmp_path / "out", wb_temp=1800)
        assert result.success
        with Image.open(result.output_path) as out:
            r, g, b = out.convert("RGB").getpixel((0, 0))
        assert b >= r  # 暖光校正 → 提蓝


class TestBatchSeqCounter:
    """Regression: process_image's replace() dropped the dynamically attached
    _seq_counter — every {seq} rendered 000 and overwrite=True batches
    clobbered each other."""

    def test_seq_increments_in_batch(self, tmp_path):
        from photo_s.engine import batch_process
        paths = [_make_image(tmp_path / f"IMG_{i}.jpg") for i in range(3)]
        out = tmp_path / "out"
        result = batch_process(paths, ProcessOptions(
            output_dir=str(out), rename_pattern="photo_{seq}",
            overwrite=True, jobs=2))
        assert result.success_count == 3
        names = sorted(p.name for p in out.iterdir())
        assert names == ["photo_001.jpg", "photo_002.jpg", "photo_003.jpg"]


class TestParallelUniqueOutputs:
    """Regression: same-name inputs from different source dirs raced the
    exists() dedup in _get_output_path and overwrote each other's output
    under parallel workers."""

    def _two_dirs_same_name(self, tmp_path):
        d1 = tmp_path / "d1"
        d2 = tmp_path / "d2"
        d1.mkdir()
        d2.mkdir()
        a = str(d1 / "same.jpg")
        b = str(d2 / "same.jpg")
        Image.new("RGB", (40, 30), (255, 0, 0)).save(a, quality=95)
        Image.new("RGB", (40, 30), (0, 0, 255)).save(b, quality=95)
        return a, b

    def test_unique_outputs_sequential_and_parallel(self, tmp_path):
        from photo_s.engine import batch_process
        a, b = self._two_dirs_same_name(tmp_path)
        for jobs in (1, 2):
            out = tmp_path / f"out{jobs}"
            result = batch_process([a, b], ProcessOptions(
                output_dir=str(out), suffix="_c", jobs=jobs))
            assert result.success_count == 2
            outputs = sorted(r.output_path for r in result.results)
            assert [os.path.basename(p) for p in outputs] == \
                ["same_c.jpg", "same_c_1.jpg"]
            # distinct content survived (no clobber)
            colors = set()
            for p in outputs:
                with Image.open(p) as im:
                    colors.add(im.convert("RGB").getpixel((5, 5)))
            assert len(colors) == 2

    def test_resume_consistent_with_preassigned_paths(self, tmp_path):
        from photo_s.engine import batch_process
        a, b = self._two_dirs_same_name(tmp_path)
        out = str(tmp_path / "out")
        first = batch_process([a, b], ProcessOptions(
            output_dir=out, suffix="_c"))
        assert first.success_count == 2
        second = batch_process([a, b], ProcessOptions(
            output_dir=out, suffix="_c", resume=True))
        # both outputs already exist → nothing reprocessed, no _2 copies
        assert second.success_count == 0
        assert len(second.results) == 0
        assert sorted(os.listdir(out)) == ["same_c.jpg", "same_c_1.jpg"]


class TestUserCommentHeader:
    """Regression: the UserComment charset-header check ran after
    decode/strip and could never match, so repeated apply_exif_tags calls
    piled another "ASCII\\0\\0\\0" prefix onto the comment each time."""

    def test_known_charset_headers_stripped(self):
        import piexif
        from photo_s.engine import _usercomment_text_from_dict
        for header in (b"ASCII\x00\x00\x00", b"UNICODE\x00",
                       b"JIS\x00\x00\x00\x00\x00", b"\x00" * 8):
            d = {"Exif": {piexif.ExifIFD.UserComment: header + b"hello"}}
            assert _usercomment_text_from_dict(d) == "hello"

    def test_repeated_writes_do_not_accumulate_header(self, tmp_path):
        import piexif
        from photo_s.engine import apply_exif_tags, _exif_bytes
        src = _make_jpeg_with_gps(tmp_path / "uc.jpg")
        assert apply_exif_tags(src, {"rating": 3})
        assert apply_exif_tags(src, {"rating": 4})
        raw = _exif_bytes(
            piexif.load(src)["Exif"][piexif.ExifIFD.UserComment])
        assert raw.count(b"ASCII\x00\x00\x00") == 1
        assert raw.endswith(b"rating=4")


class TestMissingInput:
    """Regression: os.path.getsize/os.stat ran outside the try, so a source
    deleted after the batch scan killed the whole sequential batch instead
    of failing just that file."""

    def test_ghost_input_is_per_file_error(self, tmp_path):
        from photo_s.engine import batch_process
        a = _make_image(tmp_path / "a.jpg")
        ghost = str(tmp_path / "ghost.jpg")  # never created
        result = batch_process([ghost, a], ProcessOptions(
            output_dir=str(tmp_path / "out"), jobs=1))
        assert result.fail_count == 1
        assert result.success_count == 1
        ghost_result = result.results[0]
        assert not ghost_result.success
        assert ghost_result.input_size == 0
        assert result.results[1].success


class TestTempFileCleanup:
    """Regression: sips-fallback temp files (_temp_png/_temp_raw_tiff) were
    looked up on the FINAL image object — any pipeline transform swaps in a
    fresh Image without the attribute, and mid-pipeline exceptions skipped
    the cleanup entirely."""

    def _parked_get_image(self, monkeypatch, parked):
        import photo_s.engine as eng
        real_get_image = eng._get_image

        def fake_get_image(path, options=None):
            img = real_get_image(path, options)
            img.load()  # detach pixels from the source file
            img._temp_png = str(parked)  # stand in for the sips temp file
            return img

        monkeypatch.setattr(eng, "_get_image", fake_get_image)

    def test_temp_deleted_despite_transform(self, tmp_path, monkeypatch):
        src = _make_image(tmp_path / "t.jpg", size=(100, 50))
        parked = tmp_path / "sips_tmp.png"
        Image.new("RGB", (4, 4)).save(parked)
        self._parked_get_image(monkeypatch, parked)
        # rotate forces a fresh Image — the old cleanup lost the attribute
        result = _process(src, tmp_path / "out", rotate_degrees=90)
        assert result.success
        assert not parked.exists()

    def test_temp_deleted_on_pipeline_error(self, tmp_path, monkeypatch):
        import photo_s.engine as eng
        src = _make_image(tmp_path / "t2.jpg")
        parked = tmp_path / "sips_tmp2.png"
        Image.new("RGB", (4, 4)).save(parked)
        self._parked_get_image(monkeypatch, parked)

        def boom(*args, **kwargs):
            raise RuntimeError("simulated save failure")

        monkeypatch.setattr(eng, "_save_image", boom)
        result = _process(src, tmp_path / "out")
        assert not result.success
        assert not parked.exists()


class TestRenameEmptyStem:
    """Regression: an all-empty pattern render (e.g. "{date}" on an
    EXIF-less photo) produced a hidden ".jpg" output file."""

    def test_empty_render_falls_back_to_prefix_suffix(self, tmp_path):
        src = _make_image(tmp_path / "plain.jpg")  # no EXIF
        result = _process(src, tmp_path / "out", rename_pattern="{date}")
        assert result.success
        name = os.path.basename(result.output_path)
        assert name == "plain_out.jpg"  # helper default suffix "_out"
        assert not name.startswith(".")


class TestJpegSubsampling:
    """JPEG chroma subsampling is configurable via jpeg_subsampling
    (444 = full color detail, 422/420 progressively smaller)."""

    @staticmethod
    def _sampling_factors(path):
        """Parse JPEG SOF0/SOF2 frame header → [(h, v), ...] per component.

        4:4:4 → all (1,1); 4:2:2 → [(2,1),(1,1),(1,1)]; 4:2:0 → [(2,2),(1,1),(1,1)].
        """
        with open(path, "rb") as f:
            data = f.read()
        i = 2
        sof = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
               0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
        while i < len(data) - 1:
            if data[i] != 0xFF:
                i += 1
                continue
            if data[i + 1] in sof:
                n_comp = data[i + 9]
                factors, pos = [], i + 10
                for _ in range(n_comp):
                    sf = data[pos + 1]
                    factors.append((sf >> 4, sf & 0x0F))
                    pos += 3
                return factors
            i += 2
        return None

    def test_default_is_420(self, tmp_path):
        src = _make_image(tmp_path / "src.jpg")
        result = _process(src, tmp_path / "out", quality=90)
        assert result.success
        factors = self._sampling_factors(result.output_path)
        assert factors is not None
        assert factors[0] == (2, 2)      # luma 2x2
        assert factors[1:] == [(1, 1), (1, 1)]  # chroma 1x1

    def test_444_full_sampling(self, tmp_path):
        src = _make_image(tmp_path / "src.jpg")
        result = _process(src, tmp_path / "out", quality=90,
                          jpeg_subsampling="444")
        assert result.success
        assert self._sampling_factors(result.output_path) == [
            (1, 1), (1, 1), (1, 1)]

    def test_422(self, tmp_path):
        src = _make_image(tmp_path / "src.jpg")
        result = _process(src, tmp_path / "out", quality=90,
                          jpeg_subsampling="422")
        assert result.success
        factors = self._sampling_factors(result.output_path)
        assert factors[0] == (2, 1)

    def test_invalid_value_falls_back_to_420(self, tmp_path):
        src = _make_image(tmp_path / "src.jpg")
        result = _process(src, tmp_path / "out", quality=90,
                          jpeg_subsampling="bogus")
        assert result.success
        assert self._sampling_factors(result.output_path)[0] == (2, 2)


class TestRawDemosaic:
    """--raw-demosaic maps to rawpy.DemosaicAlgorithm; "auto" omits it."""

    @staticmethod
    def _fake_rawpy(monkeypatch, captured):
        import types
        import numpy as np
        fake = types.ModuleType("rawpy")

        class FakeRaw:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def postprocess(self, **kw):
                captured.update(kw)
                return np.zeros((4, 6, 3), dtype=np.uint8)

        fake.imread = lambda p: FakeRaw()
        fake.ColorSpace = types.SimpleNamespace(sRGB="sRGB")

        class _Enum(dict):  # subscriptable name → value, like a real Enum
            def __getattr__(self, k):
                return self[k]

        fake.DemosaicAlgorithm = _Enum(AMAZE="AMAZE", AHD="AHD", VNG="VNG",
                                       PPG="PPG", DCB="DCB", DHT="DHT")
        monkeypatch.setitem(sys.modules, "rawpy", fake)

    def test_amaze_passes_demosaic_algorithm(self, tmp_path, monkeypatch):
        from photo_s.engine import _load_raw_via_rawpy, ProcessOptions
        captured = {}
        self._fake_rawpy(monkeypatch, captured)
        img = _load_raw_via_rawpy("fake.dng", ProcessOptions(raw_demosaic="amaze"))
        assert img.size == (6, 4)
        assert captured["demosaic_algorithm"] == "AMAZE"

    def test_auto_omits_demosaic(self, tmp_path, monkeypatch):
        from photo_s.engine import _load_raw_via_rawpy, ProcessOptions
        captured = {}
        self._fake_rawpy(monkeypatch, captured)
        _load_raw_via_rawpy("fake.dng", ProcessOptions(raw_demosaic="auto"))
        assert "demosaic_algorithm" not in captured

    def test_invalid_raises_value_error(self, tmp_path, monkeypatch):
        import pytest
        from photo_s.engine import _load_raw_via_rawpy, ProcessOptions
        captured = {}
        self._fake_rawpy(monkeypatch, captured)
        with pytest.raises(ValueError):
            _load_raw_via_rawpy("fake.dng", ProcessOptions(raw_demosaic="bogus"))


class TestMetadataSurvivesTone:
    """Regression: ImageEnhance.Brightness/Contrast return fresh images with
    an empty .info — any brightness/contrast pass used to silently drop
    EXIF + ICC + DPI. apply_tone_adjustments now restores img.info."""

    def test_exif_and_icc_survive_brightness(self, tmp_path):
        import piexif
        from photo_s.engine import process_image, ProcessOptions
        src = _make_jpeg_with_gps(tmp_path / "src.jpg")
        result = _process(src, tmp_path / "out", brightness=1.3)
        assert result.success
        d = _load_exif(result.output_path)
        assert d["0th"].get(piexif.ImageIFD.Make) == b"TestCam"

    def test_exif_and_icc_survive_contrast(self, tmp_path):
        import piexif
        from photo_s.engine import process_image, ProcessOptions
        src = _make_jpeg_with_gps(tmp_path / "src.jpg")
        result = _process(src, tmp_path / "out", contrast=0.8)
        assert result.success
        assert _load_exif(result.output_path)["0th"].get(
            piexif.ImageIFD.Make) == b"TestCam"

    def test_icc_survives_brightness(self, tmp_path):
        from PIL import Image, ImageCms
        import piexif
        from photo_s.engine import process_image, ProcessOptions
        src = tmp_path / "src.jpg"
        img = Image.new("RGB", (40, 30), (10, 90, 200))
        exif = piexif.dump({"0th": {}, "Exif": {}, "1st": {},
                            "thumbnail": None, "GPS": {}})
        icc = ImageCms.ImageCmsProfile(
            ImageCms.createProfile("sRGB")).tobytes()
        img.save(src, exif=exif, icc_profile=icc)
        result = _process(str(src), tmp_path / "out", brightness=1.3)
        assert result.success
        assert Image.open(result.output_path).info.get("icc_profile")


class TestRawDecodeIcc:
    """RAW decode tags output with sRGB ICC (the decoded pixels are sRGB)."""

    @staticmethod
    def _fake_rawpy(monkeypatch):
        import types
        import numpy as np
        fake = types.ModuleType("rawpy")

        class FakeRaw:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def postprocess(self, **kw):
                return np.zeros((4, 6, 3), dtype=np.uint8)

        fake.imread = lambda p: FakeRaw()
        fake.ColorSpace = types.SimpleNamespace(sRGB="sRGB")
        monkeypatch.setitem(sys.modules, "rawpy", fake)

    def test_decode_attaches_srgb_icc(self, tmp_path, monkeypatch):
        from photo_s.engine import _load_raw_via_rawpy, ProcessOptions
        self._fake_rawpy(monkeypatch)
        img = _load_raw_via_rawpy("fake.dng", ProcessOptions())
        assert img.info.get("icc_profile")

    def test_scrub_skips_icc(self, tmp_path, monkeypatch):
        from photo_s.engine import _load_raw_via_rawpy, ProcessOptions
        self._fake_rawpy(monkeypatch)
        img = _load_raw_via_rawpy("fake.dng", ProcessOptions(scrub=True))
        assert not img.info.get("icc_profile")


class TestExportSharpenPipeline:
    """--export-sharpen sharpens the final (post-resize) pixels."""

    def test_edges_are_sharper_after_resize(self, tmp_path):
        import numpy as np
        arr = np.zeros((600, 800, 3), dtype=np.uint8)
        arr[:, :400] = (40, 40, 40)
        arr[:, 400:] = (200, 200, 200)
        src = tmp_path / "edges.jpg"
        Image.fromarray(arr).save(src, quality=95)
        base = _process(str(src), tmp_path / "base")
        sharp = _process(str(src), tmp_path / "sharp", export_sharpen=1.5)
        assert base.success and sharp.success
        b = np.asarray(Image.open(base.output_path).convert("L"), dtype=int)
        s = np.asarray(Image.open(sharp.output_path).convert("L"), dtype=int)
        # edge halo appears in the sharpened output, not the baseline
        assert s[300, 399] < b[300, 399]     # darker just-left of edge
        assert s[300, 400] > b[300, 400]     # brighter just-right of edge
