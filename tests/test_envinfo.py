"""Tests for photo_s.envinfo — environment probing (was previously untested)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from photo_s import envinfo


class TestOptionalFeatures:
    def test_returns_dict_of_bools(self):
        feats = envinfo.optional_features()
        assert isinstance(feats, dict) and feats
        assert all(isinstance(v, bool) for v in feats.values())

    def test_rawpy_listed(self):
        # rawpy is a core dependency — it must always probe as available
        feats = envinfo.optional_features()
        assert any("raw" in k.lower() for k in feats)


class TestPlugins:
    def test_returns_list(self):
        plugins = envinfo.plugins()
        assert isinstance(plugins, list)
        for p in plugins:
            assert "name" in p and "provides" in p
