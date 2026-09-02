"""v2.5 XMP 写出 — lrxmp 反向桥接 + 读侧曲线/蒙版 shim + resolve + CLI。

往返契约：crs_to_options「直接映射」表的逐字段逆变换——
options → XMP → parse → crs_to_options 应还原同一组值（读侧格式化造成的
字符串差异按 parse 后的语义比较）。不可逆字段必须出现在 warnings 里。
"""

import json
import math
import os
import xml.etree.ElementTree as ET

import pytest

from photo_s.engine import ProcessOptions
from photo_s.lrxmp import (LrError, crs_to_options, options_to_xmp,
                           parse_xmp_sidecar, write_xmp_sidecar)


def _roundtrip(opts, image_size=(6000, 4000), **meta):
    xmp, warnings = options_to_xmp(opts, image_size=image_size, **meta)
    settings = parse_xmp_sidecar(xmp)
    back = crs_to_options(settings, image_size=image_size,
                          white_balance=settings.get("WhiteBalance"))
    back["ev"] = back.pop("exposure", None)
    return xmp, warnings, back


class TestScalars:
    def test_direct_field_inverse(self):
        opts = ProcessOptions(ev=0.35, contrast=1.19, saturation=1.02,
                              vibrance=0.1, clarity=0.05, texture=0.02,
                              dehaze=0.2, wb_temp=5500, wb_tint=14)
        _, warns, back = _roundtrip(opts)
        assert not warns
        assert back["ev"] == pytest.approx(0.35, abs=0.005)
        assert back["contrast"] == pytest.approx(1.19, abs=0.01)
        assert back["saturation"] == pytest.approx(1.02, abs=0.01)
        assert back["vibrance"] == pytest.approx(0.1, abs=0.01)
        assert back["clarity"] == pytest.approx(0.05, abs=0.011)
        assert back["texture"] == pytest.approx(0.02, abs=0.011)
        assert back["dehaze"] == pytest.approx(0.2, abs=0.011)
        assert back["wb_temp"] == 5500
        assert back["wb_tint"] == pytest.approx(14.0, abs=0.01)

    def test_neutral_options_write_only_structural(self):
        xmp, warns, back = _roundtrip(ProcessOptions())
        assert not warns
        assert back == {"ev": None}
        # 中性值不写具体调整属性（LR 对缺省取默认）
        assert "Exposure2012" not in xmp
        assert "Contrast2012" not in xmp

    def test_wb_none_not_written(self):
        # wb_temp None → 不写 WhiteBalance/Temperature（As Shot 语义保留）
        xmp, _, _ = _roundtrip(ProcessOptions(ev=0.3))
        assert "WhiteBalance" not in xmp

    def test_signed_exposure_format(self):
        xmp, _, _ = _roundtrip(ProcessOptions(ev=-0.4))
        assert 'Exposure2012="-0.4"' in xmp
        xmp2, _, _ = _roundtrip(ProcessOptions(ev=0.35))
        assert 'Exposure2012="+0.35"' in xmp2


class TestCompactStrings:
    def test_hsl_roundtrip(self):
        opts = ProcessOptions(hsl="red:54.000,0.200,0.000;blue:-18.0,-0.3,0.5")
        _, _, back = _roundtrip(opts)
        got = dict(seg.split(":") for seg in back["hsl"].split(";"))
        assert float(got["red"].split(",")[0]) == pytest.approx(54.0, abs=0.91)
        assert float(got["blue"].split(",")[1]) == pytest.approx(-0.3, abs=0.006)

    def test_curves_roundtrip(self):
        opts = ProcessOptions(curves="rgb:0,0;128,140;255,255|r:0,0;128,120;255,255")
        _, _, back = _roundtrip(opts)
        segs = dict(s.split(":", 1) for s in back["curves"].split("|"))
        pts = [tuple(float(v) for v in p.split(","))
               for p in segs["rgb"].split(";")]
        assert pts == [(0.0, 0.0), (128.0, 140.0), (255.0, 255.0)]

    def test_identity_curve_skipped(self):
        xmp, _, back = _roundtrip(
            ProcessOptions(curves="rgb:0,0;255,255"))
        assert "curves" not in back
        assert "ToneCurve" not in xmp

    def test_color_grading_negative_hue_wraps(self):
        opts = ProcessOptions(color_grading="shadows:-60.0,0.400,0.000")
        _, _, back = _roundtrip(opts)
        assert back["color_grading"] == "shadows:-60.0,0.400,0.000"

    def test_vignette_roundtrip_drops_feather(self):
        # feather 无 LR 手动暗角对应——单向丢失（docstring 声明）
        opts = ProcessOptions(vignette="-0.3,0.5,0.9")
        _, _, back = _roundtrip(opts)
        a, m = (float(v) for v in back["vignette"].split(",")[:2])
        assert a == pytest.approx(-0.3, abs=0.006)
        assert m == pytest.approx(0.5, abs=0.006)

    def test_bad_compact_string_raises(self):
        with pytest.raises(LrError):
            options_to_xmp(ProcessOptions(vignette="abc"))


