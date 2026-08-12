"""Unit tests for engine utility functions."""

import sys
import os

# Ensure src package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from photo_s.engine import (
    _format_from_path,
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
