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


class TestLiteEditionFallback:
    """Builds without the GUI module (photo-s-lite exe) must degrade
    gracefully instead of crashing on `from .gui import run_gui`."""

    @staticmethod
    def _block_gui(monkeypatch):
        # None in sys.modules makes `from .gui import run_gui` raise
        # ImportError — exactly what the lite exe's excludes cause.
        monkeypatch.setitem(sys.modules, "photo_s.gui", None)

    def test_no_args_prints_help_instead_of_crashing(self, monkeypatch,
                                                     capsys):
        import photo_s.cli as cli_mod
        self._block_gui(monkeypatch)
        monkeypatch.setattr(sys, "argv", ["photo-s"])
        rc = cli_mod.main()
        assert rc == 0
        out, err = capsys.readouterr()
        assert "Commands" in out or "命令" in out  # argparse help body
        assert "lite" in err or "精简" in err      # the no-GUI hint

    def test_gui_subcommand_exits_1_with_hint(self, monkeypatch, capsys):
        import photo_s.cli as cli_mod
        self._block_gui(monkeypatch)
        monkeypatch.setattr(sys, "argv", ["photo-s", "gui"])
        rc = cli_mod.main()
        assert rc == 1
        err = capsys.readouterr().err
        assert "lite" in err or "精简" in err

    def test_version_marks_lite_build(self, monkeypatch, capsys):
        import photo_s.cli as cli_mod
        monkeypatch.setattr(cli_mod, "_gui_module_available",
                            lambda: False)
        with pytest.raises(SystemExit) as exc:
            run_cli(["--version"])
        assert exc.value.code == 0
        assert "(lite)" in capsys.readouterr().out

    def test_version_unmarked_when_gui_present(self, capsys):
        with pytest.raises(SystemExit):
            run_cli(["--version"])
        assert "(lite)" not in capsys.readouterr().out

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


class TestCliDedupConfirmWording:
    def test_keep_sharpest_prompt_says_delete(self, tmp_path, monkeypatch):
        # regression: keep-sharpest permanently deletes via os.unlink — the
        # confirm prompt must say 删除, not 移动
        import shutil
        a = _pattern_image(tmp_path / "a.jpg", "a")
        b = shutil.copyfile(a, tmp_path / "b.jpg")
        prompts = []
        monkeypatch.setattr("builtins.input",
                            lambda p="": (prompts.append(p), "n")[1])
        rc = run_cli(["dedup", a, str(b), "--action", "keep-sharpest"])
        assert rc == 0
        assert prompts and "删除" in prompts[0] and "移动" not in prompts[0]
        assert os.path.exists(a) and os.path.exists(b)  # declined → untouched


class TestCliExifPerFileErrors:
    """One bad file must not abort the whole exif write batch."""

    def test_write_loop_continues_after_bad_file(self, tmp_path, capsys):
        # regression: PNG (no EXIF support in piexif) used to crash the loop
        img = _make_image(tmp_path / "good.jpg")
        png = _make_image(tmp_path / "bad.png")
        rc = run_cli(["exif", img, png, "--artist", "me"])
        assert rc == 1  # partial failure reported via exit code
        import piexif
        d = piexif.load(img)
        assert d["0th"][piexif.ImageIFD.Artist] == b"me"  # good file written
        cap = capsys.readouterr()
        assert "bad.png" in cap.out
        assert "1 个文件写入失败" in cap.err

    def test_from_csv_partial_failure_continues(self, tmp_path, capsys):
        # regression: a missing file mid-CSV aborted the import, leaving a
        # silently half-written batch with a traceback
        img = _make_image(tmp_path / "row1.jpg")
        csv_path = tmp_path / "meta.csv"
        csv_path.write_text("path,artist\n"
                            f"{img},alice\n"
                            f"{tmp_path / 'gone.jpg'},bob\n",
                            encoding="utf-8")
        rc = run_cli(["exif", "--from-csv", str(csv_path)])
        assert rc == 1
        import piexif
        d = piexif.load(img)
        assert d["0th"][piexif.ImageIFD.Artist] == b"alice"
        assert "1 个文件写入失败" in capsys.readouterr().err

    def test_from_json_partial_failure_continues(self, tmp_path, capsys):
        img = _make_image(tmp_path / "row1.jpg")
        json_path = tmp_path / "meta.json"
        json_path.write_text(json.dumps(
            [{"path": img, "artist": "alice"},
             {"path": str(tmp_path / "gone.jpg"), "artist": "bob"}]),
            encoding="utf-8")
        rc = run_cli(["exif", "--from-json", str(json_path)])
        assert rc == 1
        import piexif
        d = piexif.load(img)
        assert d["0th"][piexif.ImageIFD.Artist] == b"alice"

    def test_date_from_mtime_per_file_errors(self, tmp_path, capsys):
        img = _make_image(tmp_path / "ok.jpg")
        png = _make_image(tmp_path / "bad.png")
        rc = run_cli(["exif", img, png, "--date-from-mtime"])
        assert rc == 1
        assert "1 个文件写入失败" in capsys.readouterr().err
        import piexif
        d = piexif.load(img)
        assert d["Exif"][piexif.ExifIFD.DateTimeOriginal]  # good file written


