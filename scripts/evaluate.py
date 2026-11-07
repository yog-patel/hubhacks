"""Measure BlueSight and write EVALUATION.md (measured numbers only).

    python scripts/evaluate.py --tune     # tune T_KNOWN / T_UNKNOWN / V_MIN, save to config.yaml, then evaluate
    python scripts/evaluate.py            # evaluate with the current config

Data used (only one survey video exists, so all video results come from ONE video):
* image level: the registry prototype is built from T2-STAT2 13+14 min tally-dot crops; "known"
  test crops are the T2-STAT2 21 min tally-dot crops; held-out crops are the green crab and the
  38 circled benthic organisms (never in the registry).
* video: T1-STAT2 411 split into a TUNING half (60 s - 1073.6 s) and a DEMO half (1073.6 s - 2087.3 s).
  V_MIN is tuned on the tuning half only. Ground truth: 36 fish at 14:01 (tuning half, with point
  labels) and 102 fish + 1 green crab at 22:00 (demo half).
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bluesight.config import ROOT, load_config, path, resolve_device, save_identify_thresholds  # noqa: E402
from bluesight.db import DB  # noqa: E402
from bluesight.identify import KNOWN, LOW_VIS, UNCERTAIN, UNFAMILIAR, Thresholds, decide_status  # noqa: E402
from bluesight.io_video import video_info  # noqa: E402
from bluesight.pipeline import hardware_string, run_video  # noqa: E402

VIDEO = ROOT / "data" / "videos" / "T1-STAT2 411.MP4"
EVAL = ROOT / "outputs" / "eval"


def halves(cfg: dict) -> tuple[tuple[float, float], tuple[float, float]]:
    d = video_info(VIDEO).duration_s
    a, b = float(cfg["protocol"]["trim_start_s"]), d - float(cfg["protocol"]["trim_end_s"])
    mid = d / 2.0
    return (a, mid), (mid, b)


# --------------------------------------------------------------------------- image level
def image_level_sets(cfg: dict) -> dict[str, np.ndarray]:
    from bluesight.embed import get_embedder

    E = get_embedder(cfg)
    emb = lambda fs: E.embed_images([cv2.imread(f) for f in fs])
    ref = sorted(glob.glob(str(path(cfg, "reference_dir") / "small_schooling_fish" / "*")))
    proto_f = [f for f in ref if "_13min_" in f or "_14min_" in f]
    known_f = [f for f in ref if "_21min_" in f]
    from bluesight.registry import compute_prototypes

    ic = cfg["identify"]
    # same prototype rule as the registry (k-means sub-prototypes if configured; best one counts)
    P = compute_prototypes(emb(proto_f), int(ic.get("prototypes_per_species", 1)), int(ic.get("images_per_prototype", 8)))
    sim = lambda X: (X @ P.T).max(1)
    out = {"n_proto_images": len(proto_f), "n_prototypes": int(len(P)), "known": sim(emb(known_f))}
    for sp in cfg.get("held_out_species") or []:
        fs = sorted(glob.glob(str(path(cfg, "held_out_dir") / sp / "*")))
        out[f"held:{sp}"] = sim(emb(fs)) if fs else np.zeros(0)
    out["held"] = np.concatenate([v for k, v in out.items() if k.startswith("held:")])
    return out


def image_metrics(sims: dict, t_known: float, t_unknown: float) -> dict[str, float]:
    k, h = sims["known"], sims["held"]
    st = lambda v: np.where(v >= t_known, KNOWN, np.where(v >= t_unknown, UNCERTAIN, UNFAMILIAR))
    sk, sh = st(k), st(h)
    m = {"known_n": len(k), "held_n": len(h),
         "known_correct_pct": 100 * float((sk == KNOWN).mean()),
         "known_false_alarm_pct": 100 * float((sk != KNOWN).mean()),
         "known_flagged_unfamiliar_pct": 100 * float((sk == UNFAMILIAR).mean()),
         "held_flagged_pct": 100 * float((sh != KNOWN).mean()),
         "held_unfamiliar_pct": 100 * float((sh == UNFAMILIAR).mean()),
         "held_mislabelled_known_pct": 100 * float((sh == KNOWN).mean())}
    for key in sims:
        if key.startswith("held:") and len(sims[key]):
            s = st(sims[key])
            m[f"{key}_unfamiliar_pct"] = 100 * float((s == UNFAMILIAR).mean())
            m[f"{key}_mislabelled_pct"] = 100 * float((s == KNOWN).mean())
            m[f"{key}_sims"] = [round(float(x), 3) for x in sims[key]][:5]
    return m


def tune_similarity(sims: dict) -> tuple[float, float, pd.DataFrame]:
    """T_KNOWN maximises (held-out flagged % - known false-alarm %), ties -> fewer false alarms.
    T_UNKNOWN = highest value with <= 5% of known crops called unfamiliar."""
    grid = np.round(np.arange(0.40, 0.951, 0.01), 2)
    rows = []
    for tk in grid:
        m = image_metrics(sims, tk, tk)
        rows.append({"T_KNOWN": tk, "J": m["held_flagged_pct"] - m["known_false_alarm_pct"], **m})
    df = pd.DataFrame(rows)
    best_tk = float(df.sort_values(["J", "known_false_alarm_pct"], ascending=[False, True]).iloc[0].T_KNOWN)
    # T_UNKNOWN: the highest value that calls at most 5% of KNOWN fish "unfamiliar" (wrongly telling a
    # biologist a familiar fish may be new is the costliest error); the band in between stays "uncertain".
    ok = [tu for tu in grid[grid <= best_tk] if image_metrics(sims, best_tk, tu)["known_flagged_unfamiliar_pct"] <= 5.0]
    best_tu = float(max(ok)) if ok else float(grid[0])
    return best_tk, best_tu, df


# --------------------------------------------------------------------------- V_MIN
def tune_vmin(cfg: dict, db: DB, run_id: str, th: Thresholds) -> tuple[float, pd.DataFrame]:
    """Tune V_MIN on the TUNING half only (visibility gate disabled).

    Murky crops carry no more information than clear ones, so if murky tracks are matched to a known
    species MORE often than clear-water tracks, the matcher is matching haze, not fish. V_MIN is
    set to the upper edge of the contiguous low-visibility range whose known-match rate exceeds the
    clear-water (visibility >= 0.5) rate by more than 10 percentage points. The unfamiliar-flag
    rate per bin is reported too.
    """
    tr = pd.DataFrame(db.q("SELECT * FROM tracks WHERE run_id=?", (run_id,)))
    tr = tr[(tr.n_frames >= th.MIN_FRAMES) & (tr.mean_area >= th.MIN_AREA)].copy()
    tr["status_nogate"] = [decide_status(s, 1.0, 99, 1e9, th) for s in tr.best_similarity]
    tr["known"] = tr.status_nogate == KNOWN
    tr["unf"] = tr.status_nogate == UNFAMILIAR
    bins = np.round(np.arange(0.10, 0.86, 0.05), 2)
    tr["bin"] = pd.cut(tr.visibility, bins, labels=bins[:-1])
    tab = tr.groupby("bin", observed=False).agg(tracks=("known", "size"), known_rate=("known", "mean"),
                                                unfamiliar_rate=("unf", "mean"), mean_similarity=("best_similarity", "mean")).reset_index()
    clear = tr[tr.visibility >= 0.5]
    base = float(clear.known.mean()) if len(clear) else 0.0
    vmin = float(bins[0])
    for row in tab.sort_values("bin").itertuples():
        if row.tracks < 5:
            continue
        if row.known_rate > base + 0.10 and float(row.bin) < 0.5:
            vmin = float(row.bin) + 0.05
        else:
            break
    tab["clear_water_known_rate"] = base
    tab["clear_water_unfamiliar_rate"] = float(clear.unf.mean()) if len(clear) else 0.0
    return round(vmin, 2), tab


# --------------------------------------------------------------------------- counts
def count_at(db: DB, run_id: str, t: float) -> dict[str, float]:
    d = pd.DataFrame(db.q("SELECT t_s, label FROM detections WHERE run_id=? AND abs(t_s-?)<=0.51", (run_id, t)))
    if d.empty:
        return {}
    inv = set(load_config().get("invertebrate_species") or [])
    rows = []
    for ts, g in d.groupby("t_s"):
        counted = g[g.label != "transient (not counted)"]
        rows.append({"t_s": ts, "raw": len(g), "counted_fish": int((~counted.label.isin(inv)).sum()),
                     "invertebrates": int(counted.label.isin(inv).sum())})
    r = pd.DataFrame(rows)
    best = r.iloc[int(np.argmax(r.counted_fish.to_numpy()))]  # protocol: +/-0.5 s window, frame with most fish
    nearest = r.iloc[int(np.argmin(np.abs(r.t_s.to_numpy() - t)))]
    return {"counted_fish": int(best.counted_fish), "raw_detections_nearest": int(nearest.raw), "invertebrates": int(best.invertebrates)}


def pct_diff(a: float, b: float) -> float:
    """The protocol's QC metric: |a - b| / mean(a, b)."""
    return 100.0 * abs(a - b) / max(1e-9, (a + b) / 2)


