"""Tests for photographer batch features: metadata tagging/filtering (core),
cull, checksum manifests, HTML gallery, white balance / auto-levels /
print-size, dedup keep-sharpest, EV / auto-exposure / LOG recovery /
denoise / auto-straighten."""

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PIL import Image

from photo_s.cli import run_cli
from photo_s.engine import (read_exif_metadata, apply_exif_tags,
                            _parse_print_size)
from photo_s.adjust import (apply_auto_levels, apply_white_balance,
                            apply_exposure)
from photo_s.dedup import handle_duplicates


def _img(path, color=(120, 100, 80), size=(64, 48)):
    Image.new("RGB", size, color).save(str(path), quality=95)
    return str(path)


class TestExifTagAndFilter:
    """批量打标 + 按打标筛选（工作流核心）。"""

    def test_write_and_read_rating_keywords_title(self, tmp_path):
        img = _img(tmp_path / "a.jpg")
        rc = run_cli(["exif", img, "--rating", "4", "--keywords", "beach,trip",
                      "--title", "Summer"])
        assert rc == 0
        m = read_exif_metadata(img)
        assert m["rating"] == 4
        assert m["keywords"] == ["beach", "trip"]
        assert m["title"] == "Summer"

    def test_clear_rating_keywords_title(self, tmp_path):
        """rating=None / keywords='' / title='' explicitly clear the
        fields (the undo path relies on this semantics)."""
        img = _img(tmp_path / "a.jpg")
        apply_exif_tags(img, {"rating": 4, "keywords": "beach,trip",
                              "title": "Summer"})
        assert read_exif_metadata(img)["rating"] == 4
        apply_exif_tags(img, {"rating": None, "keywords": "", "title": ""})
        m = read_exif_metadata(img)
        assert m["rating"] is None
        assert m["keywords"] == []
        assert m["title"] == ""

    def test_write_and_read_multiword_title(self, tmp_path):
        """Multi-word titles round-trip: title= is the last UserComment
        segment, so the parser must join the remaining tokens."""
        img = _img(tmp_path / "a.jpg")
        rc = run_cli(["exif", img, "--title", "Summer Trip 2026"])
        assert rc == 0
        m = read_exif_metadata(img)
        assert m["title"] == "Summer Trip 2026"

    def test_roundtrip_via_subprocess_persists(self, tmp_path):
        """Regression: running as `python -m photo_s.cli` (__main__) used to
        truncate the written EXIF; the console-script path is equivalent."""
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        img = _img(tmp_path / "a.jpg")
        subprocess.run([sys.executable, "-m", "photo_s.cli", "exif", img,
                        "--rating", "4", "--keywords", "x"], check=True,
                       cwd=repo)
        m = read_exif_metadata(img)
        assert m["rating"] == 4
        assert m["keywords"] == ["x"]

    def test_preserve_existing_usercomment(self, tmp_path):
        img = _img(tmp_path / "a.jpg")
        apply_exif_tags(img, {"rating": 4})
        apply_exif_tags(img, {"keywords": "beach"})  # rating must survive
        m = read_exif_metadata(img)
        assert m["rating"] == 4
        assert m["keywords"] == ["beach"]

    def test_filter_rating_min(self, tmp_path, capsys):
        a = _img(tmp_path / "a.jpg")
        b = _img(tmp_path / "b.jpg")
        run_cli(["exif", a, "--rating", "4"])
        run_cli(["exif", b, "--rating", "2"])
        capsys.readouterr()  # drain write-mode progress
        rc = run_cli(["exif", str(tmp_path), "-r", "--show", "--rating-min", "3",
                      "--list"])
        assert rc == 0
        lines = [l for l in capsys.readouterr().out.splitlines() if l.strip()]
        assert len(lines) == 1
        assert os.path.basename(lines[0]) == "a.jpg"

    def test_filter_exact_rating_and_keywords(self, tmp_path, capsys):
        a = _img(tmp_path / "a.jpg")
        b = _img(tmp_path / "b.jpg")
        run_cli(["exif", a, "--rating", "4", "--keywords", "beach"])
        run_cli(["exif", b, "--rating", "5", "--keywords", "trip"])
        capsys.readouterr()
        run_cli(["exif", str(tmp_path), "-r", "--show", "--keywords", "trip",
                 "--list"])
        assert os.path.basename(capsys.readouterr().out.splitlines()[0]) == "b.jpg"
        run_cli(["exif", str(tmp_path), "-r", "--show", "--rating", "4", "--list"])
        assert os.path.basename(capsys.readouterr().out.splitlines()[0]) == "a.jpg"

    def test_filter_camera_and_date(self, tmp_path, capsys):
        a = _img(tmp_path / "a.jpg")
        b = _img(tmp_path / "b.jpg")
        apply_exif_tags(a, {"model": "ILCE-7M4", "date": "2024:07:30 10:00:00"})
        apply_exif_tags(b, {"model": "D850", "date": "2023:01:01 09:00:00"})
        run_cli(["exif", str(tmp_path), "-r", "--show", "--camera", "ilce",
                 "--list"])
        assert os.path.basename(capsys.readouterr().out.splitlines()[0]) == "a.jpg"
        run_cli(["exif", str(tmp_path), "-r", "--show", "--date-from",
                 "2024-01-01", "--list"])
        assert os.path.basename(capsys.readouterr().out.splitlines()[0]) == "a.jpg"

    def test_show_json(self, tmp_path, capsys):
        img = _img(tmp_path / "a.jpg")
        run_cli(["exif", img, "--rating", "3"])
        capsys.readouterr()
        rc = run_cli(["exif", img, "--show", "--json"])
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert d["count"] == 1
        assert d["results"][0]["rating"] == 3

    def test_from_csv_absolute(self, tmp_path, capsys):
        a = _img(tmp_path / "a.jpg")
        b = _img(tmp_path / "b.jpg")
        csv_path = tmp_path / "m.csv"
        csv_path.write_text(
            f"path,rating,keywords,caption\n{a},5,wedding,final\n{b},3,party,\n",
            encoding="utf-8")
        rc = run_cli(["exif", "--from-csv", str(csv_path)])
        assert rc == 0
        assert read_exif_metadata(a)["rating"] == 5
        assert read_exif_metadata(a)["caption"] == "final"
        assert read_exif_metadata(b)["rating"] == 3

    def test_from_csv_relative_path(self, tmp_path, monkeypatch, capsys):
        img = _img(tmp_path / "a.jpg")
        csv_path = tmp_path / "m.csv"
        csv_path.write_text("path,rating\na.jpg,4\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        rc = run_cli(["exif", "--from-csv", str(csv_path)])
        assert rc == 0
        assert read_exif_metadata(img)["rating"] == 4


class TestCull:
    def test_exposure_stats(self, tmp_path, capsys):
        _img(tmp_path / "bright.jpg", color=(255, 255, 255))
        _img(tmp_path / "dark.jpg", color=(3, 3, 3))
        _img(tmp_path / "normal.jpg", color=(128, 128, 128))
        rc = run_cli(["cull", str(tmp_path), "-r", "--json"])
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        by_name = {os.path.basename(r["path"]): r for r in d["results"]}
        assert by_name["bright.jpg"]["overexposed_pct"] > 90
        assert by_name["dark.jpg"]["underexposed_pct"] > 90
        assert 0.3 < by_name["normal.jpg"]["luminance"] < 0.7

    def test_filter_overexposed(self, tmp_path, capsys):
        _img(tmp_path / "bright.jpg", color=(255, 255, 255))
        _img(tmp_path / "normal.jpg", color=(128, 128, 128))
        rc = run_cli(["cull", str(tmp_path), "-r", "--overexposed-max", "50",
                      "--list"])
        names = [os.path.basename(l) for l in
                 capsys.readouterr().out.splitlines() if l.strip()]
        assert names == ["normal.jpg"]

    def test_filter_underexposed(self, tmp_path, capsys):
        _img(tmp_path / "dark.jpg", color=(3, 3, 3))
        _img(tmp_path / "normal.jpg", color=(128, 128, 128))
        run_cli(["cull", str(tmp_path), "-r", "--underexposed-max", "10",
                 "--list"])
        names = [os.path.basename(l) for l in
                 capsys.readouterr().out.splitlines() if l.strip()]
        assert names == ["normal.jpg"]


class TestHashManifest:
    def test_generate_and_verify(self, tmp_path, capsys):
        a = _img(tmp_path / "a.jpg")
        b = _img(tmp_path / "b.jpg")
        manifest = tmp_path / "m.csv"
        rc = run_cli(["hash", str(tmp_path), "-r", "-o", str(manifest), "--json"])
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert d["count"] == 2

        assert run_cli(["hash", "--verify", str(manifest)]) == 0
        with open(a, "ab") as f:
            f.write(b"x")  # tamper → mismatch
        assert run_cli(["hash", "--verify", str(manifest)]) == 1
        os.unlink(b)  # missing → still exit 1
        assert run_cli(["hash", "--verify", str(manifest)]) == 1

    def test_verify_json_shape(self, tmp_path, capsys):
        a = _img(tmp_path / "a.jpg")
        manifest = tmp_path / "m.csv"
        run_cli(["hash", a, "-o", str(manifest)])
        capsys.readouterr()
        run_cli(["hash", "--verify", str(manifest), "--json"])
        d = json.loads(capsys.readouterr().out)
        assert d["ok"] == 1
        assert d["missing"] == []
        assert d["mismatched"] == []


class TestGallery:
    def test_build(self, tmp_path, capsys):
        a = _img(tmp_path / "a.jpg")
        b = _img(tmp_path / "b.jpg")
        out = tmp_path / "gal"
        rc = run_cli(["gallery", a, b, "-o", str(out), "--title", "Trip",
                      "--json"])
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert d["count"] == 2
        assert (out / "index.html").exists()
        assert (out / "thumbs" / "1.jpg").exists()
        html = (out / "index.html").read_text(encoding="utf-8")
        assert "<title>Trip</title>" in html


class TestPrintSize:
    def test_parse(self):
        assert _parse_print_size("8x10") == (8.0, 10.0, 300)
        assert _parse_print_size("8x10@72") == (8.0, 10.0, 72)
        assert _parse_print_size("4x6@300dpi") == (4.0, 6.0, 300)
        with pytest.raises(ValueError):
            _parse_print_size("abc")

    def test_print_output_dims(self, tmp_path, capsys):
        img = _img(tmp_path / "a.jpg", size=(400, 300))
        out = tmp_path / "out"
        rc = run_cli(["batch", img, "-o", str(out), "--print-size", "4x3@72dpi",
                      "--json"])
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert d["results"][0]["output_dims"] == [288, 216]  # 4*72 x 3*72


class TestBatchTransforms:
    def test_auto_levels_batch(self, tmp_path, capsys):
        img = _img(tmp_path / "a.jpg", color=(30, 30, 30))
        out = tmp_path / "out"
        rc = run_cli(["batch", img, "-o", str(out), "--auto-levels", "--json"])
        assert rc == 0
        assert json.loads(capsys.readouterr().out)["results"][0]["status"] == "ok"

    def test_wb_batch(self, tmp_path, capsys):
        img = _img(tmp_path / "a.jpg")
        out = tmp_path / "out"
        rc = run_cli(["batch", img, "-o", str(out), "--wb", "5600", "--json"])
        assert rc == 0
        assert json.loads(capsys.readouterr().out)["results"][0]["status"] == "ok"


class TestAdjustUnits:
    def test_auto_levels_expands_range(self):
        im = Image.new("L", (64, 64), 20)
        px = im.load()
        for y in range(8):  # 512 bright pixels (> 2% clip)
            for x in range(64):
                px[x, y] = 200
        out = apply_auto_levels(im)
        vals = list(out.getdata())  # getdata works across supported Pillows
        assert min(vals) <= 5   # dark end stretched toward black
        assert max(vals) >= 250  # bright end stretched toward white

    def test_auto_levels_solid_unchanged(self):
        im = Image.new("L", (32, 32), 30)
        assert apply_auto_levels(im).getpixel((0, 0)) == 30

    def test_white_balance_temp(self):
        im = Image.new("RGB", (16, 16), (128, 128, 128))
        out = apply_white_balance(im, temp=4000)  # correct warm light
        r, g, b = out.split()
        # 4000K 暖光 → 降红提蓝，向中性 6500K 靠
        assert b.getpixel((0, 0)) > r.getpixel((0, 0))

    def test_white_balance_reference_neutralizes(self, tmp_path):
        ref = tmp_path / "ref.png"
        Image.new("RGB", (16, 16), (100, 128, 150)).save(ref)  # bluish-gray
        im = Image.new("RGB", (16, 16), (100, 128, 150))
        out = apply_white_balance(im, reference=str(ref))
        r, g, b = out.split()
        # 校正后应趋于中性（三通道接近）
        assert abs(r.getpixel((0, 0)) - g.getpixel((0, 0))) <= 3
        assert abs(g.getpixel((0, 0)) - b.getpixel((0, 0))) <= 3


class TestKeepSharpest:
    def test_keeps_sharpest(self, tmp_path):
        from PIL import ImageDraw
        base = Image.new("L", (48, 48), 128)
        sharp = base.copy()
        dr = ImageDraw.Draw(sharp)
        for i in range(0, 48, 4):
            dr.line([(i, 0), (i, 47)], fill=255)
        a = str(tmp_path / "a.jpg")
        b = str(tmp_path / "b.jpg")
        sharp.save(a)
        base.save(b)
        groups = {"h": [a, b]}
        kept, removed = handle_duplicates(groups, action="keep-sharpest",
                                          dry_run=True)
        assert removed == 1
        handle_duplicates(groups, action="keep-sharpest")
        assert os.path.exists(a) and not os.path.exists(b)  # sharp kept


class TestExposure:
    def test_ev_gain(self):
        im = Image.new("RGB", (16, 16), (60, 60, 60))
        out = apply_exposure(im, ev=1.0)
        assert out.getpixel((0, 0)) == (120, 120, 120)  # 2^1 gain

    def test_ev_minus(self):
        im = Image.new("RGB", (16, 16), (100, 100, 100))
        out = apply_exposure(im, ev=-1.0)
        assert out.getpixel((0, 0)) == (50, 50, 50)

    def test_auto_exposure_normalizes(self):
        im = Image.new("RGB", (64, 64), (60, 60, 60))  # mean 60/255 ≈ 0.235
        out = apply_exposure(im, auto_exposure=0.5)
        gray = out.convert("L")
        mean = sum(gray.getdata()) / (64 * 64)
        assert 125 <= mean <= 130  # ~128

    def test_batch_ev(self, tmp_path, capsys):
        img = _img(tmp_path / "a.jpg", color=(60, 60, 60))
        out = tmp_path / "out"
        rc = run_cli(["batch", img, "-o", str(out), "--ev", "1", "--json"])
        assert rc == 0
        assert json.loads(capsys.readouterr().out)["results"][0]["status"] == "ok"


class TestLogRecovery:
    def test_all_curves_lut_monotonic(self):
        from photo_s.logcurve import LOG_CURVES, build_log_recovery_lut
        for name in LOG_CURVES:
            lut = build_log_recovery_lut(name)
            assert lut[0] == 0 and lut[255] == 255
            assert all(lut[i] <= lut[i + 1] for i in range(255)), name

    def test_batch_log_curve(self, tmp_path, capsys):
        img = _img(tmp_path / "a.jpg")
        out = tmp_path / "out"
        rc = run_cli(["batch", img, "-o", str(out), "--log-curve", "SLOG3",
                      "--json"])
        assert rc == 0
        assert json.loads(capsys.readouterr().out)["results"][0]["status"] == "ok"


class TestDenoise:
    def test_reduces_noise(self):
        cv2 = pytest.importorskip("cv2")
        import numpy as np
        from photo_s.denoise import apply_denoise
        noisy = Image.fromarray(
            np.random.default_rng(0).normal(128, 25, (200, 300, 3)).astype("uint8"))
        out = apply_denoise(noisy, 10)
        arr = np.asarray(out.convert("L"))
        assert arr.std() < 12  # was ~25

    def test_missing_cv2_clear_error(self, monkeypatch):
        import builtins
        from photo_s.denoise import apply_denoise
        real = builtins.__import__

        def fake(name, *a, **k):
            if name == "cv2":
                raise ImportError("No module named 'cv2'")
            return real(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake)
        with pytest.raises(RuntimeError, match="enhance"):
            apply_denoise(Image.new("RGB", (8, 8)), 10)

    def test_batch_denoise(self, tmp_path, capsys, monkeypatch):
        pytest.importorskip("cv2")
        # hermetic: force the NLM fallback even if a denoise provider plugin
        # (e.g. editable-installed scunet) is present in the dev environment
        from photo_s import plugin as _plugin_mod
        monkeypatch.setattr(_plugin_mod, "discover_plugins", lambda: [])
        img = _img(tmp_path / "a.jpg")
        out = tmp_path / "out"
        rc = run_cli(["batch", img, "-o", str(out), "--denoise", "10", "--json"])
        assert rc == 0
        assert json.loads(capsys.readouterr().out)["results"][0]["status"] == "ok"


class TestAutoStraighten:
    def _tilted(self, tmp_path, angle_deg=6.0):
        import math
        pytest.importorskip("cv2")
        import cv2
        import numpy as np
        w, h = 500, 300
        img = np.full((h, w, 3), 90, "uint8")
        y0 = h // 2 - int(w / 2 * math.tan(math.radians(angle_deg)))
        y1 = h // 2 + int(w / 2 * math.tan(math.radians(angle_deg)))
        cv2.line(img, (0, y0), (w, y1), (255, 255, 255), 4)
        cv2.rectangle(img, (0, max(y0, y1)), (w, h), (40, 40, 40), -1)
        p = str(tmp_path / "tilted.jpg")
        Image.fromarray(img).save(p)
        return p

    def test_detect_and_apply(self, tmp_path):
        pytest.importorskip("cv2")
        from photo_s.straighten import (detect_horizon_angle,
                                        apply_auto_straighten)
        im = Image.open(self._tilted(tmp_path))
        angle = detect_horizon_angle(im)
        assert angle is not None and abs(angle - 6.0) < 1.0
        out, ok = apply_auto_straighten(im)
        assert ok is True
        # 扶正后重新检测 → 接近 0
        assert abs(detect_horizon_angle(out) or 0.0) < 0.5

    def test_flat_image_not_straightened(self, tmp_path):
        pytest.importorskip("cv2")
        from photo_s.straighten import apply_auto_straighten
        im = _img(tmp_path / "flat.jpg", color=(90, 90, 90), size=(320, 240))
        out, ok = apply_auto_straighten(Image.open(im))
        assert ok is False
        assert out.size == Image.open(im).size  # unchanged

    def test_batch_reports_straightened(self, tmp_path, capsys):
        pytest.importorskip("cv2")
        tilted = self._tilted(tmp_path)
        out = tmp_path / "out"
        rc = run_cli(["batch", tilted, "-o", str(out), "--auto-straighten",
                      "--json"])
        assert rc == 0
        r = json.loads(capsys.readouterr().out)["results"][0]
        assert r["status"] == "ok"
        assert r["auto_straightened"] is True
