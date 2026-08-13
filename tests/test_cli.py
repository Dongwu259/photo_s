"""Unit tests for CLI parsing functions."""

import json
import sys
import os
import pytest

# Ensure src package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from photo_s.cli import (
    _date_shift_arg, _parse_dimensions, _parse_size, _parse_sizes, run_cli,
)


class TestParseDimensions:
    """Tests for _parse_dimensions() — parses 'WxH' strings."""

    def test_full(self):
        assert _parse_dimensions("1920x1080") == (1920, 1080)

    def test_width_only(self):
        assert _parse_dimensions("800x") == (800, None)

    def test_height_only(self):
        assert _parse_dimensions("x600") == (None, 600)

    def test_single_number(self):
        assert _parse_dimensions("1920") == (1920, None)

    def test_with_spaces(self):
        assert _parse_dimensions(" 1920 x 1080 ") == (1920, 1080)


class TestParseSize:
    """Tests for _parse_size() — parses human-readable byte sizes."""

    def test_pure_number(self):
        assert _parse_size("500") == 500

    def test_kb(self):
        assert _parse_size("500KB") == 512000

    def test_mb(self):
        assert _parse_size("2MB") == 2097152

    def test_fractional_mb(self):
        assert _parse_size("1.5MB") == 1572864

    def test_zero(self):
        assert _parse_size("0") == 0

    def test_gb(self):
        assert _parse_size("1GB") == 1073741824

    def test_lowercase(self):
        assert _parse_size("500kb") == 512000

    def test_short_suffix_k(self):
        assert _parse_size("2K") == 2048

    def test_invalid(self):
        with pytest.raises(Exception):
            _parse_size("abc")


class TestParseSizes:
    """Tests for _parse_sizes() — parses multi-size spec strings."""

    def test_single_size(self):
        result = _parse_sizes("thumb:480x")
        assert result == [("thumb", 480, None)]

    def test_multi_size(self):
        result = _parse_sizes("thumb:480x,screen:1920x1080")
        assert result == [
            ("thumb", 480, None),
            ("screen", 1920, 1080),
        ]

    def test_none(self):
        assert _parse_sizes(None) is None

    def test_empty_string(self):
        assert _parse_sizes("") is None


def _make_image(path, size=(40, 30), color=(120, 100, 80)):
    from PIL import Image
    Image.new("RGB", size, color).save(path, quality=95)
    return str(path)


class TestDateShiftArg:
    def test_valid(self):
        assert _date_shift_arg("-5h30m") == "-5h30m"
        assert _date_shift_arg("+2h") == "+2h"
        assert _date_shift_arg("1d") == "1d"

    def test_invalid_raises(self):
        with pytest.raises(Exception):
            _date_shift_arg("abc")


class TestCliTransformFlags:
    def test_brightness_json(self, tmp_path, capsys):
        img = _make_image(tmp_path / "in.jpg")
        rc = run_cli(["compress", img, "--brightness", "1.5",
                      "-o", str(tmp_path / "out"), "--json"])
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert d["results"][0]["status"] == "ok"

    def test_rotate_and_pad_dims(self, tmp_path, capsys):
        img = _make_image(tmp_path / "in.jpg", size=(400, 300))
        rc = run_cli(["compress", img, "--rotate", "90", "--pad", "1:1",
                      "-o", str(tmp_path / "out"), "--json"])
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        # 400x300 rotated → 300x400, padded to 1:1 → 400x400
        assert d["results"][0]["output_dims"] == [400, 400]

    def test_report_written(self, tmp_path, capsys):
        img = _make_image(tmp_path / "in.jpg")
        report = tmp_path / "r.csv"
        rc = run_cli(["compress", img, "--report", str(report),
                      "-o", str(tmp_path / "out")])
        assert rc == 0
        text = report.read_text()
        assert text.startswith("input,output,status,")
        assert os.path.basename(img) in text


