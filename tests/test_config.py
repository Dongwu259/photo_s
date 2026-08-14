"""Tests for config file support: discovery, parsing, and CLI precedence."""

import os
import sys

# Ensure src package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from photo_s.engine import ProcessOptions
from photo_s.config import (
    _parse_size, find_config, load_config, save_config,
    default_config_text, apply_config, _SIMPLE_FIELDS,
)


class TestParseSize:
    def test_pure_number(self):
        assert _parse_size("500") == 500

    def test_kb(self):
        assert _parse_size("500KB") == 512000

    def test_mb(self):
        assert _parse_size("2MB") == 2097152

    def test_fractional(self):
        assert _parse_size("1.5MB") == 1572864

    def test_lowercase(self):
        assert _parse_size("500kb") == 512000

    def test_int_input(self):
        assert _parse_size(2048) == 2048

    def test_invalid_returns_none(self):
        assert _parse_size("abc") is None

    def test_none_returns_none(self):
        assert _parse_size(None) is None


class TestDefaultConfigText:
    def test_has_options_section(self):
        text = default_config_text()
        assert "[options]" in text
        assert "quality" in text

    def test_enhance_extra_uses_pypi_name(self):
        # Regression: 模板注释写的是旧包名 photo-s[enhance]，
        # PyPI 发行名是 photo-s-tools（photo-s 被 PyPI 拦截）
        text = default_config_text()
        assert "photo-s-tools[enhance]" in text
        assert "photo-s[" not in text


class TestSaveLoad:
    def test_save_then_load(self, tmp_path):
        path = str(tmp_path / "sub" / "photo-s.toml")
        save_config(path, "[options]\nquality = 60\n")
        assert os.path.isfile(path)
        cfg = load_config(path)
        assert cfg["options"]["quality"] == 60


class TestApplyConfig:
    def test_simple_field_mapping(self):
        cfg = {"options": {"quality": 60, "jobs": 4, "strip_gps": True}}
        opts = apply_config(cfg, ProcessOptions())
        assert opts.quality == 60
        assert opts.jobs == 4
        assert opts.strip_gps is True

    def test_preserve_exif_bool(self):
        cfg = {"options": {"preserve_exif": False}}
        opts = apply_config(cfg, ProcessOptions())
        assert opts.preserve_exif is False

    def test_target_size_string(self):
        cfg = {"options": {"target_size": "500KB"}}
        opts = apply_config(cfg, ProcessOptions())
        assert opts.target_size_bytes == 512000

    def test_folder_pattern_preset(self):
        cfg = {"options": {"folder_pattern": "date-camera"}}
        opts = apply_config(cfg, ProcessOptions())
        assert opts.folder_pattern == "{year}/{month}/{camera}"

    def test_unknown_keys_ignored(self):
        cfg = {"options": {"nope": 1, "quality": 75}}
        opts = apply_config(cfg, ProcessOptions())
        assert opts.quality == 75  # known key still applied

    def test_sprint3_fields(self):
        cfg = {"options": {"brightness": 1.2, "crop": "800x600+0+0",
                           "scrub": True, "grayscale": True, "pad": "16:9"}}
        opts = apply_config(cfg, ProcessOptions())
        assert opts.brightness == 1.2
        assert opts.crop == "800x600+0+0"
        assert opts.scrub is True
        assert opts.grayscale is True
        assert opts.pad_ratio == "16:9"  # config key "pad" maps to pad_ratio

    def test_output_format_case_insensitive(self):
        cfg = {"options": {"output_format": "webp"}}
        opts = apply_config(cfg, ProcessOptions())
        assert opts.output_format == "WebP"


class TestFindConfig:
    def test_cwd_walk_up(self, tmp_path, monkeypatch):
        (tmp_path / "photo-s.toml").write_text("[options]\n")
        deep = tmp_path / "a" / "b"
        deep.mkdir(parents=True)
        monkeypatch.chdir(deep)
        assert find_config() == str(tmp_path / "photo-s.toml")

    def test_xdg_config_home(self, tmp_path, monkeypatch):
        xdg = tmp_path / "xdg"
        cfg = xdg / "photo-s" / "config.toml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text("[options]\n")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
        monkeypatch.delenv("HOME", raising=False)
        assert find_config() == str(cfg)

    def test_none_when_no_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path / "nonexistent-home"))
        assert find_config() is None


