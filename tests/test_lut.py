"""LUT engine core: .cube parse, trilinear apply, engine slot."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PIL import Image

from photo_s.lut import LutError, apply_lut, load_cube


def _write_cube(path, size, mode="identity"):
    """Write a synthetic 3D .cube; ``mode`` is identity / swap / redout."""
    rows = []
    for b in range(size):
        for g in range(size):
            for r in range(size):
                if mode == "identity":
                    out = (r, g, b)
                elif mode == "swap":
                    out = (b, g, r)
                else:
                    out = (r, 0, 0)
                rows.append(f"{out[0] / (size - 1):.6f} "
                            f"{out[1] / (size - 1):.6f} "
                            f"{out[2] / (size - 1):.6f}")
    path.write_text(
        f"# test lut\nLUT_3D_SIZE {size}\n" + "\n".join(rows) + "\n")


def _write_cube_1d(path, size=4):
    """1D LUT that darkens: output = input * 0.5 per channel."""
    rows = [f"{i / (size - 1) * 0.5:.6f} " * 3
            for i in range(size)]
    path.write_text(f"LUT_1D_SIZE {size}\n" + "\n".join(rows) + "\n")


class TestLoadCube:
    def test_identity_3d_shape(self, tmp_path):
        p = tmp_path / "id.cube"
        _write_cube(p, size=2)
        kind, size, table = load_cube(str(p))
        assert kind == "3d"
        assert size == 2
        assert table.shape == (2, 2, 2, 3)
        # table[b, g, r] = (r, g, b) for identity
        assert tuple(table[1, 0, 1]) == pytest.approx((1.0, 0.0, 1.0))

    def test_swap_ordering(self, tmp_path):
        p = tmp_path / "swap.cube"
        _write_cube(p, size=2, mode="swap")
        _k, _s, table = load_cube(str(p))
        # input (r=1,g=0,b=0) → output (0, 0, 1): R becomes B
        assert tuple(table[0, 0, 1]) == pytest.approx((0.0, 0.0, 1.0))

    def test_1d_shape(self, tmp_path):
        p = tmp_path / "d.cube"
        _write_cube_1d(p)
        kind, size, table = load_cube(str(p))
        assert kind == "1d"
        assert size == 4
        assert table.shape == (4, 3)

    def test_malformed_raises(self, tmp_path):
        p = tmp_path / "bad.cube"
        p.write_text("LUT_3D_SIZE 2\n0.1 0.2\n")  # wrong row count
        with pytest.raises(LutError):
            load_cube(str(p))

    def test_not_a_lut_raises(self, tmp_path):
        p = tmp_path / "no.cube"
        p.write_text("hello world\n")
        with pytest.raises(LutError):
            load_cube(str(p))


class TestApply:
    def test_identity_3d_preserves(self, tmp_path):
        p = tmp_path / "id.cube"
        _write_cube(p, size=17)
        im = Image.new("RGB", (8, 8), (100, 150, 200))
        out = apply_lut(im, str(p))
        px = out.convert("RGB").getpixel((3, 3))
        assert abs(px[0] - 100) <= 3 and abs(px[1] - 150) <= 3

    def test_swap_red_blue(self, tmp_path):
        p = tmp_path / "swap.cube"
        _write_cube(p, size=17, mode="swap")
        im = Image.new("RGB", (4, 4), (200, 50, 30))
        out = apply_lut(im, str(p))
        px = out.convert("RGB").getpixel((1, 1))
        # input R=200 ≈ 0.78 → output B≈0.78*255≈200; input B=30→R≈30
        assert abs(px[0] - 30) <= 8
        assert abs(px[2] - 200) <= 8

    def test_1d_darkens(self, tmp_path):
        p = tmp_path / "d.cube"
        _write_cube_1d(p)
        im = Image.new("RGB", (4, 4), (100, 100, 100))
        out = apply_lut(im, str(p))
        px = out.convert("RGB").getpixel((0, 0))
        assert abs(px[0] - 50) <= 5  # half brightness

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(LutError):
            apply_lut(Image.new("RGB", (4, 4)), str(tmp_path / "nope.cube"))


class TestEngineSlot:
    """--lut flows through the pipeline (built-in fallback, no provider)."""

    def test_process_with_lut(self, tmp_path):
        from photo_s.engine import ProcessOptions, batch_process
        p = tmp_path / "id.cube"
        _write_cube(p, size=17)
        src = tmp_path / "in.png"
        Image.new("RGB", (16, 16), (120, 80, 40)).save(src)
        out_dir = tmp_path / "out"
        result = batch_process(
            [str(src)],
            ProcessOptions(output_dir=str(out_dir), overwrite=True,
                           output_format="PNG", lut_file=str(p), suffix=""),
        )
        assert result.success_count == 1
        assert (out_dir / "in.png").exists()


class TestApply1dMultiMode:
    """Regression: 1D LUT assumed exactly 3 bands (crashed on RGBA/L/P)."""

    def _cube(self, tmp_path):
        p = tmp_path / "d.cube"
        p.write_text("LUT_1D_SIZE 4\n0 0 0\n0.2 0.2 0.2\n0.5 0.5 0.5\n0.8 0.8 0.8\n")
        return str(p)

    def test_rgba_keeps_alpha(self, tmp_path):
        im = Image.new("RGBA", (8, 8), (100, 100, 100, 200))
        out = apply_lut(im, self._cube(tmp_path))
        assert out.mode == "RGBA"
        assert out.getpixel((0, 0))[3] == 200

    def test_grayscale_ok(self, tmp_path):
        im = Image.new("L", (8, 8), 128)
        out = apply_lut(im, self._cube(tmp_path))
        assert out.mode == "L"

    def test_palette_converts(self, tmp_path):
        im = Image.new("P", (8, 8))
        out = apply_lut(im, self._cube(tmp_path))
        assert out.mode == "RGB"

    def test_la_converts(self, tmp_path):
        im = Image.new("LA", (8, 8), (128, 255))
        out = apply_lut(im, self._cube(tmp_path))
        assert out.mode == "RGB"

    def test_cmyk_converts(self, tmp_path):
        im = Image.new("CMYK", (8, 8), (0, 0, 0, 0))
        out = apply_lut(im, self._cube(tmp_path))
        assert out.mode == "RGB"

    def test_single_band_exotics_convert(self, tmp_path):
        # Regression: I;16/F/1 crashed unpacking r,g,b = img.split()
        cube = self._cube(tmp_path)
        for mode, color in [("I;16", 1000), ("F", 0.5), ("1", 1)]:
            out = apply_lut(Image.new(mode, (8, 8), color), cube)
            assert out.mode == "RGB"
