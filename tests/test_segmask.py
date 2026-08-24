"""test_segmask.py — AI segmentation masks (v1.8.0).

Hermetic by default: forward passes are monkeypatched (no cv2.dnn, no
weight download), so CI never touches the network. A small set of tests
runs against real local ONNX weights when they exist (dev machine), so
the actual model paths stay exercised locally.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest
from PIL import Image

from photo_s import segmask
from photo_s.mask import MaskError, parse_masks, render_mask


def _img(w=64, h=48):
    return Image.new("RGB", (w, h), (120, 130, 140))


# ── weights registry ─────────────────────────────────────────────────────────

def test_weights_registered_with_sha256():
    assert set(segmask.WEIGHTS) == {"subject", "person", "object"}
    for kind, spec in segmask.WEIGHTS.items():
        assert spec.name.endswith(".onnx")
        assert len(spec.sha256) == 64
        assert spec.url.startswith("https://github.com/")
        assert spec.size > 0


def test_weights_under_10mb_network_safety():
    # all three release weights stay inside the user's known drop threshold
    for spec in segmask.WEIGHTS.values():
        assert spec.size < 10_000_000


# ── hermetic forward (monkeypatched, no cv2 / no download) ──────────────────

class _FakeNet:
    """Minimal cv2.dnn.Net stand-in: ``fwd(name=None) -> output array``."""

    def __init__(self, fwd):
        self._fwd = fwd

    def setInput(self, blob):
        pass

    def forward(self, name=None):
        return self._fwd(name)


def _monkeypatch_net(monkeypatch, fwd):
    monkeypatch.setattr(segmask, "_load_net",
                        lambda kind, force_classic=False: _FakeNet(fwd))
    monkeypatch.setattr(segmask, "_model_path", lambda kind: "/fake/{}")


def test_subject_forward_shape_and_range(monkeypatch):
    # u2netp: output (1, 1, 320, 320) in 0..1
    out = np.full((1, 1, 320, 320), 0.7, np.float32)
    _monkeypatch_net(monkeypatch, lambda name: out)
    m = segmask.segment(_img(), "subject")
    assert m.shape == (48, 64)
    assert m.min() >= 0.0 and m.max() <= 1.0
    assert m.mean() == pytest.approx(0.7, abs=0.05)


def test_person_forward_shape(monkeypatch):
    # pphumanseg: (1, 2, 192, 192) softmax, person = channel 1
    out = np.zeros((1, 2, 192, 192), np.float32)
    out[0, 1] = 0.9
    _monkeypatch_net(monkeypatch, lambda name: out)
    m = segmask.segment(_img(), "person")
    assert m.shape == (48, 64)
    assert m.mean() == pytest.approx(0.9, abs=0.05)


def test_object_forward_shape_and_class_filter(monkeypatch):
    # YOLOv8n-seg: preds (1, 116, 8400) + proto (1, 32, 160, 160)
    preds = np.zeros((1, 116, 8400), np.float32)
    # one strong person detection (cls row 4 + 0): score 0.9
    preds[0, 4 + 0, 100] = 0.9
    preds[0, 0, 100] = 0.5   # cx
    preds[0, 1, 100] = 0.5   # cy
    preds[0, 2, 100] = 0.2   # w
    preds[0, 3, 100] = 0.2   # h
    preds[0, 84:, 100] = 1.0  # mask coeffs
    proto = np.ones((1, 32, 160, 160), np.float32)

    def _fwd(name):
        return preds if name == "output0" else proto

    _monkeypatch_net(monkeypatch, _fwd)
    m = segmask.segment(_img(), "object", label="person")
    assert m.shape == (48, 64)
    assert m.max() > 0.5  # person detected
    # car: no strong score -> empty
    m2 = segmask.segment(_img(), "object", label="car")
    assert m2.max() == 0.0


def test_object_unknown_label_raises():
    with pytest.raises(RuntimeError, match="unknown COCO label"):
        segmask.segment(_img(), "object", label="hovercar")


def test_coco_classes_person_first():
    assert segmask.COCO_CLASSES[0] == "person"
    assert len(segmask.COCO_CLASSES) == 80


# ── missing cv2 / weights raise clearly ──────────────────────────────────────

def test_missing_cv2_raises(monkeypatch):
    def _no_cv2():
        raise RuntimeError("opencv: pip install 'photo-s-tools[enhance]'")
    monkeypatch.setattr(segmask, "_cv2", _no_cv2)
    with pytest.raises(RuntimeError, match="opencv"):
        segmask.segment(_img(), "subject")


def test_missing_weight_sha256_raises(monkeypatch):
    from dataclasses import replace
    import photo_s.segmask as sm
    monkeypatch.setattr(sm, "_cv2", lambda: object())  # fake cv2 present
    spec = replace(sm.WEIGHTS["subject"], sha256="")
    monkeypatch.setitem(sm.WEIGHTS, "subject", spec)
    with pytest.raises(RuntimeError, match="not yet pinned"):
        sm._model_path("subject")


# ── mask.py integration (render_mask dispatches to segmask) ─────────────────

def test_ai_mask_renders_through_mask_module(monkeypatch):
    out = np.full((1, 1, 320, 320), 0.6, np.float32)
    _monkeypatch_net(monkeypatch, lambda name: out)
    spec = parse_masks("main:subject")[0]
    m = render_mask(spec, 64, 48, img=_img())
    assert m.shape == (48, 64)
    assert m.mean() == pytest.approx(0.6, abs=0.05)


def test_ai_mask_missing_image_raises():
    spec = parse_masks("main:subject")[0]
    with pytest.raises(MaskError, match="needs the image"):
        render_mask(spec, 64, 48)


# ── real local weights (dev machine only, skipped in CI) ─────────────────────

_REAL = {
    "subject": "/tmp/v18_weights/u2netp.onnx",
    "person": "/tmp/v18_weights/pphumanseg.onnx",
    "object": "/tmp/v18_weights/yolov8n-seg-fp16.onnx",
}

_real_weights = pytest.mark.skipif(
    not all(os.path.exists(p) for p in _REAL.values()),
    reason="real ONNX weights only on dev machine")


@pytest.mark.parametrize("kind", ["subject", "person"])
@_real_weights
def test_real_weight_forward(kind, monkeypatch):
    import photo_s.segmask as sm
    spec = sm.WEIGHTS[kind]
    # monkeypatch (not bare assignment) so the override can't leak into
    # other tests once this one has run
    monkeypatch.setattr(sm, "_model_path", lambda k: _REAL[k])
    m = sm.segment(_img(128, 96), kind)
    assert m.shape == (96, 128)
    assert 0.0 <= m.min() <= m.max() <= 1.0


@_real_weights
def test_real_yolo_person_detection():
    import photo_s.segmask as sm
    sm._model_path = lambda k: _REAL[k]
    # bus.jpg ships inside ultralytics; skip if unavailable
    import ultralytics, os as _os
    bus = _os.path.join(_os.path.dirname(ultralytics.__file__),
                        "assets", "bus.jpg")
    if not _os.path.exists(bus):
        pytest.skip("no bus.jpg")
    m = sm.segment(Image.open(bus), "object", label="person")
    assert m.max() > 0.5          # people detected
    m2 = sm.segment(Image.open(bus), "object", label="bus")
    assert m2.max() > 0.5         # bus detected
