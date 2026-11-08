"""Count check: a person checks the AI's count on the protocol's subsample frames.

Two modes, both following Coastal Action's protocol:

* **assisted** - the AI's marks are shown on the subsample frame; the person removes marks that are not fish and adds
  the fish the AI missed. This is the fast, everyday mode (it turns a 10-60 s count into a few clicks), and every
  correction is saved as training data for a future detector (``export_training_labels``).
* **blind** - quality control as in the protocol: the person counts the frame without seeing the AI's marks, and the
  two counts are compared. The protocol asks for less than 6 % difference between counters and at least 95 %
  agreement overall.

Checked counts replace the AI's counts in the "checked" MeanCount; unchecked subsamples keep the AI's count, and the
report says how many of the 15 were checked.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from .db import DB

SCHEMA = """
CREATE TABLE IF NOT EXISTS frame_checks (
    run_id TEXT, subsample_t_s REAL, frame_t_s REAL, mode TEXT, reviewer TEXT,
    ai_fish INTEGER, ai_invert INTEGER, removed TEXT, missed_fish INTEGER,
    human_fish INTEGER, human_invert INTEGER, notes TEXT, seconds_spent REAL, ts TEXT,
    PRIMARY KEY (run_id, subsample_t_s, mode)
);
"""
NOT_COUNTED = "transient (not counted)"
PCT_DIFF_LIMIT = 6.0     # protocol: "less than 6% difference between the two counts"
AGREEMENT_TARGET = 95.0  # protocol: "if agreement is below 95% ... reannotation should be undertaken"


def ensure(db: DB) -> None:
    db.conn.executescript(SCHEMA)
    db.conn.commit()


def pct_difference(a: float, b: float) -> float:
    """Percent difference between two counts, |a-b| / mean(a, b) * 100 (0 when both are 0)."""
    m = (a + b) / 2.0
    return 0.0 if m == 0 else abs(a - b) / m * 100.0


def agreement(pairs: Sequence[tuple[float, float]]) -> float | None:
    """Overall agreement (%) between two sets of counts: sum of min / sum of max. 100 = identical."""
    if not pairs:
        return None
    lo = sum(min(a, b) for a, b in pairs)
    hi = sum(max(a, b) for a, b in pairs)
    return 100.0 if hi == 0 else 100.0 * lo / hi


def frame_time_for(sub: dict[str, Any], dets: list[dict[str, Any]], window_s: float = 1.0) -> float:
    """The sampled frame the AI counted for a subsample (stored in new reports; recomputed for older ones)."""
    if sub.get("frame_t_s") is not None:
        return float(sub["frame_t_s"])
    p = float(sub["subsample_t_s"])
    by_t: dict[float, int] = {}
    for d in dets:
        if abs(d["t_s"] - p) <= window_s / 2 + 1e-6:
            by_t.setdefault(round(d["t_s"], 3), 0)
            if d["label"] and d["label"] != NOT_COUNTED:
                by_t[round(d["t_s"], 3)] += 1
    if not by_t:
        return p
    return max(sorted(by_t), key=lambda t: by_t[t])


def ai_marks(db: DB, run_id: str, frame_t_s: float) -> list[dict[str, Any]]:
    """The AI's counted detections on one sampled frame (boxes in process-width pixels), numbered from 1."""
    rows = db.q("SELECT track_id, x1, y1, x2, y2, label FROM detections WHERE run_id=? AND abs(t_s-?)<0.002 "
                "AND label IS NOT NULL AND label != ? ORDER BY x1", (run_id, frame_t_s, NOT_COUNTED))
    for i, r in enumerate(rows, start=1):
        r["mark"] = i
    return rows


def save_check(db: DB, run_id: str, subsample_t_s: float, frame_t_s: float, mode: str, reviewer: str,
               ai_fish: int, ai_invert: int, removed: list[int], missed_fish: int, human_fish: int, human_invert: int,
               notes: str = "", seconds_spent: float | None = None) -> None:
    """Store one person's count for one subsample (one row per subsample and mode; the latest wins)."""
    ensure(db)
    db.x("INSERT OR REPLACE INTO frame_checks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
         (run_id, float(subsample_t_s), float(frame_t_s), mode, reviewer, int(ai_fish), int(ai_invert),
          json.dumps(sorted(int(r) for r in removed)), int(missed_fish), int(human_fish), int(human_invert), notes,
          seconds_spent, dt.datetime.now().isoformat(timespec="seconds")))


