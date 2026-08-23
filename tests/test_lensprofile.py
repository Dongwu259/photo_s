"""Lens profile registry + engine resolution tests."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PIL import Image

from photo_s.engine import process_image, ProcessOptions


@pytest.fixture
def profiles_dir(tmp_path, monkeypatch):
    d = tmp_path / "lens_profiles.json"
    monkeypatch.setattr("photo_s.lensprofile.PROFILES_PATH", d)
    return d


class TestLensProfileRegistry:
    def test_save_load_roundtrip(self, profiles_dir):
        from photo_s.lensprofile import (save_lens_profile, load_lens_profile,
                                         list_lens_profiles, lens_profile_names)
        save_lens_profile("RF 24-70", distort=0.012, vignette="0.3,0.5",
                          ca="0.999,1.001", description="zoom")
        prof = load_lens_profile("RF 24-70")
        assert prof["distort"] == 0.012
        assert prof["vignette"] == "0.3,0.5"
        assert prof["ca"] == "0.999,1.001"
        assert any("RF 24-70" in p and "zoom" in p for p in list_lens_profiles())
        assert "RF 24-70" in lens_profile_names()

    def test_save_partial(self, profiles_dir):
        from photo_s.lensprofile import save_lens_profile, load_lens_profile
        save_lens_profile("prime", distort=0.005)
        prof = load_lens_profile("prime")
        assert prof["distort"] == 0.005
        assert "vignette" not in prof

    def test_unknown_returns_none(self, profiles_dir):
        from photo_s.lensprofile import load_lens_profile
        assert load_lens_profile("nope") is None

    def test_delete(self, profiles_dir):
        from photo_s.lensprofile import (save_lens_profile, delete_lens_profile,
                                         load_lens_profile)
        save_lens_profile("x", distort=0.1)
        assert delete_lens_profile("x") is True
        assert load_lens_profile("x") is None
        assert delete_lens_profile("x") is False  # already gone


def _make_src(tmp_path):
    src = tmp_path / "src.jpg"
    Image.new("RGB", (60, 40), (100, 150, 200)).save(src)
    return str(src)


class TestLensProfileEngine:
    def test_profile_resolves_lens_params(self, tmp_path, profiles_dir):
        from photo_s.lensprofile import save_lens_profile
        save_lens_profile("kit", distort=0.01, vignette="0.2,0.5",
                          ca="0.999,1.001")
        r = process_image(
            _make_src(tmp_path), ProcessOptions(
                output_dir=str(tmp_path / "out"), suffix="_out",
                lens_profile="kit"))
        assert r.success

    def test_explicit_lens_args_win(self, tmp_path, profiles_dir):
        from photo_s.lensprofile import save_lens_profile
        save_lens_profile("kit", distort=0.99)
        # explicit --lens-distort overrides the profile's value
        r = process_image(
            _make_src(tmp_path), ProcessOptions(
                output_dir=str(tmp_path / "out2"), suffix="_out",
                lens_profile="kit", lens_distort=0.5))
        assert r.success

    def test_unknown_profile_is_per_file_error(self, tmp_path, profiles_dir):
        r = process_image(
            _make_src(tmp_path), ProcessOptions(
                output_dir=str(tmp_path / "out3"), suffix="_out",
                lens_profile="no-such-lens"))
        assert not r.success
        assert "no-such-lens" in r.error

    def test_profile_applies_vignette_pixels(self, tmp_path, profiles_dir):
        # a strong vignette profile visibly darkens the corners
        from photo_s.lensprofile import save_lens_profile
        save_lens_profile("strong", vignette="0.8,0.5")
        arr = Image.new("RGB", (80, 80), (200, 200, 200))
        src = tmp_path / "flat.jpg"
        arr.save(src)
        r = process_image(
            str(src), ProcessOptions(
                output_dir=str(tmp_path / "out4"), suffix="_out",
                lens_profile="strong"))
        out = Image.open(r.output_path)
        center = out.getpixel((40, 40))[0]
        corner = out.getpixel((2, 2))[0]
        assert corner > center  # vignette fix lifts the corners