# --------------------------------------------------------------------------- detectors
def compare_detectors(cfg: dict) -> list[dict]:
    from scipy.optimize import linear_sum_assignment

    from bluesight.detect import MotionDetector, OWLv2Detector
    from bluesight.enhance import enhanced_luminance

    device = resolve_device(cfg)
    gt_pts = np.array(json.loads((path(cfg, "ground_truth_dir") / "points_841s.json").read_text())["points"]) / 2.0
    cap = cv2.VideoCapture(str(VIDEO))

    def small(t):
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, f = cap.read()
        return cv2.resize(f, (1920, 1080), interpolation=cv2.INTER_AREA)

    mot = MotionDetector(cfg["detector"]["motion"], cfg["enhance"], device)
    owl = OWLv2Detector(cfg["detector"]["owlv2"], device)
    lum = lambda im: cv2.GaussianBlur(enhanced_luminance(im, cfg["enhance"]), (5, 5), 0)
    W, step = cfg["detector"]["motion"]["window_s"], cfg["detector"]["motion"]["step_s"]
    out = []
    for t, gt, half in ((841.0, 36, "tuning"), (1320.0, 102, "demo")):
        f = small(t)
        ctx = [lum(small(t + d)) for d in np.arange(-W, W + 1e-6, step) if abs(d) > 1e-6]
        for name, fn in (("motion (default)", lambda: mot.detect_lum(lum(f), ctx)), ("OWLv2 tiled 3x3", lambda: owl.detect_image(f))):
            t0 = time.time()
            b = fn()
            secs = time.time() - t0
            row = {"time": f"{int(t // 60)}:{int(t % 60):02d}", "half": half, "detector": name, "gt": gt, "detections": len(b),
                   "sec_per_frame": round(secs, 2)}
            if t == 841.0 and len(b):
                cen = np.c_[(b[:, 0] + b[:, 2]) / 2, (b[:, 1] + b[:, 3]) / 2]
                D = np.linalg.norm(cen[:, None] - gt_pts[None], axis=2)
                ri, ci = linear_sum_assignment(D)
                tp = int((D[ri, ci] < 40).sum())
                p, r = tp / len(b), tp / len(gt_pts)
                row.update(precision=round(p, 2), recall=round(r, 2), f1=round(0 if tp == 0 else 2 * p * r / (p + r), 2))
            out.append(row)
    return out


