"""test_lrxmp.py — Lightroom 数据桥接（真实 LR 18 样本夹具）

夹具来源：本机 Lightroom 会话目录（Adobe_imageDevelopSettings.text 明文快照 +
XMP sidecar），数值为真实修图数据。
"""

import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

from photo_s import lrxmp
from photo_s.lrxmp import (LrError, coverage, crs_to_options,
                           parse_develop_blob, parse_xmp_sidecar, scan_catalog)

FIXTURES = Path(__file__).parent / "fixtures"
BLOB = (FIXTURES / "lr_blob_mask.txt").read_text(encoding="utf-8")
XMP = (FIXTURES / "lr_crs_edited.xmp").read_text(encoding="utf-8")


def blob():
    return parse_develop_blob(BLOB)


# ---------------------------------------------------------------- XMP sidecar

def test_xmp_fixture_parses():
    x = parse_xmp_sidecar(XMP)
    assert x["Exposure2012"] == "+0.35"
    assert x["Contrast2012"] == "+19"
    assert x["WhiteBalance"] == "As Shot"
    assert len(x) > 100


def test_xmp_as_shot_skips_wb():
    x = parse_xmp_sidecar(XMP)
    o = crs_to_options(x, white_balance=x.get("WhiteBalance"))
    assert "wb_temp" not in o  # 机内白平衡不是编辑
    assert o["exposure"] == pytest.approx(0.35)
    assert o["contrast"] == pytest.approx(1.19)  # +19 → 1.19
    assert o["saturation"] == pytest.approx(1.02)  # +2


def test_xmp_custom_wb_maps():
    x = dict(parse_xmp_sidecar(XMP))
    x["WhiteBalance"] = "Custom"
    x["Temperature"] = "5500"
    o = crs_to_options(x, white_balance="Custom")
    assert o["wb_temp"] == 5500
    assert o["wb_tint"] == pytest.approx(14.0)  # Tint="+14"


def test_xmp_bad_raises():
    with pytest.raises(LrError):
        parse_xmp_sidecar("<not-xml")


def test_xmp_path_or_string():
    assert parse_xmp_sidecar(str(FIXTURES / "lr_crs_edited.xmp"))["Exposure2012"] == "+0.35"


# ---------------------------------------------------------------- catalog 快照

def test_blob_fixture_parses():
    s = blob()
    assert len(s) > 50
    corrs = s["MaskGroupBasedCorrections"]
    assert len(corrs) == 3  # 3 个修正（径向×2 + AI 聚合×1）


def test_blob_to_options():
    s = blob()
    o = crs_to_options(s, image_size=(6000, 4000), white_balance="As Shot")
    assert o["exposure"] == pytest.approx(0.4, abs=0.01)
    assert o["contrast"] == pytest.approx(1.26, abs=0.01)  # Contrast2012=26
    assert o["crop"] == "5562x3708+28+54"
    assert o["masks"].startswith(
        "蒙版_1:radial:0.4311,0.4108,0.6304,0.3295,feather=0.510")
    assert "蒙版_3:radial:0.5304,0.6394" in o["masks"]
    assert o["mask_adjust"].startswith("蒙版_1:exposure=")


def test_blob_masks_parseable_by_photo_s():
    """lrxmp 输出的 masks/mask_adjust 必须能被 PhotoS 管线消费（同格式闭环）。"""
    from photo_s.mask import parse_mask_adjust, parse_masks

    o = crs_to_options(blob(), image_size=(6000, 4000))
    parse_masks(o["masks"])  # 名字已消毒（无空格/冒号），不抛
    parse_mask_adjust(o["mask_adjust"])


def test_blob_point_colors():
    pts = lrxmp._point_color_tuples(blob())
    assert len(pts) == 1
    assert pts[0]["rgb"] == (131, 159, 182)  # 取样色 0-1 → 0-255
    assert len(pts[0]["raw"]) == 19  # 偏移/范围字段待标定


def test_blob_coverage():
    c = coverage(blob(), white_balance="As Shot")
    assert c["edited"] is True
    assert any("Mask/Aggregate" in v for v in c["v1_8"])  # 笔刷/AI 蒙版归 v1.8
    assert c["mappable_ratio"] > 0.3


def test_blob_bad_raises():
    with pytest.raises(LrError):
        parse_develop_blob("not a blob")


def test_blob_curves_identity_skipped():
    s = parse_develop_blob('s = { ToneCurvePV2012 = { 0, 0, 255, 255 } }')
    assert lrxmp._curves_string(s) == ""


