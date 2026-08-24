"""Unit tests for engine utility functions."""

import sys
import os

# Ensure src package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from photo_s.engine import (
    _format_from_path,
    _has_path_traversal,
    _render_rename_pattern,
    _resolve_folder_pattern,
    format_size,
    parse_date_shift,
)


class TestFormatFromPath:
    """Tests for _format_from_path() — infers format from file extension."""

    def test_jpg(self):
        assert _format_from_path("photo.jpg") == "JPEG"

    def test_jpeg(self):
        assert _format_from_path("photo.jpeg") == "JPEG"

    def test_png(self):
        assert _format_from_path("photo.png") == "PNG"

    def test_webp(self):
        assert _format_from_path("photo.webp") == "WebP"

    def test_tiff(self):
        assert _format_from_path("photo.tiff") == "TIFF"

    def test_raw_cr2(self):
        assert _format_from_path("photo.CR2") == "RAW"

    def test_raw_nef(self):
        assert _format_from_path("photo.NEF") == "RAW"

    def test_heic(self):
        assert _format_from_path("photo.HEIC") == "HEIC"

    def test_unknown(self):
        assert _format_from_path("photo.xyz") == "JPEG"


class TestRenderRenamePattern:
    """Tests for _render_rename_pattern() — template variable substitution."""

    def _meta(self, **kwargs):
        defaults = {
            "date": "", "time": "", "camera": "", "make": "",
            "original": "DSC0001", "iso": "", "focal": "",
            "year": "", "month": "", "day": "",
        }
        defaults.update(kwargs)
        return defaults

    def test_date(self):
        meta = self._meta(date="2024-07-30")
        assert _render_rename_pattern("{date}", meta) == "2024-07-30"

    def test_camera(self):
        meta = self._meta(camera="ILCE-7M4")
        assert _render_rename_pattern("{camera}", meta) == "ILCE-7M4"

    def test_seq(self):
        meta = self._meta()
        assert _render_rename_pattern("{seq}", meta, 1) == "001"
        assert _render_rename_pattern("{seq}", meta, 42) == "042"

    def test_combination(self):
        meta = self._meta(date="2024-07-30", camera="ILCE-7M4")
        result = _render_rename_pattern("{date}_{camera}_{seq}", meta, 5)
        assert result == "2024-07-30_ILCE-7M4_005"

    def test_year_month_day(self):
        meta = self._meta(year="2024", month="08", day="15")
        result = _render_rename_pattern("{year}/{month}/{day}", meta)
        assert result == "2024/08/15"

    def test_unknown_variable_preserved(self):
        meta = self._meta()
        result = _render_rename_pattern("{foo}_{bar}", meta)
        assert result == "{foo}_{bar}"

    def test_empty_template(self):
        meta = self._meta(date="2024-07-30")
        assert _render_rename_pattern("", meta) == ""

    def test_original(self):
        meta = self._meta(original="IMG_0001")
        assert _render_rename_pattern("{original}", meta) == "IMG_0001"

    def test_iso_and_focal(self):
        meta = self._meta(iso="400", focal="50mm")
        result = _render_rename_pattern("ISO{iso}_{focal}", meta)
        assert result == "ISO400_50mm"


class TestHasPathTraversal:
    """Defense-in-depth guard: rendered rename stems must stay in-dir."""

    def test_plain_ok(self):
        assert _has_path_traversal("2024-07-30_ILCE-7M4") is False

    def test_dot_segments(self):
        assert _has_path_traversal("..") is True
        assert _has_path_traversal(".") is True

    def test_separators(self):
        assert _has_path_traversal("a/b") is True
        assert _has_path_traversal("..\\..\\evil") is True

    def test_windows_drive_relative(self):
        # "C:evil" makes ntpath.join drop the base directory on Windows
        assert _has_path_traversal("C:evil") is True

    def test_empty_ok(self):
        assert _has_path_traversal("") is False