class TestCrop:
    def test_crop_roundtrip(self):
        opts = ProcessOptions(crop="3000x2000+100+50")
        _, _, back = _roundtrip(opts)
        assert back["crop"] == "3000x2000+100+50"

    def test_crop_centered_roundtrip(self):
        opts = ProcessOptions(crop="3000x2000")
        _, _, back = _roundtrip(opts)  # 6000x4000 → 中心 (1500,1000)
        assert back["crop"] == "3000x2000+1500+1000"

    def test_crop_needs_size_else_warning(self):
        xmp, warns, _ = _roundtrip(ProcessOptions(crop="10x10"),
                                   image_size=None)
        assert any("image_size" in w for w in warns)
        assert "CropLeft" not in xmp


class TestMasks:
    def test_radial_full_roundtrip(self):
        opts = ProcessOptions(
            masks="face:radial:0.4,0.3,0.2,0.25,feather=0.51,invert",
            mask_adjust="face:exposure=-0.3,contrast=1.1,saturation=0.9,"
                        "brightness=1.05,vibrance=0.2,clarity=0.3,"
                        "texture=0.1,sharpen=1.2,temp=5400,tint=5")
        xmp, warns, back = _roundtrip(opts)
        assert not warns
        assert "face:radial:" in back["masks"]
        assert "invert" in back["masks"]
        adj = dict(kv.split("=", 1)
                   for kv in back["mask_adjust"].split(":", 1)[1].split(","))
        assert float(adj["exposure"]) == pytest.approx(-0.3, abs=1e-3)
        assert float(adj["contrast"]) == pytest.approx(1.1, abs=0.011)
        assert float(adj["brightness"]) == pytest.approx(1.05, abs=0.011)
        assert float(adj["sharpen"]) == pytest.approx(1.2, abs=0.011)
        assert float(adj["temp"]) == pytest.approx(5400.0, abs=1.1)
        assert float(adj["tint"]) == pytest.approx(5.0, abs=1e-3)

    def test_linear_angle_math(self):
        # 端点 (0.5,0)→(0.5,1)：垂直渐变 → Angle=0（LR 自上而下）
        opts = ProcessOptions(masks="sky:linear:0.5,0,0.5,1,feather=0.3")
        xmp, _, back = _roundtrip(opts)
        assert "sky:linear:" in back["masks"]
        # 水平端点 → Angle=±90
        opts2 = ProcessOptions(masks="l2:linear:0,0.5,1,0.5")
        _, _, back2 = _roundtrip(opts2)
        seg = back2["masks"]
        x0, y0, x1, y1 = (float(v) for v in
                          seg.split(":")[2].split(",")[:4])
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        assert dx == pytest.approx(1.0, abs=1e-3)
        assert dy == pytest.approx(0.0, abs=1e-3)

    def test_ai_mask_warned_not_written(self):
        opts = ProcessOptions(masks="ai0:subject;geo:radial:0.5,0.5,0.2,0.2",
                              mask_adjust="ai0:exposure=-0.2;"
                                          "geo:exposure=0.1")
        xmp, warns, back = _roundtrip(opts)
        assert any("subject" in w for w in warns)
        assert "geo:radial:" in back["masks"]
        assert "subject" not in back["masks"]

    def test_string_local_adjust_warned(self):
        opts = ProcessOptions(
            masks="sky:radial:0.5,0.5,0.2,0.2",
            mask_adjust="sky:curves={rgb:0,0;255,255}")
        _, warns, _ = _roundtrip(opts)
        assert any("curves" in w for w in warns)


