"""Tests for photo_s.check — image integrity verification."""

import os
import sys

# Ensure src package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PIL import Image

from photo_s.check import verify_images


class TestVerifyImages:
    def test_valid_images_ok(self, tmp_path):
        p1 = tmp_path / "a.png"
        p2 = tmp_path / "b.jpg"
        Image.new("RGB", (10, 10), (1, 2, 3)).save(p1)
        Image.new("RGB", (10, 10), (4, 5, 6)).save(p2)
        results = verify_images([str(p1), str(p2)])
        assert all(r["ok"] for r in results)
        assert all(r["error"] == "" for r in results)

    def test_truncated_file_broken(self, tmp_path):
        p = tmp_path / "trunc.jpg"
        Image.new("RGB", (64, 64), (1, 2, 3)).save(p)
        data = p.read_bytes()
        p.write_bytes(data[:len(data) // 2])  # cut in half
        results = verify_images([str(p)])
        assert not results[0]["ok"]
        assert results[0]["error"]

    def test_missing_file_broken(self, tmp_path):
        results = verify_images([str(tmp_path / "nope.jpg")])
        assert not results[0]["ok"]

    def test_not_an_image_broken(self, tmp_path):
        p = tmp_path / "fake.png"
        p.write_bytes(b"this is not an image at all")
        results = verify_images([str(p)])
        assert not results[0]["ok"]


class TestVerifyRawSkipped:
    """Regression: PIL has no CR2/NEF/ARW decoder, so verify() condemned
    every camera RAW as corrupt — CI exit codes read healthy RAW archives
    as broken. RAWs must be marked skipped, not corrupt."""

    def test_raw_skipped_not_corrupt(self, tmp_path):
        raw = tmp_path / "shot.CR2"  # uppercase ext must also match
        raw.write_bytes(b"fake raw bytes")
        results = verify_images([str(raw)])
        assert results[0]["ok"]
        assert results[0]["skipped"]
        assert results.skipped == 1

    def test_mixed_results_count(self, tmp_path):
        good = tmp_path / "a.png"
        Image.new("RGB", (10, 10)).save(good)
        bad = tmp_path / "b.png"
        bad.write_bytes(b"garbage")
        raw = tmp_path / "c.nef"
        raw.write_bytes(b"fake")
        results = verify_images([str(good), str(bad), str(raw)])
        assert [r["ok"] for r in results] == [True, False, True]
        assert [r["skipped"] for r in results] == [False, False, True]
        assert results.skipped == 1
        corrupt = [r for r in results if not r["ok"]]
        assert len(corrupt) == 1  # only the truly broken PNG

    def test_no_raw_skipped_zero(self, tmp_path):
        p = tmp_path / "a.png"
        Image.new("RGB", (10, 10)).save(p)
        results = verify_images([str(p)])
        assert results.skipped == 0


class TestChecksumAlgorithmValidation:
    """Regression: unknown algorithm silently fell back to sha256."""

    def test_unknown_algo_raises(self, tmp_path):
        from photo_s.check import compute_checksums
        p = tmp_path / "a.bin"
        p.write_bytes(b"data")
        with pytest.raises(ValueError, match="unsupported checksum algorithm"):
            compute_checksums([str(p)], algorithm="sha99")

    def test_valid_algo_works(self, tmp_path):
        from photo_s.check import compute_checksums
        p = tmp_path / "a.bin"
        p.write_bytes(b"data")
        res = compute_checksums([str(p)], algorithm="md5")
        assert "md5" in res[0]