def test_blob_curves_mapped():
    s = parse_develop_blob(
        's = { ToneCurvePV2012 = { 0, 0, 22, 16, 40, 35, 255, 255 },'
        ' ToneCurvePV2012Red = { 0, 0, 255, 255 } }')
    assert lrxmp._curves_string(s) == "rgb:0,0;22,16;40,35;255,255"


def test_hsl_only_nonzero_colors():
    s = {"SaturationAdjustmentRed": 20}
    assert lrxmp._hsl_string(s) == "red:0.000,0.200,0.000"
    s = {"HueAdjustmentRed": 0, "SaturationAdjustmentRed": 0,
         "LuminanceAdjustmentRed": 0}
    assert lrxmp._hsl_string(s) == ""


def test_color_grading_hue_wrap():
    s = {"ColorGradeShadowHue": 300, "ColorGradeShadowSat": 40}
    assert lrxmp._color_grading_string(s) == "shadows:-60.0,0.400,0.000"


def test_coverage_zero_strings_not_edited():
    c = coverage({"Exposure2012": "0", "Contrast2012": 0, "Temperature": 5250})
    assert c["edited"] is False


def test_coverage_wb_as_shot_not_edited():
    c = coverage({"Temperature": 5200, "Tint": 5}, white_balance="As Shot")
    assert "Temperature" not in c["mapped"]
    c2 = coverage({"Temperature": 5200, "Tint": 5}, white_balance="Custom")
    assert "Temperature" in c2["mapped"]


# ---------------------------------------------------------------- catalog 扫描

