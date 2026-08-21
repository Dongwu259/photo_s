#!/usr/bin/env python3
"""自动基调回归（torch 升级版，参考实现）——冻结 CLIP + MLP 头。

模型 A 的升级路径：84 维直方图特征（numpy 岭回归，`photo-s lr-train`）
→ 768 维 CLIP embedding（本脚本）。数据格式完全复用 lr_records.jsonl。

用法：
    pip install open-clip-torch torch
    python3 tools/train_tone_torch.py --data data/lr_records.jsonl \
        --images data/before --out tone_clip.npz --epochs 40
    python3 tools/train_tone_torch.py --predict new.jpg --model tone_clip.npz

输出 npz：W (hidden, emb) + b (hidden,) + W2 (9, hidden) + b2 (9,) + targets，
与 lrxmp.TARGETS 同序；`photo-s lr-predict` 自动识别该格式（含旧版转置兼容）。

推理建议直接用 `photo-s lr-predict IMG --model tone_clip.npz`
（本脚本 predict 子命令亦委托 photo_s.lrxmp，保证单一实现）。
"""

import argparse
import json
import sys


def _records(data: str) -> list:
    with open(data, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def train(args) -> None:
    try:
        import torch
        import open_clip
    except ImportError:
        raise SystemExit("需要 torch + open-clip-torch："
                         "pip install torch open-clip-torch")
    import numpy as np
    from PIL import Image
    try:
        from photo_s.lrxmp import TARGETS, load_training_data
    except ModuleNotFoundError:
        raise SystemExit(
            "需要 photo-s-tools 包：pip install photo-s-tools "
            "（或从仓库根目录运行：python tools/train_tone_torch.py）")

    recs = _records(args.data)
    X, Y, metas, _stats = load_training_data(recs, args.images)
    if len(X) < 30:
        raise SystemExit(f"样本不足（{len(X)} < 30），先合并各电脑数据")
    print(f"样本 {len(X)} 张，目标 {len(TARGETS)} 项")

    model, _, preprocess = open_clip.create_model_and_transforms(
        args.clip_model, pretrained=args.clip_pretrained)
    model.eval()
    for p in model.parameters():
        p.requires_grad_(False)
    emb_dim = model.visual.output_dim or 768

    feats = []
    for _x, meta in zip(X, metas):
        img = Image.open(meta["image"]).convert("RGB")
        with torch.no_grad():
            f = model.encode_image(preprocess(img).unsqueeze(0))
        feats.append(f.squeeze(0).numpy())
    F = np.stack(feats)
    Yn = np.asarray(Y, dtype=np.float32)

    head = torch.nn.Sequential(
        torch.nn.Linear(emb_dim, 256),
        torch.nn.ReLU(),
        torch.nn.Dropout(args.dropout),
        torch.nn.Linear(256, len(TARGETS)),
    )
    opt = torch.optim.AdamW(head.parameters(), lr=args.lr, weight_decay=1e-4)
    loss_fn = torch.nn.MSELoss()
    Xt = torch.from_numpy(F)
    Yt = torch.from_numpy(Yn)
    n = len(F)
    for epoch in range(args.epochs):
        head.train()
        total = 0.0
        perm = torch.randperm(n)
        for i in range(0, n, args.batch):
            idx = perm[i:i + args.batch]
            pred = head(Xt[idx])
            loss = loss_fn(pred, Yt[idx])
            opt.zero_grad()
            loss.backward()
            opt.step()
            total += float(loss) * len(idx)
        if (epoch + 1) % 10 == 0 or epoch == 0:
            print(f"epoch {epoch + 1}/{args.epochs}  mse={total / n:.5f}")

    head.eval()
    with torch.no_grad():
        pred = head(Xt).numpy()
    ss_res = float(((Yn - pred) ** 2).sum())
    ss_tot = float(((Yn - Yn.mean(axis=0)) ** 2).sum())
    r2 = 1.0 - ss_res / max(ss_tot, 1e-12)

    W = head[0].weight.detach().numpy()
    b0 = head[0].bias.detach().numpy()
    W2 = head[3].weight.detach().numpy()
    b2 = head[3].bias.detach().numpy()
    np.savez(args.out, W=W, b=b0, W2=W2, b2=b2, targets=np.array(TARGETS),
             emb_dim=emb_dim, clip_model=args.clip_model,
             clip_pretrained=args.clip_pretrained, r2=float(r2),
             n_samples=n)
    print(f"已存 {args.out}  R²={r2:.3f}")


def predict(args) -> None:
    try:
        from photo_s.lrxmp import predict_auto_tone
    except ModuleNotFoundError:
        raise SystemExit(
            "需要 photo-s-tools 包：pip install photo-s-tools "
            "（或从仓库根目录运行：python tools/train_tone_torch.py）")

    print(json.dumps(predict_auto_tone(args.predict, args.model),
                     ensure_ascii=False, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    t = sub.add_parser("train")
    t.add_argument("--data", required=True)
    t.add_argument("--images", default=None)
    t.add_argument("--out", default="tone_clip.npz")
    t.add_argument("--clip-model", default="ViT-L-14")
    t.add_argument("--clip-pretrained", default="openai")
    t.add_argument("--epochs", type=int, default=40)
    t.add_argument("--batch", type=int, default=32)
    t.add_argument("--lr", type=float, default=1e-3)
    t.add_argument("--dropout", type=float, default=0.1)
    t.set_defaults(func=train)
    p = sub.add_parser("predict")
    p.add_argument("--predict", required=True)
    p.add_argument("--model", default="tone_clip.npz")
    p.set_defaults(func=predict)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
