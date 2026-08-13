"""PIL 解压炸弹阈值：photo_s 包入口有界放宽，且仍拦截真炸弹。"""
import warnings

import pytest
from PIL import Image


def _forge_dimensions(path, w, h):
    """把真实 2x2 BMP 的 BITMAPINFOHEADER 宽高篡改为 (w, h)，不实际分配像素。"""
    data = bytearray(path.read_bytes())
    # BMP BITMAPINFOHEADER: width @18-21, height @22-25（小端，无 CRC 校验）
    data[18:22] = int(w).to_bytes(4, "little", signed=True)
    data[22:26] = int(h).to_bytes(4, "little", signed=True)
    path.write_bytes(data)


@pytest.fixture()
def forged(tmp_path):
    def _make(w, h):
        p = tmp_path / f"{w}x{h}.bmp"
        Image.new("RGB", (2, 2), "red").save(p, "BMP")
        _forge_dimensions(p, w, h)
        return p
    return _make


def test_bounded_cap_applied_on_import():
    # photo_s/__init__.py 在导入任何子模块前就应把 PIL 阈值抬高到有界值
    import photo_s  # noqa: F401
    assert Image.MAX_IMAGE_PIXELS == photo_s.MAX_IMAGE_PIXELS
    assert Image.MAX_IMAGE_PIXELS >= 112_266_000  # 覆盖用户实际遇到的 112MP


def test_large_legit_image_opens_without_warning(forged):
    # 12000x10000 = 120MP，落在默认警告带 (89.5M~179M)，打开不应再告警
    p = forged(12000, 10000)
    with warnings.catch_warnings(record=True) as rec:
        warnings.simplefilter("always")
        im = Image.open(p)
        assert not any("DecompressionBomb" in str(x.message) for x in rec), rec
        assert im.size == (12000, 10000)
        im.close()


def test_user_reported_case_112mp_clean(forged):
    # 用户实际报错尺寸：112266000 px（如 9000x12474）
    p = forged(9000, 12474)
    with warnings.catch_warnings(record=True) as rec:
        warnings.simplefilter("always")
        im = Image.open(p)
        assert not any("DecompressionBomb" in str(x.message) for x in rec), rec
        im.close()


def test_genuine_bomb_still_blocked(forged):
    # 30000x70000 = 2.1G px > 2×512M（硬报错阈值），真炸弹依旧被拦
    p = forged(30000, 70000)
    with pytest.raises(Image.DecompressionBombError):
        Image.open(p)
