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
