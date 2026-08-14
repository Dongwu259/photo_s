"""Tests for photo_s.gpx — GPX parsing and interpolation."""

import os
import sys
from datetime import datetime

# Ensure src package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from photo_s.gpx import parse_gpx, position_at, to_dms_rational

GPX = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test">
  <trk>
    <trkseg>
      <trkpt lat="10.0" lon="20.0">
        <time>2024-07-30T10:00:00Z</time>
      </trkpt>
      <trkpt lat="10.1" lon="20.1">
        <time>2024-07-30T10:10:00Z</time>
      </trkpt>
    </trkseg>
  </trk>
</gpx>
"""


class TestParseGpx:
    def test_parses_points_sorted(self, tmp_path):
        p = tmp_path / "t.gpx"
        p.write_text(GPX)
        points = parse_gpx(str(p))
        assert len(points) == 2
        assert points[0][0] == datetime(2024, 7, 30, 10, 0)
        assert points[0][1] == 10.0
        assert points[0][2] == 20.0

    def test_missing_file_empty(self, tmp_path):
        assert parse_gpx(str(tmp_path / "nope.gpx")) == []

    def test_invalid_xml_empty(self, tmp_path):
        p = tmp_path / "bad.gpx"
        p.write_text("not xml <<<")
        assert parse_gpx(str(p)) == []

    def test_namespace_prefix_stripped(self, tmp_path):
        p = tmp_path / "ns.gpx"
        p.write_text(GPX.replace("<gpx", '<gpx xmlns="http://www.topografix.com/GPX/1/1"'))
        points = parse_gpx(str(p))
        assert len(points) == 2

    def test_nan_coordinate_skipped(self, tmp_path):
        # Regression: float("nan") parses fine, so NaN track points leaked
        # into interpolation and got written into the GPS EXIF
        p = tmp_path / "nan.gpx"
        p.write_text(GPX.replace('lat="10.1"', 'lat="nan"'))
        points = parse_gpx(str(p))
        assert len(points) == 1
        assert points[0][1] == 10.0

    def test_inf_coordinate_skipped(self, tmp_path):
        p = tmp_path / "inf.gpx"
        p.write_text(GPX.replace('lon="20.0"', 'lon="inf"'))
        points = parse_gpx(str(p))
        assert len(points) == 1
        assert points[0][2] == 20.1


class TestPositionAt:
    def _gpx(self, tmp_path):
        p = tmp_path / "t.gpx"
        p.write_text(GPX)
        return str(p)

    def test_interpolates_midpoint(self, tmp_path):
        path = self._gpx(tmp_path)
        lat, lon = position_at(path, datetime(2024, 7, 30, 10, 5))
        assert abs(lat - 10.05) < 1e-6
        assert abs(lon - 20.05) < 1e-6

    def test_exact_point(self, tmp_path):
        path = self._gpx(tmp_path)
        lat, lon = position_at(path, datetime(2024, 7, 30, 10, 0))
        assert abs(lat - 10.0) < 1e-9

    def test_outside_range_none(self, tmp_path):
        path = self._gpx(tmp_path)
        assert position_at(path, datetime(2024, 7, 30, 9, 0)) is None
        assert position_at(path, datetime(2024, 7, 30, 11, 0)) is None

    def test_unknown_file_none(self, tmp_path):
        assert position_at(str(tmp_path / "nope.gpx"),
                           datetime(2024, 1, 1)) is None


class TestToDmsRational:
    def test_positive(self):
        d, m, s = to_dms_rational(42.375)
        assert d == (42, 1)
        assert m == (22, 1)
        assert s[0] >= 2900  # ~29.99 × 100

    def test_negative_uses_abs(self):
        d, _, _ = to_dms_rational(-12.5)
        assert d == (12, 1)

    def test_seconds_rounding_carries_into_minutes(self):
        # Regression: 12° 34' 59.999" rounded seconds to 60.00 without
        # carrying, emitting the invalid DMS 12° 34' 60.00"
        d, m, s = to_dms_rational(12 + 34 / 60 + 59.999 / 3600)
        assert d == (12, 1)
        assert m == (35, 1)
        assert s == (0, 100)

    def test_seconds_rounding_carries_into_degrees(self):
        # 12° 59' 59.999" must carry all the way: 13° 0' 0.00"
        d, m, s = to_dms_rational(12 + 59 / 60 + 59.999 / 3600)
        assert d == (13, 1)
        assert m == (0, 1)
        assert s == (0, 100)


class TestGpxInjection:
    """End-to-end: JPEG with EXIF datetime → GPX lookup → GPS written."""

    def _jpeg(self, tmp_path, ts_str=b"2024:07:30 10:05:00"):
        import piexif
        exif_bytes = piexif.dump({
            "0th": {piexif.ImageIFD.Make: b"TestCam"},
            "Exif": {piexif.ExifIFD.DateTimeOriginal: ts_str},
            "GPS": {}, "1st": {}, "thumbnail": None,
        })
        from PIL import Image
        p = tmp_path / "shot.jpg"
        Image.new("RGB", (40, 30), (10, 90, 200)).save(p, quality=92,
                                                       exif=exif_bytes)
        return str(p)

    def test_injects_interpolated_gps(self, tmp_path):
        from photo_s.engine import process_image, ProcessOptions
        src = self._jpeg(tmp_path)
        gpx = tmp_path / "t.gpx"
        gpx.write_text(GPX)

        result = process_image(src, ProcessOptions(
            output_dir=str(tmp_path / "out"), suffix="_out",
            gpx_trace=str(gpx)))
        assert result.success

        import piexif
        d = piexif.load(open(result.output_path, "rb").read())
        gps = d["GPS"]
        assert gps  # GPS IFD populated
        # midpoint: ~10.05 N / 20.05 E
        lat_deg = gps[piexif.GPSIFD.GPSLatitude][0][0] / gps[piexif.GPSIFD.GPSLatitude][0][1]
        assert gps[piexif.GPSIFD.GPSLatitudeRef] == b"N"
        assert 10.0 <= lat_deg <= 10.1

    def test_outside_track_no_gps(self, tmp_path):
        from photo_s.engine import process_image, ProcessOptions
        src = self._jpeg(tmp_path, b"2020:01:01 00:00:00")
        gpx = tmp_path / "t.gpx"
        gpx.write_text(GPX)

        result = process_image(src, ProcessOptions(
            output_dir=str(tmp_path / "out2"), suffix="_out",
            gpx_trace=str(gpx)))
        assert result.success
        import piexif
        d = piexif.load(open(result.output_path, "rb").read())
        assert d["GPS"] == {}