class TestCliCheck:
    def test_valid_images_rc0(self, tmp_path, capsys):
        img = _make_image(tmp_path / "ok.jpg")
        assert run_cli(["check", img]) == 0

    def test_corrupt_image_rc1(self, tmp_path, capsys):
        img = _make_image(tmp_path / "bad.jpg")
        data = open(img, "rb").read()
        open(img, "wb").write(data[:len(data) // 2])
        assert run_cli(["check", img]) == 1

    def test_json_shape(self, tmp_path, capsys):
        img = _make_image(tmp_path / "ok.jpg")
        rc = run_cli(["check", img, "--json"])
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert d["checked"] == 1
        assert d["ok"] == 1
        assert d["corrupt"] == []


class TestCliContactSheet:
    def test_generates_sheet(self, tmp_path, capsys):
        a = _make_image(tmp_path / "a.jpg")
        b = _make_image(tmp_path / "b.jpg")
        out = tmp_path / "sheet.jpg"
        rc = run_cli(["contact-sheet", a, b, "-o", str(out), "--cols", "2"])
        assert rc == 0
        assert out.exists()


class TestCliExifDate:
    def test_exif_date_written(self, tmp_path):
        # regression: CLI --date must actually write DateTimeOriginal
        img = _make_image(tmp_path / "in.jpg")
        rc = run_cli(["exif", img, "--date", "2024:07:30 14:30:00"])
        assert rc == 0
        import piexif
        d = piexif.load(img)
        assert d["Exif"][piexif.ExifIFD.DateTimeOriginal] == b"2024:07:30 14:30:00"

    def test_date_from_mtime_reverse_sync(self, tmp_path):
        import datetime as dtmod
        img = _make_image(tmp_path / "in.jpg")
        fixed = dtmod.datetime(2020, 1, 2, 3, 4, 5)
        os.utime(img, (fixed.timestamp(), fixed.timestamp()))
        rc = run_cli(["exif", img, "--date-from-mtime"])
        assert rc == 0
        import piexif
        d = piexif.load(img)
        assert d["Exif"][piexif.ExifIFD.DateTimeOriginal] == b"2020:01:02 03:04:05"


class TestCliProfiles:
    def test_profiles_override_preset_dirs(self, tmp_path, capsys, monkeypatch):
        from pathlib import Path
        from photo_s.presets import save_preset, PRESETS_DIR
        from photo_s.engine import ProcessOptions
        monkeypatch.setattr("photo_s.presets.PRESETS_DIR",
                            Path(tmp_path / "presets"))

        save_preset("web", ProcessOptions(output_format="JPEG", quality=70,
                                          output_dir="/stale", suffix="_web"), "")
        img = _make_image(tmp_path / "in.jpg")
        out = tmp_path / "out"
        rc = run_cli(["batch", img, "-o", str(out), "--profiles", "web",
                      "--json"])
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        prof = d["profiles"]["web"]
        assert prof["results"][0]["quality"] == 70
        # output_dir comes from CLI (out/), not the stale preset dir
        assert str(out) in prof["results"][0]["output"]
        assert "/stale" not in prof["results"][0]["output"]

    def test_missing_preset_rc1(self, tmp_path, capsys, monkeypatch):
        from pathlib import Path
        from photo_s.presets import PRESETS_DIR
        monkeypatch.setattr("photo_s.presets.PRESETS_DIR",
                            Path(tmp_path / "presets"))
        img = _make_image(tmp_path / "in.jpg")
        rc = run_cli(["batch", img, "--profiles", "nope"])
        assert rc == 1


class TestCliJsonCoverage:
    """--json must be available on every agent-facing subcommand and produce
    parseable stdout (regression: convert/dedup/rename/contact-sheet/info
    previously had no --json; dedup/rename printed emoji text)."""

    def test_remove_original_json_skips_prompt(self, tmp_path, capsys):
        # regression: input() confirmation used to hang on a closed stdin
        img = _make_image(tmp_path / "in.jpg")
        out = tmp_path / "out"
        rc = run_cli(["compress", img, "--remove-original",
                      "-o", str(out), "--json"])
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert d["results"][0]["status"] == "ok"
        assert not os.path.exists(img)  # original removed, no prompt needed

    def test_convert_json(self, tmp_path, capsys):
        img = _make_image(tmp_path / "in.png", color=(1, 2, 3))
        out = tmp_path / "out"
        rc = run_cli(["convert", img, "-f", "JPEG", "-o", str(out), "--json"])
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert d["results"][0]["output_format"] == "JPEG"
        assert d["results"][0]["status"] == "ok"

    def test_info_json(self, capsys):
        rc = run_cli(["info", "--json"])
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert "JPEG" in d["formats"]
        assert ".jpg" in d["input_extensions"]
        assert "writable" in d

    def test_rename_json(self, tmp_path, capsys):
        img = _make_image(tmp_path / "a.jpg")
        rc = run_cli(["rename", img, "--pattern", "Trip_{seq}", "--json"])
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert d["ok"] == 1
        assert d["results"][0]["status"] == "ok"

    def test_contact_sheet_json(self, tmp_path, capsys):
        a = _make_image(tmp_path / "a.jpg")
        b = _make_image(tmp_path / "b.jpg")
        out = tmp_path / "sheet.png"
        rc = run_cli(["contact-sheet", a, b, "-o", str(out), "--json"])
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert d["output"] == str(out)
        assert d["count"] == 2
        assert out.exists()

    def test_dry_run_json(self, tmp_path, capsys):
        img = _make_image(tmp_path / "in.jpg")
        out = tmp_path / "out"
        rc = run_cli(["compress", img, "-o", str(out), "--dry-run", "--json"])
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert d["dry_run"] is True
        assert d["count"] == 1
        assert not os.path.exists(str(out))  # nothing processed

    def test_version_flag(self, capsys):
        from photo_s import __version__
        with pytest.raises(SystemExit) as exc:
            run_cli(["--version"])
        assert exc.value.code == 0
        assert "photo-s {}".format(__version__) in capsys.readouterr().out

    def test_convert_format_case_insensitive(self, tmp_path, capsys):
        # regression: -f png (lowercase) used to be rejected by choices
        img = _make_image(tmp_path / "in.png", color=(1, 2, 3))
        out = tmp_path / "out"
        rc = run_cli(["convert", img, "-f", "png", "-o", str(out), "--json"])
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert d["results"][0]["output_format"] == "PNG"

    def test_batch_format_case_insensitive_webp(self, tmp_path, capsys):
        img = _make_image(tmp_path / "in.jpg")
        out = tmp_path / "out"
        rc = run_cli(["batch", img, "-f", "webp", "-o", str(out), "--json"])
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert d["results"][0]["output_format"] == "WebP"


def _pattern_image(path, kind):
    """A small image with a distinct structural pattern (two solid colors
    would hash identically under dhash — these differ)."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (40, 40), "white")
    dr = ImageDraw.Draw(img)
    if kind == "a":
        dr.rectangle([5, 5, 15, 15], fill="black")
    else:
        dr.ellipse([20, 20, 35, 35], fill="black")
    img.save(path)
    return str(path)


class TestCliDedupJson:
    def test_duplicates_found_exit1(self, tmp_path, capsys):
        import shutil
        img = _pattern_image(tmp_path / "a.jpg", "a")
        shutil.copyfile(img, tmp_path / "b.jpg")
        rc = run_cli(["dedup", img, str(tmp_path / "b.jpg"), "--json"])
        assert rc == 1  # duplicates found → exit 1 (agents branch on it)
        d = json.loads(capsys.readouterr().out)
        assert d["count"] == 1
        assert len(d["groups"][0]["paths"]) == 2
        assert d["duplicate_count"] == 1

    def test_no_duplicates_exit0(self, tmp_path, capsys):
        a = _pattern_image(tmp_path / "a.jpg", "a")
        b = _pattern_image(tmp_path / "b.jpg", "b")
        rc = run_cli(["dedup", a, b, "--json"])
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert d["count"] == 0


class TestAutoJobsCli:
    """-j not passed → auto_jobs() default; explicit -j wins."""

    def _recorder(self, captured):
        from photo_s.engine import BatchResult

        def _fake(p, o, **kw):
            captured.update(paths=p, options=o)
            return BatchResult(results=[], total_input_size=0,
                               total_output_size=0, success_count=0,
                               fail_count=0)
        return _fake

    def test_auto_when_not_passed(self, tmp_path, monkeypatch):
        import photo_s.cli as cli_mod
        captured = {}
        monkeypatch.setattr(cli_mod, "auto_jobs", lambda: 5)
        monkeypatch.setattr(cli_mod, "batch_process", self._recorder(captured))
        img = _make_image(tmp_path / "in.jpg")
        rc = run_cli(["compress", img, "-o", str(tmp_path / "out")])
        assert rc == 0
        assert captured["options"].jobs == 5

    def test_explicit_jobs_wins(self, tmp_path, monkeypatch):
        import photo_s.cli as cli_mod
        captured = {}
        monkeypatch.setattr(cli_mod, "auto_jobs", lambda: 5)
        monkeypatch.setattr(cli_mod, "batch_process", self._recorder(captured))
        img = _make_image(tmp_path / "in.jpg")
        rc = run_cli(["compress", img, "-j", "2", "-o", str(tmp_path / "out")])
        assert rc == 0
        assert captured["options"].jobs == 2


class TestBench:
    """bench: structure present, jobs list honored, no timing assertions."""

    def test_structure_and_dedupe(self, tmp_path, monkeypatch, capsys):
        import photo_s.cli as cli_mod
        seen = []
        monkeypatch.setattr(cli_mod, "batch_process",
                            lambda p, o, **kw: seen.append(o.jobs))
        _make_image(tmp_path / "in.jpg")
        rc = run_cli(["bench", "--dir", str(tmp_path), "-j", "1,2,2", "--json"])
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert set(d) == {"dir", "files", "runs"}
        assert [r["jobs"] for r in d["runs"]] == [1, 2]  # dedup, keep order
        assert all(r["speedup"] > 0 for r in d["runs"])
        assert seen == [1, 2]

    def test_bad_jobs_rejected(self, tmp_path, monkeypatch):
        import photo_s.cli as cli_mod
        monkeypatch.setattr(cli_mod, "batch_process", lambda *a, **k: None)
        _make_image(tmp_path / "in.jpg")
        assert run_cli(["bench", "--dir", str(tmp_path), "-j", "abc", "--json"]) != 0
