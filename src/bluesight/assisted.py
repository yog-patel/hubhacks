"""AI-assisted counting on the protocol subsample frames.

No automatic detector finds every fish in this footage: about half of the fish the biologists counted are
faint streaks that are only recognisable in motion (EVALUATION.md E9-E10). So for the protocol count the
pipeline *pre-marks* the fish it counted on each subsample frame, and the biologist clicks to add a missed fish
or remove a wrong mark. The verified count is exact by construction, takes seconds per frame, and every
correction is saved as point labels (``outputs/training/assisted/``) for retraining FishSpotter.

Coordinates are in detection-frame pixels (``sampling.process_width``, 1920 px for 4K video).
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS assisted_counts (
    run_id TEXT, subsample_t_s REAL, frame_t_s REAL, ai_count INTEGER, removed INTEGER, added INTEGER,
    final_count INTEGER, marks TEXT, reviewer TEXT, seconds REAL, saved_at TEXT,
    PRIMARY KEY (run_id, subsample_t_s)
);
"""


@dataclass
class Mark:
    """One counted organism on a frame. ``src`` is 'ai' (pre-marked by the pipeline) or 'human' (added)."""

    x: float
    y: float
    src: str = "ai"
    label: str | None = None


@dataclass
class Session:
    """The state of one subsample frame being verified."""

    run_id: str
    subsample_t_s: float
    frame_t_s: float
    marks: list[Mark] = field(default_factory=list)
    removed_ai: list[Mark] = field(default_factory=list)
    ai_count: int = 0

    @property
    def added(self) -> int:
        return sum(m.src == "human" for m in self.marks)

    @property
    def final_count(self) -> int:
        return len(self.marks)


def ensure_schema(db) -> None:
    """Create the assisted_counts table if needed (safe to call every time)."""
    with db.tx() as c:
        c.executescript(SCHEMA)


def protocol_frame(dets: list[dict[str, Any]], point: float, window_s: float) -> tuple[float | None, list[Mark]]:
    """Pick the sampled frame the protocol count uses for ``point`` and return its counted detections as marks.

    Mirrors ``count.protocol_counts``: among sampled frames within +/- window/2 of the point (nearest frame if none),
    the one holding the most counted individuals. ``dets`` are rows with t_s, x1..y2 and label (None = not counted).
    """
    if not dets:
        return None, []
    times = np.array(sorted({round(float(d["t_s"]), 3) for d in dets}))
    sel = times[np.abs(times - point) <= window_s / 2 + 1e-6]
    if not len(sel):
        sel = times[np.abs(times - point) == np.abs(times - point).min()]
    by_t: dict[float, list[Mark]] = {float(t): [] for t in sel}
    for d in dets:
        t = round(float(d["t_s"]), 3)
        if t in by_t and d.get("label"):
            by_t[t].append(Mark((d["x1"] + d["x2"]) / 2, (d["y1"] + d["y2"]) / 2, "ai", d["label"]))
    best = max(by_t, key=lambda t: (len(by_t[t]), -abs(t - point)))
    return best, by_t[best]


def new_session(run_id: str, point: float, frame_t: float, marks: list[Mark]) -> Session:
    return Session(run_id, float(point), float(frame_t), list(marks), [], len(marks))


def toggle(s: Session, x: float, y: float, radius: float) -> str:
    """Click at (x, y): remove the nearest mark within ``radius``, otherwise add a human mark. Returns 'removed'/'added'."""
    if s.marks:
        d = [np.hypot(m.x - x, m.y - y) for m in s.marks]
        i = int(np.argmin(d))
        if d[i] <= radius:
            m = s.marks.pop(i)
            if m.src == "ai":
                s.removed_ai.append(m)
            return "removed"
    s.marks.append(Mark(float(x), float(y), "human", None))
    return "added"


def undo_remove(s: Session) -> bool:
    """Put back the last AI mark that was removed."""
    if s.removed_ai:
        s.marks.append(s.removed_ai.pop())
        return True
    return False


