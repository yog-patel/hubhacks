"""Train and evaluate FishSpotter (src/bluesight/spotter.py) on the biologists' tally dots. Dev tool; every number is measured.

Training labels (one dot per counted fish, placed by Coastal Action biologists):
* T2-STAT2 (another station / video): the gridded screenshots with red tally dots. Red marks, grid lines and the
  VLC control bar are painted out before training.
* T1-STAT2 14:01 (this video, tuning half): the exact video frames 25212-25216 with the 36 extracted tally points.
The 22:00 count (demo half) is NEVER used for training or for choosing anything.

    python scripts/train_spotter.py cross     # honest test: train on T2-STAT2 only, test on T1-STAT2 14:01 (never seen)
    python scripts/train_spotter.py final     # train on T2-STAT2 + T1 14:01 + frames verified in the app
                                              # (outputs/training/assisted/) -> models/fishspotter/fishspotter_v1.pt
Results are appended to outputs/eval/experiments.json (id "E9").
"""
from __future__ import annotations

import argparse
import glob
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bluesight.config import ROOT, load_config, path, resolve_device  # noqa: E402
from bluesight.enhance import enhance_frame  # noqa: E402
from bluesight.spotter import STRIDE, build_model, peaks, to_tensor  # noqa: E402
from experiments import EXP, GT_IDX, VFPS, decode_exact, gt_points, log_result, prf  # noqa: E402
from prepare_resources import find_red_annotations, red_mask  # noqa: E402

OUT = ROOT / "models" / "fishspotter"


# ----------------------------------------------------------------------------- data
def clean_screenshot(img: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Paint out red marks and black grid lines; return (clean image, valid mask: 0 over the VLC control bar)."""
    m = cv2.dilate(red_mask(img), np.ones((5, 5), np.uint8))
    dark = (img.max(axis=2) < 45).astype(np.uint8)
    lines = cv2.morphologyEx(dark, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (61, 1)))
    lines |= cv2.morphologyEx(dark, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 61)))
    m |= cv2.dilate(lines, np.ones((5, 5), np.uint8))
    clean = cv2.inpaint(img, m, 3, cv2.INPAINT_TELEA)
    H, W = img.shape[:2]
    valid = np.ones((H, W), np.uint8)
    # VLC control bar (bottom centre; same layout in every screenshot)
    valid[int(0.90 * H):, int(0.30 * W):int(0.74 * W)] = 0
    return clean, valid


def t2_samples(min_dots: int = 10) -> list[dict]:
    out = []
    for f in sorted(glob.glob(str(ROOT / "data" / "raw_photos" / "**" / "T2_STAT 2*.png"), recursive=True)):
        img = cv2.imread(f)
        _, dots = find_red_annotations(img)
        if len(dots) < min_dots:  # photos without systematic tally dots: other fish there are unlabelled
            continue
        clean, valid = clean_screenshot(img)
        out.append({"name": Path(f).name, "img": clean, "pts": np.array(dots, np.float32), "valid": valid})
    return out


def t1_samples() -> list[dict]:
    EXP.mkdir(parents=True, exist_ok=True)
    decode_exact()
    z = np.load(EXP / "gt_exact.npz")
    fr = dict(zip(z["idx"].tolist(), z["ims"]))
    pts = gt_points().astype(np.float32)
    return [{"name": f"T1-14:01 frame {i}", "img": fr[i], "pts": pts, "valid": np.ones(fr[i].shape[:2], np.uint8)}
            for i in GT_IDX]


def assisted_samples(cfg: dict) -> list[dict]:
    """Frames verified on the Verify counts page: the biologist's final marks are the labels (outputs/training/assisted/)."""
    import json

    out = []
    for f in sorted(path(cfg, "training_dir").glob("*.json")) if path(cfg, "training_dir").exists() else []:
        rec = json.loads(f.read_text())
        img = cv2.imread(str(f.with_suffix(".jpg")))
        if img is None or not rec.get("points"):
            continue
        out.append({"name": f"verified {rec['run_id']} @ {rec['subsample_t_s']:.0f}s", "img": img,
                    "pts": np.array(rec["points"], np.float32), "valid": np.ones(img.shape[:2], np.uint8)})
    return out


def target(h: int, w: int, pts: np.ndarray, sigma: float = 1.5) -> np.ndarray:
    """Gaussian heatmap at stride 4 with an exact 1.0 at each point's cell."""
    gh, gw = h // STRIDE, w // STRIDE
    yy, xx = np.mgrid[0:gh, 0:gw].astype(np.float32)
    t = np.zeros((gh, gw), np.float32)
    for x, y in pts:
        cx, cy = x / STRIDE, y / STRIDE
        if 0 <= cx < gw and 0 <= cy < gh:
            t = np.maximum(t, np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * sigma ** 2)))
            t[int(cy), int(cx)] = 1.0
    return t


