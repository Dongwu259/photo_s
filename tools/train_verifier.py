#!/usr/bin/env python3
"""美学 verifier 训练（SigLIP 嵌入 + MLP 回归头 → 1-10 分）。

v2.4 全自动闭环的 reward/stop 条件。数据源（任一）：
  1. lr-scan 导出的 lr_records.jsonl——每条带 ``rating``（0-5 星，
     v2.4 起 lr-scan 从 Adobe_images.rating 读出）。星级 ×2 = 1-10 分
     （你的星级就是你的美学标注）。
  2. 任意 JSONL：每行 ``{"path": ..., "score": 1-10}``（或 ``image`` 键）。

输出 ``aesthetic_head.pt``（纯 tensor/内建类型，weights_only 兼容），
放 ``~/.cache/photo-s/models/`` 或设 ``PHOTOS_AUTO_TONE_AESTHETIC_HEAD``；
之后 ``photo-s audit --aesthetic 6`` / MCP ``verify_aesthetic`` / REST
``/v1/aesthetic/verify`` 即用它打分。

用法：
    pip install 'photo-s-plugin-auto-tone[model]'
    python3 tools/train_verifier.py --data data/lr_records.jsonl \
        --images data/before --out aesthetic_head.pt
    python3 tools/train_verifier.py --data ratings.jsonl   # score 字段
"""

import argparse
import json
import sys


def _records(data: str) -> list:
    with open(data, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _labels(recs: list, images: str):
    """(image_path, score) 列表：rating×2 或显式 score 字段。"""
    import os

    out = []
    for r in recs:
        path = r.get("path") or r.get("image") or ""
        if not path:
            continue
        if images and not os.path.isabs(path):
            path = os.path.join(images, path)
        if r.get("score") is not None:
            score = float(r["score"])
        else:
            rating = int(r.get("rating") or 0)
            if rating < 1:  # 未评级/淘汰不给监督信号
                continue
            score = float(min(rating, 5) * 2)
        if not (1.0 <= score <= 10.0):
            continue
        if not os.path.isfile(path):
            continue
        out.append((path, score))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True,
                    help="JSONL：lr_records.jsonl（rating）或 {path,score}")
    ap.add_argument("--images", default=None,
                    help="相对路径时的图片根目录（lr-scan --render-dir 产物）")
    ap.add_argument("--out", default="aesthetic_head.pt")
    ap.add_argument("--hidden", type=int, default=256)
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--dropout", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    try:
        import torch
    except ImportError:
        raise SystemExit("需要 torch：pip install torch")
    try:
        from photo_s_plugin_auto_tone import models as plugin_models
    except ImportError:
        raise SystemExit(
            "需要 auto-tone 插件（塔复用其 SigLIP + ModelScope 下载链）：\n"
            "  pip install 'photo-s-plugin-auto-tone[model]'")
    import numpy as np
    from PIL import Image

    recs = _records(args.data)
    labels = _labels(recs, args.images)
    if len(labels) < 40:
        raise SystemExit(
            f"带评分样本不足（{len(labels)} < 40）——多台机器可用 lr-merge 合并")
    scores = np.array([s for _, s in labels], dtype=np.float32)
    print(f"样本 {len(labels)}，分数分布 "
          f"min={scores.min():.1f} max={scores.max():.1f} "
          f"mean={scores.mean():.2f} std={scores.std():.2f}")

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    device = plugin_models.pick_device()

    model_name = "ViT-L-16-SigLIP-384"
    pretrained = "webli"
    tower, preprocess = plugin_models.get_shared_clip(
        model_name, pretrained, device)
    tower.eval()

    feats = []
    for path, _ in labels:
        img = Image.open(path).convert("RGB")
        with torch.no_grad():
            emb = tower.encode_image(
                preprocess(img).unsqueeze(0).to(device)).float().cpu()
            emb = emb / (emb.norm(dim=-1, keepdim=True) + 1e-8)
        feats.append(emb.squeeze(0).numpy())
    F = np.stack(feats).astype(np.float32)
    sig_dim = int(F.shape[1])
    print(f"嵌入 {sig_dim} 维（{model_name}）")

    # 分数归一化：回归目标 ~N(0,1)，推理侧反归一化（checkpoint norm 键）
    y_mean, y_std = float(scores.mean()), float(scores.std() or 1.0)
    Y = ((scores - y_mean) / y_std).astype(np.float32)

    n_total = len(F)
    val_n = max(1, n_total // 10)
    rng = np.random.RandomState(args.seed)
    val_idx = set(rng.choice(n_total, size=val_n, replace=False).tolist())
    train_idx = [i for i in range(n_total) if i not in val_idx]
    val_idx = sorted(val_idx)

    head = torch.nn.Sequential(
        torch.nn.Linear(sig_dim, args.hidden),
        torch.nn.GELU(),
        torch.nn.Dropout(args.dropout),
        torch.nn.Linear(args.hidden, 1),
    ).to(device)
    opt = torch.optim.AdamW(head.parameters(), lr=args.lr,
                            weight_decay=1e-4)
    loss_fn = torch.nn.MSELoss()
    Xt = torch.from_numpy(F).to(device)
    Yt = torch.from_numpy(Y).to(device).unsqueeze(1)
    Xtr, Ytr = Xt[train_idx], Yt[train_idx]
    n = len(train_idx)
    for epoch in range(args.epochs):
        head.train()
        total = 0.0
        perm = torch.randperm(n)
        for i in range(0, n, args.batch):
            idx = perm[i:i + args.batch]
            loss = loss_fn(head(Xtr[idx]), Ytr[idx])
            opt.zero_grad()
            loss.backward()
            opt.step()
            total += float(loss) * len(idx)
        if (epoch + 1) % 10 == 0 or epoch == 0:
            print(f"epoch {epoch + 1}/{args.epochs}  mse={total / n:.5f}")

    head.eval()
    with torch.no_grad():
        vpred = head(Xt[val_idx]).cpu().numpy().reshape(-1)
    yv = Y[val_idx]
    mae = float(np.abs(yv - vpred).mean())
    # 分数域 MAE（1-10 尺度，直观）
    mae_score = mae * y_std
    vz, vzp = yv, vpred
    if vz.std() > 1e-6 and vzp.std() > 1e-6:
        pearson = float(np.corrcoef(vz, vzp)[0, 1])
    else:
        pearson = 0.0
    print(f"val MAE={mae_score:.2f} 分（1-10 尺度）  pearson={pearson:.3f} "
          f"(held-out {len(val_idx)})")

    sd = {k: v.detach().cpu() for k, v in head.state_dict().items()}
    torch.save({
        "schema": 1,
        "type": "aesthetic_head",
        "model_name": model_name,
        "pretrained": pretrained,
        "sig_dim": sig_dim,
        "state_dict": sd,
        "norm": {"mean": y_mean, "std": y_std},
        "val": {"mae_score": mae_score, "pearson": pearson,
                "n_val": len(val_idx)},
        "n_samples": n_total,
    }, args.out)
    print(f"已存 {args.out}  →  放 ~/.cache/photo-s/models/ 或设 "
          f"PHOTOS_AUTO_TONE_AESTHETIC_HEAD；试：photo-s audit IMG "
          f"--aesthetic 6")


if __name__ == "__main__":
    sys.exit(main())
