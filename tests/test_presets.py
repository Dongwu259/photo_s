"""Tests for preset storage: UTF-8 encoding, robustness, roundtrip."""

import json
import os
import sys

# Ensure src package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from photo_s.cli import run_cli
from photo_s.engine import ProcessOptions


@pytest.fixture()
def presets_dir(tmp_path, monkeypatch):
    """Isolate the preset store into a tmp dir."""
    d = tmp_path / "presets"
    monkeypatch.setattr("photo_s.presets.PRESETS_DIR", d)
    return d


class TestPresetEncoding:
    def test_chinese_preset_roundtrip_utf8(self, presets_dir):
        # regression: read_text/write_text without encoding="utf-8" broke
        # Chinese presets on Windows (save: UnicodeEncodeError, load: silent
        # UnicodeDecodeError swallowed by except)
        from photo_s.presets import save_preset, load_preset, list_presets
        save_preset("网页", ProcessOptions(quality=66), "中文描述")
        text = (presets_dir / "网页.json").read_bytes().decode("utf-8")
        assert "中文描述" in text
        opts = load_preset("网页")
        assert opts is not None and opts.quality == 66
        assert any("中文描述" in p for p in list_presets())

    def test_import_presets_utf8(self, presets_dir, tmp_path):
        from photo_s.presets import import_presets_from_json, load_preset
        src = tmp_path / "import.json"
        src.write_text(json.dumps({"缩略图": {"quality": 55}},
                                  ensure_ascii=False),
                       encoding="utf-8")
        assert import_presets_from_json(str(src)) == 1
        opts = load_preset("缩略图")
        assert opts is not None and opts.quality == 55


class TestLoadPresetRobustness:
    def test_non_dict_json_returns_none(self, presets_dir):
        # regression: a valid-JSON non-object preset (e.g. [1,2,3]) crashed
        # with TypeError on data.pop
        from photo_s.presets import load_preset
        presets_dir.mkdir(parents=True)
        (presets_dir / "bad.json").write_text("[1, 2, 3]", encoding="utf-8")
        assert load_preset("bad") is None

    def test_scalar_json_returns_none(self, presets_dir):
        from photo_s.presets import load_preset
        presets_dir.mkdir(parents=True)
        (presets_dir / "num.json").write_text("42", encoding="utf-8")
        assert load_preset("num") is None

    def test_invalid_json_returns_none(self, presets_dir):
        from photo_s.presets import load_preset
        presets_dir.mkdir(parents=True)
        (presets_dir / "broken.json").write_text("{not json", encoding="utf-8")
        assert load_preset("broken") is None


