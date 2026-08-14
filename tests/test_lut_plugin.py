"""Hermetic tests for the official LUT plugin (plugins/lut).

Mirrors test_scunet_plugin.py: sys.path-insert the plugin source, exercise
presets / tetrahedral apply / engine slot with a monkeypatched
discover_plugins so the dev machine's installed plugins never leak in.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "plugins", "lut"))

import pytest
from PIL import Image

from photo_s.cli import run_cli
from photo_s import plugin as plugin_mod

from photo_s_plugin_lut import LutPlugin, PRESETS, _apply_tetrahedral


def _write_cube(path, size, identity=True):
    rows = []
    for b in range(size):
        for g in range(size):
            for r in range(size):
                if identity:
                    out = (r, g, b)
                else:
                    out = (b, g, r)  # swap R↔B
                rows.append(f"{out[0] / (size - 1):.6f} "
                            f"{out[1] / (size - 1):.6f} "
                            f"{out[2] / (size - 1):.6f}")
    path.write_text(f"LUT_3D_SIZE {size}\n" + "\n".join(rows) + "\n")


def _write_cube_1d(path, size=4):
    rows = [f"{i / (size - 1) * 0.5:.6f} " * 3 for i in range(size)]
    path.write_text(f"LUT_1D_SIZE {size}\n" + "\n".join(rows) + "\n")


class TestPresets:
    def test_five_filmic_presets(self):
        assert set(PRESETS) == {"filmic-v1", "filmic-warm", "cinema-cool",
                                "portrait-soft", "punchy"}
        for name, table in PRESETS.items():
            assert table.shape == (33, 33, 33, 3), name
            assert table.min() >= 0.0 and table.max() <= 1.0, name

    def test_punchy_tone_response(self):
        """contrast>1 S-curve: darkens shadows, brightens highlights."""
        plugin = LutPlugin()
        dark = Image.new("RGB", (8, 8), (60, 60, 60))    # lum ≈ 0.235
        bright = Image.new("RGB", (8, 8), (200, 200, 200))  # lum ≈ 0.784
        out_dark = plugin.lut(dark, "punchy", None)
        out_bright = plugin.lut(bright, "punchy", None)
        assert out_dark.convert("RGB").getpixel((0, 0))[0] < 55
        assert out_bright.convert("RGB").getpixel((0, 0))[0] > 205

    def test_cinema_cool_tints_blue(self):
        plugin = LutPlugin()
        gray = Image.new("RGB", (8, 8), (180, 180, 180))
        out = plugin.lut(gray, "cinema-cool", None).convert("RGB")
        px = out.getpixel((0, 0))
        assert px[2] > px[0]  # blue channel lifted by the cool tint


class TestTetrahedralApply:
    def test_identity_preserves(self, tmp_path):
        p = tmp_path / "id.cube"
        _write_cube(p, size=17, identity=True)
        from photo_s.lut import load_cube
        _k, _s, table = load_cube(str(p))
        im = Image.new("RGB", (16, 16), (100, 150, 200))
        out = _apply_tetrahedral(im, table)
        px = out.convert("RGB").getpixel((3, 3))
        assert abs(px[0] - 100) <= 3 and abs(px[1] - 150) <= 3

    def test_swap_channels(self, tmp_path):
        p = tmp_path / "swap.cube"
        _write_cube(p, size=17, identity=False)
        from photo_s.lut import load_cube
        _k, _s, table = load_cube(str(p))
        im = Image.new("RGB", (8, 8), (200, 50, 30))
        out = _apply_tetrahedral(im, table)
        px = out.convert("RGB").getpixel((1, 1))
        assert abs(px[0] - 30) <= 8 and abs(px[2] - 200) <= 8


class TestLutPluginFile:
    def test_1d_file_via_plugin(self, tmp_path):
        p = tmp_path / "d.cube"
        _write_cube_1d(p)
        plugin = LutPlugin()
        im = Image.new("RGB", (8, 8), (100, 100, 100))
        out = plugin.lut(im, str(p), None)
        assert abs(out.convert("RGB").getpixel((0, 0))[0] - 50) <= 6

    def test_1d_file_via_plugin_exotic_modes(self, tmp_path):
        # Regression: the plugin's 1D path reuses photo_s.lut._apply_1d,
        # which crashed on LA/CMYK/I;16/F (r,g,b = img.split() unpack)
        p = tmp_path / "d.cube"
        _write_cube_1d(p)
        plugin = LutPlugin()
        for mode, color in [("LA", (128, 255)), ("CMYK", (0, 0, 0, 0)),
                            ("I;16", 1000)]:
            out = plugin.lut(Image.new(mode, (8, 8), color), str(p), None)
            assert out.mode == "RGB"

    def test_unknown_preset_raises(self):
        plugin = LutPlugin()
        with pytest.raises(Exception):
            plugin.lut(Image.new("RGB", (4, 4)), "nope-preset", None)

    def test_missing_file_raises(self, tmp_path):
        plugin = LutPlugin()
        with pytest.raises(Exception):
            plugin.lut(Image.new("RGB", (4, 4)),
                       str(tmp_path / "missing.cube"), None)


class TestLutInEngine:
    def test_batch_uses_provider(self, tmp_path, monkeypatch, capsys):
        src = tmp_path / "a.jpg"
        Image.new("RGB", (64, 64), (60, 60, 60)).save(str(src), quality=95)
        out = tmp_path / "out"
        monkeypatch.setattr(plugin_mod, "discover_plugins",
                            lambda: [LutPlugin()])
        rc = run_cli(["batch", str(src), "-o", str(out), "--lut", "punchy",
                      "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["results"][0]["status"] == "ok"
        # dark gray punched darker by the filmic curve
        px = Image.open(out / "a_processed.jpg").convert("RGB").getpixel((4, 4))
        assert px[0] < 60