def augment(img: np.ndarray, pts: np.ndarray, valid: np.ndarray, size: int, rng) -> tuple:
    H, W = img.shape[:2]
    s = rng.uniform(0.8, 1.25)
    img = cv2.resize(img, (int(W * s), int(H * s)), interpolation=cv2.INTER_LINEAR)
    valid = cv2.resize(valid, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST)
    pts = pts * s
    H, W = img.shape[:2]
    if len(pts) and rng.random() < 0.7:  # most crops centred near a fish
        cx, cy = pts[rng.integers(len(pts))] + rng.uniform(-size / 3, size / 3, 2)
        x0, y0 = int(np.clip(cx - size / 2, 0, W - size)), int(np.clip(cy - size / 2, 0, H - size))
    else:
        x0, y0 = int(rng.integers(0, W - size + 1)), int(rng.integers(0, H - size + 1))
    img = img[y0:y0 + size, x0:x0 + size].astype(np.float32)
    valid = valid[y0:y0 + size, x0:x0 + size]
    pts = pts - [x0, y0]
    pts = pts[(pts[:, 0] >= 0) & (pts[:, 0] < size) & (pts[:, 1] >= 0) & (pts[:, 1] < size)] if len(pts) else pts
    if rng.random() < 0.5:
        img, valid = img[:, ::-1], valid[:, ::-1]
        pts = np.c_[size - 1 - pts[:, 0], pts[:, 1]] if len(pts) else pts
    # water colour, brightness, contrast, haze, blur, noise: the two stations look different
    img = img * rng.uniform(0.8, 1.2, 3)[None, None]
    mean = img.mean()
    img = (img - mean) * rng.uniform(0.6, 1.4) + mean * rng.uniform(0.8, 1.2)
    if rng.random() < 0.3:
        img = img * (1 - (a := rng.uniform(0.1, 0.4))) + a * img.mean((0, 1))[None, None]
    if rng.random() < 0.3:
        img = cv2.GaussianBlur(img, (0, 0), rng.uniform(0.5, 1.5))
    img = img + rng.normal(0, rng.uniform(0, 6), img.shape)
    return np.clip(img, 0, 255).astype(np.uint8), np.ascontiguousarray(pts, np.float32), np.ascontiguousarray(valid)


def focal_loss(logits, gt, valid):
    import torch

    p = torch.sigmoid(logits).clamp(1e-4, 1 - 1e-4)
    pos = gt.eq(1).float()
    neg = (1 - pos) * valid
    pos_l = -torch.log(p) * (1 - p) ** 2 * pos
    neg_l = -torch.log(1 - p) * p ** 2 * (1 - gt) ** 4 * neg
    return (pos_l.sum() + neg_l.sum()) / pos.sum().clamp(min=1.0)


def prep(img: np.ndarray, ecfg: dict | None) -> np.ndarray:
    return enhance_frame(img, ecfg) if ecfg is not None else img