class TestExifSanitize:
    """EXIF-derived rename values must be sanitized at extraction."""

    def _extract(self, tmp_path, make=b"", dt=b""):
        import piexif
        from PIL import Image
        from photo_s.engine import _extract_exif_metadata

        exif_dict = {
            "0th": {piexif.ImageIFD.Make: make},
            "Exif": {},
            "GPS": {}, "1st": {}, "thumbnail": None,
        }
        if dt:
            exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = dt
        path = tmp_path / "x.jpg"
        Image.new("RGB", (8, 8)).save(path, quality=90,
                                      exif=piexif.dump(exif_dict))
        with Image.open(path) as img:
            return _extract_exif_metadata(img, str(path))

    def test_normal_make_kept(self, tmp_path):
        meta = self._extract(tmp_path, make=b"TestCam")
        assert meta["make"] == "TestCam"

    def test_make_traversal_sanitized(self, tmp_path):
        # "../../evil" → every unsafe char becomes "_" → strip "_" → "evil"
        meta = self._extract(tmp_path, make=b"../../evil")
        assert meta["make"] == "evil"
        assert _has_path_traversal(meta["make"]) is False

    def test_make_abs_sanitized(self, tmp_path):
        meta = self._extract(tmp_path, make=b"/tmp/evil")
        assert "/" not in meta["make"]

    def test_date_traversal_rejected(self, tmp_path):
        # Crafted DateTimeOriginal that would previously yield year=".."
        meta = self._extract(tmp_path, dt=b"../../../etc:08:15 00:00:00")
        assert meta["year"] == ""
        assert meta["date"] == ""
        assert meta["month"] == ""

    def test_date_normal_kept(self, tmp_path):
        meta = self._extract(tmp_path, dt=b"2024:07:30 14:30:00")
        assert meta["date"] == "2024-07-30"
        assert meta["year"] == "2024"


class TestResolveFolderPattern:
    """Tests for _resolve_folder_pattern() — shorthand preset → template."""

    def test_date(self):
        assert _resolve_folder_pattern("date") == "{year}/{month}"

    def test_camera(self):
        assert _resolve_folder_pattern("camera") == "{camera}"

    def test_date_camera(self):
        assert _resolve_folder_pattern("date-camera") == "{year}/{month}/{camera}"

    def test_empty_string(self):
        assert _resolve_folder_pattern("") == ""

    def test_custom_passthrough(self):
        assert _resolve_folder_pattern("{year}/{camera}") == "{year}/{camera}"


class TestFormatSize:
    """Tests for format_size() — byte count → human-readable."""

    def test_zero(self):
        assert format_size(0) == "0.0 B"

    def test_bytes(self):
        assert format_size(500).startswith("500")

    def test_kb(self):
        result = format_size(2048)
        assert "KB" in result

    def test_mb(self):
        result = format_size(5 * 1024**2)
        assert "MB" in result

    def test_gb(self):
        result = format_size(3 * 1024**3)
        assert "GB" in result


class TestParseDateShift:
    """Tests for parse_date_shift() — compound offset parsing."""

    def test_negative_hours_minutes(self):
        assert parse_date_shift("-5h30m").total_seconds() == -19800

    def test_positive_hours(self):
        assert parse_date_shift("+2h").total_seconds() == 7200

    def test_days(self):
        assert parse_date_shift("1d").total_seconds() == 86400

    def test_seconds(self):
        assert parse_date_shift("30s").total_seconds() == 30

    def test_fractional_hours(self):
        assert parse_date_shift("1.5h").total_seconds() == 5400

    def test_compound_positive(self):
        assert parse_date_shift("+1h30m").total_seconds() == 5400

    def test_sign_only_first_component(self):
        # "-" applies to the WHOLE spec
        assert parse_date_shift("-1h30m").total_seconds() == -5400

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_date_shift("abc")

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            parse_date_shift("")


