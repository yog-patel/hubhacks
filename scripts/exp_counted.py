"""E10: score what actually gets COUNTED. Dev tool; tuning half only (14:01), every number measured.

Earlier experiments (E2) scored raw single-frame detections, but the count only uses detections on persistent
tracks (>= MIN_FRAMES sampled frames). A more sensitive motion detector adds noise that the tracker may remove.
This scores the counted detections at the two sampled frames around the annotated instant (840.97 and 841.47 s; the
tally points belong to 841.31 s) against the 36 tally points, for a grid of detector / persistence settings.

    python scripts/exp_counted.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bluesight.config import load_config  # noqa: E402
from experiments import EXP, GT_N, decode, gt_points, load_win, log_result, prf  # noqa: E402


def run(cfg: dict, fps: float = 2.0) -> pd.DataFrame:
    from bluesight.detect import Frame, get_detector
    from bluesight.track import Tracker

    ts, ims = load_win(fps)
    det = get_detector(cfg)
    trk = Tracker(cfg["tracker"], fps)
    frames = (Frame(i, float(t), im, im, 1.0, 1.0) for i, (t, im) in enumerate(zip(ts, ims)))
    rows, prev = [], None
    for fr, boxes in det.detect_stream(frames):
        ids, back = trk.update(boxes)
        if prev is not None:
            for j, tid in back:
                rows[prev + j][1] = int(tid)
        prev = len(rows)
        for b, tid in zip(boxes, ids):
            rows.append([round(fr.t, 3), int(tid), *b[:4]])
    return pd.DataFrame(rows, columns=["t", "tid", "x1", "y1", "x2", "y2"])


def score(d: pd.DataFrame, min_frames: int) -> dict:
    pts = gt_points()
    nfr = d[d.tid >= 0].groupby("tid").t.nunique()
    d = d.assign(counted=d.tid.isin(set(nfr[nfr >= min_frames].index)))
    out = {}
    ts = np.array(sorted(d.t.unique()))
    near = ts[np.argsort(np.abs(ts - 841.31))[:2]]  # the two sampled frames around the annotated instant
    for t in sorted(near):
        sub = d[(np.abs(d.t - t) < 1e-3) & d.counted]
        out[t] = prf(sub[["x1", "y1", "x2", "y2"]].to_numpy(np.float32), pts)
    m = {k: round(float(np.mean([out[t][k] for t in out])), 3) for k in ("detections", "precision", "recall", "f1")}
    m["count_frames"] = [out[t]["detections"] for t in out]
    m["count_pct_diff"] = round(100 * abs(m["detections"] - GT_N) / ((m["detections"] + GT_N) / 2), 1)
    return m


def main() -> None:
    EXP.mkdir(parents=True, exist_ok=True)
    decode((2.0,))
    base = load_config()
    grid = []
    for z in (2.0, 2.25, 2.5):
        for area in (150,):
            for elong in (1.2, 1.4):
                cfg = copy.deepcopy(base)
                cfg["detector"]["name"] = "motion"
                cfg["detector"]["motion"].update(z_thresh=z, min_area=area, min_elongation=elong)
                d = run(cfg)
                for mf in (3, 4, 5):
                    m = score(d, mf)
                    grid.append({"z": z, "min_area": area, "min_elong": elong, "MIN_FRAMES": mf, **m})
                    print(grid[-1], flush=True)
    df = pd.DataFrame(grid).sort_values("f1", ascending=False)
    print(df.head(12).to_string(index=False))
    cur = [g for g in grid if g["z"] == 2.5 and g["min_area"] == 150 and g["min_elong"] == 1.4 and g["MIN_FRAMES"] == 3][0]
    log_result({"id": "E10", "variant": "counted-detections grid",
                "what": "P/R/F1 of COUNTED (persistent-track) detections at 841.0/841.5 s vs the 36 tally points (tuning half).",
                "metrics": {"current_config": cur, "top5": df.head(5).to_dict("records")}, "grid": grid})


if __name__ == "__main__":
    main()