# --------------------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tune", action="store_true")
    ap.add_argument("--skip-detectors", action="store_true")
    a = ap.parse_args()
    cfg = load_config()
    EVAL.mkdir(parents=True, exist_ok=True)
    db = DB(path(cfg, "db_path"))
    (t0, t1), (d0, d1) = halves(cfg)
    tune_run = f"T1_STAT2_411__{int(t0)}-{int(t1)}s"
    demo_run = f"T1_STAT2_411__{int(d0)}-{int(d1)}s"
    before = json.loads((EVAL / "initial_thresholds.json").read_text())
    th_before = Thresholds(before["T_KNOWN"], before["T_UNKNOWN"], before["V_MIN"], before["MIN_FRAMES"], before["MIN_AREA"])

    sims = image_level_sets(cfg)
    m_before = image_metrics(sims, th_before.T_KNOWN, th_before.T_UNKNOWN)
    if a.tune:
        tk, tu, sweep = tune_similarity(sims)
        th_mid = Thresholds(tk, tu, th_before.V_MIN, th_before.MIN_FRAMES, th_before.MIN_AREA)
        vmin, vtab = tune_vmin(cfg, db, tune_run, th_mid)  # uses stored similarities + visibility only
        save_identify_thresholds({"T_KNOWN": tk, "T_UNKNOWN": tu, "V_MIN": vmin})
        sweep.to_csv(EVAL / "threshold_sweep.csv", index=False)
        vtab.to_csv(EVAL / "vmin_tuning.csv", index=False)
        cfg = load_config()
    th = Thresholds.from_cfg(cfg)
    m_after = image_metrics(sims, th.T_KNOWN, th.T_UNKNOWN)
    vtab = pd.read_csv(EVAL / "vmin_tuning.csv") if (EVAL / "vmin_tuning.csv").exists() else None

    # keep the cost of the first (uncached) full runs before cached re-runs overwrite the reports
    rt_file = EVAL / "full_run_runtime.json"
    rt_note = json.loads(rt_file.read_text()) if rt_file.exists() else {}
    for name, (s, e) in (("tuning", (t0, t1)), ("demo", (d0, d1))):
        rp = path(cfg, "runs_dir") / "T1_STAT2_411" / f"{int(s)}-{int(e)}s" / "report.json"
        if name not in rt_note and rp.exists():
            rep = json.loads(rp.read_text())
            if not rep.get("cached_detection"):
                tm = rep["timings_s"]
                rt_note[name] = {"detect_track_s": tm["detect_track_s"], "embed_s": tm["embed_s"], "total_s": rep["runtime_s"],
                                 "s_per_video_min": round((tm["detect_track_s"] + tm["embed_s"] + tm["identify_s"]) / rep["window"]["duration_min"], 1)}
    rt_file.write_text(json.dumps(rt_note, indent=1))
    # refresh both halves with the current thresholds (detections/embeddings are cached)
    reps = {}
    for name, (s, e) in (("tuning", (t0, t1)), ("demo", (d0, d1))):
        reps[name] = run_video(VIDEO, cfg, s, e - s, make_evidence=(name == "demo"))
    det_cmp = [] if a.skip_detectors else compare_detectors(cfg)
    det_file = EVAL / "final_detectors.json"
    if det_cmp:
        det_file.write_text(json.dumps(det_cmp, indent=1))
    elif det_file.exists():
        det_cmp = json.loads(det_file.read_text())  # last measured comparison (same config), so the table stays
    gt = pd.read_csv(path(cfg, "ground_truth_dir") / "manual_counts.csv")
    count_rows = []
    for r in gt.itertuples():
        run = tune_run if r.time_s < t1 else demo_run
        c = count_at(db, run, float(r.time_s))
        count_rows.append({"time": f"{int(r.time_s // 60)}:{int(r.time_s % 60):02d}", "half": "tuning" if run == tune_run else "demo",
                           "manual_fish": int(r.total_fish), "bluesight_counted_fish": c.get("counted_fish"),
                           "raw_detections": c.get("raw_detections_nearest"),
                           "pct_difference": round(pct_diff(r.total_fish, c.get("counted_fish", 0)), 1),
                           "manual_invertebrates": "" if pd.isna(r.invertebrates) else int(r.invertebrates),
                           "bluesight_invertebrates": c.get("invertebrates")})
    result = {"generated": dt.datetime.now().isoformat(timespec="seconds"), "hardware": hardware_string(resolve_device(cfg)),
              "thresholds_before": before, "thresholds_after": th.as_dict(), "image_before": m_before, "image_after": m_after,
              "n_proto_images": sims["n_proto_images"], "counts": count_rows, "detectors": det_cmp,
              "runs": {k: {x: v[x] for x in ("run_id", "window", "runtime_s", "timings_s", "full_processing_s_per_video_min",
                                              "visibility", "track_status_counts", "MeanCount_total_fish", "review_items",
                                              "protocol_window", "transient_detections_per_frame_not_counted", "species")}
                       for k, v in reps.items()}}
    (EVAL / "evaluation.json").write_text(json.dumps(result, indent=2, default=float))
    write_markdown(result, vtab, cfg)
    print(json.dumps({k: result[k] for k in ("thresholds_before", "thresholds_after", "counts")}, indent=1, default=float))