def draw(view: np.ndarray, s: Session, radius: int = 14, offset: tuple[int, int] = (0, 0), scale: float = 1.0) -> np.ndarray:
    """Overlay marks on a view of the frame: AI marks as cyan rings, human-added marks as magenta rings with a dot.

    ``view`` is the frame region starting at ``offset`` (frame pixels), resized by ``scale``.
    """
    out = view.copy()
    h, w = out.shape[:2]
    for m in s.marks:
        x, y = int((m.x - offset[0]) * scale), int((m.y - offset[1]) * scale)
        if not (-radius <= x < w + radius and -radius <= y < h + radius):
            continue
        c = (255, 220, 0) if m.src == "ai" else (255, 0, 255)
        cv2.circle(out, (x, y), radius, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.circle(out, (x, y), radius, c, 2, cv2.LINE_AA)
        if m.src == "human":
            cv2.circle(out, (x, y), 3, c, -1, cv2.LINE_AA)
    return out


def save(db, s: Session, reviewer: str, seconds: float, frame: np.ndarray | None, training_dir: Path, video_file: str) -> dict:
    """Store the verified count and export the frame + point labels for retraining FishSpotter."""
    ensure_schema(db)
    now = dt.datetime.now().isoformat(timespec="seconds")
    marks = [asdict(m) for m in s.marks]
    db.x("INSERT OR REPLACE INTO assisted_counts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
         (s.run_id, s.subsample_t_s, s.frame_t_s, s.ai_count, len(s.removed_ai), s.added, s.final_count,
          json.dumps(marks), reviewer, float(seconds), now))
    rec = {"run_id": s.run_id, "video_file": video_file, "subsample_t_s": s.subsample_t_s, "frame_t_s": s.frame_t_s,
           "ai_count": s.ai_count, "removed": len(s.removed_ai), "added": s.added, "final_count": s.final_count,
           "points": [[m["x"], m["y"]] for m in marks], "removed_points": [[m.x, m.y] for m in s.removed_ai],
           "reviewer": reviewer, "seconds": float(seconds), "saved_at": now}
    if frame is not None:
        training_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{s.run_id}_{s.subsample_t_s:.0f}s"
        cv2.imwrite(str(training_dir / f"{stem}.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
        (training_dir / f"{stem}.json").write_text(json.dumps(rec, indent=1))
    return rec


def load_saved(db, run_id: str) -> dict[float, dict]:
    """Verified counts already saved for a run, keyed by subsample time."""
    ensure_schema(db)
    return {float(r["subsample_t_s"]): r for r in db.q("SELECT * FROM assisted_counts WHERE run_id=?", (run_id,))}


def summary(saved: dict[float, dict], points: list[float], ai_counts: dict[float, int]) -> dict[str, Any]:
    """Protocol MeanCount from verified frames (AI count where not yet verified) and agreement statistics."""
    rows = []
    for p in points:
        r = saved.get(float(p))
        ai = int(ai_counts.get(float(p), 0))
        rows.append({"subsample_t_s": p, "ai_count": ai, "verified": r is not None,
                     "final_count": int(r["final_count"]) if r else None,
                     "added": int(r["added"]) if r else None, "removed": int(r["removed"]) if r else None,
                     "seconds": float(r["seconds"]) if r else None})
    done = [r for r in rows if r["verified"]]
    out: dict[str, Any] = {"rows": rows, "n_points": len(points), "n_verified": len(done)}
    if done:
        out["MeanCount_verified"] = float(np.mean([r["final_count"] for r in done]))
        out["MeanCount_ai_same_frames"] = float(np.mean([r["ai_count"] for r in done]))
        out["ai_kept_pct"] = 100.0 * (1 - sum(r["removed"] for r in done) / max(1, sum(r["ai_count"] for r in done)))
        out["ai_found_pct"] = 100.0 * sum(r["ai_count"] - r["removed"] for r in done) / max(1, sum(r["final_count"] for r in done))
        out["median_seconds_per_frame"] = float(np.median([r["seconds"] for r in done]))
    return out
