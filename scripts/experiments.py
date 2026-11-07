"""Phase-2 model experiments. Every result is MEASURED and appended to outputs/eval/experiments.json.

Never uses the demo half for selection. Tuning data:
* the 14:01 frame (841 s, tuning half) with 36 biologist tally points -> detection precision/recall/F1 and the
  protocol count (best frame within +/-0.5 s, persistent tracks only) against 36;
* the cached tuning-half run (60-1073 s): raw detections for re-tracking, best crops for crop selection;
* the image-level sets (T2-STAT2 13+14 min prototype crops, 21 min known crops, 39 held-out crops).

    python scripts/experiments.py decode            # cache the 14:01 window (818-864 s) at 0.5/1/2/3 fps
    python scripts/experiments.py enhance           # E1  raw vs CLAHE settings (detection) + raw vs enhanced crops (ID)
    python scripts/experiments.py detector          # E2  motion z / area / elongation; OWLv2 prompts, thresholds, NMS, variant
    python scripts/experiments.py tracker           # E4  ByteTrack parameters on cached tuning-half detections
    python scripts/experiments.py crops             # E5  crop-selection rules (needs per-crop embeddings, cached)
    python scripts/experiments.py prototypes        # E6  k-means prototypes, text-embedding blend
    python scripts/experiments.py fps               # E8  sampling rate
Results: outputs/eval/experiments.json (list of {id, what, params, metrics, ...}).
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import glob
import json
import pickle
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bluesight.config import ROOT, load_config, path, resolve_device  # noqa: E402

VIDEO = ROOT / "data" / "videos" / "T1-STAT2 411.MP4"
EXP = ROOT / "outputs" / "experiments"
LOG = ROOT / "outputs" / "eval" / "experiments.json"
GT_T, GT_N = 841.0, 36
# The 14:01 screenshot pins the annotated instant only to the second. Correlating the screenshot's high-pass detail
# with every video frame 840-842 s peaks at frame 25214 (841.31 s), and the v1 detector's F1 peaks there too
# (DECISIONS D19). Detection F1 is the mean over the 5 exact frames 25212-25216 (+/-67 ms; fish move a few px).
GT_IDX = list(range(25212, 25217))
VFPS = 30000 / 1001
WIN = (818.0, 864.0)          # 14:01 +/- 23 s: room for the motion detector's +/- 8 s background window
TUNE_CACHE_GLOB = "outputs/cache/T1_STAT2_411/60-1073s_*"


def log_result(rec: dict) -> None:
    rows = json.loads(LOG.read_text()) if LOG.exists() else []
    rec["when"] = dt.datetime.now().isoformat(timespec="seconds")
    rows = [r for r in rows if not (r["id"] == rec["id"] and r.get("variant") == rec.get("variant"))]
    rows.append(rec)
    LOG.write_text(json.dumps(rows, indent=1, default=float))
    print(json.dumps({k: rec[k] for k in ("id", "variant", "metrics") if k in rec}, default=float))


def gt_points() -> np.ndarray:
    cfg = load_config()
    return np.array(json.loads((path(cfg, "ground_truth_dir") / "points_841s.json").read_text())["points"]) / 2.0


def prf(boxes: np.ndarray, pts: np.ndarray, tol: float = 40.0) -> dict:
    """Hungarian matching of detection centres to tally points (same rule as scripts/evaluate.py)."""
    from scipy.optimize import linear_sum_assignment

    if len(boxes) == 0:
        return {"detections": 0, "tp": 0, "precision": 0.0, "recall": 0.0, "f1": 0.0}
    cen = np.c_[(boxes[:, 0] + boxes[:, 2]) / 2, (boxes[:, 1] + boxes[:, 3]) / 2]
    D = np.linalg.norm(cen[:, None] - pts[None], axis=2)
    ri, ci = linear_sum_assignment(D)
    tp = int((D[ri, ci] < tol).sum())
    p, r = tp / len(boxes), tp / len(pts)
    return {"detections": int(len(boxes)), "tp": tp, "precision": round(p, 3), "recall": round(r, 3),
            "f1": round(0.0 if tp == 0 else 2 * p * r / (p + r), 3)}


# ----------------------------------------------------------------------------- decode cache
def decode(fps_list=(0.5, 1.0, 2.0, 3.0)) -> None:
    from bluesight.io_video import iter_sampled_frames, resize_width

    EXP.mkdir(parents=True, exist_ok=True)
    for fps in fps_list:
        f = EXP / f"win_{fps:g}fps.npz"
        if f.exists():
            continue
        t0 = time.time()
        ts, ims = [], []
        for idx, t, full in iter_sampled_frames(VIDEO, fps, *WIN):
            ims.append(resize_width(full, 1920)[0])
            ts.append(t)
        np.savez(f, t=np.array(ts), ims=np.stack(ims))
        print(f"decoded {len(ts)} frames at {fps} fps in {time.time() - t0:.1f}s")


def decode_exact(max_window_s: float = 12.0) -> None:
    """Exact frames for the GT instant plus whole-second background frames up to +/- max_window_s."""
    f = EXP / "gt_exact.npz"
    if f.exists():
        return
    from bluesight.io_video import resize_width

    need = set()
    for i in GT_IDX:
        need.add(i)
        for d in range(1, int(max_window_s) + 1):
            need.update({int(round(i + d * VFPS)), int(round(i - d * VFPS))})
    cap = cv2.VideoCapture(str(VIDEO))
    idx = sorted(need)
    cap.set(cv2.CAP_PROP_POS_FRAMES, idx[0])
    cur, out = idx[0], {}
    while cur <= idx[-1]:
        ok, fr = cap.read()
        if not ok:
            break
        if cur in need:
            out[cur] = resize_width(fr, 1920)[0]
        cur += 1
    np.savez(f, idx=np.array(sorted(out)), ims=np.stack([out[k] for k in sorted(out)]))
    print(f"decoded {len(out)} exact frames")


def frame_f1(cfg: dict, detector=None) -> dict:
    """Mean precision / recall / F1 of the motion detector over the 5 exact GT frames (exact +/- k s backgrounds)."""
    from bluesight.detect import MotionDetector

    decode_exact()
    z = np.load(EXP / "gt_exact.npz")
    fr = dict(zip(z["idx"].tolist(), z["ims"]))
    det = detector or MotionDetector(cfg["detector"]["motion"], cfg["enhance"], resolve_device(cfg))
    W, step = float(cfg["detector"]["motion"]["window_s"]), float(cfg["detector"]["motion"]["step_s"])
    pts = gt_points()
    rows, t0 = [], time.time()
    for i in GT_IDX:
        ks = [k for k in range(-int(W / step), int(W / step) + 1) if k]
        ctx = [det._lum(fr[int(round(i + k * step * VFPS))]) for k in ks]
        rows.append(prf(det.detect_lum(det._lum(fr[i]), ctx), pts))
    m = {k: round(float(np.mean([r[k] for r in rows])), 3) for k in ("detections", "precision", "recall", "f1")}
    m["f1_min"], m["f1_max"] = min(r["f1"] for r in rows), max(r["f1"] for r in rows)
    m["s_per_frame_detect"] = round((time.time() - t0) / len(GT_IDX), 3)
    return m


def load_win(fps: float = 2.0):
    z = np.load(EXP / f"win_{fps:g}fps.npz")
    return z["t"], z["ims"]


def window_eval(cfg: dict, fps: float = 2.0, detector=None) -> dict:
    """Run detect -> track on the cached 14:01 window; F1 at the GT frame + protocol count vs 36 + cost."""
    from bluesight.detect import Frame, get_detector
    from bluesight.enhance import visibility_score
    from bluesight.track import Tracker

    ts, ims = load_win(fps)
    det = detector or get_detector(cfg)
    trk = Tracker(cfg["tracker"], fps)
    frames = (Frame(i, float(t), im, im, 1.0, visibility_score(im, cfg["enhance"])) for i, (t, im) in enumerate(zip(ts, ims)))
    rows, t0 = [], time.time()
    prev = None
    for fr, boxes in det.detect_stream(frames):
        ids, back = trk.update(boxes)
        if prev is not None:
            for j, tid in back:
                rows[prev + j][1] = int(tid)
        prev = len(rows)
        for b, tid in zip(boxes, ids):
            rows.append([fr.t, int(tid), *b[:4]])
    secs = time.time() - t0
    d = pd.DataFrame(rows, columns=["t", "tid", "x1", "y1", "x2", "y2"])
    mf = int(cfg["identify"]["MIN_FRAMES"])
    nfr = d[d.tid >= 0].groupby("tid").t.nunique()
    persistent = set(nfr[nfr >= mf].index)
    d["counted"] = d.tid.isin(persistent)
    near = d[np.abs(d.t - GT_T) <= 0.5 + 1e-6]
    count = int(near.groupby("t").counted.sum().max()) if len(near) else 0
    m = {}
    m.update(count_at_1401=count, count_pct_diff=round(100 * abs(count - GT_N) / ((count + GT_N) / 2), 1),
             s_per_frame=round(secs / len(ts), 3), frames=int(len(ts)))
    return m


# ----------------------------------------------------------------------------- E1 enhancement
def both(cfg: dict, fps: float = 2.0) -> dict:
    """Frame-level F1 (exact GT frames) + pipeline-style protocol count at 14:01 (streamed window)."""
    m = frame_f1(cfg)
    m.update(window_eval(cfg, fps))
    return m


def exp_enhance() -> None:
    import bluesight.detect as D
    import bluesight.enhance as En

    cfg = load_config()
    base = both(cfg)
    log_result({"id": "E1", "variant": "baseline CLAHE clip 3, grid 8", "params": {"clahe_clip": 3.0, "clahe_grid": 8},
                "metrics": base, "kept": "baseline"})
    # raw luminance (no CLAHE) for the detector
    orig = En.enhanced_luminance
    D.enhanced_luminance = lambda img, c=None: cv2.cvtColor(img, cv2.COLOR_BGR2LAB)[:, :, 0]
    m = both(cfg)
    D.enhanced_luminance = orig
    log_result({"id": "E1", "variant": "raw luminance (no enhancement)", "params": {"clahe": None}, "metrics": m})
    for clip, grid in ((2.0, 8), (4.0, 8), (3.0, 16), (2.0, 4)):
        c = copy.deepcopy(cfg)
        c["enhance"].update(clahe_clip=clip, clahe_grid=grid)
        log_result({"id": "E1", "variant": f"CLAHE clip {clip:g}, grid {grid}", "params": {"clahe_clip": clip, "clahe_grid": grid},
                    "metrics": both(c)})
    # identification: raw vs enhanced crops (image level, current single prototype)
    from bluesight.embed import get_embedder

    E = get_embedder(cfg)
    for name, f in (("raw crops", lambda im: im), ("enhanced crops", lambda im: En.enhance_frame(im, cfg["enhance"]))):
        sims = image_sets(E, transform=f)
        log_result({"id": "E1-ID", "variant": name, "params": {}, "metrics": image_metrics_auc(sims)})


# ----------------------------------------------------------------------------- image level helpers
def image_files(cfg: dict) -> dict[str, list[str]]:
    ref = sorted(glob.glob(str(path(cfg, "reference_dir") / "small_schooling_fish" / "*")))
    held = []
    for sp in cfg.get("held_out_species") or []:
        held += sorted(glob.glob(str(path(cfg, "held_out_dir") / sp / "*")))
    return {"proto": [f for f in ref if "_13min_" in f or "_14min_" in f], "known": [f for f in ref if "_21min_" in f],
            "held": held}


def image_sets(E, transform=None, protos_fn=None) -> dict:
    """Similarities of known-test and held-out crops to the schooling-fish prototype(s)."""
    cfg = load_config()
    fs = image_files(cfg)
    tf = transform or (lambda im: im)
    emb = {k: E.embed_images([tf(cv2.imread(f)) for f in v]) for k, v in fs.items()}
    P = protos_fn(emb["proto"]) if protos_fn else mean_proto(emb["proto"])[None]
    return {"known": (emb["known"] @ P.T).max(1), "held": (emb["held"] @ P.T).max(1),
            "crab": (emb["held"][:1] @ P.T).max(1), "_emb": emb}


def mean_proto(e: np.ndarray) -> np.ndarray:
    m = e.mean(0)
    return m / np.linalg.norm(m)


def auc(pos: np.ndarray, neg: np.ndarray) -> float:
    """P(similarity of a known crop > similarity of a held-out crop)."""
    pos, neg = np.asarray(pos), np.asarray(neg)
    return float(((pos[:, None] > neg[None]).mean() + 0.5 * (pos[:, None] == neg[None]).mean()))


def image_metrics_auc(sims: dict, tk: float | None = None, tu: float | None = None) -> dict:
    sys.path.insert(0, str(ROOT / "scripts"))
    from evaluate import image_metrics, tune_similarity

    s = {"known": sims["known"], "held": sims["held"]}
    if tk is None:
        tk, tu, _ = tune_similarity(s)
    m = image_metrics(s, tk, tu)
    return {"auc_known_vs_heldout": round(auc(sims["known"], sims["held"]), 4), "T_KNOWN": tk, "T_UNKNOWN": tu,
            "known_correct_pct": round(m["known_correct_pct"], 1), "known_false_alarm_pct": round(m["known_false_alarm_pct"], 1),
            "known_flagged_unfamiliar_pct": round(m["known_flagged_unfamiliar_pct"], 1),
            "held_flagged_pct": round(m["held_flagged_pct"], 1), "held_unfamiliar_pct": round(m["held_unfamiliar_pct"], 1),
            "held_mislabelled_known_pct": round(m["held_mislabelled_known_pct"], 1),
            "crab_similarity": round(float(sims["crab"][0]), 3)}


# ----------------------------------------------------------------------------- E2 detector
def exp_detector(skip_owl: bool = False, owl_large: bool = False) -> None:
    cfg = load_config()
    mc = cfg["detector"]["motion"]
    base = both(cfg)
    log_result({"id": "E2", "variant": "motion baseline", "params": dict(mc), "metrics": base, "kept": "baseline"})
    c = copy.deepcopy(cfg)
    c["detector"]["motion"]["ctx_tol_s"] = 0.26
    log_result({"id": "E2", "variant": "motion context fix (constant 16-frame background)", "params": {"ctx_tol_s": 0.26},
                "metrics": both(c)})
    grid = [("z_thresh", v) for v in (2.0, 2.25, 2.75, 3.0)] + [("min_area", v) for v in (100, 220)] + \
           [("min_elongation", v) for v in (1.2, 1.6)] + [("k", v) for v in (0.5, 2.0)] + [("window_s", v) for v in (6.0, 12.0)]
    for key, v in grid:
        c = copy.deepcopy(cfg)
        c["detector"]["motion"][key] = v
        log_result({"id": "E2", "variant": f"motion {key}={v:g}", "params": {key: v}, "metrics": both(c)})
    if skip_owl:
        return
    owl_frame(cfg, owl_large)


def owl_frame(cfg: dict, large: bool) -> None:
    """OWLv2 on the 14:01 frame: prompts x thresholds x NMS (and optionally the large variant)."""
    import torch
    from torchvision.ops import nms
    from transformers import Owlv2ForObjectDetection, Owlv2Processor

    decode_exact()
    z = np.load(EXP / "gt_exact.npz")
    img = dict(zip(z["idx"].tolist(), z["ims"]))[GT_IDX[2]]   # the best-aligned frame (25214)
    pts = gt_points()
    dev = resolve_device(cfg)
    models = ["google/owlv2-base-patch16-ensemble"] + (["google/owlv2-large-patch14-ensemble"] if large else [])
    prompts = [["a photo of a fish"], ["fish"], ["a fish underwater"], ["small fish"],
               ["a photo of a fish", "a photo of a small fish", "a fish underwater"]]
    for mid in models:
        try:
            proc = Owlv2Processor.from_pretrained(mid)
            model = Owlv2ForObjectDetection.from_pretrained(mid).to(dev).eval()
        except Exception as exc:
            log_result({"id": "E2-OWL", "variant": f"{mid} (not available offline)", "params": {}, "metrics": {"error": str(exc)[:200]}})
            continue
        for grid in (3, 4):
            H, W = img.shape[:2]
            th_, tw_ = H // grid, W // grid
            for pr in prompts:
                t0 = time.time()
                raw = []
                for gy in range(grid):
                    for gx in range(grid):
                        tile = cv2.cvtColor(img[gy * th_:(gy + 1) * th_, gx * tw_:(gx + 1) * tw_], cv2.COLOR_BGR2RGB)
                        inp = proc(text=[pr], images=tile, return_tensors="pt").to(dev)
                        with torch.no_grad():
                            out = model(**inp)
                        s = max(th_, tw_)
                        r = proc.post_process_object_detection(out, threshold=0.01, target_sizes=torch.tensor([[s, s]]))[0]
                        for b, sc in zip(r["boxes"].cpu().numpy(), r["scores"].cpu().numpy()):
                            raw.append([b[0] + gx * tw_, b[1] + gy * th_, b[2] + gx * tw_, b[3] + gy * th_, sc])
                secs = time.time() - t0
                a = np.array(raw, np.float32).reshape(-1, 5)
                for thr in (0.03, 0.05, 0.10):
                    for iou in (0.3, 0.5):
                        sel = a[a[:, 4] >= thr]
                        # drop boxes bigger than a tile quarter (seabed/pole "objects")
                        sel = sel[((sel[:, 2] - sel[:, 0]) * (sel[:, 3] - sel[:, 1])) < (th_ * tw_) / 4] if len(sel) else sel
                        if len(sel):
                            keep = nms(torch.from_numpy(sel[:, :4]), torch.from_numpy(sel[:, 4]), iou).numpy()
                            sel = sel[keep]
                        m = prf(sel, pts)
                        m["s_per_frame"] = round(secs, 2)
                        log_result({"id": "E2-OWL", "variant": f"{mid.split('/')[1]} grid{grid} {'+'.join(pr)} thr{thr} nms{iou}",
                                    "params": {"model": mid, "grid": grid, "prompts": pr, "score_threshold": thr, "nms_iou": iou},
                                    "metrics": m})
        del model


# ----------------------------------------------------------------------------- E4 tracker
def retrack(dets: pd.DataFrame, tcfg: dict, fps: float) -> pd.DataFrame:
    from bluesight.track import Tracker

    trk = Tracker(tcfg, fps)
    out = []
    prev_rows = None
    for t, g in dets.groupby("t_s", sort=True):
        boxes = g[["x1", "y1", "x2", "y2", "score"]].to_numpy(np.float32)
        ids, back = trk.update(boxes)
        rows = [[t, int(i), *b[:4]] for b, i in zip(boxes, ids)]
        if prev_rows is not None:
            for j, tid in back:
                prev_rows[j][1] = int(tid)
        out.extend(rows)
        prev_rows = rows
    return pd.DataFrame(out, columns=["t", "tid", "x1", "y1", "x2", "y2"])


def track_metrics(d: pd.DataFrame, min_frames: int) -> dict:
    """Proxies for ID switches / double counts (no tracking ground truth exists):
    * fragmentation: a track starts within 1.5 s and 150 px of where another persistent track ended (same fish re-IDed);
    * implausible jumps: a track's centre moves > 250 px (at 1920 px) between consecutive samples (two fish merged);
    * tracks per persistent-fish-minute, count at 14:01."""
    d = d.copy()
    d["cx"], d["cy"] = (d.x1 + d.x2) / 2, (d.y1 + d.y2) / 2
    tr = d[d.tid >= 0]
    g = tr.groupby("tid")
    nfr = g.t.nunique()
    pers = nfr[nfr >= min_frames].index
    P = tr[tr.tid.isin(pers)].sort_values("t")
    ends = P.groupby("tid").agg(t0=("t", "min"), t1=("t", "max"))
    first = P.groupby("tid").first()
    last = P.groupby("tid").last()
    frag = 0
    starts = ends.sort_values("t0")
    e_t1, e_x, e_y = ends.t1.to_numpy(), last.cx.reindex(ends.index).to_numpy(), last.cy.reindex(ends.index).to_numpy()
    for tid, r in starts.iterrows():
        dt_ = r.t0 - e_t1
        ok = (dt_ > 0) & (dt_ <= 1.5)
        if ok.any():
            dist = np.hypot(e_x[ok] - first.cx[tid], e_y[ok] - first.cy[tid])
            frag += int((dist < 150).any())
    jumps = 0
    for tid, gg in P.groupby("tid"):
        dxy = np.hypot(np.diff(gg.cx.to_numpy()), np.diff(gg.cy.to_numpy()))
        jumps += int((dxy > 250).sum())
    d["counted"] = d.tid.isin(set(pers))
    near = d[np.abs(d.t - GT_T) <= 0.5 + 1e-6]
    cnt = int(near.groupby("t").counted.sum().max()) if len(near) else 0
    return {"tracks": int(tr.tid.nunique()), "persistent_tracks": int(len(pers)),
            "mean_persistent_len_frames": round(float(nfr[nfr >= min_frames].mean()), 2) if len(pers) else 0,
            "fragmentation_events": frag, "fragmentation_per_100_tracks": round(100 * frag / max(1, len(pers)), 2),
            "implausible_jumps": jumps, "jumps_per_100_tracks": round(100 * jumps / max(1, len(pers)), 2),
            "count_at_1401": cnt}


def exp_tracker() -> None:
    cfg = load_config()
    cdir = Path(sorted(glob.glob(str(ROOT / TUNE_CACHE_GLOB)))[0])
    dets = pd.read_csv(cdir / "detections.csv")
    fps = float(cfg["sampling"]["fps"])
    mf = int(cfg["identify"]["MIN_FRAMES"])
    base_t = dict(cfg["tracker"])
    t0 = time.time()
    m = track_metrics(retrack(dets, base_t, fps), mf)
    m["s_total"] = round(time.time() - t0, 1)
    log_result({"id": "E4", "variant": "baseline", "params": base_t, "metrics": m, "kept": "baseline"})
    grid = [("lost_track_buffer", v) for v in (2, 6, 8)] + [("minimum_matching_threshold", v) for v in (0.7, 0.8, 0.95)] + \
           [("box_expand", v) for v in (2.0, 2.5, 4.0)] + [("min_assoc_size", v) for v in (80, 160)] + \
           [("track_activation_threshold", v) for v in (0.1, 0.3)] + \
           [("lost_track_buffer", v) for v in (15, 30, 45)] + [("min_assoc_size", v) for v in (200, 240, 320)]
    for key, v in grid:
        tc = dict(base_t)
        tc[key] = v
        log_result({"id": "E4", "variant": f"{key}={v:g}", "params": {key: v}, "metrics": track_metrics(retrack(dets, tc, fps), mf)})
    # supervision scales lost_track_buffer by frame_rate/30: at 2 fps a buffer < 15 means 0 frames (no effect).
    for combo in ({"min_assoc_size": 160, "lost_track_buffer": 15}, {"min_assoc_size": 200, "lost_track_buffer": 15},
                  {"min_assoc_size": 160, "box_expand": 2.5}, {"min_assoc_size": 200, "box_expand": 2.5},
                  {"min_assoc_size": 200, "minimum_matching_threshold": 0.95}):
        tc = dict(base_t)
        tc.update(combo)
        log_result({"id": "E4", "variant": " + ".join(f"{k}={v:g}" for k, v in combo.items()), "params": combo,
                    "metrics": track_metrics(retrack(dets, tc, fps), mf)})


# ----------------------------------------------------------------------------- E5 crop selection
def crop_embeddings(cdir: Path, E) -> dict:
    """Embed every cached best crop individually (once), so selection rules can be compared cheaply."""
    f = EXP / "tuning_crop_embs.pkl"
    if f.exists():
        return pickle.loads(f.read_bytes())
    crops = pickle.loads((cdir / "crops.pkl").read_bytes())
    dets = pd.read_csv(cdir / "detections.csv")
    nf = dets[dets.track_id >= 0].groupby("track_id").frame_idx.nunique()
    elig = set(nf[nf >= 3].index)
    keys, ims = [], []
    for tid, lst in crops.items():
        if tid not in elig:
            continue
        for j, (jpg, t) in enumerate(lst):
            keys.append((tid, j, t))
            ims.append(cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR))
    t0 = time.time()
    em = E.embed_images(ims)
    out = {"keys": keys, "emb": em, "secs": time.time() - t0}
    f.write_bytes(pickle.dumps(out))
    return out


def quality_features(cdir: Path, keys: list) -> pd.DataFrame:
    crops = pickle.loads((cdir / "crops.pkl").read_bytes())
    dets = pd.read_csv(cdir / "detections.csv")
    by_t = {round(t, 3): g for t, g in dets.groupby(dets.t_s.round(3))}
    rows = []
    for tid, j, t in keys:
        jpg = crops[tid][j][0]
        im = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
        g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY).astype(np.float32)
        lap = float(cv2.Laplacian(g, cv2.CV_32F).var())
        contrast = float(g.std()) + 1e-3
        area = g.shape[0] * g.shape[1]
        fr = by_t.get(round(t, 3))
        occl = 0.0
        if fr is not None:
            me = fr[fr.track_id == tid]
            if len(me):
                b = me.iloc[0]
                others = fr[fr.track_id != tid]
                if len(others):
                    ix = np.clip(np.minimum(b.x2, others.x2) - np.maximum(b.x1, others.x1), 0, None)
                    iy = np.clip(np.minimum(b.y2, others.y2) - np.maximum(b.y1, others.y1), 0, None)
                    occl = float((ix * iy).max() / max(1.0, (b.x2 - b.x1) * (b.y2 - b.y1)))
        rows.append({"tid": tid, "j": j, "t": t, "lap": lap, "lap_norm": lap / contrast ** 2, "area": area, "occl": occl,
                     "aspect": max(g.shape) / max(1, min(g.shape))})
    return pd.DataFrame(rows)


def exp_crops() -> None:
    from bluesight.embed import get_embedder
    from bluesight.identify import mean_embedding
    from bluesight.registry import Registry
    from bluesight.db import DB

    cfg = load_config()
    cdir = Path(sorted(glob.glob(str(ROOT / TUNE_CACHE_GLOB)))[0])
    E = get_embedder(cfg)
    ce = crop_embeddings(cdir, E)
    q = quality_features(cdir, ce["keys"])
    q["row"] = np.arange(len(q))
    names, protos = Registry(cfg, DB(path(cfg, "db_path")), E).prototypes()
    P = protos[names.index("small_schooling_fish")]
    # labels: tracks whose detection at the 14:01 GT frame matches a tally point (fish) vs not (likely not a fish)
    dets = pd.read_csv(cdir / "detections.csv")
    t_gt = dets.t_s.iloc[int(np.argmin(np.abs(dets.t_s.to_numpy() - GT_T)))]
    fr = dets[(dets.t_s == t_gt) & (dets.track_id >= 0)]
    pts = gt_points()
    from scipy.optimize import linear_sum_assignment

    cen = np.c_[(fr.x1 + fr.x2) / 2, (fr.y1 + fr.y2) / 2]
    D = np.linalg.norm(cen[:, None] - pts[None], axis=2)
    ri, ci = linear_sum_assignment(D)
    fish = {int(fr.track_id.iloc[r]) for r, c in zip(ri, ci) if D[r, c] < 40}
    other = set(int(x) for x in fr.track_id) - fish
    have = set(q.tid)
    fish, other = fish & have, other & have
    rules = {
        "v1: Laplacian var x sqrt(area), all 5": lambda g: g.sort_values("j").head(5),
        "v1 rule, best 3": lambda g: g.sort_values("j").head(3),
        "contrast-normalised sharpness x sqrt(area), best 3": lambda g: g.assign(s=g.lap_norm * np.sqrt(g.area)).nlargest(3, "s"),
        "normalised sharpness x sqrt(area) x (1-occlusion), best 3":
            lambda g: g.assign(s=g.lap_norm * np.sqrt(g.area) * (1 - g.occl.clip(0, 1))).nlargest(3, "s"),
        "largest 3": lambda g: g.nlargest(3, "area"),
        "least occluded 3, then sharpest": lambda g: g.sort_values(["occl", "lap"], ascending=[True, False]).head(3),
    }
    emb = ce["emb"]
    for name, rule in rules.items():
        sims = {}
        for tid, g in q.groupby("tid"):
            sel = rule(g)
            e = mean_embedding(emb[sel.row.to_numpy()])
            sims[tid] = float(e @ P)
        s = pd.Series(sims)
        fs, os_ = s[list(fish)].to_numpy(), s[list(other)].to_numpy()
        m = {"tracks": int(len(s)), "gt_fish_tracks": len(fs), "gt_nonfish_tracks": len(os_),
             "mean_sim_gt_fish": round(float(fs.mean()), 4) if len(fs) else None,
             "mean_sim_gt_nonfish": round(float(os_.mean()), 4) if len(os_) else None,
             "auc_fish_vs_nonfish": round(auc(fs, os_), 3) if len(fs) and len(os_) else None,
             "known_rate_all_tracks": round(float((s >= cfg["identify"]["T_KNOWN"]).mean()), 3)}
        log_result({"id": "E5", "variant": name, "params": {}, "metrics": m,
                    "note": f"per-crop embedding of {len(emb)} crops took {ce['secs']:.0f}s (one-off)"})


# ----------------------------------------------------------------------------- E6 prototypes
def kmeans_protos(e: np.ndarray, k: int, seed: int = 0) -> np.ndarray:
    """Spherical k-means: k unit prototypes (max similarity is used at match time)."""
    k = max(1, min(k, len(e) // 8))
    if k == 1:
        return mean_proto(e)[None]
    rng = np.random.default_rng(seed)
    C = e[rng.choice(len(e), k, replace=False)]
    for _ in range(50):
        a = np.argmax(e @ C.T, 1)
        C2 = np.stack([mean_proto(e[a == i]) if (a == i).any() else C[i] for i in range(k)])
        if np.allclose(C2, C):
            break
        C = C2
    return C


def exp_prototypes() -> None:
    from bluesight.embed import get_embedder

    cfg = load_config()
    E = get_embedder(cfg)
    base = image_sets(E)
    emb = base.pop("_emb")
    log_result({"id": "E6", "variant": "baseline: 1 mean prototype", "params": {"k": 1}, "metrics": image_metrics_auc(base), "kept": "baseline"})

    def evalP(P):
        return {"known": (emb["known"] @ P.T).max(1), "held": (emb["held"] @ P.T).max(1), "crab": (emb["held"][:1] @ P.T).max(1)}

    for k in (2, 3, 4, 6):
        for seed in (0, 1, 2):
            log_result({"id": "E6", "variant": f"k-means k={k} seed={seed}", "params": {"k": k, "seed": seed},
                        "metrics": image_metrics_auc(evalP(kmeans_protos(emb["proto"], k, seed)))})
    from bluesight.registry import compute_prototypes

    for k in (2, 3, 4, 6):
        log_result({"id": "E6", "variant": f"k-means k={k}, best of 5 restarts by inertia (deterministic, as shipped)",
                    "params": {"k": k, "n_init": 5}, "metrics": image_metrics_auc(evalP(compute_prototypes(emb["proto"], k, 8, 5)))})
    texts = {"small fish": "a photo of a small fish", "schooling fish": "a photo of small schooling fish underwater",
             "taxonomic": "a photo of Actinopterygii, ray-finned fish"}
    for tn, txt in texts.items():
        T = E.embed_texts([txt])[0]
        for alpha in (0.9, 0.8, 0.6):
            P = alpha * mean_proto(emb["proto"]) + (1 - alpha) * T
            P = (P / np.linalg.norm(P))[None]
            log_result({"id": "E6", "variant": f"image+text blend '{tn}' alpha={alpha}", "params": {"text": txt, "alpha": alpha},
                        "metrics": image_metrics_auc(evalP(P))})


# ----------------------------------------------------------------------------- E8 sampling rate
def exp_fps() -> None:
    cfg = load_config()
    for fps in (0.5, 1.0, 2.0, 3.0):
        c = copy.deepcopy(cfg)
        c["sampling"]["fps"] = fps
        m = window_eval(c, fps)
        m["frames_per_video_minute"] = fps * 60
        log_result({"id": "E8", "variant": f"{fps:g} fps", "params": {"fps": fps}, "metrics": m,
                    "kept": "baseline" if fps == 2.0 else None})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["decode", "enhance", "detector", "tracker", "crops", "prototypes", "fps", "owl"])
    ap.add_argument("--owl-large", action="store_true")
    ap.add_argument("--skip-owl", action="store_true")
    a = ap.parse_args()
    if a.what != "decode" and not (EXP / "win_2fps.npz").exists() and a.what in ("enhance", "detector", "fps", "owl"):
        decode()
    {"decode": decode, "enhance": exp_enhance, "detector": lambda: exp_detector(a.skip_owl, a.owl_large),
     "tracker": exp_tracker, "crops": exp_crops, "prototypes": exp_prototypes, "fps": exp_fps,
     "owl": lambda: owl_frame(load_config(), a.owl_large)}[a.what]()
