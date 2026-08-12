"""Tests for photo_s.check — image integrity verification."""

import os
import sys

# Ensure src package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