class TestBatchProcessCancel:
    """Tests for batch_process() cancel_checker support."""

    def _make_images(self, tmp_path, count=3):
        from PIL import Image
        paths = []
        for i in range(count):
            p = tmp_path / f"img_{i}.png"
            Image.new("RGB", (32, 32), (i * 60, 100, 200)).save(p)
            paths.append(str(p))
        return paths

    def test_cancel_sequential_skips_remaining(self, tmp_path):
        from photo_s.engine import batch_process, ProcessOptions
        paths = self._make_images(tmp_path)
        options = ProcessOptions(
            output_dir=str(tmp_path / "out"), jobs=1, overwrite=True,
        )

        calls = {"n": 0}

        def cancel_after_first():
            # Called by the loop guard and by process_one for each image;
            # allow both checks for image 0, then cancel
            calls["n"] += 1
            return calls["n"] > 2

        result = batch_process(paths, options, cancel_checker=cancel_after_first)
        # First image processed, rest omitted from results
        assert result.success_count == 1
        assert len(result.results) == 1
        assert result.fail_count == 0

    def test_cancel_parallel_marks_cancelled(self, tmp_path):
        from photo_s.engine import batch_process, ProcessOptions
        paths = self._make_images(tmp_path, count=5)
        options = ProcessOptions(
            output_dir=str(tmp_path / "out"), jobs=2, overwrite=True,
        )

        result = batch_process(paths, options, cancel_checker=lambda: True)
        assert result.success_count == 0
        assert result.fail_count == 5
        assert all("Cancelled" in r.error for r in result.results)

    def test_no_cancel_checker_processes_all(self, tmp_path):
        from photo_s.engine import batch_process, ProcessOptions
        paths = self._make_images(tmp_path)
        options = ProcessOptions(
            output_dir=str(tmp_path / "out"), jobs=2, overwrite=True,
        )
        result = batch_process(paths, options)
        assert result.success_count == 3
        assert result.fail_count == 0


class TestAutoJobs:
    """Smart default worker count: capped CPU count, never crashes."""

    def test_bounds(self):
        from photo_s.engine import auto_jobs
        assert 1 <= auto_jobs() <= 8

    def test_none_cpu_count_falls_back(self, monkeypatch):
        from photo_s.engine import auto_jobs
        monkeypatch.setattr("os.cpu_count", lambda: None)
        assert auto_jobs() == 2  # unknown → assume 2 cores

    def test_zero_cpu_count_falls_back(self, monkeypatch):
        from photo_s.engine import auto_jobs
        monkeypatch.setattr("os.cpu_count", lambda: 0)
        assert auto_jobs() == 2  # unknown → assume 2 cores

    def test_capped_at_eight(self, monkeypatch):
        from photo_s.engine import auto_jobs
        monkeypatch.setattr("os.cpu_count", lambda: 128)
        assert auto_jobs() == 8


class TestOutputFormatCanonical:
    """Library path: output_format is case-insensitive, bad formats raise."""

    def _img(self, tmp_path):
        from PIL import Image
        p = tmp_path / "a.png"
        Image.new("RGB", (8, 8), (100, 100, 100)).save(p)
        return str(p)

    def test_lowercase_format_ok(self, tmp_path):
        from photo_s.engine import ProcessOptions, batch_process
        src = self._img(tmp_path)
        out = tmp_path / "out"
        res = batch_process([src], ProcessOptions(
            output_dir=str(out), output_format="jpeg"))
        assert res.success_count == 1
        assert res.results[0].output_path.endswith(".jpg")

    def test_mixed_case_format_ok(self, tmp_path):
        from photo_s.engine import ProcessOptions, batch_process
        src = self._img(tmp_path)
        out = tmp_path / "out"
        res = batch_process([src], ProcessOptions(
            output_dir=str(out), output_format="weBp"))
        assert res.success_count == 1
        assert res.results[0].output_path.endswith(".webp")

    def test_unsupported_format_raises(self, tmp_path):
        from photo_s.engine import ProcessOptions, batch_process
        src = self._img(tmp_path)
        with pytest.raises(ValueError, match="unsupported output format"):
            batch_process([src], ProcessOptions(
                output_dir=str(tmp_path / "out"), output_format="bogus"))


class TestResumeCanonicalFormat:
    """Regression: resume pre-pass + lowercase format crashed the whole batch."""

    def test_resume_lowercase_ok(self, tmp_path):
        from PIL import Image
        from photo_s.engine import ProcessOptions, batch_process
        p = tmp_path / "a.png"
        Image.new("RGB", (8, 8), (100, 100, 100)).save(p)
        res = batch_process([str(p)], ProcessOptions(
            output_dir=str(tmp_path / "out"), output_format="jpeg",
            resume=True))
        assert res.success_count == 1


