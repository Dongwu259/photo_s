"""AutoTonePredictor: v7_clean 推理核心（CLIP+MLP → 9 字段调色参数）"""

import threading
from typing import Dict, List, Optional

import numpy as np
from PIL import Image

from .. import models

_predictor_singleton: Optional["AutoTonePredictor"] = None
_lock = threading.Lock()

DEFAULT_TARGETS = [
    "exposure", "contrast", "saturation", "vibrance",
    "wb_temp", "wb_tint", "clarity", "texture", "dehaze",
]

DEFAULT_RANGES = {
    "exposure": (-2.0, 2.0),
    "contrast": (0.5, 1.5),
    "saturation": (0.0, 2.0),
    "vibrance": (-1.0, 1.0),
    "wb_temp": (2000.0, 10000.0),
    "wb_tint": (-100.0, 100.0),
    "clarity": (-1.0, 1.0),
    "texture": (-1.0, 1.0),
    "dehaze": (-1.0, 1.0),
}


def _need_torch():
    try:
        import torch  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "auto-tone 插件需要 torch: pip install 'photo-s-plugin-auto-tone[model]'"
        ) from e
    import torch
    return torch


class AutoTonePredictor:
    """CLIP+MLP 自动调色推理器

    输入：PIL Image
    输出：9 字段调整参数 dict（实际值范围）
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        device: Optional[str] = None,
    ):
        self.model_path = model_path  # None → 从 modelstore 解析
        self.device = device or models.pick_device()

        self.clip_model = None
        self.mlp = None
        self.preprocess = None
        self.checkpoint = None
        self.qwen_dim = 0
        self.targets = DEFAULT_TARGETS
        self.ranges = DEFAULT_RANGES

    def load(self):
        """加载模型（懒加载；torch / open_clip 缺失时报清晰错误）"""
        if self.clip_model is not None:
            return

        try:
            import open_clip  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                "auto-tone 插件需要 open_clip: "
                "pip install 'photo-s-plugin-auto-tone[model]'"
            ) from e

        torch = _need_torch()
        model_path = self.model_path or models.core_path("auto_tone_v7_clean.pt")
        self.model_path = model_path

        # weights_only=True: the checkpoint is a plain dict of tensors —
        # unpickling arbitrary objects from a downloaded file is an
        # arbitrary-code-execution vector if the weight source is ever
        # compromised.
        ck = torch.load(model_path, weights_only=True,
                        map_location=self.device)

        self.clip_model, self.preprocess = models.get_shared_clip(
            ck['model_name'], ck['pretrained'], self.device)

        # 维度推断
        sd_keys = list(ck['state_dict'].keys())
        linear_keys = [k for k in sd_keys if k.endswith('.weight')
                       and ck['state_dict'][k].ndim == 2]
        actual_in = ck['state_dict'][linear_keys[0]].shape[1]

        self.qwen_dim = ck.get('qwen_dim', 0)
        hand_dim = max(0, actual_in - ck['feat_dim'] - self.qwen_dim)
        in_dim = ck['feat_dim'] + hand_dim + self.qwen_dim

        self.mlp = self._build_mlp(ck['state_dict'], in_dim).to(self.device)
        sd = {(k[len('net.'):] if k.startswith('net.') else k): v
              for k, v in ck['state_dict'].items()}
        self.mlp.load_state_dict(sd, strict=True)
        self.mlp.eval()

        if 'targets' in ck:
            self.targets = ck['targets']
        if 'ranges' in ck:
            self.ranges = ck['ranges']

        self.checkpoint = ck

    @staticmethod
    def _build_mlp(state_dict, in_dim):
        """按 checkpoint 的实际索引重建 MLP（net.<i>.<param>）

        约定：weight 为 1 维 → LayerNorm；2 维 → Linear；
        无参数的索引 → GELU（训练时的激活函数）。
        """
        torch = _need_torch()

        # key 形如 "net.<idx>.<param>"
        idx_params = {}  # idx → {param_name: tensor}
        for k, v in state_dict.items():
            seg = k.split('.')
            assert seg[0] == 'net', f"unexpected key: {k}"
            idx_params.setdefault(int(seg[1]), {})[seg[2]] = v

        modules = {}
        for idx in sorted(idx_params):
            params = idx_params[idx]
            w = params.get('weight')
            if w is not None and w.ndim == 1:
                modules[idx] = torch.nn.LayerNorm(w.shape[0])
            elif w is not None and w.ndim == 2:
                modules[idx] = torch.nn.Linear(w.shape[1], w.shape[0])
            else:
                modules[idx] = torch.nn.GELU()

        max_idx = max(modules)
        layers = [modules.get(i, torch.nn.GELU()) for i in range(max_idx + 1)]
        return torch.nn.Sequential(*layers)

    def _extract_features(self, img: Image.Image):
        from photo_s.lrxmp import _content_features

        torch = _need_torch()
        x = self.preprocess(img).unsqueeze(0).to(self.device)
        with torch.no_grad():
            cf = self.clip_model.encode_image(x).float()
        hand = np.array(_content_features(img), dtype=np.float32)
        hand_t = torch.tensor(hand, dtype=torch.float32).unsqueeze(0).to(self.device)
        return torch.cat([cf, hand_t], dim=-1)

    def predict(self, image: Image.Image) -> Dict[str, float]:
        """单图预测 → 9 字段 dict（实际值范围）"""
        self.load()
        torch = _need_torch()
        feats = self._extract_features(image)
        with torch.no_grad():
            pred = self.mlp(feats).cpu().numpy()[0]

        result = {}
        for i, f in enumerate(self.targets):
            lo, hi = self.ranges[f]
            val = (pred[i] + 1) / 2 * (hi - lo) + lo
            result[f] = float(val)
        return result

    def predict_batch(self, images: List[Image.Image]) -> List[Dict[str, float]]:
        """批量预测"""
        self.load()
        torch = _need_torch()
        feats_list = [self._extract_features(img) for img in images]
        feats = torch.cat(feats_list, dim=0)
        with torch.no_grad():
            pred = self.mlp(feats).cpu().numpy()

        results = []
        for i in range(len(images)):
            r = {}
            for j, f in enumerate(self.targets):
                lo, hi = self.ranges[f]
                r[f] = float((pred[i, j] + 1) / 2 * (hi - lo) + lo)
            results.append(r)
        return results


def get_predictor() -> AutoTonePredictor:
    """全局单例 predictor（线程安全）"""
    global _predictor_singleton
    if _predictor_singleton is None:
        with _lock:
            if _predictor_singleton is None:
                _predictor_singleton = AutoTonePredictor()
                _predictor_singleton.load()
    return _predictor_singleton
