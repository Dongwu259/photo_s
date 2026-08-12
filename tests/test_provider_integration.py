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
