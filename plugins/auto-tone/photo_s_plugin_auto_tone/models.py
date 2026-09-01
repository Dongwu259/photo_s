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

视觉塔（SigLIP / CLIP，open_clip 运行时从 HuggingFace 拉取的大文件）
由 :func:`resolve_tower_pretrained` 经 modelstore 下载校验，国内可回落
ModelScope 镜像（见 TOWERS 注释）。
"""

import json
import os
import shutil
import threading
from typing import Dict, List, Optional

GITHUB_REPO = "Dongwu259/photo_s"
RELEASE_TAG = "auto-tone-v0.1.0"
URL_BASE = f"https://github.com/{GITHUB_REPO}/releases/download/{RELEASE_TAG}"
# v2.1 风格化权重托管在独立 release tag（老 tag 不动，已有缓存不受影响）
STYLE_RELEASE_TAG = "auto-tone-v2.1.0"
STYLE_URL_BASE = f"https://github.com/{GITHUB_REPO}/releases/download/{STYLE_RELEASE_TAG}"

QWEN_BASE_MODEL = os.environ.get("PHOTOS_AUTO_TONE_QWEN_BASE",
                                 "Qwen/Qwen3-VL-2B-Instruct")

# ── 视觉塔（open_clip 的大权重，~1.7-2.6GB）───────────────────────────────
#
# open_clip 默认经 huggingface_hub 从 HF 拉塔（国内常 SSL 失败）。
# resolve_tower_pretrained() 在交给 open_clip 前把 pretrained tag 解析成
# 本地文件：先查 HF hub 缓存（老用户零重复下载），否则按来源链下载到
# modelstore towers/ 目录——复用 ensure() 的断点续传/重试/sha256 校验。
#
# 来源链 PHOTOS_AUTO_TONE_TOWER_SOURCE：
#   auto（默认）= 先 HuggingFace，失败回落 ModelScope 镜像
#   hf          = 仅 HuggingFace
#   modelscope  = 仅 ModelScope（国内推荐，跳过必失败的 HF 尝试）
# 单塔 URL / sha256 可用 PHOTOS_AUTO_TONE_TOWER_URL / _SHA256 整体覆盖。
#
# sha256 为上游文件内容哈希（HF LFS blob 名，本机缓存实测复核）；
# ModelScope 镜像按同一 sha 校验——镜像与上游不一致会在校验处报错，
# 不会静默用上被替换的权重。
TOWERS: Dict[str, dict] = {
    # SigLIP ViT-L/16 384 webli —— auto_tone_with_style / analyze_visual_style
    # sha256 = ModelScope 镜像实测（2.61GB 全量下载校验，2026-09-02）
    "timm/ViT-L-16-SigLIP-384": {
        "filename": "open_clip_pytorch_model.bin",
        "sha256": "0e5943977fd1c6048c056921cc34da37aa0374a8f56ad3b1e111be6ea90aea8d",
        "size": 2_610_158_302,
        "modelscope": "timm/ViT-L-16-SigLIP-384",
    },
    # CLIP ViT-L/14 openai —— v7_clean predictor / RAG / anomaly
    "timm/vit_large_patch14_clip_224.openai": {
        "filename": "open_clip_pytorch_model.bin",
        "sha256": "9ce2e8a8ebfff3793d7d375ad6d3c35cb9aebf3de7ace0fc7308accab7cd207e",
        "size": 1_710_517_724,
        "modelscope": "timm/vit_large_patch14_clip_224.openai",
    },
}

_TOWER_CANDIDATE_FILES = ("open_clip_model.safetensors",
                          "open_clip_pytorch_model.bin")


def _tower_repo(model_name: str, pretrained) -> Optional[str]:
    """(model_name, pretrained tag) → open_clip 配置里的 HF repo id。

    无 hf_hub（直链 URL 型 pretrained）或 open_clip 不可导入时返回 None，
    调用方原样透传给 open_clip 维持旧行为。
    """
    try:
        from open_clip.pretrained import get_pretrained_cfg
    except ImportError:
        return None
    try:
        cfg = get_pretrained_cfg(model_name, pretrained)
    except Exception:
        return None
    repo = None
    if isinstance(cfg, dict):
        repo = (cfg.get("hf_hub") or "").rstrip("/") or None
    elif isinstance(cfg, (tuple, list)) and cfg and cfg[0]:
        loc = str(cfg[0])
        repo = None if loc.startswith(("http://", "https://")) else loc
    return repo


def _hf_cache_hit(repo: str) -> Optional[str]:
    """HF hub 本地缓存已命中 → 直接用（完整性由 HF blob sha 布局保证）。"""
    try:
        from huggingface_hub import try_to_load_from_cache
    except ImportError:
        return None
    for fn in _TOWER_CANDIDATE_FILES:
        try:
            p = try_to_load_from_cache(repo_id=repo, filename=fn)
        except Exception:
            p = None
        if p and os.path.isfile(p):
            return p
    return None


def _tower_spec(repo: str, source: str):
    """构建塔的 WeightSpec（modelstore 缓存名 towers/<repo>/<filename>）。"""
    from photo_s.modelstore import WeightSpec

    meta = TOWERS[repo]
    fn = meta["filename"]
    if source == "modelscope":
        url = (f"https://modelscope.cn/models/{meta['modelscope']}"
               f"/resolve/master/{fn}")
    else:
        url = f"https://huggingface.co/{repo}/resolve/main/{fn}"
    url = os.environ.get("PHOTOS_AUTO_TONE_TOWER_URL", url)
    sha = os.environ.get("PHOTOS_AUTO_TONE_TOWER_SHA256", meta["sha256"])
    return WeightSpec(
        name=f"towers/{repo.replace('/', '__')}/{fn}",
        url=url, sha256=sha, size=meta["size"])


def resolve_tower_pretrained(model_name: str, pretrained):
    """把 open_clip 的 pretrained tag 解析成本地塔文件路径（可下载）。

    返回值直接作 create_model_and_transforms 的 pretrained 参数：
    本地文件路径、或原样透传的 URL/未知 tag。已有 HF 缓存优先复用。
    """
    if (not isinstance(pretrained, str) or not pretrained
            or os.path.exists(pretrained)
            or pretrained.startswith(("http://", "https://", "file://"))):
        return pretrained

    repo = _tower_repo(model_name, pretrained)
    if not repo or repo not in TOWERS:
        # 未登记的塔：维持 open_clip 自身下载行为
        return pretrained

    cached = _hf_cache_hit(repo)
    if cached:
        return cached

    source = os.environ.get("PHOTOS_AUTO_TONE_TOWER_SOURCE",
                            "auto").strip().lower()
    chain = {"hf": ["hf"], "modelscope": ["modelscope"]}.get(
        source, ["hf", "modelscope"])

    from photo_s.modelstore import ensure

    errors = []
    for src in chain:
        try:
            return ensure(_tower_spec(repo, src))
        except RuntimeError as e:
            errors.append(f"{src}: {e}")
    raise RuntimeError(
        "auto-tone 视觉塔下载失败 ({})。可设 PHOTOS_AUTO_TONE_TOWER_SOURCE="
        "modelscope 走国内镜像，或 PHOTOS_AUTO_TONE_TOWER_URL 指向自备文件"
        "（sha256 需匹配）。详情: {}".format(repo, "; ".join(errors)))

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
        # v0.1.0 起此值多打了一个字符（db21d4→db1d4），导致线上资产校验
        # 必败——2026-08-28 以 GitHub release 资产实测 sha 修正
        "sha256": "de29659dd0a5668f2689fe5d83ead27e1449d9d1d0ae6b1db1d421aa3a616c37",
        "size": 593_590,
        "required": True,
    },
    # ── v2.1 风格化（auto_tone_with_style / analyze_visual_style）──
    # SigLIP+MLP h192 d=0.3（PSNR 32.21，比 v7_clean 高 2.93 dB）。
    # 重存为纯 tensor/Python 类型，兼容 torch.load(weights_only=True)。
    "auto_tone_siglip_h192_d03.pt": {
        "sha256": "d64d2ea67cc725ffb61663c50239e1d9be95c6a559abaed37aedfcb0d2b68c92",
        "size": 871_277,
        "required": False,
        "url_base": STYLE_URL_BASE,
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

    # PHOTOS_AUTO_TONE_URL_BASE 覆盖所有条目的前缀（离线/镜像/测试），
    # 优先级高于条目各自的 url_base；未覆盖时 v2.1 条目用 STYLE_URL_BASE
    env_base = os.environ.get("PHOTOS_AUTO_TONE_URL_BASE")
    base = env_base or URL_BASE
    specs = []
    for name, meta in WEIGHTS.items():
        if names is not None and name not in names:
            continue
        entry_base = env_base or meta.get("url_base", base)
        url = os.environ.get(
            f"PHOTOS_AUTO_TONE_{_env_suffix(name)}_URL",
            f"{entry_base}/{name}")
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

    返回 (model, preprocess)。塔权重经 resolve_tower_pretrained 解析
    （HF 缓存命中 / modelstore 下载 + ModelScope 国内回落）。
    """
    with _shared_clip_lock:
        key = f"{model_name}|{pretrained}|{device}"
        if key not in _shared_clip:
            import open_clip

            model, _, preprocess = open_clip.create_model_and_transforms(
                model_name,
                pretrained=resolve_tower_pretrained(model_name, pretrained),
                device=device)
            model.eval()
            for p in model.parameters():
                p.requires_grad_(False)
            _shared_clip[key] = (model, preprocess)
        return _shared_clip[key]
