"""Non-interactive demo rehearsal; records measured results, then resets the state.

1. analyse the demo window, 2. take the most unfamiliar review item, 3. approve it as a new species
(reviewer "rehearsal"), 4. re-run, 5. record what is recognised -> outputs/eval/demo_rehearsal.json,
6. reset (scripts/reset_demo.py logic).   Usage: python scripts/rehearse_demo.py --name "European green crab"
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bluesight.config import ROOT, load_config, path  # noqa: E402
from bluesight.db import DB  # noqa: E402
from bluesight.pipeline import run_video  # noqa: E402
from bluesight.registry import Registry  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", default="data/videos/T1-STAT2 411.MP4")
    ap.add_argument("--start", type=float, default=1280)
    ap.add_argument("--duration", type=float, default=75)
    ap.add_argument("--name", default="European green crab")
    a = ap.parse_args()
    cfg = load_config()
    rep1 = run_video(a.video, cfg, a.start, a.duration)
    db = DB(path(cfg, "db_path"))
    run = rep1["run_id"]
    q = db.q("SELECT * FROM flags WHERE run_id=? AND review_decision IS NULL ORDER BY best_similarity", (run,))
    top = q[0]
    tids = json.loads(top["track_ids"])
    crops = sorted(Path(top["folder"]).glob("crop_*.jpg"))
    key = Registry(cfg, db).add_images(a.name, crops, "rehearsal", new_species=True, ref_tag=f"{top['flag_id']}_")
    db.set_review(top["flag_id"], "new_species", key, "rehearsal", "rehearsal")
    rep2 = run_video(a.video, cfg, a.start, a.duration)
    tr = db.q("SELECT track_id, status, species, best_similarity, n_frames, start_s, end_s FROM tracks WHERE run_id=? AND species=?", (run, key))
    out = {"window": rep1["window"], "first_review_item": {k: top[k] for k in ("flag_id", "status", "best_similarity", "start_s", "end_s")},
           "first_item_tracks": tids, "approved_as": key, "rerun_runtime_s": rep2["runtime_s"],
           "species_rows_after": [r for r in rep2["species"] if key in r["label"]],
           "tracks_known_as_new_species": [t for t in tr if t["status"] == "known"],
           "tracks_uncertain_as_new_species": len([t for t in tr if t["status"] == "uncertain"]),
           "review_items_before": rep1["review_items"], "review_items_after": rep2["review_items"]}
    (ROOT / "outputs" / "eval" / "demo_rehearsal.json").write_text(json.dumps(out, indent=1, default=float))
    print(json.dumps(out, indent=1, default=float)[:2500])
    subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "reset_demo.py"), "--start", str(a.start), "--duration", str(a.duration)], check=True)
