"""模型权重注册与路径解析

许可注意：本模块管理的权重文件采用 CC-BY-NC 4.0（非商用），
代码本身为 MIT。详见插件目录 LICENSE-WEIGHTS.txt。

权重不打进 wheel，首次使用时从 photo_s 仓库的 GitHub Release 下载到
photo_s.modelstore 缓存目录（~/.cache/photo-s/models，可用
$PHOTOS_CACHE_DIR 覆盖），并做 sha256 校验。

所有 URL / sha256 均可用环境变量覆盖（离线 / 镜像 / 测试场景）：
    PHOTOS_AUTO_TONE_URL_BASE       覆盖整个 URL 前缀
    PHOTOS_AUTO_TONE_<NAME>_URL     覆盖单个文件 URL（file:// 亦可）
    PHOTOS_AUTO_TONE_<NAME>_SHA256  覆盖单个文件 sha256
    PHOTOS_AUTO_TONE_QWEN_BASE      Qwen3-VL 基座（本地路径或 HF model id）
"""

import json
import os
import shutil
import threading
from typing import Dict, List, Optional

GITHUB_REPO = "Dongwu259/photo_s"
RELEASE_TAG = "auto-tone-v0.1.0"
URL_BASE = f"https://github.com/{GITHUB_REPO}/releases/download/{RELEASE_TAG}"

QWEN_BASE_MODEL = os.environ.get("PHOTOS_AUTO_TONE_QWEN_BASE",
                                 "Qwen/Qwen3-VL-2B-Instruct")

# name → (sha256, size, required)
WEIGHTS: Dict[str, dict] = {
    # ── 核心（auto_tone 主流程必需）────────────────────────────
    "auto_tone_v7_clean.pt": {
        "sha256": "6b41c1f9e43415a19277bf0e2f70ccce6c0da27079c915502990459bef95a15a",
        "size": 452_309,
        "required": True,
    },
    "clip_train_rag.npz": {
        "sha256": "0c830971c1ea4457758fee2353e63ec9338c428d114cf0eb68a94a89a6d6e580",
        "size": 3_713_369,
        "required": True,
    },
    "hand_features.npz": {
        "sha256": "de29659dd0a5668f2689fe5d83ead27e1449d9d1d0ae6b1db1d421aa3a616c37",
        "size": 593_590,
        "required": True,
    },
    # ── 可选（Qwen3-VL LoRA，仅 aesthetic / advisor 需要）──────
    "lora_aesthetic.safetensors": {
        "sha256": "571d808074916ddd5e244114bb2fb0084df900ab346815ea81b083a901e9add2",
        "size": 139_518_856,
        "required": False,
    },
    "lora_aesthetic_config.json": {
        "sha256": "a8cd78bdac08d501f54806dc82acc0c8daf35a501a3bacb4aadc082825db4071",
        "size": 1_156,
        "required": False,
    },
    "lora_advisor.safetensors": {
        "sha256": "26381130c226b49e73ab589fa53fe6e5791dd03f0ca173813b083e69f7df4b31",
        "size": 278_979_768,
        "required": False,
    },
    "lora_advisor_config.json": {
        "sha256": "a9e945d0c0a03fe7d964c666f681cbf6853a2cdbda1b29496bb9c4acf6979655",
        "size": 1_157,
        "required": False,
    },
}


def _env_suffix(name: str) -> str:
    return name.upper().replace(".", "_").replace("-", "_")


def weight_specs(names: Optional[List[str]] = None) -> "List":
    """构建 WeightSpec 列表（带环境变量覆盖）。"""
    from photo_s.modelstore import WeightSpec

    base = os.environ.get("PHOTOS_AUTO_TONE_URL_BASE", URL_BASE)
    specs = []
    for name, meta in WEIGHTS.items():
        if names is not None and name not in names:
            continue
        url = os.environ.get(f"PHOTOS_AUTO_TONE_{_env_suffix(name)}_URL",
                             f"{base}/{name}")
        sha = os.environ.get(f"PHOTOS_AUTO_TONE_{_env_suffix(name)}_SHA256",
                             meta["sha256"])
        specs.append(WeightSpec(name=name, url=url, sha256=sha, size=meta["size"]))
    return specs


def ensure_core() -> Dict[str, str]:
    """下载（如需）核心权重，返回 {name: 本地路径}。"""
    from photo_s.modelstore import ensure

    paths = {}
    for spec in weight_specs():
        if WEIGHTS[spec.name]["required"]:
            paths[spec.name] = ensure(spec)
    return paths


def core_path(name: str) -> str:
    """单个核心权重的本地路径（不存在则下载）。"""
    from photo_s.modelstore import ensure, cache_dir

    cached = os.path.join(cache_dir(), name)
    specs = weight_specs([name])
    if not specs:
        raise KeyError(f"unknown weight: {name}")
    # Verify on every use: "exists → trust" let a tampered/stale cache file
    # bypass the sha256 gate entirely after landing there once.
    from photo_s.modelstore import cached_path
    verified = cached_path(specs[0])
    if verified:
        return verified
    return ensure(specs[0])


_LORA_PREFIX = {"aesthetic": "lora_aesthetic", "advisor": "lora_advisor"}
_lora_lock = threading.Lock()
_lora_dirs: Dict[str, str] = {}


def ensure_lora_dir(kind: str) -> str:
    """组装 PEFT 需要的 LoRA 目录（adapter_config.json + adapter_model.safetensors）。

    modelstore 缓存是平铺文件，PEFT 需要目录布局，这里在缓存目录下建
    lora_<kind>/ 并把两个文件链接/复制进去。
    """
    if kind not in _LORA_PREFIX:
        raise ValueError(f"kind must be one of {sorted(_LORA_PREFIX)}")
    with _lora_lock:
        if kind in _lora_dirs:
            return _lora_dirs[kind]

        from photo_s.modelstore import cache_dir, ensure

        prefix = _LORA_PREFIX[kind]
        safetensors = ensure(weight_specs([f"{prefix}.safetensors"])[0])
        config = ensure(weight_specs([f"{prefix}_config.json"])[0])

        lora_dir = os.path.join(cache_dir(), f"lora_{kind}")
        os.makedirs(lora_dir, exist_ok=True)
        dst_w = os.path.join(lora_dir, "adapter_model.safetensors")
        dst_c = os.path.join(lora_dir, "adapter_config.json")
        _link_or_copy(safetensors, dst_w)
        _link_or_copy(config, dst_c)
        _lora_dirs[kind] = lora_dir
        return lora_dir


def _link_or_copy(src: str, dst: str) -> None:
    if os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(src):
        return
    tmp = dst + ".tmp"
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)


def pick_device() -> str:
    """cuda → mps → cpu 自动选择（保持多平台可用）。"""
    import torch

    if torch.cuda.is_available():
        return "cuda"
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


_shared_clip_lock = threading.Lock()
_shared_clip: Dict[str, tuple] = {}


def get_shared_clip(model_name: str, pretrained, device: str):
    """进程内共享的 CLIP 模型（predictor / rag / anomaly 复用同一份权重）。

    返回 (model, preprocess)。
    """
    key = f"{model_name}|{pretrained}|{device}"
    with _shared_clip_lock:
        if key not in _shared_clip:
            import open_clip

            model, _, preprocess = open_clip.create_model_and_transforms(
                model_name, pretrained=pretrained, device=device)
            model.eval()
            for p in model.parameters():
                p.requires_grad_(False)
            _shared_clip[key] = (model, preprocess)
        return _shared_clip[key]