class TestCliPresetApply:
    """CLI `preset save` full-option capture + `batch --preset` merge."""

    def _save(self, *args, **kw):
        return run_cli(["preset", "save", *args])

    def test_save_captures_full_options(self, presets_dir):
        # regression: CLI save used to store only quality/format/resize/suffix;
        # now it captures the whole option set via the shared builder
        from photo_s.presets import load_preset
        rc = self._save("web", "-q", "78", "--contrast", "1.3", "--grayscale")
        assert rc == 0
        opts = load_preset("web")
        assert opts.quality == 78
        assert opts.contrast == 1.3
        assert opts.grayscale is True

    def test_batch_applies_preset(self, presets_dir, tmp_path, capsys):
        # --preset feeds the batch options; quality is read from the JSON
        # dry-run report (locale-independent)
        self._save("web", "-q", "72", "--saturation", "1.4")
        capsys.readouterr()  # drain the save confirmation
        src = tmp_path / "a.jpg"
        from PIL import Image
        Image.new("RGB", (40, 30), (10, 20, 30)).save(str(src))
        rc = run_cli(["batch", str(src), "-o", str(tmp_path / "out"),
                      "--preset", "web", "--dry-run", "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["settings"]["quality"] == 72

    def test_explicit_cli_overrides_preset(self, presets_dir, tmp_path, capsys):
        # explicit -q beats the preset's quality (hasattr semantics)
        self._save("web", "-q", "72")
        capsys.readouterr()  # drain the save confirmation
        src = tmp_path / "a.jpg"
        from PIL import Image
        Image.new("RGB", (40, 30), (10, 20, 30)).save(str(src))
        rc = run_cli(["batch", str(src), "-o", str(tmp_path / "out"),
                      "--preset", "web", "-q", "90", "--dry-run", "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["settings"]["quality"] == 90

    def test_missing_preset_errors(self, presets_dir, tmp_path):
        src = tmp_path / "a.jpg"
        from PIL import Image
        Image.new("RGB", (40, 30), (10, 20, 30)).save(str(src))
        rc = run_cli(["batch", str(src), "-o", str(tmp_path / "out"),
                      "--preset", "nope", "--dry-run"])
        assert rc == 1


class TestBuiltinPresets:
    def test_lr_look_resolves_without_user_file(self, presets_dir):
        from photo_s.presets import load_preset, list_presets
        # isolated dir has no user presets
        opts = load_preset("lr-look")
        assert opts is not None
        assert opts.curves  # S-curve present
        assert opts.export_sharpen == 1.0  # LR-style output sharpening
        assert any("lr-look" in p for p in list_presets())

    def test_user_preset_shadows_builtin(self, presets_dir):
        from photo_s.presets import save_preset, load_preset, list_presets
        save_preset("lr-look", ProcessOptions(quality=42),
                    "user override")
        opts = load_preset("lr-look")
        assert opts.quality == 42
        assert opts.curves == ""  # builtin values gone
        listed = list_presets()
        assert any("user override" in p for p in listed)

    def test_unknown_returns_none(self, presets_dir):
        from photo_s.presets import load_preset
        assert load_preset("definitely-not-a-preset") is None


class TestPresetSkipDefaults:
    """A preset field at its dataclass default carries no intent — applying
    it must not clobber command-level defaults (batch suffix '_processed')
    or config values."""

    def test_builtin_does_not_clobber_batch_suffix(self, presets_dir):
        # The builtin ProcessOptions has default suffix "_compressed"; a batch
        # run must keep "_processed" (regression: lr-look output was named
        # *_compressed.jpg before the fix).
        import types
        import photo_s.cli as cli
        from photo_s.engine import ProcessOptions
        from photo_s.presets import load_preset
        parsed = types.SimpleNamespace(command="batch", preset="lr-look")
        options = ProcessOptions(suffix="_processed")
        out = cli._apply_preset_defaults(options, parsed)
        assert out.suffix == "_processed"
        # and the look fields DID apply
        assert out.curves and out.export_sharpen == 1.0

    def test_explicit_cli_still_wins(self, presets_dir):
        import types
        import photo_s.cli as cli
        from photo_s.engine import ProcessOptions
        parsed = types.SimpleNamespace(command="batch", preset="lr-look",
                                       sharpen=3.0)
        options = ProcessOptions(sharpen=3.0)
        out = cli._apply_preset_defaults(options, parsed)
        assert out.sharpen == 3.0  # CLI explicit beats preset

    def test_non_default_preset_field_applies(self, presets_dir):
        import types
        import photo_s.cli as cli
        from photo_s.presets import save_preset
        from photo_s.engine import ProcessOptions
        save_preset("web", ProcessOptions(quality=70, suffix="_web"), "")
        parsed = types.SimpleNamespace(command="batch", preset="web")
        options = ProcessOptions(suffix="_processed")
        out = cli._apply_preset_defaults(options, parsed)
        assert out.suffix == "_web"   # non-default preset value applies
        assert out.quality == 70


class TestPresetSafety:
    def test_load_strips_destructive_fields(self, tmp_path, monkeypatch):
        """A shared preset carrying remove_original/overwrite must not
        become 'delete the originals' when loaded."""
        import json
        from photo_s import presets as P
        monkeypatch.setattr(P, "PRESETS_DIR", tmp_path)
        (tmp_path / "evil.json").write_text(json.dumps({
            "quality": 70, "remove_original": True, "overwrite": True,
            "curves": "0,0;255,200",
        }), encoding="utf-8")
        opts = P.load_preset("evil")
        assert opts is not None
        assert opts.remove_original is False
        assert opts.overwrite is False
        assert opts.quality == 70
        assert opts.curves == "0,0;255,200"

    def test_import_strips_destructive_fields(self, tmp_path, monkeypatch):
        import json
        from photo_s import presets as P
        monkeypatch.setattr(P, "PRESETS_DIR", tmp_path)
        pkg = tmp_path / "pkg.json"
        pkg.write_text(json.dumps({
            "boom": {"remove_original": True, "brightness": 1.2}}),
            encoding="utf-8")
        assert P.import_presets_from_json(str(pkg)) == 1
        data = json.loads((tmp_path / "boom.json").read_text())
        assert "remove_original" not in data
        assert data["brightness"] == 1.2