def _build_cli_namespace(**present):
    """Namespace mimicking argparse with default=argparse.SUPPRESS:
    attributes only exist when explicitly passed on the CLI."""
    import argparse
    return argparse.Namespace(**present)


class TestApplyConfigDefaults:
    """Direct tests of _apply_config_defaults precedence logic."""

    @pytest.fixture()
    def apply_defaults(self):
        from photo_s.cli import _apply_config_defaults
        return _apply_config_defaults

    def test_config_applied_when_arg_absent(self, apply_defaults):
        cfg = {"options": {"quality": 60}}
        parsed = _build_cli_namespace(command="compress")
        opts = apply_defaults(ProcessOptions(), parsed, cfg)
        assert opts.quality == 60

    def test_config_skipped_when_arg_present(self, apply_defaults):
        # even a value equal to the argparse default counts as "explicitly set";
        # the base options already carry the CLI value (85), config 60 is skipped
        cfg = {"options": {"quality": 60}}
        parsed = _build_cli_namespace(command="compress", quality=85)
        opts = apply_defaults(ProcessOptions(quality=85), parsed, cfg)
        assert opts.quality == 85

    def test_config_skipped_when_arg_differs(self, apply_defaults):
        cfg = {"options": {"quality": 60}}
        parsed = _build_cli_namespace(command="compress", quality=80)
        opts = apply_defaults(ProcessOptions(quality=80), parsed, cfg)
        assert opts.quality == 80

    def test_suffix_applied_when_absent(self, apply_defaults):
        cfg = {"options": {"suffix": "_cfg"}}
        parsed = _build_cli_namespace(command="compress")
        opts = apply_defaults(ProcessOptions(), parsed, cfg)
        assert opts.suffix == "_cfg"

    def test_suffix_skipped_when_present(self, apply_defaults):
        cfg = {"options": {"suffix": "_cfg"}}
        parsed = _build_cli_namespace(command="compress", suffix="_mine")
        opts = apply_defaults(ProcessOptions(suffix="_mine"), parsed, cfg)
        assert opts.suffix == "_mine"

    def test_inverse_flag_blocks_config(self, apply_defaults):
        # --no-exif present → config preserve_exif ignored; base already False
        cfg = {"options": {"preserve_exif": True}}
        parsed = _build_cli_namespace(command="compress", no_exif=True)
        opts = apply_defaults(ProcessOptions(preserve_exif=False), parsed, cfg)
        assert opts.preserve_exif is False

    def test_inverse_flag_absent_allows_config(self, apply_defaults):
        cfg = {"options": {"preserve_exif": False}}
        parsed = _build_cli_namespace(command="compress")
        opts = apply_defaults(ProcessOptions(preserve_exif=True), parsed, cfg)
        assert opts.preserve_exif is False


