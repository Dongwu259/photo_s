"""Tests for the official plugin registry (photo_s.registry)."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from photo_s.registry import OFFICIAL_PLUGINS, get_official, to_dict, version_ok


class TestRegistry:
    def test_scunet_in_registry(self):
        assert "scunet" in OFFICIAL_PLUGINS

    def test_pypi_distribution_prefix(self):
        for name, o in OFFICIAL_PLUGINS.items():
            assert o.pypi_distribution == "photo-s-plugin-" + name

    def test_unknown_name_is_none(self):
        assert get_official("nope") is None

    def test_to_dict_json_serializable(self):
        for o in OFFICIAL_PLUGINS.values():
            d = to_dict(o)
            round_tripped = json.loads(json.dumps(d))
            assert round_tripped == d
            assert round_tripped["name"] == o.name

    def test_requires_is_tuple_or_none(self):
        for o in OFFICIAL_PLUGINS.values():
            if o.requires is not None:
                assert isinstance(o.requires, tuple)
                assert all(isinstance(r, str) for r in o.requires)

    def test_version_ok_current(self):
        # current __version__ is 1.0.0 which satisfies min_photo_s_version
        assert version_ok(OFFICIAL_PLUGINS["scunet"])