def train(samples: list[dict], cfg: dict, steps: int, size: int = 320, batch: int = 8, seed: int = 0, log_every: int = 100):
    import torch

    device = resolve_device(cfg)
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    ecfg = cfg["enhance"] if cfg["fishspotter"].get("enhance_input", True) else None
    pre = [{**s, "img": prep(s["img"], ecfg)} for s in samples]
    net = build_model(pretrained=True).to(device)
    back = [p for n, p in net.named_parameters() if n.startswith(("stem", "l1", "l2", "l3"))]
    rest = [p for n, p in net.named_parameters() if not n.startswith(("stem", "l1", "l2", "l3"))]
    opt = torch.optim.AdamW([{"params": back, "lr": 2e-4}, {"params": rest, "lr": 1e-3}], weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=[2e-4, 1e-3], total_steps=steps, pct_start=0.1)
    net.train()
    t0, run = time.time(), []
    for step in range(steps):
        xs, ts, vs = [], [], []
        for _ in range(batch):
            s = pre[rng.integers(len(pre))]
            im, pts, val = augment(s["img"], s["pts"], s["valid"], size, rng)
            xs.append(to_tensor(im)[0])
            ts.append(torch.from_numpy(target(size, size, pts)))
            vs.append(torch.from_numpy(cv2.resize(val, (size // STRIDE, size // STRIDE), interpolation=cv2.INTER_NEAREST).astype(np.float32)))
        x = torch.stack(xs).to(device)
        gt = torch.stack(ts)[:, None].to(device)
        va = torch.stack(vs)[:, None].to(device)
        loss = focal_loss(net(x), gt, va)
        opt.zero_grad()
        loss.backward()
        opt.step()
        sched.step()
        run.append(float(loss))
        if (step + 1) % log_every == 0:
            print(f"step {step + 1}/{steps} loss {np.mean(run[-log_every:]):.3f} ({time.time() - t0:.0f}s)", flush=True)
    net.eval()
    return net, time.time() - t0


def detect_with(net, img: np.ndarray, cfg: dict, thresh: float) -> np.ndarray:
    import torch

    sc = cfg["fishspotter"]
    ecfg = cfg["enhance"] if sc.get("enhance_input", True) else None
    device = next(net.parameters()).device
    with torch.no_grad():
        p = torch.sigmoid(net(to_tensor(prep(img, ecfg)).to(device)))[0, 0].cpu().numpy()
    pk = peaks(p[: img.shape[0] // STRIDE, : img.shape[1] // STRIDE], thresh)
    cx, cy = (pk[:, 0] + 0.5) * STRIDE, (pk[:, 1] + 0.5) * STRIDE
    bw, bh = sc["box_w"] / 2, sc["box_h"] / 2
    return np.c_[cx - bw, cy - bh, cx + bw, cy + bh, pk[:, 2]].astype(np.float32).reshape(-1, 5)


def motion_boxes(cfg: dict) -> dict[int, np.ndarray]:
    """FINAL motion detector on the 5 exact GT frames (same as experiments.frame_f1)."""
    from bluesight.detect import MotionDetector

    z = np.load(EXP / "gt_exact.npz")
    fr = dict(zip(z["idx"].tolist(), z["ims"]))
    det = MotionDetector(cfg["detector"]["motion"], cfg["enhance"], resolve_device(cfg))
    W, step = float(cfg["detector"]["motion"]["window_s"]), float(cfg["detector"]["motion"]["step_s"])
    out = {}
    for i in GT_IDX:
        ks = [k for k in range(-int(W / step), int(W / step) + 1) if k]
        ctx = [det._lum(fr[int(round(i + k * step * VFPS))]) for k in ks]
        out[i] = det.detect_lum(det._lum(fr[i]), ctx)
    return out


def mean_prf(per_frame: list[np.ndarray], pts: np.ndarray) -> dict:
    rows = [prf(b, pts) for b in per_frame]
    m = {k: round(float(np.mean([r[k] for r in rows])), 3) for k in ("detections", "precision", "recall", "f1")}
    m["f1_min"], m["f1_max"] = min(r["f1"] for r in rows), max(r["f1"] for r in rows)
    return m


def cross(steps: int) -> None:
    from bluesight.detect import fuse_boxes

    cfg = load_config()
    t2 = t2_samples()
    t1 = t1_samples()  # decode the test frames first (cheap to fail early)
    print("T2-STAT2 training photos:", [(s["name"], len(s["pts"])) for s in t2])
    net, secs = train(t2, cfg, steps)
    pts = gt_points()
    fixed = float(cfg["fishspotter"]["score_threshold"])
    mot = motion_boxes(cfg)
    m_motion = mean_prf([mot[i] for i in GT_IDX], pts)
    print("motion (FINAL v2):", m_motion)
    sweep = {}
    for th in (0.1, 0.2, 0.3, 0.4, 0.5):
        sp = [detect_with(net, s["img"], cfg, th) for s in t1]
        fu = [fuse_boxes(mot[i], b, cfg["fishspotter"]) for i, b in zip(GT_IDX, sp)]
        sweep[th] = {"spotter": mean_prf(sp, pts), "fused": mean_prf(fu, pts)}
        print(f"thr {th}: spotter {sweep[th]['spotter']}  fused {sweep[th]['fused']}")
    log_result({"id": "E9", "variant": f"cross-station:T2->T1@14:01 steps={steps}",
                "what": "FishSpotter trained ONLY on T2-STAT2 tally dots, tested on T1-STAT2 14:01 (never seen). "
                        f"Threshold fixed at {fixed} before testing; the sweep is for information only.",
                "params": {"steps": steps, "train_photos": [s["name"] for s in t2], "train_points": int(sum(len(s["pts"]) for s in t2)),
                           "train_s": round(secs, 1)},
                "metrics": {"motion_final": m_motion, "spotter_at_fixed": sweep[fixed]["spotter"],
                            "fused_at_fixed": sweep[fixed]["fused"], "sweep": sweep}})


def final(steps: int) -> None:
    import torch

    cfg = load_config()
    t2, t1, ver = t2_samples(), t1_samples(), assisted_samples(cfg)
    print(f"training on {len(t2)} T2-STAT2 photos, {len(t1)} T1 14:01 frames, {len(ver)} verified frames")
    samples = t2 + t1 * 2 + ver * 2  # the target video's own frames (and biologist-verified ones) weigh a little more
    net, secs = train(samples, cfg, steps)
    OUT.mkdir(parents=True, exist_ok=True)
    f = ROOT / cfg["fishspotter"]["weights"]
    torch.save({"model": net.state_dict(), "steps": steps, "train_s": secs,
                "trained_on": [s["name"] for s in t2] + ["T1-STAT2 14:01 frames 25212-25216"] + [s["name"] for s in ver]}, f)
    print(f"saved {f} ({f.stat().st_size / 1e6:.1f} MB) after {secs:.0f}s")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["cross", "final", "data"])
    ap.add_argument("--steps", type=int, default=1500)
    a = ap.parse_args()
    if a.mode == "data":
        S = Path(sys.argv[0]).resolve().parents[1] / "outputs" / "eval"
        S.mkdir(parents=True, exist_ok=True)
        for s in t2_samples():
            vis = s["img"].copy()
            for x, y in s["pts"]:
                cv2.circle(vis, (int(x), int(y)), 9, (0, 0, 255), 1)
            cv2.imwrite(str(S / f"spotter_train_{s['name'][:22].replace(' ', '_')}.jpg"), vis)
            print(s["name"], len(s["pts"]))
    elif a.mode == "cross":
        cross(a.steps)
    else:
        final(a.steps)
