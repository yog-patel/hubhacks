"""Create mock outputs under outputs/mock/ so the Streamlit UI can be developed without models.

Usage: python scripts/make_mock_data.py   then pick "Mock data" in the app sidebar.
"""
import datetime as dt
import json
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bluesight.config import ROOT  # noqa: E402
from bluesight.db import DB, dumps, to_blob  # noqa: E402

MOCK = ROOT / "outputs" / "mock"


def fake_crop(rng: np.random.Generator, colour: tuple[int, int, int]) -> np.ndarray:
    img = np.clip(rng.normal(120, 12, (90, 140, 3)), 0, 255).astype(np.uint8)
    cv2.ellipse(img, (70, 45), (40, 14), 0, 0, 360, colour, -1)
    return img


def main() -> None:
    if MOCK.exists():
        shutil.rmtree(MOCK)
    (MOCK / "runs" / "mock_video" / "60-960s").mkdir(parents=True)
    rng = np.random.default_rng(0)
    db = DB(MOCK / "bluesight.db")
    now = dt.datetime.now().isoformat(timespec="seconds")
    for name, col in (("atlantic_silverside", (200, 200, 200)), ("winter_flounder", (60, 90, 120))):
        d = MOCK / "registry" / name
        d.mkdir(parents=True)
        for i in range(3):
            cv2.imwrite(str(d / f"{i}.jpg"), fake_crop(rng, col))
        db.x("INSERT INTO species VALUES (?,?,?,?,?,?,?,?,1,?)",
             (name, name.replace("_", " "), "reference", now, "mock", 3, to_blob(rng.normal(size=8)), "mock", "mock data"))
        for i in range(3):
            db.x("INSERT INTO species_images VALUES (?,?,?,?,?)", (name, str(d / f"{i}.jpg"), "reference", now, None))
    run_id = "mock_video__60-960s"
    subs = [{"subsample_t_s": 60.0 + 60 * i, "time": f"{1 + i}:00", "visibility": round(float(rng.uniform(0.1, 0.8)), 2),
             "total_fish_count": int(rng.integers(0, 12)), "invertebrate_count": int(rng.integers(0, 2)),
             "atlantic_silverside": int(rng.integers(0, 10)), "Unfamiliar (flagged for review)": int(rng.integers(0, 2))}
            for i in range(15)]
    report = {"video_file": "mock_video.mp4", "site": "T0-STAT0", "date": "2025-09-10", "run_id": run_id,
              "window": {"start_s": 60, "end_s": 960, "duration_min": 15}, "ran_on": "mock", "offline": True,
              "runtime_s": 1.0, "timings_s": {}, "models": {"detector": "mock", "embedder": "mock"},
              "thresholds": {"T_KNOWN": 0.8, "T_UNKNOWN": 0.6, "V_MIN": 0.3},
              "visibility": {"mean": 0.45, "min": 0.1, "max": 0.8, "fraction_below_v_min": 0.3},
              "species": [{"label": "atlantic_silverside", "MaxN": 9, "MeanCount": 4.2, "MeanCount_all_sampled_frames": 4.0,
                           "n_tracks": 30, "confidence": 0.86, "verified_tracks": 0},
                          {"label": "Unfamiliar (flagged for review)", "MaxN": 1, "MeanCount": 0.4,
                           "MeanCount_all_sampled_frames": 0.3, "n_tracks": 3, "confidence": 0.41, "verified_tracks": 0}],
              "subsamples": subs, "MeanCount_total_fish": float(np.mean([s["total_fish_count"] for s in subs])),
              "review_items": 3, "flags": [], "annotated_video": "", "generated_at": now, "n_tracks": 33,
              "track_status_counts": {"known": 30, "unfamiliar": 3}, "protocol_window": None,
              "transient_detections_per_frame_not_counted": 2.0, "cached_detection": False}
    rd = MOCK / "runs" / "mock_video" / "60-960s"
    (rd / "report.json").write_text(json.dumps(report, indent=2))
    import pandas as pd

    pd.DataFrame(subs).to_csv(rd / "report.csv", index=False)
    db.x("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
         (run_id, "mock_video.mp4", "T0-STAT0", "2025-09-10", 60, 960, now, 1.0, "mock", "mock", "mock", 1800, 33,
          str(rd / "report.json"), 0))
    for k, (status, sim) in enumerate((("unfamiliar", 0.41), ("unfamiliar", 0.52), ("uncertain", 0.71))):
        fid = f"mock_flag_{k}"
        fd = MOCK / "flags" / fid
        fd.mkdir(parents=True)
        for i in range(1, 4):
            cv2.imwrite(str(fd / f"crop_{i}.jpg"), fake_crop(rng, (40 + 60 * k, 160, 90)))
        top3 = [{"species": "atlantic_silverside", "similarity": sim}, {"species": "winter_flounder", "similarity": sim - 0.1}]
        flag = {"flag_id": fid, "video_file": "mock_video.mp4", "status": status, "top3": top3, "visibility": 0.6,
                "start_time_s": 100 + 50 * k, "end_time_s": 104 + 50 * k, "track_frames": 8,
                "review": {"decision": None, "species": None, "reviewer": None, "timestamp": None}}
        (fd / "flag.json").write_text(json.dumps(flag, indent=2))
        db.x("INSERT INTO flags(flag_id, run_id, video_file, status, track_ids, start_s, end_s, top3, best_similarity, visibility, "
             "track_frames, folder, embedding, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
             (fid, run_id, "mock_video.mp4", status, "[1]", 100 + 50 * k, 104 + 50 * k, dumps(top3), sim, 0.6, 8, str(fd), None, now))
    print(f"mock data written to {MOCK}")


if __name__ == "__main__":
    main()
