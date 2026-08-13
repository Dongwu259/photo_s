"""Engine-level tests for the operation-provider interface.

Proves:
  * a plugin with provides=("denoise",) is invoked at the denoise slot
    (batch --denoise N goes through provider.denoise),
  * provider plugins are excluded from the generic on_pre_process pass,
  * with no provider, the engine falls back to the built-in NLM.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PIL import Image

from photo_s.cli import run_cli
from photo_s.hooks import PhotoSPlugin
from photo_s import plugin as plugin_mod


class _MarkerDenoise(PhotoSPlugin):
    """Provider that paints a known marker block into the denoised image."""
    name = "marker-denoise"
    provides = ("denoise",)
    pre_called = False

    def denoise(self, img, strength, ctx):
        # paint a distinctive block so we can detect the provider path
        # (single-pixel markers get lost to JPEG chroma subsampling)
        px = img.load()
        for y in range(0, 8):
            for x in range(0, 8):
                px[x, y] = (255, 0, 255)
        return img

    def on_pre_process(self, img, options, ctx):
        type(self).pre_called = True


def _img(path, color=(120, 100, 80), size=(16, 16)):
    Image.new("RGB", size, color).save(str(path), quality=95)
    return str(path)


class TestProviderDenoiseSlot:
    def test_provider_used_when_installed(self, tmp_path, monkeypatch, capsys):
        src = _img(tmp_path / "a.jpg")
        out = tmp_path / "out"
        monkeypatch.setattr(plugin_mod, "discover_plugins",
                            lambda: [_MarkerDenoise()])
        rc = run_cli(["batch", src, "-o", str(out), "--denoise", "10",
                      "--json"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert rc == 0
        assert data["results"][0]["status"] == "ok"

        # marker block proves the provider path ran
        res = Image.open(out / "a_processed.jpg").convert("RGB")
        assert res.getpixel((3, 3)) == (255, 0, 255)

    def test_provider_excluded_from_pre_hook(self, tmp_path, monkeypatch, capsys):
        _MarkerDenoise.pre_called = False
        src = _img(tmp_path / "a.jpg")
        out = tmp_path / "out"
        monkeypatch.setattr(plugin_mod, "discover_plugins",
                            lambda: [_MarkerDenoise()])
        run_cli(["batch", src, "-o", str(out), "--denoise", "10", "--json"])
        capsys.readouterr()
        assert _MarkerDenoise.pre_called is False

    def test_provider_not_invoked_without_denoise(self, tmp_path, monkeypatch,
                                                  capsys):
        src = _img(tmp_path / "a.jpg")
        out = tmp_path / "out"
        monkeypatch.setattr(plugin_mod, "discover_plugins",
                            lambda: [_MarkerDenoise()])
        rc = run_cli(["batch", src, "-o", str(out), "--json"])
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        res = Image.open(out / "a_processed.jpg").convert("RGB")
        assert res.getpixel((3, 3)) != (255, 0, 255)

    def test_fallback_to_nlm_without_provider(self, tmp_path, monkeypatch,
                                              capsys):
        cv2 = pytest.importorskip("cv2")  # NLM fallback needs opencv
        src = _img(tmp_path / "a.jpg")
        out = tmp_path / "out"
        calls = []

        def _fake_nlm(img, strength):
            calls.append(strength)
            return img

        monkeypatch.setattr(plugin_mod, "discover_plugins", lambda: [])
        monkeypatch.setattr("photo_s.denoise.apply_denoise", _fake_nlm)
        rc = run_cli(["batch", src, "-o", str(out), "--denoise", "7", "--json"])
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["results"][0]["status"] == "ok"
        assert calls == [7.0]


class TestFindProvider:
    def test_find_provider_none(self, monkeypatch):
        monkeypatch.setattr(plugin_mod, "discover_plugins", lambda: [])
        assert plugin_mod.find_provider("denoise") is None

    def test_find_provider_first_wins(self, monkeypatch):
        class _A(PhotoSPlugin):
            provides = ("denoise",)
        class _B(PhotoSPlugin):
            provides = ("denoise",)
        a, b = _A(), _B()
        monkeypatch.setattr(plugin_mod, "discover_plugins", lambda: [a, b])
        assert plugin_mod.find_provider("denoise") is a

    def test_find_provider_ignores_filters(self, monkeypatch):
        class _F(PhotoSPlugin):
            pass  # no provides → filter only
        assert _F.provides == ()
        monkeypatch.setattr(plugin_mod, "discover_plugins", lambda: [_F()])
        assert plugin_mod.find_provider("denoise") is None

    def test_clear_cache(self, monkeypatch):
        plugin_mod._PLUGINS = ["stale"]
        plugin_mod.clear_cache()
        assert plugin_mod._PLUGINS is None


class _MarkerLut(PhotoSPlugin):
    """LUT provider that paints a known marker block instead of grading."""
    name = "marker-lut"
    provides = ("lut",)
    pre_called = False

    def lut(self, img, lut_path, ctx):
        px = img.load()
        for y in range(0, 8):
            for x in range(0, 8):
                px[x, y] = (0, 255, 0)  # unmistakable green block
        return img

    def on_pre_process(self, img, options, ctx):
        type(self).pre_called = True


class TestProviderLutSlot:
    """--lut flows to the provider when installed; falls back to built-in."""

    def _make_cube(self, tmp_path):
        p = tmp_path / "id.cube"
        rows = []
        n = 17
        for b in range(n):
            for g in range(n):
                for r in range(n):
                    rows.append(f"{r/(n-1):.6f} {g/(n-1):.6f} {b/(n-1):.6f}")
        p.write_text(f"LUT_3D_SIZE {n}\n" + "\n".join(rows) + "\n")
        return str(p)

    def test_provider_used_when_installed(self, tmp_path, monkeypatch, capsys):
        lut = self._make_cube(tmp_path)
        src = _img(tmp_path / "a.jpg")
        out = tmp_path / "out"
        monkeypatch.setattr(plugin_mod, "discover_plugins",
                            lambda: [_MarkerLut()])
        rc = run_cli(["batch", src, "--lut", lut, "-o", str(out), "--json"])
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert d["results"][0]["status"] == "ok"
        # provider painted green at top-left; built-in identity would keep 120,100,80
        px = Image.open(out / "a_processed.jpg").convert("RGB").getpixel((2, 2))
        assert px[1] > 200 and px[0] < 60  # green block present → provider ran

    def test_builtin_fallback_when_no_provider(self, tmp_path, monkeypatch, capsys):
        lut = self._make_cube(tmp_path)
        src = _img(tmp_path / "b.jpg", color=(120, 100, 80))
        out = tmp_path / "out"
        monkeypatch.setattr(plugin_mod, "discover_plugins", lambda: [])
        rc = run_cli(["batch", src, "--lut", lut, "-o", str(out), "--json"])
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert d["results"][0]["status"] == "ok"
        # identity built-in LUT ≈ unchanged (within JPEG tolerance)
        px = Image.open(out / "b_processed.jpg").convert("RGB").getpixel((2, 2))
        assert abs(px[0] - 120) <= 12 and abs(px[1] - 100) <= 12

    def test_provider_excluded_from_pre_process(self, tmp_path, monkeypatch, capsys):
        lut = self._make_cube(tmp_path)
        src = _img(tmp_path / "c.jpg")
        out = tmp_path / "out"
        _MarkerLut.pre_called = False
        monkeypatch.setattr(plugin_mod, "discover_plugins",
                            lambda: [_MarkerLut()])
        run_cli(["batch", src, "--lut", lut, "-o", str(out)])
        assert _MarkerLut.pre_called is False  # slot provider, not a generic hook

    def test_no_lut_flag_does_not_call_provider(self, tmp_path, monkeypatch, capsys):
        src = _img(tmp_path / "d.jpg")
        out = tmp_path / "out"
        monkeypatch.setattr(plugin_mod, "discover_plugins",
                            lambda: [_MarkerLut()])
        rc = run_cli(["batch", src, "-o", str(out), "--json"])
        assert rc == 0
        px = Image.open(out / "d_processed.jpg").convert("RGB").getpixel((2, 2))
        assert not (px[1] > 200 and px[0] < 60)  # provider not invoked