def _make_catalog(tmp_path: Path) -> str:
    db = tmp_path / "test.lrcat"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE Adobe_images (id_local INTEGER PRIMARY KEY,
                                   rootFile, fileWidth, fileHeight);
        CREATE TABLE AgLibraryFile (id_local INTEGER PRIMARY KEY,
                                    baseName, extension, folder);
        CREATE TABLE AgLibraryFolder (id_local INTEGER PRIMARY KEY,
                                      pathFromRoot, rootFolder);
        CREATE TABLE AgLibraryRootFolder (id_local INTEGER PRIMARY KEY,
                                          absolutePath);
        CREATE TABLE Adobe_imageDevelopSettings (
            id_local INTEGER PRIMARY KEY, image, text,
            hasMasks, hasAIMasks, hasPointColor, whiteBalance);
        CREATE TABLE Adobe_libraryImageDevelopHistoryStep (
            id_local INTEGER PRIMARY KEY, image, name,
            valueString, relValueString);
        INSERT INTO AgLibraryRootFolder VALUES (1, '/tmp/photos/');
        INSERT INTO AgLibraryFolder VALUES (2, '', 1);
        INSERT INTO AgLibraryFile VALUES (10, 'DSC0001', 'ARW', 2);
        INSERT INTO Adobe_images VALUES (5, 10, 6000, 4000);
        INSERT INTO Adobe_imageDevelopSettings VALUES (
            5, 5, 's = { Exposure2012 = 0.5, Contrast2012 = 26 }',
            1, 0, 0, 'As Shot');
        INSERT INTO Adobe_libraryImageDevelopHistoryStep VALUES (1, 5, '曝光度', '0.50', '');
    """)
    conn.commit()
    conn.close()
    return str(db)


def test_scan_catalog(tmp_path):
    recs = scan_catalog(_make_catalog(tmp_path))
    assert len(recs) == 1
    r = recs[0]
    assert r["path"] == "/tmp/photos/DSC0001.ARW"
    assert r["image_size"] == (6000, 4000)
    assert r["settings"]["Exposure2012"] == pytest.approx(0.5)
    assert r["history"] == [{"name": "曝光度", "value": "0.50"}]
    assert r["has_masks"] is True
    assert r["white_balance"] == "As Shot"


def test_scan_catalog_missing_db():
    with pytest.raises(LrError):
        scan_catalog("/nonexistent/x.lrcat")


# ---------------------------------------------------------------- 发现 + 报告

def test_discover_inputs(tmp_path):
    cat = tmp_path / "sub" / "1.lrcat"
    cat.parent.mkdir()
    cat.write_text("")
    (tmp_path / "a.xmp").write_text("")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "b.xmp").write_text("")
    catalogs, xmp = lrxmp.discover_inputs([str(tmp_path)], max_depth=3)
    assert catalogs == [str(cat)]
    assert xmp == [str(tmp_path / "a.xmp")]  # 隐藏目录跳过
    assert lrxmp.discover_inputs([str(cat)])[0] == [str(cat)]  # 文件直收


def test_scan_and_report_end_to_end(tmp_path):
    db = _make_catalog(tmp_path)
    (tmp_path / "b.xmp").write_text(XMP)
    report, records = lrxmp.scan_and_report([str(tmp_path)])
    s = report["summary"]
    assert s["photos"] == 1
    assert s["xmp_photos"] == 1
    assert s["edited"] == 2  # catalog 已编辑 1 + XMP 已编辑 1
    assert report["param_usage"]["Exposure2012"] == 2
    assert isinstance(report["unmapped"], dict)
    # 训练记录：catalog 记录带 options
    cat_recs = [r for r in records if r["source"] == "catalog"]
    assert len(cat_recs) == 1
    assert cat_recs[0]["options"]["exposure"] == pytest.approx(0.5)
    assert cat_recs[0]["edited"] is True
    # 导出
    out = lrxmp.write_export(records, str(tmp_path / "out"))
    lines = open(out, encoding="utf-8").read().strip().splitlines()
    assert len(lines) == 2
    assert '"edited": true' in lines[0]


# ---------------------------------------------------------------- 数据层（训练）

def _synthetic_records(tmp_path, n=40):
    from PIL import Image
    records = []
    for i in range(n):
        img = Image.new("RGB", (64, 64),
                        (i * 4 % 255, 100 + i % 80, 50 + i % 100))
        p = tmp_path / f"p{i}.jpg"
        img.save(p)
        exp = round((i % 21 - 10) / 20.0, 2)
        records.append({"path": str(p), "image": str(p), "edited": True,
                        "options": {"exposure": exp,
                                    "contrast": 1.0 + i / 200.0}})
    return records


def test_train_predict_roundtrip(tmp_path):
    recs = _synthetic_records(tmp_path)
    model = str(tmp_path / "m.npz")
    res = lrxmp.train_auto_tone(recs, model)
    assert res["samples"] == 40
    assert 0.0 <= res["r2"] <= 1.0
    assert lrxmp.predict_auto_tone(str(tmp_path / "p5.jpg"), model)["options"]


# ---------------------------------------------------------------- CLIP+MLP 分支

def _clip_weights(emb=4, hidden=3, transposed=False, rng=42):
    import numpy as np
    r = np.random.RandomState(rng)
    W = r.randn(hidden, emb)          # 旧格式 (hidden, emb)
    b = r.randn(hidden)
    W2 = r.randn(len(lrxmp.TARGETS), hidden)
    b2 = r.randn(len(lrxmp.TARGETS))
    if transposed:                    # 新格式 (emb, hidden)
        W, W2 = W.T, W2.T
    return W, b, W2, b2


def _fake_clip_modules(monkeypatch, feats):
    """注入假 torch/open_clip（无需真实安装）——encode_image 返回固定特征。"""
    import types
    import numpy as np
    from contextlib import nullcontext

    class _T:
        def __init__(self, arr):
            self._a = np.asarray(arr, dtype=np.float32)

        def unsqueeze(self, _d):
            return self

        def squeeze(self, _d):
            return self

        def numpy(self):
            return self._a

    class _Clip:
        def __init__(self, feats):
            self._feats = np.asarray(feats, dtype=np.float32)

        def eval(self):
            return self

        def encode_image(self, x):
            return _T(self._feats)

    class _Preproc:
        def __call__(self, img):
            return _T(np.zeros((3, 224, 224), dtype=np.float32))

    torch_mod = types.ModuleType("torch")
    torch_mod.no_grad = lambda: nullcontext()
    open_clip_mod = types.ModuleType("open_clip")
    open_clip_mod.create_model_and_transforms = (
        lambda name, pretrained: (_Clip(feats), None, _Preproc()))
    monkeypatch.setitem(sys.modules, "torch", torch_mod)
    monkeypatch.setitem(sys.modules, "open_clip", open_clip_mod)


def _clip_model_file(tmp_path, name, transposed=False):
    import numpy as np
    emb, hidden = 4, 3
    W, b, W2, b2 = _clip_weights(emb, hidden, transposed)
    path = tmp_path / name
    np.savez(path, W=W, b=b, W2=W2, b2=b2, emb_dim=emb,
             clip_model="ViT-L-14", clip_pretrained="openai",
             targets=np.array(lrxmp.TARGETS))
    return str(path)


def _expected_clip_options(emb=4, hidden=3, transposed=False, feats=(0.5, 1.0, 1.5, 2.0)):
    import numpy as np
    W, b, W2, b2 = _clip_weights(emb, hidden, transposed)
    h = np.maximum(np.asarray(feats, dtype=np.float64) @ W + b, 0.0)
    vec = h @ W2 + b2
    return vec


def test_predict_clip_mlp_new_format(tmp_path, monkeypatch):
    from PIL import Image
    from photo_s.lrxmp import TARGETS, _target_options
    feats = (0.5, 1.0, 1.5, 2.0)
    _fake_clip_modules(monkeypatch, feats)
    img = tmp_path / "x.jpg"
    Image.new("RGB", (64, 64), (120, 140, 160)).save(img)
    model = _clip_model_file(tmp_path, "clip.npz", transposed=True)
    res = lrxmp.predict_auto_tone(str(img), model)
    # 输出键 = TARGETS 中 exposure 换成 ProcessOptions 字段名 ev
    expected_keys = {("ev" if t == "exposure" else t) for t in TARGETS}
    assert set(res["options"]) == expected_keys
    vec = _expected_clip_options(transposed=True, feats=feats)
    expect = _target_options(vec)
    for t in expected_keys:
        assert res["options"][t] == expect[t]


def test_predict_clip_mlp_legacy_transpose(tmp_path, monkeypatch):
    """旧脚本存 (hidden, emb)：emb_dim 键存在时按转置兼容。"""
    from PIL import Image
    feats = (0.25, 0.5, 0.75, 1.0)
    _fake_clip_modules(monkeypatch, feats)
    img = tmp_path / "y.jpg"
    Image.new("RGB", (64, 64), (80, 90, 100)).save(img)
    model = _clip_model_file(tmp_path, "legacy.npz", transposed=False)
    res = lrxmp.predict_auto_tone(str(img), model)
    assert "ev" in res["options"]          # 消费层输出对齐 ProcessOptions 字段
    assert "exposure" not in res["options"]
    assert "wb_temp" in res["options"]


def test_predict_clip_mlp_missing_deps(tmp_path, monkeypatch):
    """无 torch/open_clip 时报清晰 LrError（不静默、不 TypeError）。"""
    import builtins
    from PIL import Image
    img = tmp_path / "z.jpg"
    Image.new("RGB", (16, 16), (10, 20, 30)).save(img)
    model = _clip_model_file(tmp_path, "no_deps.npz")
    real_import = builtins.__import__

    def _no_torch(name, *a, **k):
        if name.split(".")[0] in ("torch", "open_clip"):
            raise ImportError("simulate missing")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _no_torch)
    with pytest.raises(LrError, match="open-clip-torch"):
        lrxmp.predict_auto_tone(str(img), model)


def test_train_too_few_samples(tmp_path):
    recs = _synthetic_records(tmp_path, 5)
    with pytest.raises(LrError):
        lrxmp.train_auto_tone(recs, str(tmp_path / "m.npz"))


def test_predict_clear_errors_for_bad_inputs(tmp_path):
    """缺模型/缺图/坏 npz → 清晰 LrError（非裸 KeyError/ValueError）。"""
    from PIL import Image
    img = tmp_path / "y.jpg"
    Image.new("RGB", (32, 32), (80, 90, 100)).save(img)
    with pytest.raises(LrError, match="模型文件不存在"):
        lrxmp.predict_auto_tone(str(img), str(tmp_path / "none.npz"))
    with pytest.raises(LrError, match="图片不存在"):
        lrxmp.predict_auto_tone(str(tmp_path / "none.jpg"),
                                str(tmp_path / "none.npz"))
    import numpy as np
    np.savez(tmp_path / "no_targets.npz", W=np.zeros((84, 9)))
    with pytest.raises(LrError, match="targets"):
        lrxmp.predict_auto_tone(str(img), str(tmp_path / "no_targets.npz"))
    np.savez(tmp_path / "bad_w.npz", W=np.zeros((10, 9)),
             targets=np.array(lrxmp.TARGETS))
    with pytest.raises(LrError, match="维度不匹配"):
        lrxmp.predict_auto_tone(str(img), str(tmp_path / "bad_w.npz"))


def test_sanitize_package_loads_with_image_dir(tmp_path):
    """sanitize 包内 image 是 basename：--images 按目录解析（原 0 样本）。"""
    from PIL import Image
    bdir = tmp_path / "before"
    bdir.mkdir()
    recs = []
    for i in range(8):
        Image.new("RGB", (16, 16), (100 + i, 100, 100)).save(
            bdir / f"img{i}.jpg")
        recs.append({"path": f"/catalog/img{i}.ARW", "image": f"img{i}.jpg",
                     "edited": True, "options": {"exposure": 0.5}})
    X, Y, metas, stats = lrxmp.load_training_data(recs, str(bdir))
    assert stats == {"edited": 8, "missing": 0, "loaded": 8}
    assert len(X) == 8 and len(Y) == 8
    # 无 image_dir：0 样本但 stats 精确说明
    _x, _y, _m, stats2 = lrxmp.load_training_data(recs, None)
    assert stats2["missing"] == 8
    with pytest.raises(LrError, match="缺图跳过"):
        lrxmp.train_auto_tone(recs, str(tmp_path / "m.npz"))


def test_cluster_recipes(tmp_path):
    recs = _synthetic_records(tmp_path)
    res = lrxmp.cluster_recipes(recs, k=4)
    assert res["k"] == 4
    assert sum(c["size"] for c in res["clusters"]) == 40
    assert all(c["options"]["ev"] is not None
               for c in res["clusters"])


def test_similar_photos_excludes_self(tmp_path):
    recs = _synthetic_records(tmp_path)
    hits = lrxmp.similar_photos(str(tmp_path / "p0.jpg"), recs, k=3)
    assert len(hits) == 3
    assert not any(os.path.splitext(os.path.basename(h["path"]))[0] == "p0"
                   for h in hits)
    assert hits[0]["distance"] <= hits[-1]["distance"]


def test_render_before_images(tmp_path):
    from PIL import Image
    src = tmp_path / "a.jpg"
    Image.new("RGB", (200, 100), (120, 140, 160)).save(src)
    recs = [{"path": str(src), "edited": True}]
    out = tmp_path / "before"
    res = lrxmp.render_before_images(recs, str(out))
    assert res["rendered"] == 1
    assert (out / "a.jpg").exists()
    res2 = lrxmp.render_before_images(recs, str(out))
    assert res2["skipped"] == 1  # 幂等


def test_write_export_with_images(tmp_path):
    recs = [{"path": "/x/a.ARW", "edited": True, "options": {"exposure": 1.0}}]
    out = lrxmp.write_export(recs, str(tmp_path), images={"/x/a.ARW": "/y/a.jpg"})
    line = open(out, encoding="utf-8").readline()
    assert '"image": "/y/a.jpg"' in line


def test_write_export_sanitize(tmp_path):
    recs = [{"path": "/secret/千岛湖/x.ARW", "catalog": "/secret/Lrc目录/8-2/1/1.lrcat",
             "edited": True, "options": {"exposure": 1.0}}]
    out = lrxmp.write_export(recs, str(tmp_path), sanitize=True)
    line = open(out, encoding="utf-8").readline()
    assert "x.ARW" in line and "/secret/" not in line and "千岛湖" not in line
    assert '"catalog": "8-2"' in line
    mapping = open(tmp_path / "lr_paths.json", encoding="utf-8").read()
    assert "/secret/千岛湖/x.ARW" in mapping  # 原始映射仅存本地


def test_merge_packages(tmp_path):
    from PIL import Image
    # 两个"机器"数据包
    pkgs = []
    for mi, stem in enumerate(("DSC0001", "DSC0002")):
        pkg = tmp_path / f"pkg{mi}"
        before = pkg / "before"
        before.mkdir(parents=True)
        Image.new("RGB", (32, 32), (100 + mi, 100, 100)).save(before / f"{stem}.jpg")
        with open(pkg / "lr_records.jsonl", "w", encoding="utf-8") as f:
            f.write(json.dumps({"path": f"/x/{stem}.ARW", "image": f"before/{stem}.jpg",
                                "edited": True, "options": {"exposure": 0.3}}) + "\n")
        pkgs.append(str(pkg))
    # 第三包：与第一包重复 stem + 缺 before
    pkg3 = tmp_path / "pkg3"
    pkg3.mkdir()
    with open(pkg3 / "lr_records.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps({"path": f"/y/DSC0001.ARW", "edited": False,
                            "options": {}}) + "\n")
    pkgs.append(str(pkg3))

    res = lrxmp.merge_packages(pkgs, str(tmp_path / "merged"))
    assert res["records"] == 2      # DSC0001 重复被去
    assert res["edited"] == 2
    assert res["images_copied"] == 2
    assert res["duplicates"] == ["DSC0001"]
    merged = open(tmp_path / "merged" / "lr_records.jsonl",
                  encoding="utf-8").read()
    assert '"source_pkg": "pkg0"' in merged
    assert (tmp_path / "merged" / "before" / "DSC0001.jpg").exists()
