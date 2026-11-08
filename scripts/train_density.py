"""Train and evaluate the fish density counter (src/bluesight/density.py) on the biologists' tally dots.

Evaluation is leave-one-frame-out: for each annotated frame, a head is trained on the OTHER frames only and its count
on the held-out frame is compared with the biologists' count (and, for the two survey-video frames, with the motion
detector's count at the same instant from EVALUATION.md). The final model is then trained on all frames.

Usage:  python scripts/train_density.py [--variant raw|clahe] [--scale 1.0] [--steps 1500]
Writes: models/density/head.pt, outputs/density/eval.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bluesight.config import load_config, path, resolve_device  # noqa: E402
from bluesight.density import PATCH, Backbone, Head, dot_map, motion_channels, motion_zmap  # noqa: E402
from bluesight.enhance import enhance_frame  # noqa: E402

MOTION_COUNT = {"T1-STAT2@841": 14, "T1-STAT2@1320": 80}  # EVALUATION.md FINAL, protocol count at that instant


def prep(img: np.ndarray, variant: str, cfg: dict) -> np.ndarray:
    return enhance_frame(img, cfg["enhance"]) if variant == "clahe" else img


def cache_features(bb: Backbone, data, variant: str, scale: float, cfg: dict, cdir: Path, motion: bool = False) -> list[dict]:
    """Features for each image and its horizontal flip and two photometric variants (cached on disk)."""
    out = []
    meta = json.loads(str(data["meta"]))
    video = path(cfg, "videos_dir") / "T1-STAT2 411.MP4"
    for i, m in enumerate(meta):
        z = None
        if motion and m.get("time_s") is not None:
            zf = cdir / f"motion_{i}.npy"
            if not zf.exists():
                np.save(zf, motion_zmap(video, float(m["time_s"]), cfg))
            z = np.load(zf)
        img = prep(data["images"][i], variant, cfg)
        pts = np.asarray(data["points"][i], np.float32).reshape(-1, 2)
        ign = data["ignore"][i]
        views = []
        for k, (im, flip) in enumerate([(img, False), (img, True),
                                        (cv2.convertScaleAbs(img, alpha=1.15, beta=-10), False),
                                        (cv2.convertScaleAbs(img, alpha=0.85, beta=12), True)]):
            f = cdir / f"{variant}_{scale}_{i}_{k}.npy"
            if f.exists():
                feat = np.load(f)
            else:
                feat = bb.features(im[:, ::-1].copy() if flip else im, scale)
                np.save(f, feat)
            hp, wp = feat.shape[1:]
            if motion:
                mc = motion_channels(None if z is None else (z[:, ::-1] if flip else z), (hp, wp))
                feat = np.concatenate([feat.astype(np.float32), mc])
            p = pts.copy()
            if flip:
                p[:, 0] = im.shape[1] - 1 - p[:, 0]
            target = dot_map(p, (hp, wp), scale)
            ig = cv2.resize((ign[:, ::-1] if flip else ign).astype(np.uint8), (wp, hp), interpolation=cv2.INTER_AREA) > 0
            views.append({"feat": feat.astype(np.float32), "target": target, "valid": ~ig})
        out.append({"name": m["name"], "n": int(m["n"]), "views": views})
    return out


def smooth(t: np.ndarray, sigma: float) -> np.ndarray:
    return cv2.GaussianBlur(t, (0, 0), sigma) if sigma > 0 else t


SCALE = 100.0  # the head predicts density x 100 (keeps targets away from softplus' flat region)


def norm_stats(items: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    c = items[0]["views"][0]["feat"].shape[0]
    f = np.concatenate([v["feat"].reshape(c, -1) for it in items for v in it["views"][:1]], axis=1)
    return f.mean(1).astype(np.float32), (f.std(1) + 1e-3).astype(np.float32)


def train(items: list[dict], steps: int, device: str, sigma: float = 1.0, crop: int = 24, seed: int = 0,
          width: int = 128) -> Head:
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    c_in = items[0]["views"][0]["feat"].shape[0]
    head = Head(c_in=c_in, width=width).to(device)
    mu, sd = norm_stats(items)
    head.mu, head.sd = mu, sd
    opt = torch.optim.AdamW(head.parameters(), lr=1e-3, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, steps)
    views = [v for it in items for v in it["views"]]
    tgt = [smooth(v["target"], sigma) for v in views]
    # oversample crops that contain fish so the few positives are seen often
    for step in range(steps):
        fb, tb, vb = [], [], []
        for _ in range(16):
            j = rng.integers(len(views))
            v, t = views[j], tgt[j]
            hp, wp = t.shape
            if rng.random() < 0.6 and v["target"].sum() > 0:
                r, c = np.argwhere(v["target"] > 0)[rng.integers((v["target"] > 0).sum())]
                y = int(np.clip(r - rng.integers(crop), 0, hp - crop))
                x = int(np.clip(c - rng.integers(crop), 0, wp - crop))
            else:
                y, x = rng.integers(0, hp - crop + 1), rng.integers(0, wp - crop + 1)
            fb.append((v["feat"][:, y:y + crop, x:x + crop] - mu[:, None, None]) / sd[:, None, None])
            tb.append(t[y:y + crop, x:x + crop] * SCALE)
            vb.append(v["valid"][y:y + crop, x:x + crop])
        f = torch.from_numpy(np.stack(fb)).to(device)
        t = torch.from_numpy(np.stack(tb))[:, None].to(device)
        m = torch.from_numpy(np.stack(vb).astype(np.float32))[:, None].to(device)
        p = head(f)
        loss = (((p - t) ** 2) * m).sum() / m.sum().clamp(min=1) + \
            ((((p * m).sum((1, 2, 3)) - (t * m).sum((1, 2, 3))) / SCALE) ** 2).mean() * 1.0
        opt.zero_grad()
        loss.backward()
        opt.step()
        sched.step()
    return head.eval()


@torch.no_grad()
def predict(head: Head, item: dict, device: str) -> tuple[float, float]:
    v = item["views"][0]
    f = (v["feat"] - head.mu[:, None, None]) / head.sd[:, None, None]
    d = head(torch.from_numpy(f)[None].to(device))[0, 0].cpu().numpy() / SCALE
    return float((d * v["valid"]).sum()), float(v["target"][v["valid"]].sum())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="raw", choices=["raw", "clahe"])
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--steps", type=int, default=1500)
    ap.add_argument("--sigma", type=float, default=1.0)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--motion", action="store_true", help="add motion z-score channels (survey-video frames only)")
    ap.add_argument("--final", action="store_true", help="also train on all frames and save models/density/head.pt")
    a = ap.parse_args()
    cfg = load_config()
    device = resolve_device(cfg)
    out_dir = path(cfg, "outputs_dir") / "density"
    cdir = out_dir / "feat_cache"
    cdir.mkdir(parents=True, exist_ok=True)
    data = np.load(out_dir / "dataset.npz", allow_pickle=True)
    t0 = time.time()
    bb = Backbone(device)
    items = cache_features(bb, data, a.variant, a.scale, cfg, cdir, a.motion)
    print(f"features ready in {time.time() - t0:.0f} s; patch grid {items[0]['views'][0]['feat'].shape[1:]}")
    rows = []
    for k, it in enumerate(items):
        rest = [x for j, x in enumerate(items) if j != k]
        preds = []
        for s in range(a.seeds):
            h = train(rest, a.steps, device, a.sigma, seed=s)
            preds.append(predict(h, it, device)[0])
        _, truth = predict(h, it, device)
        key = next((m for m in MOTION_COUNT if it["name"].startswith(m)), None)
        rows.append({"held_out": it["name"], "biologists": round(truth), "density_mean": round(float(np.mean(preds)), 1),
                     "density_seeds": [round(p, 1) for p in preds], "motion_detector": MOTION_COUNT.get(key) if key else None})
        print(rows[-1])
    res = {"variant": a.variant, "scale": a.scale, "steps": a.steps, "sigma": a.sigma, "seeds": a.seeds, "folds": rows,
           "device": device, "seconds": round(time.time() - t0)}
    tag = f"{a.variant}_s{a.scale}_sig{a.sigma}" + ("_motion" if a.motion else "")
    allres = json.loads((out_dir / "eval.json").read_text()) if (out_dir / "eval.json").exists() else {}
    allres[tag] = res
    (out_dir / "eval.json").write_text(json.dumps(allres, indent=1))
    if a.final:
        h = train(items, a.steps, device, a.sigma, seed=0)
        wdir = ROOT / "models" / "density"
        wdir.mkdir(parents=True, exist_ok=True)
        torch.save({"state": h.state_dict(), "cfg": {"variant": a.variant, "scale": a.scale, "width": 128, "motion": a.motion,
                                                     "c_in": int(items[0]["views"][0]["feat"].shape[0]),
                                                     "target_scale": SCALE}, "mu": h.mu, "sd": h.sd,
                    "tag": tag, "trained_on": [it["name"] for it in items], "loo": rows}, wdir / "head.pt")
        print("saved", wdir / "head.pt")


if __name__ == "__main__":
    main()
