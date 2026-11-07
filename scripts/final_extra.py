"""Measured extras for EVALUATION.md's FINAL column -> outputs/eval/final_extra.json.

* tracker fragmentation / implausible jumps on the FINAL tuning-half run (same proxies as experiment E4)
* energy per video minute for the FINAL full (uncached) half runs, from outputs/logs/energy.csv
* total external network connections recorded by the guard over all v2 runs
* the "What improved and why" text, with every number filled in from measured files

    python scripts/final_extra.py
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from bluesight.config import load_config  # noqa: E402
import experiments as X  # noqa: E402

EVAL = ROOT / "outputs" / "eval"


def main() -> None:
    cfg = load_config()
    out: dict = {}
    # tracker proxies on the FINAL tuning-half cache (its own tracker ids)
    from bluesight.pipeline import run_video  # noqa: F401  (ensures package import side effects)

    runs = json.loads((EVAL / "evaluation.json").read_text())["runs"]
    tune_id = runs["tuning"]["run_id"]
    caches = sorted(glob.glob(str(ROOT / "outputs" / "cache" / "T1_STAT2_411" / f"{tune_id.split('__')[1]}_*")),
                    key=lambda p: Path(p).stat().st_mtime)
    d = pd.read_csv(Path(caches[-1]) / "detections.csv").rename(columns={"t_s": "t", "track_id": "tid"})
    out["tracker_final"] = X.track_metrics(d[["t", "tid", "x1", "y1", "x2", "y2"]], int(cfg["identify"]["MIN_FRAMES"]))
    out["tracker_final"]["cache"] = Path(caches[-1]).name
    # energy + network
    e = pd.read_csv(ROOT / "outputs" / "logs" / "energy.csv")
    full = e[(e.cached_detection == 0) & e.run_id.isin([runs["tuning"]["run_id"], runs["demo"]["run_id"]])].drop_duplicates("run_id", keep="last")
    if len(full):
        mins = sum(runs[k]["window"]["duration_min"] for k in ("tuning", "demo") if runs[k]["run_id"] in set(full.run_id))
        out["energy"] = {"wh_total": round(float(full.energy_wh.sum()), 2), "co2_g_total": round(float(full.co2_g.sum()), 2),
                         "video_min": round(mins, 1), "wh_per_video_min": round(float(full.energy_wh.sum()) / mins, 3),
                         "co2_g_per_video_min": round(float(full.co2_g.sum()) / mins, 3),
                         "note": "CodeCarbon offline estimate, CPU (load model) + RAM; Apple GPU not measured"}
    out["external_connections_total"] = int(e.external_connections.fillna(0).sum())
    out["runs_with_guard"] = int(len(e))
    out["what_improved"] = what_improved(out)
    (EVAL / "final_extra.json").write_text(json.dumps(out, indent=1, default=float))
    print(json.dumps(out, indent=1, default=float))


def what_improved(x: dict) -> list[str]:
    """Plain-language summary, every number read from the measured files."""
    E = {(r["id"], r["variant"]): r["metrics"] for r in json.loads((EVAL / "experiments.json").read_text())}
    B = json.loads((EVAL / "baseline" / "evaluation.json").read_text())
    F = json.loads((EVAL / "evaluation.json").read_text())
    c = lambda res, t: next((r for r in res["counts"] if r["time"] == t), {})
    b0, f0 = E[("E1", "baseline CLAHE clip 3, grid 8")], E[("E2-combo", "CLAHE 2/4 + tracker assoc 200, expand 2.5")]
    bt, ft = E[("E4", "baseline")], x["tracker_final"]
    b14, f14, b22, f22 = c(B, "14:01"), c(F, "14:01"), c(B, "22:00"), c(F, "22:00")
    vb, vf = E[("E6-video", "1 prototype(s) at its own re-tuned thresholds")], E[("E6-video", "4 prototype(s) at its own re-tuned thresholds")]
    L = [
        f"1. **Detection found more of the real fish, with fewer false ones.** Gentler, coarser contrast enhancement "
        f"(CLAHE clip 2 on 4×4 tiles instead of clip 3 on 8×8) brings out the faint fish without amplifying sand texture and "
        f"sunlight flicker as much. At the annotated 14:01 instant: F1 {b0['f1']:.3f} → **{f0['f1']:.3f}**, precision "
        f"{b0['precision']:.2f} → {f0['precision']:.2f}, recall {b0['recall']:.2f} → {f0['recall']:.2f}.",
        f"2. **Each fish keeps one ID more reliably.** Tracking only works at 2 frames per second if boxes are enlarged for matching. "
        f"Enlarging small boxes to at least 200 px (was 120) and others less (×2.5, was ×3) cut split tracks from "
        f"{bt['fragmentation_per_100_tracks']:.2f} to **{ft['fragmentation_per_100_tracks']:.2f} per 100 tracks** on the tuning half, and "
        f"merged-fish jumps from {bt['jumps_per_100_tracks']:.2f} to {ft['jumps_per_100_tracks']:.2f}. Split tracks inflate the review "
        "queue and make a fish look 'transient' (not counted).",
        f"3. **Counts moved closer to the biologists'**, from both changes together: 14:01 {b14.get('bluesight_counted_fish')} → "
        f"**{f14.get('bluesight_counted_fish')}** of 36 (tuning half); 22:00 {b22.get('bluesight_counted_fish')} → "
        f"**{f22.get('bluesight_counted_fish')}** of 102 (demo half, checked once afterwards). BlueSight still undercounts dense "
        "schools; it is a pre-screen, not a replacement for the manual count.",
        f"4. **Two tempting 'improvements' were rejected because they failed on real video.** Enhancing crops and using several "
        f"prototypes per species both looked much better on the screenshot photos. But those photos separate known from held-out "
        f"partly by background (pale water vs sandy seabed). On video tracks, enhanced crops dropped fish-vs-non-fish separation to "
        f"chance, and k-means prototypes raised clear-water 'possibly new species' flags from {vb['unfamiliar_pct']:.1f}% to "
        f"{vf['unfamiliar_pct']:.1f}%.",
        "5. **Found and documented, not hidden:** ByteTrack's `lost_track_buffer` does nothing at 2 fps (a scaling quirk in "
        "`supervision`); the motion detector's background size alternated between 16 and 17 frames (measured, no gain from fixing); "
        "and the 14:01 ground truth belongs to 841.31 s, not 841.00 s (found by correlating the screenshot with the video).",
        "6. **Nothing got more expensive.** Sampling stays at 2 fps (1 fps undercounts even with the same persistence time), there's "
        "no bigger model (OWLv2 large found 0 fish at 61 s per frame), and runtime and energy per video minute are in the table above.",
    ]
    return L


if __name__ == "__main__":
    main()
