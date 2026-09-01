#!/usr/bin/env python3
"""局部调整标签制备：LR 几何蒙版 × AI 分割 → 语义 region 标签。

v2.4 词汇表扩展的训练侧。auto-tone 局部头输出语义 region
（subject/person/object:label），但 LR 数据里的蒙版是几何的
（linear/radial/color）。本脚本用 IoU 把两者接起来：

    对每条 lr_records 记录（含 masks/mask_adjust）：
      1. 渲染 LR 几何蒙版（photo_s.mask.render_mask）
      2. 渲染 AI 语义蒙版（photo_s.segmask：subject / person）
      3. IoU >= 阈值（默认 0.45）→ 该 LR 蒙版的标量调整记为该语义
         region 的局部标签
    输出 local_labels.jsonl：{"path": ..., "local": [{region, params}]}

    python3 tools/train_verifier.py 的兄弟件——把 local_labels.jsonl 并进
    你的 .pt 训练（checkpoint 增 local_state_dict / local_regions /
    local_params / local_ranges，推理侧 predictor 已支持）。

用法：
    python3 tools/prep_local_labels.py --data data/lr_records.jsonl \
        --images data/before --out data/local_labels.jsonl
"""

import argparse
import json
import sys


def _records(data: str) -> list:
    with open(data, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, help="lr_records.jsonl")
    ap.add_argument("--images", default=None, help="相对路径图片根目录")
    ap.add_argument("--out", default="local_labels.jsonl")
    ap.add_argument("--iou", type=float, default=0.45,
                    help="LR 蒙版与语义蒙版的 IoU 阈值（默认 0.45）")
    ap.add_argument("--regions", default="subject,person",
                    help="候选语义 region（逗号分隔）")
    args = ap.parse_args()

    try:
        import numpy as np
        from PIL import Image
        from photo_s.mask import parse_mask_adjust, parse_masks, render_mask
        from photo_s.segmask import segment
    except ImportError as e:
        raise SystemExit(f"缺依赖：{e}\n  pip install photo-s-tools pillow numpy")

    import os

    regions = [r.strip() for r in args.regions.split(",") if r.strip()]
    recs = _records(args.data)
    out = []
    n_with = 0
    for rec in recs:
        path = rec.get("path") or ""
        opts = rec.get("options") or {}
        masks_s, adj_s = opts.get("masks", ""), opts.get("mask_adjust", "")
        if not path or not masks_s or not adj_s:
            continue
        if args.images and not os.path.isabs(path):
            path = os.path.join(args.images, path)
        if not os.path.isfile(path):
            continue
        try:
            img = Image.open(path).convert("RGB")
        except OSError:
            continue
        specs = {s.name: s for s in parse_masks(masks_s)}
        adjusts = parse_mask_adjust(adj_s)
        w, h = img.width, img.height

        # 该图的语义蒙版（懒渲染一次）：region -> bool 数组
        sem = {}
        try:
            for region in regions:
                kind = region if ":" not in region else region.split(":", 1)[0]
                label = region.split(":", 1)[1] if ":" in region else None
                m = segment(img, kind, label=label)
                if m is not None:
                    sem[region] = np.asarray(m) > 0.5
        except Exception as e:
            print(f"  跳过 {os.path.basename(path)}：AI 蒙版失败 {e}",
                  file=sys.stderr)
            continue

        local = []
        for name, adjust in adjusts.items():
            spec = specs.get(name)
            if spec is None or not adjust:
                continue
            try:
                m = render_mask(spec, w, h, img=img, refs=specs)
            except Exception:
                continue
            mb = np.asarray(m) > 0.5
            if not mb.any():
                continue
            best_region, best_iou = None, args.iou
            for region, sb in sem.items():
                inter = float((mb & sb).sum())
                union = float((mb | sb).sum()) or 1.0
                iou = inter / union
                if iou >= best_iou:
                    best_region, best_iou = region, iou
            if best_region is None:
                continue
            scalars = {k: float(v) for k, v in adjust.items()
                       if isinstance(v, (int, float)) and v}
            if scalars:
                local.append({"region": best_region,
                              "params": scalars,
                              "iou": round(best_iou, 3)})
        if local:
            out.append({"path": path, "local": local})
            n_with += 1

    with open(args.out, "w", encoding="utf-8") as f:
        for row in out:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"完成：{len(recs)} 条记录 → {n_with} 条带语义局部标签 → {args.out}")
    if not out:
        print("提示：需要 [enhance] extra（AI 分割）+ 本地图片；"
              "检查 --images 是否指向 lr-scan --render-dir 产物")


if __name__ == "__main__":
    sys.exit(main())