class TestConfigMappingParity:
    """Guard against drift between the config key→field mapping and the CLI
    half of that mapping (the historical ("pad" → .pad) silent-drop bug)."""

    @pytest.fixture()
    def apply_defaults(self):
        from photo_s.cli import _apply_config_defaults
        return _apply_config_defaults

    def test_config_mapping_targets_real_fields(self):
        """Every config._SIMPLE_FIELDS value must be a real ProcessOptions
        field — a missing field means config is silently dropped (pad bug)."""
        fields = set(ProcessOptions.__dataclass_fields__)
        for key, field in _SIMPLE_FIELDS.items():
            assert field in fields, f"config {key!r} → missing field {field!r}"

    def test_cli_config_dests_are_known_keys(self):
        """_CONFIG_CLI_DESTS only overrides keys that exist in the canonical
        config mapping — no drift between the two tables."""
        from photo_s.cli import _CONFIG_CLI_DESTS
        assert set(_CONFIG_CLI_DESTS) <= set(_SIMPLE_FIELDS)

    def test_pad_config_maps_to_pad_ratio(self, apply_defaults):
        cfg = {"options": {"pad": "16:9"}}
        parsed = _build_cli_namespace(command="compress")
        opts = apply_defaults(ProcessOptions(), parsed, cfg)
        assert opts.pad_ratio == "16:9"  # was silently dropped before the fix
        assert not hasattr(opts, "pad") or opts.pad is None

    def test_max_width_scale_rename_applied(self, apply_defaults):
        cfg = {"options": {"max_width": 1200, "scale_percent": 50,
                           "rename_pattern": "{date}"}}
        parsed = _build_cli_namespace(command="compress")
        opts = apply_defaults(ProcessOptions(), parsed, cfg)
        assert opts.max_width == 1200
        assert opts.scale_percent == 50
        assert opts.rename_pattern == "{date}"

    def test_rotate_config_skipped_when_cli_present(self, apply_defaults):
        # --rotate dest is "rotate"; config rotate_degrees must not win over it
        cfg = {"options": {"rotate_degrees": 180}}
        parsed = _build_cli_namespace(command="compress", rotate=90)
        opts = apply_defaults(ProcessOptions(rotate_degrees=90), parsed, cfg)
        assert opts.rotate_degrees == 90

    def test_resize_rename_cli_wins_over_config(self, apply_defaults):
        cfg = {"options": {"max_width": 1200, "rename_pattern": "{date}"}}
        parsed = _build_cli_namespace(command="compress", resize="800x",
                                      rename="Trip")
        opts = apply_defaults(ProcessOptions(max_width=800, rename_pattern="Trip"),
                              parsed, cfg)
        assert opts.max_width == 800      # --resize wins
        assert opts.rename_pattern == "Trip"  # --rename wins

    def test_output_format_case_insensitive_via_cli(self, apply_defaults):
        cfg = {"options": {"output_format": "png"}}
        parsed = _build_cli_namespace(command="compress")
        opts = apply_defaults(ProcessOptions(), parsed, cfg)
        assert opts.output_format == "PNG"


class TestCliPrecedenceIntegration:
    """End-to-end precedence through run_cli + --json output."""

    def _run(self, capsys, args):
        from photo_s.cli import run_cli
        rc = run_cli(args)
        out = capsys.readouterr().out
        return rc, out

    def test_config_applies_when_not_set(self, tmp_path, capsys):
        from PIL import Image
        img = tmp_path / "in.jpg"
        Image.new("RGB", (40, 40), (10, 10, 10)).save(img, quality=95)
        cfg = tmp_path / "photo-s.toml"
        cfg.write_text("[options]\nquality = 60\n")

        rc, out = self._run(capsys, [
            "compress", str(img), "--config", str(cfg),
            "-o", str(tmp_path / "out"), "--json",
        ])
        assert rc == 0
        import json
        d = json.loads(out)
        assert d["results"][0]["quality"] == 60

    def test_cli_wins_even_when_equals_default(self, tmp_path, capsys):
        # -q 85 equals the argparse default but must still beat config quality=60
        from PIL import Image
        img = tmp_path / "in.jpg"
        Image.new("RGB", (40, 40), (10, 10, 10)).save(img, quality=95)
        cfg = tmp_path / "photo-s.toml"
        cfg.write_text("[options]\nquality = 60\n")

        rc, out = self._run(capsys, [
            "compress", str(img), "-q", "85", "--config", str(cfg),
            "-o", str(tmp_path / "out"), "--json",
        ])
        assert rc == 0
        import json
        d = json.loads(out)
        assert d["results"][0]["quality"] == 85

    def test_config_suffix_applied(self, tmp_path, capsys):
        from PIL import Image
        img = tmp_path / "in.jpg"
        Image.new("RGB", (40, 40), (10, 10, 10)).save(img, quality=95)
        cfg = tmp_path / "photo-s.toml"
        cfg.write_text('[options]\nsuffix = "_fromcfg"\n')

        rc, out = self._run(capsys, [
            "compress", str(img), "--config", str(cfg),
            "-o", str(tmp_path / "out"), "--json",
        ])
        assert rc == 0
        import json
        d = json.loads(out)
        assert d["results"][0]["output"].endswith("_fromcfg.jpg")


