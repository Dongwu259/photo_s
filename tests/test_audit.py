"""test_audit.py — 出片质量闸门（agent 终止条件）"""

import pytest

from photo_s.audit import audit_image


def _img(path, color, textured=False):
    from PIL import Image
    if textured:
        # 渐变 + 噪声 → Laplacian 方差非零，避免误判模糊
        img = Image.new("RGB", (64, 64))
        px = img.load()
        for y in range(64):
            for x in range(64):
                v = (color[0] + x * 2 + (x * 7 + y * 13) % 9) % 256
                px[x, y] = (v, (v + 20) % 256, (v + 40) % 256)
        img.save(str(path))
    else:
        Image.new("RGB", (64, 64), color).save(str(path))
    return str(path)


def test_audit_pass(tmp_path):
    p = _img(tmp_path / "ok.jpg", (128, 128, 128), textured=True)
    r = audit_image(p)
    assert r["ok"] is True and r["passed"] is True
    assert r["reason"] == "ok"


def test_audit_overexposed_fails(tmp_path):
    p = _img(tmp_path / "bright.jpg", (255, 255, 255))
    r = audit_image(p)
    assert r["passed"] is False
    assert any(c["name"] == "overexposed" and not c["ok"] for c in r["checks"])
    assert "overexposed" in r["reason"]


def test_audit_unreadable(tmp_path):
    r = audit_image(str(tmp_path / "nope.jpg"))
    assert r["ok"] is False


def test_audit_threshold_override(tmp_path):
    p = _img(tmp_path / "mid.jpg", (200, 200, 200))
    r = audit_image(p, overexposed_max=0.1)  # 更严 → 失败
    assert r["passed"] is False
