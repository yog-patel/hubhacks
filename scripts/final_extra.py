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
    (EVAL / "final_extra.json").write_text(json.dumps(out, indent=1, default=float))
    print(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    main()