class TestApplyConfigTypeCoercion:
    """Config values are coerced to the ProcessOptions field's annotated type;
    unconvertible values raise a key-named ValueError instead of crashing
    deep in the processing pipeline."""

    def test_string_int_coerced(self):
        cfg = {"options": {"jobs": "4"}}
        opts = apply_config(cfg, ProcessOptions())
        assert opts.jobs == 4 and isinstance(opts.jobs, int)

    def test_bad_value_raises_key_named_error(self):
        cfg = {"options": {"jobs": "abc"}}
        with pytest.raises(ValueError, match="jobs"):
            apply_config(cfg, ProcessOptions())

    def test_bool_field_rejects_bool_as_int(self):
        # True is an int subclass — must not slip into an int field
        cfg = {"options": {"quality": True}}
        with pytest.raises(ValueError, match="quality"):
            apply_config(cfg, ProcessOptions())

    def test_bool_from_string(self):
        cfg = {"options": {"strip_gps": "true", "grayscale": "false"}}
        opts = apply_config(cfg, ProcessOptions())
        assert opts.strip_gps is True
        assert opts.grayscale is False

    def test_bad_bool_raises(self):
        cfg = {"options": {"strip_gps": "maybe"}}
        with pytest.raises(ValueError, match="strip_gps"):
            apply_config(cfg, ProcessOptions())

    def test_float_field_accepts_int(self):
        cfg = {"options": {"brightness": 2}}
        opts = apply_config(cfg, ProcessOptions())
        assert opts.brightness == 2.0

    def test_optional_int_from_string(self):
        cfg = {"options": {"wb": "5600"}}
        opts = apply_config(cfg, ProcessOptions())
        assert opts.wb_temp == 5600

    def test_raw_auto_bright_applied(self):
        # regression: apply_config silently ignored raw_auto_bright
        # (only the CLI path in _apply_config_defaults knew the key)
        cfg = {"options": {"raw_auto_bright": False}}
        opts = apply_config(cfg, ProcessOptions())
        assert opts.raw_auto_bright is False

    def test_raw_auto_bright_default_untouched(self):
        opts = apply_config({"options": {}}, ProcessOptions())
        assert opts.raw_auto_bright is True


class TestCliConfigCoercionIntegration:
    """The compress/batch --config path goes through _apply_config_defaults —
    the same coercion must apply there (jobs = "4" used to reach
    batch_process as a str and TypeError)."""

    def _run(self, capsys, args):
        from photo_s.cli import run_cli
        rc = run_cli(args)
        out = capsys.readouterr().out
        return rc, out

    def test_string_jobs_coerced_via_cli(self, tmp_path, capsys):
        from PIL import Image
        img = tmp_path / "in.jpg"
        Image.new("RGB", (40, 40), (10, 10, 10)).save(img, quality=95)
        cfg = tmp_path / "photo-s.toml"
        cfg.write_text('[options]\njobs = "4"\n')
        rc, out = self._run(capsys, [
            "compress", str(img), "--config", str(cfg),
            "-o", str(tmp_path / "out"), "--json",
        ])
        assert rc == 0
        import json
        assert json.loads(out)["results"][0]["status"] == "ok"

    def test_bad_value_clean_error_via_cli(self, tmp_path, capsys):
        from PIL import Image
        img = tmp_path / "in.jpg"
        Image.new("RGB", (40, 40), (10, 10, 10)).save(img, quality=95)
        cfg = tmp_path / "photo-s.toml"
        cfg.write_text('[options]\njobs = "abc"\n')
        rc, out = self._run(capsys, [
            "compress", str(img), "--config", str(cfg),
            "-o", str(tmp_path / "out"),
        ])
        assert rc == 1
        assert "jobs" in out  # key-named error, no traceback
