"""Unit tests for AI-assisted counting (bluesight.assisted)."""
import numpy as np

from bluesight.assisted import Mark, load_saved, new_session, protocol_frame, save, summary, toggle, undo_remove
from bluesight.db import DB


def det(t, x, y, label="small_schooling_fish"):
    return {"t_s": t, "x1": x - 20, "y1": y - 12, "x2": x + 20, "y2": y + 12, "label": label}


def test_protocol_frame_picks_busiest_frame_in_window_and_skips_uncounted():
    dets = [det(99.5, 10, 10), det(100.0, 10, 10), det(100.0, 50, 50), det(100.0, 90, 90, None), det(101.0, 1, 1)]
    for i in range(5):
        dets.append(det(102.0, i * 10, 0))  # busier, but outside +/- 0.5 s
    t, marks = protocol_frame(dets, 100.0, 1.0)
    assert t == 100.0 and len(marks) == 2  # the None-label detection is not counted


def test_toggle_removes_near_mark_and_adds_elsewhere():
    s = new_session("r", 100.0, 100.0, [Mark(100, 100), Mark(300, 300)])
    assert toggle(s, 105, 98, radius=20) == "removed"
    assert toggle(s, 600, 600, radius=20) == "added"
    assert s.ai_count == 2 and s.final_count == 2 and s.added == 1 and len(s.removed_ai) == 1
    assert toggle(s, 601, 599, radius=20) == "removed"  # removing a human mark doesn't count as an AI removal
    assert len(s.removed_ai) == 1 and s.final_count == 1
    assert undo_remove(s) and s.final_count == 2


def test_save_and_summary(tmp_path):
    db = DB(tmp_path / "t.db")
    s = new_session("run1", 60.0, 60.1, [Mark(10, 10), Mark(50, 50), Mark(90, 90)])
    toggle(s, 10, 10, 15)       # remove one AI mark
    toggle(s, 200, 200, 15)     # add two missed fish
    toggle(s, 400, 400, 15)
    frame = np.zeros((100, 100, 3), np.uint8)
    rec = save(db, s, "tester", 12.5, frame, tmp_path / "train", "v.mp4")
    assert rec["final_count"] == 4 and (tmp_path / "train" / "run1_60s.json").exists()
    saved = load_saved(db, "run1")
    sm = summary(saved, [0.0, 60.0], {0.0: 5, 60.0: 3})
    assert sm["n_verified"] == 1 and sm["MeanCount_verified"] == 4.0
    assert round(sm["ai_kept_pct"], 1) == 66.7      # 2 of 3 AI marks kept
    assert sm["ai_found_pct"] == 50.0               # AI found 2 of the 4 fish
    assert sm["median_seconds_per_frame"] == 12.5