class TestMetadataAndXml:
    def test_rating_keywords_title_in_xml(self):
        xmp, _, _ = _roundtrip(ProcessOptions(ev=0.3), rating=4,
                               keywords=["sunset", "beach"], title="Summer")
        root = ET.fromstring(xmp)
        assert root.find(".//{*}Description").get(
            "{http://ns.adobe.com/xap/1.0/}Rating") == "4"
        subjects = [li.text for li in root.iter(
            "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}li")]
        assert "sunset" in subjects and "beach" in subjects
        assert "Summer" in subjects

    def test_dict_and_none_options(self):
        xmp, _, back = _roundtrip({"ev": 0.5})
        assert back["ev"] == pytest.approx(0.5, abs=0.005)
        xmp2, _, back2 = _roundtrip(None, rating=5)
        assert back2 == {"ev": None}
        assert 'Rating="5"' in xmp2

    def test_write_xmp_sidecar_file(self, tmp_path):
        from PIL import Image
        p = tmp_path / "photo.jpg"
        Image.new("RGB", (600, 400), (120, 100, 80)).save(str(p))
        sidecar, warns = write_xmp_sidecar(
            str(p), ProcessOptions(ev=0.4, crop="300x200+10+5"),
            rating=3, keywords=["x"])
        assert os.path.exists(sidecar)
        assert sidecar.endswith("photo.xmp")
        assert not warns
        settings = parse_xmp_sidecar(sidecar)
        back = crs_to_options(settings, image_size=(600, 400),
                              white_balance=settings.get("WhiteBalance"))
        assert back["crop"] == "300x200+10+5"

    def test_sidecar_out_dir(self, tmp_path):
        from PIL import Image
        p = tmp_path / "a.jpg"
        Image.new("RGB", (60, 40)).save(str(p))
        out = tmp_path / "sidecars"
        sidecar, _ = write_xmp_sidecar(str(p), {"ev": 0.1}, out_dir=str(out))
        assert sidecar == str(out / "a.xmp")

    def test_fixture_roundtrip(self):
        # 真实 LR 18 sidecar：读入 → 写出 → 读回，映射字段全等
        fixture = os.path.join(os.path.dirname(__file__), "fixtures",
                               "lr_crs_edited.xmp")
        settings = parse_xmp_sidecar(fixture)
        size = (5562, 3708)
        source = crs_to_options(settings, image_size=size,
                                white_balance=settings.get("WhiteBalance"))
        opts = ProcessOptions(**{k: v for k, v in source.items()
                                 if k != "exposure"},
                              ev=source.get("exposure"))
        _, _, back = _roundtrip(opts, image_size=size)
        if "exposure" in source:
            assert back.pop("ev") == pytest.approx(source["exposure"],
                                                   abs=0.005)
        else:
            assert not back.get("ev")
        for k, v in source.items():
            if k == "exposure":
                continue  # 已在上面按 ev 比较
            if k not in back:
                continue  # 中性值（0/1/空串）写出侧省略——语义等价
            assert back[k] == v, k


class TestReaderShims:
    def test_curve_string_becomes_list(self):
        xmp, _, _ = _roundtrip(ProcessOptions(curves="rgb:0,0;128,140;255,255"))
        settings = parse_xmp_sidecar(xmp)
        assert settings["ToneCurvePV2012"] == [0.0, 0.0, 128.0, 140.0,
                                               255.0, 255.0]

    def test_mask_groups_parsed_from_xmp(self):
        xmp, _, _ = _roundtrip(
            ProcessOptions(masks="m:radial:0.4,0.3,0.2,0.25,feather=0.51,invert"))
        settings = parse_xmp_sidecar(xmp)
        groups = settings["MaskGroupBasedCorrections"]
        assert isinstance(groups, list)
        cm = groups[0]["CorrectionMasks"][0]
        assert cm["What"] == "Mask/CircularGradient"
        assert cm["MaskInverted"] is True  # 字符串 "False" 是 truthy 的坑
        assert float(cm["Feather"]) == pytest.approx(51.0)


