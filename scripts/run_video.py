"""Analyse a survey video: python scripts/run_video.py <video> [--start S] [--duration D] [--force]

Writes outputs/runs/<video>/<start>-<end>s/{report.json, report.csv, species_summary.csv, annotated.mp4}
and evidence packages to outputs/flags/. Default window = Coastal Action protocol (skip first
minute, analyse 15 minutes). Use --full for the whole video minus the first/last minute.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bluesight.config import load_config  # noqa: E402
from bluesight.io_video import video_info  # noqa: E402
from bluesight.pipeline import run_video  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--start", type=float, default=None, help="window start (s)")
    ap.add_argument("--duration", type=float, default=None, help="window length (s)")
    ap.add_argument("--full", action="store_true", help="whole video minus first/last minute")
    ap.add_argument("--force", action="store_true", help="ignore detection/embedding caches")
    ap.add_argument("--no-evidence", action="store_true")
    a = ap.parse_args()
    cfg = load_config()
    dur = a.duration
    if a.full:
        info = video_info(a.video)
        a.start = cfg["protocol"]["trim_start_s"]
        dur = info.duration_s
    last = [-1.0]

    def prog(f: float, m: str) -> None:
        if f - last[0] >= 0.05 or f >= 1.0:
            print(f"[{f * 100:5.1f}%] {m}", flush=True)
            last[0] = f

    rep = run_video(a.video, cfg, a.start, dur, prog, a.force, not a.no_evidence)
    print(json.dumps({k: rep[k] for k in ("run_id", "runtime_s", "timings_s", "visibility", "track_status_counts",
                                          "MeanCount_total_fish", "review_items")}, indent=1, default=float))
    for r in rep["species"]:
        print(r)