def checks(db: DB, run_id: str) -> list[dict[str, Any]]:
    ensure(db)
    return db.q("SELECT * FROM frame_checks WHERE run_id=? ORDER BY subsample_t_s, mode", (run_id,))


def summary(report: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """AI vs checked MeanCount, and QC agreement, for one analysis."""
    subs = report.get("subsamples", [])
    by = {}
    for r in rows:  # assisted checks win over blind ones for the checked MeanCount (they see the AI's marks)
        k = round(r["subsample_t_s"], 3)
        if k not in by or r["mode"] == "assisted":
            by[k] = r
    ai = [s["total_fish_count"] for s in subs]
    checked = [by[round(s["subsample_t_s"], 3)]["human_fish"] if round(s["subsample_t_s"], 3) in by else s["total_fish_count"]
               for s in subs]
    blind = [(r["ai_fish"], r["human_fish"]) for r in rows if r["mode"] == "blind"]
    assisted = [(r["ai_fish"], r["human_fish"]) for r in rows if r["mode"] == "assisted"]
    diffs = [pct_difference(a, h) for a, h in blind]
    secs = [r["seconds_spent"] for r in rows if r.get("seconds_spent")]
    return {
        "n_subsamples": len(subs), "n_checked": len(by),
        "MeanCount_ai": float(np.mean(ai)) if ai else 0.0,
        "MeanCount_checked": float(np.mean(checked)) if checked else 0.0,
        "n_blind": len(blind), "blind_agreement_pct": agreement(blind),
        "blind_frames_within_6pct": sum(d < PCT_DIFF_LIMIT for d in diffs),
        "n_assisted": len(assisted), "assisted_agreement_pct": agreement(assisted),
        "marks_removed": sum(len(json.loads(r["removed"] or "[]")) for r in rows if r["mode"] == "assisted"),
        "fish_added": sum(int(r["missed_fish"] or 0) for r in rows if r["mode"] == "assisted"),
        "median_seconds_per_check": float(np.median(secs)) if secs else None,
    }


def export_training_labels(db: DB, report: dict[str, Any], out_dir: Path, frame_loader) -> Path:
    """Write the reviewed subsample frames and their corrected labels as a detector training set.

    ``frame_loader(t_s) -> BGR image | None`` returns the frame at process width. Labels: kept AI boxes are
    positives, removed ones are hard negatives, and ``missed_fish`` records fish the AI did not box (count only).
    Returns the folder written (``labels.json`` + one JPEG per frame).
    """
    import cv2

    run_id = report["run_id"]
    folder = Path(out_dir) / run_id
    folder.mkdir(parents=True, exist_ok=True)
    items = []
    for r in checks(db, run_id):
        if r["mode"] != "assisted":
            continue
        img = frame_loader(r["frame_t_s"])
        if img is None:
            continue
        name = f"{run_id}_{r['frame_t_s']:.3f}.jpg"
        cv2.imwrite(str(folder / name), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
        removed = set(json.loads(r["removed"] or "[]"))
        marks = ai_marks(db, run_id, r["frame_t_s"])
        items.append({"image": name, "width": int(img.shape[1]), "height": int(img.shape[0]), "t_s": r["frame_t_s"],
                      "positives": [[m["x1"], m["y1"], m["x2"], m["y2"]] for m in marks if m["mark"] not in removed],
                      "negatives": [[m["x1"], m["y1"], m["x2"], m["y2"]] for m in marks if m["mark"] in removed],
                      "missed_fish": int(r["missed_fish"] or 0), "reviewer": r["reviewer"], "checked_at": r["ts"]})
    (folder / "labels.json").write_text(json.dumps({"run_id": run_id, "video_file": report["video_file"],
                                                    "box_format": "x1,y1,x2,y2 pixels", "frames": items}, indent=2))
    return folder
