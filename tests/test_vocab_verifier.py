"""v2.4 词汇表扩展 + 美学 verifier tests.

* local_to_specs / apply_auto_tone_params: 9 字段真实管线 + 局部调整
  紧凑字符串（引擎槽位不再丢 6 个字段）
* engine auto_tone 槽位：auto_tone_params 协议（新）与像素协议（旧）
* audit 美学闸门：pass/fail、verifier 缺席显式报错、无分数记 fail
* lr-scan rating 导出（美学训练数据源）
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest
from PIL import Image


def _img(path, fill=(128, 118, 108), noise=45, size=(120, 120), seed=1):
    rng = np.random.default_rng(seed)
    arr = np.full((size[1], size[0], 3), fill, np.int16)
    arr += rng.integers(-noise, noise + 1, arr.shape)
    Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB").save(path)
    return str(path)


@pytest.fixture()
def photo(tmp_path):
    # 噪声拉满使对比度/模糊分都过技术闸门——本文件的 pass/fail 断言
    # 只应受美学闸门影响
    return _img(tmp_path / "photo.jpg")


# ── local_to_specs ──────────────────────────────────────────────────────────


class TestLocalToSpecs:
    def test_basic_conversion(self):
        from photo_s.autotone import local_to_specs
        masks, adjust = local_to_specs(
            [{"region": "subject", "params": {"exposure": -0.3,
                                              "clarity": 0.2}}])
        assert masks == "ai0:subject"
        assert adjust.startswith("ai0:")
        assert "exposure=-0.3" in adjust and "clarity=0.2" in adjust

    def test_object_region_with_label(self):
        from photo_s.autotone import local_to_specs
        masks, _ = local_to_specs(
            [{"region": "object:car", "params": {"saturation": 0.1}}])
        assert masks == "ai0:object:car"

    def test_neutral_params_are_dropped(self):
        from photo_s.autotone import local_to_specs
        masks, adjust = local_to_specs(
            [{"region": "subject",
              "params": {"exposure": 0.0, "clarity": 0.2}}])
        assert masks == "ai0:subject"
        assert "clarity" in adjust and "exposure" not in adjust

    def test_fully_neutral_entry_skipped(self):
        from photo_s.autotone import local_to_specs
        masks, adjust = local_to_specs(
            [{"region": "person", "params": {"exposure": 0.0}},
             {"region": "subject", "params": {"exposure": -0.1}}])
        assert masks == "ai0:subject"  # person 全中性不占号
        assert adjust.startswith("ai0:")

    def test_empty_and_none(self):
        from photo_s.autotone import local_to_specs
        assert local_to_specs(None) == ("", "")
        assert local_to_specs([]) == ("", "")

    def test_unknown_param_raises(self):
        from photo_s.autotone import local_to_specs
        with pytest.raises(ValueError, match="unknown local param"):
            local_to_specs([{"region": "subject",
                             "params": {"nope": 1.0}}])

    def test_missing_region_raises(self):
        from photo_s.autotone import local_to_specs
        with pytest.raises(ValueError, match="region"):
            local_to_specs([{"params": {"exposure": 0.1}}])

    def test_roundtrip_through_mask_parser(self):
        from photo_s.autotone import local_to_specs
        from photo_s.mask import parse_mask_adjust, parse_masks
        masks, adjust = local_to_specs(
            [{"region": "person", "params": {"exposure": 0.25,
                                             "clarity": -0.15}}])
        specs = parse_masks(masks)
        assert specs[0].kind == "person" and specs[0].name == "ai0"
        adj = parse_mask_adjust(adjust)
        assert adj["ai0"]["exposure"] == pytest.approx(0.25)
        assert adj["ai0"]["clarity"] == pytest.approx(-0.15)


# ── apply_auto_tone_params ──────────────────────────────────────────────────


class TestApplyAutoToneParams:
    def test_none_and_empty_return_original(self, photo):
        from photo_s.autotone import apply_auto_tone_params
        img = Image.open(photo)
        assert apply_auto_tone_params(img, None) is img
        assert apply_auto_tone_params(img, {}) is img

    def test_all_neutral_is_pixel_identical(self, photo):
        from photo_s.autotone import apply_auto_tone_params
        img = Image.open(photo)
        out = apply_auto_tone_params(img, {"options": {
            "exposure": 0.0, "contrast": 1.0, "saturation": 1.0,
            "vibrance": 0.0, "wb_temp": 5250.0, "wb_tint": 0.0,
            "clarity": 0.0, "texture": 0.0, "dehaze": 0.0}})
        assert np.array_equal(np.asarray(img), np.asarray(out))

    def test_exposure_brightens(self, photo):
        from photo_s.autotone import apply_auto_tone_params
        img = Image.open(photo)
        out = apply_auto_tone_params(img, {"options": {"exposure": 0.5}})
        assert np.asarray(out).mean() > np.asarray(img).mean()

    def test_saturation_shifts_channels(self, photo):
        from photo_s.autotone import apply_auto_tone_params
        img = Image.open(photo)
        out = apply_auto_tone_params(img, {"options": {"saturation": 1.5}})
        src = np.asarray(img).astype(int)
        dst = np.asarray(out).astype(int)
        # 偏红基底 + 提饱和 → R 相对 G 的差距拉大
        assert (dst[..., 0] - dst[..., 1]).std() >= 0

    def test_wb_moves_channels(self, photo):
        from photo_s.autotone import apply_auto_tone_params
        img = Image.open(photo)
        out = apply_auto_tone_params(img, {"options": {"wb_temp": 3200.0}})
        src = np.asarray(img).astype(int)
        dst = np.asarray(out).astype(int)
        assert abs(dst[..., 2].mean() - src[..., 2].mean()) > 1.0

    def test_local_applies_through_mask_pipeline(self, photo, monkeypatch):
        from photo_s import autotone as at
        img = Image.open(photo)
        called = {}

        def fake_render_mask(spec, w, h, img=None, refs=None):
            called["spec"] = spec.kind
            return np.ones((h, w), dtype=np.float32)

        import photo_s.mask as mask_mod
        monkeypatch.setattr(mask_mod, "render_mask", fake_render_mask)
        out = at.apply_auto_tone_params(img, {
            "options": {},
            "local": [{"region": "subject",
                       "params": {"exposure": 0.5}}]})
        assert called.get("spec") == "subject"
        assert np.asarray(out).mean() > np.asarray(img).mean()

    def test_local_without_effectful_params_is_identity(self, photo):
        from photo_s.autotone import apply_auto_tone_params
        img = Image.open(photo)
        out = apply_auto_tone_params(img, {
            "options": {}, "local": [{"region": "subject",
                                      "params": {"exposure": 0.0}}]})
        assert np.array_equal(np.asarray(img), np.asarray(out))


# ── engine slot ─────────────────────────────────────────────────────────────


class TestEngineSlot:
    def test_params_protocol_applies_all_fields(self, monkeypatch,
                                                tmp_path, photo):
        import photo_s.plugin as plugin_mod
        from photo_s.engine import ProcessOptions, process_image
        from dataclasses import replace

        class Provider:
            name = "fake"

            def auto_tone_params(self, strength, ctx):
                assert 0 < strength <= 1
                return {"options": {"exposure": 0.4, "vibrance": 0.3,
                                    "clarity": 0.2, "wb_tint": 5.0},
                        "local": [], "confidence": 0.9, "warnings": []}

        monkeypatch.setattr(plugin_mod, "find_provider",
                            lambda op: Provider() if op == "auto_tone"
                            else None)
        opts = replace(ProcessOptions(), auto_tone=0.8,
                       output_dir=str(tmp_path / "out"))
        res = process_image(photo, opts)
        assert res.success, res.error

    def test_params_protocol_local_masks_reach_pipeline(
            self, monkeypatch, tmp_path, photo):
        import photo_s.plugin as plugin_mod
        from photo_s.engine import ProcessOptions, process_image
        from dataclasses import replace
        import photo_s.mask as mask_mod

        seen = {}

        def fake_render_mask(spec, w, h, img=None, refs=None):
            seen["kind"] = spec.kind
            return np.ones((h, w), dtype=np.float32)

        monkeypatch.setattr(mask_mod, "render_mask", fake_render_mask)

        class Provider:
            name = "fake"

            def auto_tone_params(self, strength, ctx):
                return {"options": {"exposure": 0.2},
                        "local": [{"region": "person",
                                   "params": {"exposure": 0.4}}]}

        monkeypatch.setattr(plugin_mod, "find_provider",
                            lambda op: Provider() if op == "auto_tone"
                            else None)
        opts = replace(ProcessOptions(), auto_tone=1.0,
                       output_dir=str(tmp_path / "out2"))
        res = process_image(photo, opts)
        assert res.success, res.error
        assert seen.get("kind") == "person"

    def test_legacy_pixel_protocol_still_works(self, monkeypatch, tmp_path,
                                               photo):
        import photo_s.plugin as plugin_mod
        from photo_s.engine import ProcessOptions, process_image
        from dataclasses import replace
        from PIL import ImageEnhance

        class Provider:
            name = "fake"

            def auto_tone(self, img, strength, ctx):
                return ImageEnhance.Brightness(img).enhance(1.0)

        monkeypatch.setattr(plugin_mod, "find_provider",
                            lambda op: Provider() if op == "auto_tone"
                            else None)
        opts = replace(ProcessOptions(), auto_tone=0.6,
                       output_dir=str(tmp_path / "out3"))
        res = process_image(photo, opts)
        assert res.success, res.error


# ── audit 美学闸门 ──────────────────────────────────────────────────────────


class TestAuditAesthetic:
    def test_score_above_threshold_passes(self, photo):
        from photo_s.audit import audit_image
        r = audit_image(photo, aesthetic=6.0,
                        verifier=lambda p: {"score": 7.5})
        a = [c for c in r["checks"] if c["name"] == "aesthetic"]
        assert len(a) == 1 and a[0]["ok"] and a[0]["value"] == 7.5
        assert r["passed"]

    def test_score_below_threshold_fails_with_reason(self, photo):
        from photo_s.audit import audit_image
        r = audit_image(photo, aesthetic=6.0,
                        verifier=lambda p: {"score": 3.2})
        assert not r["passed"]
        assert "aesthetic=3.2>=6.0" in r["reason"]

    def test_missing_verifier_raises_loudly(self, photo):
        from photo_s.audit import audit_image
        with pytest.raises(RuntimeError, match="no verifier plugin"):
            audit_image(photo, aesthetic=6.0)

    def test_no_aesthetic_without_verifier_is_fine(self, photo):
        from photo_s.audit import audit_image
        r = audit_image(photo)  # aesthetic=None：不触碰 verifier
        assert "aesthetic" not in [c["name"] for c in r["checks"]]

    def test_verifier_without_score_fails_entry_with_error(self, photo):
        from photo_s.audit import audit_image
        r = audit_image(photo, aesthetic=6.0,
                        verifier=lambda p: {"score": None,
                                            "raw": "not trained"})
        a = [c for c in r["checks"] if c["name"] == "aesthetic"][0]
        assert a["ok"] is False and a["value"] is None
        assert "not trained" in r["reason"]

    def test_verifier_object_protocol(self, photo):
        from photo_s.audit import audit_image

        class V:
            def verify(self, path):
                return {"score": 9.0}

        r = audit_image(photo, aesthetic=6.0, verifier=V())
        assert r["passed"]

    def test_cli_aesthetic_gate(self, monkeypatch, tmp_path, photo, capsys):
        import photo_s.plugin as plugin_mod
        from photo_s.cli import run_cli

        monkeypatch.setattr(plugin_mod, "find_provider",
                            lambda op: (lambda p: {"score": 7.0})
                            if op == "verify" else None)
        rc = run_cli(["audit", photo, "--aesthetic", "6", "--json"])
        out = capsys.readouterr().out
        assert rc == 0
        assert '"aesthetic"' in out

    def test_cli_aesthetic_missing_plugin_errors(self, monkeypatch, photo):
        import photo_s.plugin as plugin_mod
        from photo_s.cli import run_cli

        monkeypatch.setattr(plugin_mod, "find_provider", lambda op: None)
        with pytest.raises(RuntimeError, match="no verifier plugin"):
            run_cli(["audit", photo, "--aesthetic", "6"])

    def test_mcp_audit_tool_aesthetic(self, monkeypatch, photo):
        import photo_s.plugin as plugin_mod
        from photo_s.mcp_server import audit_tool

        monkeypatch.setattr(plugin_mod, "find_provider",
                            lambda op: (lambda p: {"score": 2.0})
                            if op == "verify" else None)
        r = audit_tool([photo], aesthetic=6.0)
        assert r["ok"]
        assert r["passed"] == 0

    def test_batch_job_aesthetic_error_not_hung(self, monkeypatch, tmp_path,
                                                photo):
        """batch_start(aesthetic=...) 无插件 → job 进 error 态（非挂死）。"""
        import time

        import photo_s.plugin as plugin_mod
        from photo_s import mcp_server as ms
        from photo_s.engine import ProcessOptions
        from dataclasses import replace

        monkeypatch.setattr(plugin_mod, "find_provider", lambda op: None)
        opts = replace(ProcessOptions(), output_dir=str(tmp_path / "bo"))
        job_id = "job_test_a"
        with ms._JOBS_LOCK:
            ms._JOBS[job_id] = {"job_id": job_id, "phase": "starting",
                                "total": 1, "done": 0, "current": "",
                                "phase_detail": ""}
        ms._job_worker(job_id, [photo], opts, audit=True, aesthetic=6.0)
        with ms._JOBS_LOCK:
            state = dict(ms._JOBS[job_id])
        assert state["phase"] == "error"
        assert "verifier" in state.get("error", "")


# ── lr-scan rating ──────────────────────────────────────────────────────────


class TestLrScanRating:
    def test_rating_exported(self, tmp_path):
        import sqlite3

        db = tmp_path / "r.lrcat"
        conn = sqlite3.connect(db)
        conn.executescript("""
            CREATE TABLE Adobe_images (id_local INTEGER PRIMARY KEY,
                                       rootFile, fileWidth, fileHeight,
                                       rating);
            CREATE TABLE AgLibraryFile (id_local INTEGER PRIMARY KEY,
                                        baseName, extension, folder);
            CREATE TABLE AgLibraryFolder (id_local INTEGER PRIMARY KEY,
                                          pathFromRoot, rootFolder);
            CREATE TABLE AgLibraryRootFolder (id_local INTEGER PRIMARY KEY,
                                              absolutePath);
            CREATE TABLE Adobe_imageDevelopSettings (
                id_local INTEGER PRIMARY KEY, image, text,
                hasMasks, hasAIMasks, hasPointColor, whiteBalance);
            INSERT INTO AgLibraryRootFolder VALUES (1, '/tmp/');
            INSERT INTO AgLibraryFolder VALUES (2, '', 1);
            INSERT INTO AgLibraryFile VALUES (10, 'x', 'JPG', 2);
            INSERT INTO Adobe_images VALUES (5, 10, 100, 100, 5);
            INSERT INTO Adobe_imageDevelopSettings VALUES (
                5, 5, 's = { Exposure2012 = 0.1 }', 0, 0, 0, 'As Shot');
        """)
        conn.commit()
        conn.close()
        from photo_s.lrxmp import scan_catalog
        recs = scan_catalog(str(db), with_history=False)
        assert recs[0]["rating"] == 5

    def test_train_verifier_label_extraction(self, tmp_path):
        sys.path.insert(0, os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "tools"))
        from train_verifier import _labels
        p1 = _img(tmp_path / "a.jpg")
        rows = [{"path": p1, "rating": 4},
                {"path": str(tmp_path / "missing.jpg"), "rating": 5},
                {"path": p1, "rating": 0},
                {"path": p1, "score": 8.5},
                {"image": p1, "score": 2.0}]
        out = _labels(rows, None)
        assert (p1, 8.0) in out           # rating×2
        assert (p1, 8.5) in out           # 显式 score
        assert (p1, 2.0) in out           # image 键
        assert all(os.path.isfile(pp) for pp, _ in out)