class TestResolveAutoTone:
    def _fake_provider(self, monkeypatch):
        class Fake:
            name = "fake"

            def auto_tone_params(self, strength=1.0, ctx=None):
                return {
                    "options": {"exposure": -0.3 * strength,
                                "contrast": 1.1, "saturation": 1.0,
                                "wb_temp": 5250.0, "vibrance": 0.2},
                    "local": [{"region": "subject",
                               "params": {"exposure": -0.5}}],
                    "confidence": 0.9,
                }

        import photo_s.plugin as plugin_mod
        monkeypatch.setattr(plugin_mod, "find_provider",
                            lambda op: Fake() if op == "auto_tone" else None)
        plugin_mod.clear_cache()
        return Fake

    def test_merge_semantics(self, monkeypatch):
        self._fake_provider(monkeypatch)
        from photo_s.autotone import resolve_auto_tone_options
        opts = ProcessOptions(auto_tone=0.5, wb_temp=6500,
                              masks="manual:linear:0,0,1,1",
                              mask_adjust="manual:clarity=0.1")
        merged, params = resolve_auto_tone_options(opts, "x.jpg")
        assert merged.auto_tone is None          # 引擎不再二次推理
        assert merged.ev == pytest.approx(-0.15)
        assert merged.contrast == pytest.approx(1.1)
        assert merged.vibrance == pytest.approx(0.2)
        assert merged.wb_temp == 6500            # 用户显式 WB 不被覆盖
        assert merged.masks.startswith("manual:linear:0,0,1,1")
        assert "ai0:subject" in merged.masks
        assert "ai0:exposure=-0.5" in merged.mask_adjust
        assert "manual:clarity=0.1" in merged.mask_adjust
        assert params["confidence"] == 0.9

    def test_missing_provider_raises(self, monkeypatch):
        import photo_s.plugin as plugin_mod
        monkeypatch.setattr(plugin_mod, "find_provider", lambda op: None)
        plugin_mod.clear_cache()
        from photo_s.autotone import resolve_auto_tone_options
        with pytest.raises(RuntimeError, match="auto-tone plugin"):
            resolve_auto_tone_options(ProcessOptions(auto_tone=0.8))


class TestCli:
    def test_xmp_export_rating(self, tmp_path, capsys):
        from PIL import Image
        from photo_s.cli import run_cli
        p = tmp_path / "a.jpg"
        Image.new("RGB", (60, 40), (120, 100, 80)).save(str(p))
        rc = run_cli(["xmp-export", str(p), "--rating", "4",
                      "--keywords", "beach,trip"])
        out = capsys.readouterr().out
        assert rc == 0
        assert (tmp_path / "a.xmp").exists()
        assert "a.xmp" in out

    def test_xmp_export_options_json(self, tmp_path):
        from PIL import Image
        from photo_s.cli import run_cli
        p = tmp_path / "b.jpg"
        Image.new("RGB", (60, 40)).save(str(p))
        rc = run_cli(["xmp-export", str(p), "--json",
                      "--options", json.dumps({"ev": 0.3, "contrast": 1.1})])
        settings = parse_xmp_sidecar(str(tmp_path / "b.xmp"))
        assert rc == 0
        assert float(settings["Exposure2012"]) == pytest.approx(0.3, abs=0.005)
        assert float(settings["Contrast2012"]) == pytest.approx(10.0)

    def test_xmp_export_no_source_errors(self, tmp_path):
        from PIL import Image
        from photo_s.cli import run_cli
        p = tmp_path / "c.jpg"
        Image.new("RGB", (60, 40)).save(str(p))
        rc = run_cli(["xmp-export", str(p)])
        assert rc == 2
        assert not (tmp_path / "c.xmp").exists()

    def test_batch_write_xmp(self, tmp_path):
        from PIL import Image
        from photo_s.cli import run_cli
        p = tmp_path / "d.jpg"
        Image.new("RGB", (60, 40), (120, 100, 80)).save(str(p))
        rc = run_cli(["batch", str(p), "--write-xmp",
                      "--saturation", "1.2", "-o", str(tmp_path / "out"),
                      "--json"])
        assert rc == 0
        sidecar = tmp_path / "d.xmp"
        assert sidecar.exists()
        settings = parse_xmp_sidecar(str(sidecar))
        assert float(settings["Saturation"]) == pytest.approx(20.0)

    def test_batch_write_xmp_needs_plugin_with_auto_tone(self, tmp_path,
                                                         monkeypatch):
        from PIL import Image
        from photo_s.cli import run_cli
        import photo_s.plugin as plugin_mod
        monkeypatch.setattr(plugin_mod, "find_provider", lambda op: None)
        p = tmp_path / "e.jpg"
        Image.new("RGB", (60, 40), (120, 100, 80)).save(str(p))
        rc = run_cli(["batch", str(p), "--write-xmp", "--auto-tone", "0.8"])
        assert rc == 2
