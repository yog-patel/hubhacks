"""Reset the review/registry state after a demo rehearsal.

Removes species approved in the app (outputs/registry/*), clears all review decisions, count checks,
survey details and app edits to the watch list, rebuilds the
registry from data/reference_images/, and re-runs the demo window (cached, ~1 min) so its review
queue is fresh.   Usage: python scripts/reset_demo.py [--start 1280 --duration 75]
"""
import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bluesight.config import load_config, path  # noqa: E402
from bluesight.db import DB  # noqa: E402
from bluesight.pipeline import run_video  # noqa: E402
from bluesight.registry import Registry  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", default="data/videos/T1-STAT2 411.MP4")
    ap.add_argument("--start", type=float, default=1280)
    ap.add_argument("--duration", type=float, default=75)
    a = ap.parse_args()
    cfg = load_config()
    db = DB(path(cfg, "db_path"))
    reg_dir = path(cfg, "registry_dir")
    if reg_dir.exists():
        shutil.rmtree(reg_dir)
    db.x("DELETE FROM species WHERE source='approved'")
    db.x("UPDATE flags SET review_decision=NULL, review_species=NULL, reviewer=NULL, review_timestamp=NULL")
    from bluesight import countcheck, survey  # noqa: E402

    countcheck.ensure(db)
    survey.ensure(db)
    db.x("DELETE FROM frame_checks")
    db.x("DELETE FROM surveys")
    db.x("DELETE FROM watch_list WHERE updated_by != 'config.yaml'")
    print("registry:", Registry(cfg, db).build_from_folders())
    rep = run_video(a.video, cfg, a.start, a.duration)
    print(f"demo window re-run in {rep['runtime_s']} s; {rep['review_items']} review items")
