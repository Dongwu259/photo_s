"""Tests for the bench command (photo_s.bench + CLI wiring)."""

import json
import os
import sys
import tempfile

import pytest

# Ensure src package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

from photo_s import bench
from photo_s.cli import run_cli
from photo_s.engine import ProcessOptions


def _photos(dir_path, n=3, size=(400, 300)):
    """Create n JPEGs with real pixel content (gradients, not flat
    solids) so PSNR/SSIM comparisons against the outputs are meaningful.
    400x300 keeps each bench run above Windows' ~15.6ms monotonic-clock
    resolution (a whole run inside one tick measures 0.0s and zeroes the
    baseline speedup)."""
    paths = []
    for i in range(n):
        img = Image.new("RGB", size)
        px = img.load()
        for y in range(size[1]):
            for x in range(size[0]):
                px[x, y] = ((x * 3 + i * 40) % 256,
                            (y * 5 + i * 20) % 256,
                            ((x + y) * 2 + i * 60) % 256)
        p = dir_path / f"photo_{i}.jpg"
        img.save(p, format="JPEG", quality=95)
        paths.append(str(p))
    return paths


def _bench_tmps():
    return {d for d in os.listdir(tempfile.gettempdir())
            if d.startswith(bench.TMP_PREFIX)}


def _bench_json(capsys, argv):
    rc = run_cli(argv + ["--json"])
    assert rc == 0
    return json.loads(capsys.readouterr().out)


class TestBenchCleanliness:
    def test_source_dir_untouched(self, tmp_path, capsys):
        src = tmp_path / "photos"
        src.mkdir()
        _photos(src)
        before = sorted(os.listdir(src))
        tmps_before = _bench_tmps()

        rc = run_cli(["bench", "--dir", str(src), "-j", "1,2"])
        capsys.readouterr()

        assert rc == 0
        assert sorted(os.listdir(src)) == before
        assert _bench_tmps() <= tmps_before

    def test_interrupt_cleans_up(self, tmp_path, monkeypatch):
        src = tmp_path / "photos"
        src.mkdir()
        files = _photos(src, n=1)
        tmps_before = _bench_tmps()

        def boom(*args, **kwargs):
            raise KeyboardInterrupt

        monkeypatch.setattr(bench.engine, "batch_process", boom)
        with pytest.raises(KeyboardInterrupt):
            bench.run_benchmark(files, [1], ProcessOptions())

        assert sorted(os.listdir(src)) == ["photo_0.jpg"]
        assert _bench_tmps() <= tmps_before

    def test_engine_functions_restored(self, tmp_path):
        src = tmp_path / "photos"
        src.mkdir()
        files = _photos(src, n=1)
        orig = bench.engine.process_image
        bench.run_benchmark(files, [1], ProcessOptions())
        assert bench.engine.process_image is orig
        assert not hasattr(bench.engine.process_image, "__wrapped__")


class TestBenchReport:
    def test_json_structure(self, tmp_path, capsys):
        src = tmp_path / "photos"
        src.mkdir()
        _photos(src)
        out = _bench_json(capsys, ["bench", "--dir", str(src), "-j", "1,2"])

        assert out["files"] == 3
        assert out["evaluate"] is None
        assert [r["jobs"] for r in out["runs"]] == [1, 2]
        for r in out["runs"]:
            assert r["files"] == 3
            assert r["seconds"] >= 0
            # >= 0 not > 0: a whole run inside one low-resolution clock tick
            # (Windows monotonic ~15.6ms) measures 0.0s → baseline 0.0 →
            # speedup 0.0/positive = 0.0. A measurement artifact, not a bug.
            assert r["speedup"] >= 0
            assert r["errors"] == 0
            stages = r["stages"]
            assert set(stages) == {"load", "process", "save"}
            assert all(v >= 0 for v in stages.values())
        assert out["runs"][0]["speedup"] == 1.0  # baseline run

    def test_stage_sum_matches_wall_time(self, tmp_path, capsys):
        src = tmp_path / "photos"
        src.mkdir()
        _photos(src)
        out = _bench_json(capsys, ["bench", "--dir", str(src), "-j", "1"])

        r = out["runs"][0]
        total = sum(r["stages"].values())
        # jobs=1 is sequential: stage worker-time sums to the pipeline
        # time, which is the wall time minus dispatch overhead.
        assert total <= r["seconds"] + 0.01
        assert r["seconds"] - total <= 0.05
        if r["seconds"] >= 0.01:
            assert total >= r["seconds"] * 0.5  # same order of magnitude

    def test_evaluate_reports_psnr_and_ssim(self, tmp_path, capsys):
        src = tmp_path / "photos"
        src.mkdir()
        _photos(src)
        out = _bench_json(
            capsys, ["bench", "--dir", str(src), "-j", "1", "--evaluate"])

        ev = out["evaluate"]
        assert ev["files"] == 3
        assert ev["psnr_db"] is not None and ev["psnr_db"] > 10
        assert 0.5 < ev["ssim"] <= 1.0

    def test_human_output_shows_stages_and_evaluate(self, tmp_path, capsys):
        src = tmp_path / "photos"
        src.mkdir()
        _photos(src)
        rc = run_cli(["bench", "--dir", str(src), "-j", "1", "--evaluate"])
        assert rc == 0
        text = capsys.readouterr().out
        assert "speedup=" in text
        assert "load=" in text and "process=" in text and "save=" in text
        assert "PSNR=" in text and "SSIM=" in text


class TestBenchArgs:
    def test_bad_jobs_letters(self, tmp_path, capsys):
        src = tmp_path / "photos"
        src.mkdir()
        _photos(src, n=1)
        assert run_cli(["bench", "--dir", str(src), "-j", "a,b"]) == 1
        capsys.readouterr()

    def test_bad_jobs_zero(self, tmp_path, capsys):
        src = tmp_path / "photos"
        src.mkdir()
        _photos(src, n=1)
        assert run_cli(["bench", "--dir", str(src), "-j", "0"]) == 1
        capsys.readouterr()

    def test_empty_dir(self, tmp_path, capsys):
        src = tmp_path / "empty"
        src.mkdir()
        assert run_cli(["bench", "--dir", str(src)]) == 1
        capsys.readouterr()