class TestSizedOutputReservation:
    """Regression: multi-size (output_sizes) derivatives were NOT part of
    batch_process's reserved-path pre-allocation, so they could collide with
    another input's output (parallel same-stem race, or a sized name matching
    a later input's main output name) and silently overwrite each other."""

    def _img(self, path, color, size=(64, 64)):
        from PIL import Image
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", size, color).save(path)
        return str(path)

    def _colors_of(self, paths):
        from PIL import Image
        return {Image.open(p).convert("RGB").getpixel((0, 0)) for p in paths}

    def test_sized_name_matching_other_main_not_overwritten(self, tmp_path):
        # Deterministic (jobs=1): a/photo.png derives sized "photo_thumb.png";
        # b/photo_thumb.png's main output derives the very same name. Without
        # reservation the second save overwrites the sized derivative.
        from photo_s.engine import ProcessOptions, batch_process
        red = (200, 30, 30)
        blue = (30, 30, 200)
        src_a = self._img(tmp_path / "a" / "photo.png", red)
        src_b = self._img(tmp_path / "b" / "photo_thumb.png", blue)
        out = tmp_path / "out"
        res = batch_process([src_a, src_b], ProcessOptions(
            output_dir=str(out), output_format="PNG", suffix="",
            output_sizes=[("thumb", 8, 8)]))
        assert res.success_count == 2
        outputs = sorted(p.name for p in out.iterdir())
        assert outputs == ["photo.png", "photo_thumb.png",
                           "photo_thumb_1.png", "photo_thumb_thumb.png"]
        # sized derivative keeps source a's color, renamed main keeps b's
        assert self._colors_of([out / "photo_thumb.png"]) == {red}
        assert self._colors_of([out / "photo_thumb_1.png"]) == {blue}

    def test_parallel_same_stem_sized_outputs_all_exist(self, tmp_path):
        # Parallel: four same-stem inputs from different dirs; every sized
        # derivative must land on its own reserved path.
        from photo_s.engine import ProcessOptions, batch_process
        colors = [(200, 30, 30), (30, 200, 30), (30, 30, 200),
                  (200, 200, 30)]
        srcs = [self._img(tmp_path / f"d{i}" / "photo.png", c)
                for i, c in enumerate(colors)]
        out = tmp_path / "out"
        res = batch_process(srcs, ProcessOptions(
            output_dir=str(out), output_format="PNG", suffix="", jobs=4,
            output_sizes=[("thumb", 8, 8), ("screen", 16, 16)]))
        assert res.success_count == 4
        files = list(out.iterdir())
        # 4 mains + 4 thumbs + 4 screens, all distinct paths
        assert len(files) == 12
        assert len({p.name for p in files}) == 12
        for label in ("thumb", "screen"):
            # colliding derivatives are de-suffixed as photo_thumb_1.png etc.
            sized = [p for p in files if f"_{label}" in p.stem]
            assert len(sized) == 4
            # no derivative was overwritten by another same-label output
            assert self._colors_of(sized) == set(colors)


class TestAuditRegressions:
    """Regressions from the 2026-08 audit."""

    def test_scale_percent_tiny_image_clear_error(self, tmp_path):
        from PIL import Image
        from photo_s.engine import process_image, ProcessOptions
        src = tmp_path / "tiny.jpg"
        Image.new("RGB", (3, 3), (10, 20, 30)).save(src)
        result = process_image(
            str(src), ProcessOptions(scale_percent=20,
                                     output_dir=str(tmp_path / "o"),
                                     suffix="_s"))
        assert not result.success
        assert "scale_percent" in result.error

    def test_bare_filename_output_no_makedirs_crash(self, tmp_path,
                                                     monkeypatch):
        from PIL import Image
        from photo_s.engine import process_image, ProcessOptions
        monkeypatch.chdir(tmp_path)
        src = tmp_path / "x.jpg"
        Image.new("RGB", (8, 8), (5, 5, 5)).save(src)
        # output to a bare filename in the CWD (no directory component):
        # os.makedirs("") used to raise a baffling [Errno 2] ''
        result = process_image(str(src), ProcessOptions(suffix="_out"))
        assert result.success
        assert os.path.exists(tmp_path / "x_out.jpg")

    def test_suffix_path_traversal_rejected(self, tmp_path):
        from PIL import Image
        from photo_s.engine import process_image, ProcessOptions
        src = tmp_path / "y.jpg"
        Image.new("RGB", (8, 8), (5, 5, 5)).save(src)
        result = process_image(
            str(src), ProcessOptions(suffix="/../../../tmp/pwned"))
        assert not result.success
        assert "prefix/suffix" in result.error or "traversal" in result.error