def write_markdown(r: dict, vtab: pd.DataFrame | None, cfg: dict) -> None:
    """EVALUATION.md generated from measured values only."""
    rt = {k: v for k, v in r["runs"].items()}
    runtime_note = json.loads((EVAL / "full_run_runtime.json").read_text()) if (EVAL / "full_run_runtime.json").exists() else {}
    L = ["# EVALUATION", "",
         f"_Generated by `scripts/evaluate.py` on {r['generated']}. Every number below is measured; nothing is estimated except where it says so._",
         "", "> **All video results come from ONE video** (`T1-STAT2 411.MP4`, 35:47, 4K). It is split into a **tuning half** "
         f"({rt['tuning']['window']['start_s']:.0f}–{rt['tuning']['window']['end_s']:.0f} s) and a **demo half** "
         f"({rt['demo']['window']['start_s']:.0f}–{rt['demo']['window']['end_s']:.0f} s). Thresholds were never tuned on the demo half. "
         "There are only two manually counted frames, so treat the count-accuracy figures as indicative, not statistically meaningful.", "",
         "## 1. Processing time and hardware", "", f"Hardware: **{r['hardware']}**", "",
         "| Run | Video minutes | Detect + track (s) | Embed (s) | Full processing, s per video minute | Re-run with cache (s) |", "|---|---|---|---|---|---|"]
    for k, v in rt.items():
        fr = runtime_note.get(k, {})
        L.append(f"| {k} half | {v['window']['duration_min']:.1f} | {fr.get('detect_track_s', '–')} | {fr.get('embed_s', '–')} | "
                 f"{fr.get('s_per_video_min', v['full_processing_s_per_video_min'])} | {v['runtime_s']} |")
    L += ["", "Sampling at 2 fps, detection at 1920 px, crops cut from the 4K frame. The motion detector runs its per-pixel median "
          "on the GPU (Apple MPS). Re-runs reuse cached detections and embeddings, so only identification, counting, evidence and reporting repeat.", "",
          "## 2. Count accuracy against the manual counts", "",
          "The manual counts are the biologists' gridded screenshots of this video (`data/ground_truth/manual_counts.csv`). "
          "BlueSight's count is the protocol-style count at that subsample point: the sampled frame within ±0.5 s holding the most counted fish. "
          "Transient detections (no consistent movement over MIN_FRAMES samples) are not counted.", "",
          "| Time | Half | Manual fish | BlueSight counted fish | Raw detections in frame | % difference (protocol QC metric) | Manual invertebrates | BlueSight invertebrates |",
          "|---|---|---|---|---|---|---|---|"]
    for c in r["counts"]:
        L.append(f"| {c['time']} | {c['half']} | {c['manual_fish']} | {c['bluesight_counted_fish']} | {c['raw_detections']} | "
                 f"{c['pct_difference']} % | {c['manual_invertebrates']} | {c['bluesight_invertebrates']} |")
    L += ["", "The protocol's QC requires counts within 6% for two human counters. **BlueSight does not meet that bar.** "
          "It is a pre-screen that ranks footage and flags items; it does not replace the manual count.", ""]
    if r["detectors"]:
        L += ["### Detector comparison on the ground-truth frames", "",
              "Precision, recall and F1 at 14:01 match detection centres to the 36 tally points (Hungarian matching, 40 px at 1920 px width).", "",
              "| Frame | Half | Detector | Manual | Detections | Precision | Recall | F1 | s/frame |", "|---|---|---|---|---|---|---|---|---|"]
        for d in r["detectors"]:
            L.append(f"| {d['time']} | {d['half']} | {d['detector']} | {d['gt']} | {d['detections']} | {d.get('precision', '–')} | "
                     f"{d.get('recall', '–')} | {d.get('f1', '–')} | {d['sec_per_frame']} |")
        L += ["", "This is v1's single-frame score (frame 841.00 s, about 0.3 s before the instant the biologists annotated; DECISIONS D19), "
              "kept for continuity. The v2 settings were chosen on the aligned frames (Phase 2 log above). OWLv2 (the CLAUDE.md default) "
              "misses these faint fish, so the motion detector is the configured default.", ""]
    ib, ia = r["image_before"], r["image_after"]
    L += ["## 3. Unfamiliar-fish flag (image level, held-out species)", "",
          f"The prototype is built from {r['n_proto_images']} T2-STAT2 13–14 min schooling-fish crops. Known test: {ia['known_n']} T2-STAT2 21-min "
          f"schooling-fish crops (different frames). Held out (never in the registry): {ia['held_n']} crops (1 European green crab + 38 circled benthic organisms of unconfirmed species). "
          "The visibility and size gate does not apply to still photos.", "",
          "| Metric | Before tuning | After tuning |", "|---|---|---|",
          f"| Thresholds T_KNOWN / T_UNKNOWN | {r['thresholds_before']['T_KNOWN']} / {r['thresholds_before']['T_UNKNOWN']} | {r['thresholds_after']['T_KNOWN']} / {r['thresholds_after']['T_UNKNOWN']} |",
          f"| Held-out flagged for review (uncertain or unfamiliar) | {ib['held_flagged_pct']:.1f} % | {ia['held_flagged_pct']:.1f} % |",
          f"| Held-out flagged as **unfamiliar** | {ib['held_unfamiliar_pct']:.1f} % | {ia['held_unfamiliar_pct']:.1f} % |",
          f"| Held-out **mislabelled as known** | {ib['held_mislabelled_known_pct']:.1f} % | {ia['held_mislabelled_known_pct']:.1f} % |",
          f"| European green crab → unfamiliar / mislabelled | {ib.get('held:european_green_crab_unfamiliar_pct', 0):.0f} % / {ib.get('held:european_green_crab_mislabelled_pct', 0):.0f} % | {ia.get('held:european_green_crab_unfamiliar_pct', 0):.0f} % / {ia.get('held:european_green_crab_mislabelled_pct', 0):.0f} % |",
          f"| Known species correctly recognised | {ib['known_correct_pct']:.1f} % | {ia['known_correct_pct']:.1f} % |",
          f"| **False-alarm rate on known species** (sent to review) | {ib['known_false_alarm_pct']:.1f} % | {ia['known_false_alarm_pct']:.1f} % |",
          f"| Known species wrongly called unfamiliar | {ib['known_flagged_unfamiliar_pct']:.1f} % | {ia['known_flagged_unfamiliar_pct']:.1f} % |", "",
          "There is only one green-crab crop, so its row is a single example. The benthic group's species are unconfirmed and may include several taxa.", "",
          "## 4. Threshold tuning", "",
          "| Threshold | Before | After | How it was tuned |", "|---|---|---|---|",
          f"| T_KNOWN | {r['thresholds_before']['T_KNOWN']} | {r['thresholds_after']['T_KNOWN']} | maximise (held-out flagged %) − (known false-alarm %) on the image-level sets (`outputs/eval/threshold_sweep.csv`) |",
          f"| T_UNKNOWN | {r['thresholds_before']['T_UNKNOWN']} | {r['thresholds_after']['T_UNKNOWN']} | highest value that calls ≤ 5% of known crops 'unfamiliar' (between T_UNKNOWN and T_KNOWN items are 'uncertain: probably X?') |",
          f"| V_MIN | {r['thresholds_before']['V_MIN']} | {r['thresholds_after']['V_MIN']} | top of the low-visibility range where tracks match the known species > 10 points MORE often than in clear water, i.e. the matcher is matching haze. Tuning half only (`outputs/eval/vmin_tuning.csv`) |",
          f"| MIN_FRAMES / MIN_AREA | {r['thresholds_before']['MIN_FRAMES']} / {r['thresholds_before']['MIN_AREA']} | {r['thresholds_after']['MIN_FRAMES']} / {r['thresholds_after']['MIN_AREA']} | not tuned |", ""]
    if vtab is not None:
        cw = vtab.clear_water_known_rate.iloc[0]
        L += ["V_MIN tuning data (tuning half, persistent tracks, visibility gate disabled, after the T_KNOWN/T_UNKNOWN tuning). "
              f"Clear-water (≥ 0.5) known-match rate = {cw:.2f}, unfamiliar rate = {vtab.clear_water_unfamiliar_rate.iloc[0]:.2f}:", "",
              "| Visibility bin | Tracks | Matched as known | Flagged unfamiliar | Mean best similarity |", "|---|---|---|---|---|"]
        for v in vtab.itertuples():
            if v.tracks:
                L.append(f"| {v.bin:.2f}–{v.bin + 0.05:.2f} | {v.tracks} | {v.known_rate:.2f} | {v.unfamiliar_rate:.2f} | {v.mean_similarity:.3f} |")
        L += ["", "**Finding:** in murky water the risk on this footage is not mainly false 'new species' flags (murky tracks are flagged "
              "unfamiliar *less* often). It is the opposite: featureless haze resembles the pale, hazy reference crops, so murky blobs get "
              "confidently mislabelled as the known species. The visibility gate stops both, and those tracks are counted in the protocol's "
              "'Unknown/Unable to ID due to visibility' column instead.", ""]
    L += ["## 5. Video-level behaviour with the tuned thresholds", "", "| | Tuning half | Demo half |", "|---|---|---|"]
    t, d = rt["tuning"], rt["demo"]
    L += [f"| Mean visibility | {t['visibility']['mean']:.2f} | {d['visibility']['mean']:.2f} |",
          f"| Footage below V_MIN | {100 * t['visibility']['fraction_below_v_min']:.0f} % | {100 * d['visibility']['fraction_below_v_min']:.0f} % |",
          f"| Tracks by status | {t['track_status_counts']} | {d['track_status_counts']} |",
          f"| MeanCount, total counted fish (60 s subsamples) | {t['MeanCount_total_fish']} | {d['MeanCount_total_fish']} |",
          f"| Transient detections per frame (not counted) | {t['transient_detections_per_frame_not_counted']} | {d['transient_detections_per_frame_not_counted']} |",
          f"| Review items (after merging) | {t['review_items']} | {d['review_items']} |",
          f"| **Estimated reviewer time** (items × {cfg['evaluation']['reviewer_seconds_per_item']} s) | {t['review_items'] * cfg['evaluation']['reviewer_seconds_per_item'] / 60:.1f} min for {t['window']['duration_min']:.0f} min of video | {d['review_items'] * cfg['evaluation']['reviewer_seconds_per_item'] / 60:.1f} min for {d['window']['duration_min']:.0f} min of video |", ""]
    if t.get("protocol_window"):
        pw = t["protocol_window"]
        L += [f"Protocol window ({pw['start_s']:.0f}–{pw['end_s']:.0f} s, {pw['n_subsamples']} subsamples): MeanCount total fish = **{pw['MeanCount_total_fish']}**, by column: {pw['MeanCount_by_label']}", ""]
    dr_file = EVAL / "demo_rehearsal.json"
    if dr_file.exists():
        dr = json.loads(dr_file.read_text())
        fi = dr["first_review_item"]
        known = dr["tracks_known_as_new_species"]
        crab_span = [t for t in known if t["end_s"] >= 1290 and t["start_s"] <= 1306]
        unreviewed = [t for t in crab_span if t["track_id"] not in set(dr.get("first_item_tracks", []))]
        others = [t for t in known if t not in crab_span]
        at_2200 = [t for t in others if t["start_s"] <= 1320 <= t["end_s"]]
        mmss = lambda s: f"{int(s // 60)}:{int(s % 60):02d}"
        L += ["## 5b. Video level: the held-out green crab in the demo window (`scripts/rehearse_demo.py`)", "",
              f"Demo window {dr['window']['start_s']:.0f}–{dr['window']['end_s']:.0f} s (21:20–22:35, demo half). A large European green crab, which is held out of the registry, "
              "walks along the pole from about 21:31 to 21:45 (checked by eye in the frames).", "",
              f"* **Before approval:** the crab's track is review item #1 (the most unfamiliar), status **{fi['status']}**, best similarity {fi['best_similarity']:.2f} "
              f"to the only registry species ({mmss(fi['start_s'])}–{mmss(fi['end_s'])}). It is **flagged as unfamiliar, not mislabelled.**",
              f"* **Approved** as '{dr['approved_as']}' from the first item's 5 crops. The re-run took {dr['rerun_runtime_s']:.0f} s from cache.",
              f"* **After approval:** {len(known)} tracks are recognised as {dr['approved_as']}. **{len(crab_span)} of them fall inside the walking crab's time span**, "
              f"including {len(unreviewed)} track(s) nobody reviewed ({', '.join(mmss(t['start_s']) + '–' + mmss(t['end_s']) for t in unreviewed) or 'none'}), "
              f"now recognised automatically. The other {len(others)} are outside the crab's walk (sand or caustic patches that resemble the sandy background of the crab crops); "
              f"{len(at_2200)} of them overlap 22:00, where the biologists circled a camouflaged crab, but their crops can't confirm it. "
              f"{dr['tracks_uncertain_as_new_species']} more tracks become 'probably {dr['approved_as']}?'.",
              "* **Conclusion:** the flag-approve-recognise loop works, but a species approved from a single track has a loose prototype. On sandy footage it over-matches until "
              "reviewers confirm more examples (Existing species) and reject sand items. (v1 experiment: tighter crops, padding 0.6 → 0.15, improved separation only marginally, sand max 0.86 → 0.87 vs crab 0.83 → 0.85.)", ""]
    L += ["## 6. Honest assessment", "",
          "* **Detection is the weak link.** The fish are faint, translucent and about 50 px long at 1080p. The motion detector under-detects dense, slow schools "
          "and picks up some sunlight caustics on the sand. Many of those false positives are dropped as transient, but some persist and appear as 'uncertain' review items "
          "(a reviewer rejects them in one click).",
          "* **Species identification is limited by the references.** The only fish references are screenshot crops of one unidentified school at another station (T2-STAT2). "
          "The 'known' species is therefore 'small schooling fish (species unconfirmed)'. BioCLIP zero-shot could not name the species reliably (see RESOURCES.md).",
          "* The image-level flag test uses screenshot crops, which come from a different domain than live video crops. On video, the review queue is the safety net.",
          "* Every result comes from one video and two manually counted frames. Results on other sites or seasons are unknown.", ""]
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from experiment_report import top_sections

        L = top_sections(r) + ["", "---", "", "# FINAL: detailed report", ""] + L[2:]
    except Exception as exc:  # the detailed report must still be written
        print("experiment_report failed:", exc)
    (ROOT / "EVALUATION.md").write_text("\n".join(L))


if __name__ == "__main__":
    main()
