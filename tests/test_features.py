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