class TestCliProfilesRuntimeFields:
    def test_preset_does_not_clobber_cli_runtime_fields(
            self, tmp_path, monkeypatch, capsys):
        # regression: serialized preset defaults (jobs=1, None fields) used to
        # override explicit CLI -j/--target-size/--resize under --profiles
        from pathlib import Path
        from photo_s.presets import save_preset
        from photo_s.engine import ProcessOptions, BatchResult
        import photo_s.cli as cli_mod
        monkeypatch.setattr("photo_s.presets.PRESETS_DIR",
                            Path(tmp_path / "presets"))
        save_preset("web", ProcessOptions(quality=70), "")
        captured = []

        def _fake(paths, opts, **kw):
            captured.append(opts)
            return BatchResult(results=[], total_input_size=0,
                               total_output_size=0, success_count=0,
                               fail_count=0)
        monkeypatch.setattr(cli_mod, "batch_process", _fake)
        img = _make_image(tmp_path / "in.jpg")
        rc = run_cli(["batch", img, "-o", str(tmp_path / "out"),
                      "--profiles", "web", "--resize", "800x600",
                      "-j", "3", "--target-size", "500KB", "--json"])
        assert rc == 0
        assert len(captured) == 1
        po = captured[0]
        assert po.quality == 70              # preset value applies
        assert po.jobs == 3                  # CLI runtime field survives
        assert po.target_size_bytes == 512000
        assert po.max_width == 800           # preset None must not clobber CLI


class TestRemoveOriginalConfirm:
    def test_eoferror_treated_as_refusal(self, tmp_path, monkeypatch, capsys):
        # regression: closed stdin (pipe/agent) crashed with an EOFError traceback
        img = _make_image(tmp_path / "in.jpg")

        def _closed(*a, **k):
            raise EOFError
        monkeypatch.setattr("builtins.input", _closed)
        rc = run_cli(["compress", img, "--remove-original",
                      "-o", str(tmp_path / "out")])
        assert rc == 1
        assert os.path.exists(img)  # refused → original kept
        assert "Cancelled" in capsys.readouterr().err

    def test_compress_yes_skips_prompt(self, tmp_path, monkeypatch):
        img = _make_image(tmp_path / "in.jpg")

        def _boom(*a, **k):
            raise AssertionError("prompt must not appear with -y")
        monkeypatch.setattr("builtins.input", _boom)
        rc = run_cli(["compress", img, "--remove-original", "-y",
                      "-o", str(tmp_path / "out")])
        assert rc == 0
        assert not os.path.exists(img)

    def test_convert_yes_skips_prompt(self, tmp_path, monkeypatch):
        img = _make_image(tmp_path / "in.png", color=(1, 2, 3))

        def _boom(*a, **k):
            raise AssertionError("prompt must not appear with --yes")
        monkeypatch.setattr("builtins.input", _boom)
        rc = run_cli(["convert", img, "-f", "JPEG", "--remove-original",
                      "--yes", "-o", str(tmp_path / "out")])
        assert rc == 0
        assert not os.path.exists(img)


class TestConfigLoadErrors:
    """Bad --config paths must produce a clean error, not a traceback."""

    def test_config_show_bad_toml(self, tmp_path, capsys):
        bad = tmp_path / "bad.toml"
        bad.write_text("[options\nquality = ")
        rc = run_cli(["config", "show", "--path", str(bad)])
        assert rc == 1
        assert "Config load error" in capsys.readouterr().out

    def test_serve_missing_config(self, tmp_path, capsys):
        rc = run_cli(["serve", "--config", str(tmp_path / "nope.toml")])
        assert rc == 1
        assert "Config load error" in capsys.readouterr().out
