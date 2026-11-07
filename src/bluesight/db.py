"""SQLite storage (outputs/bluesight.db): videos, runs, frames, detections, tracks, flags and the registry."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY, video_file TEXT, site TEXT, date TEXT, start_s REAL, end_s REAL,
    started_at TEXT, runtime_s REAL, device TEXT, detector TEXT, embedder TEXT,
    n_frames INTEGER, n_tracks INTEGER, report_path TEXT, cached INTEGER
);
CREATE TABLE IF NOT EXISTS frames (
    run_id TEXT, frame_idx INTEGER, t_s REAL, visibility REAL, PRIMARY KEY (run_id, frame_idx)
);
CREATE TABLE IF NOT EXISTS detections (
    run_id TEXT, frame_idx INTEGER, t_s REAL, track_id INTEGER,
    x1 REAL, y1 REAL, x2 REAL, y2 REAL, score REAL, label TEXT
);
CREATE INDEX IF NOT EXISTS det_run ON detections(run_id, frame_idx);
CREATE TABLE IF NOT EXISTS tracks (
    run_id TEXT, track_id INTEGER, start_s REAL, end_s REAL, n_frames INTEGER, visibility REAL,
    mean_area REAL, status TEXT, species TEXT, best_similarity REAL, top3 TEXT, flag_id TEXT,
    PRIMARY KEY (run_id, track_id)
);
CREATE TABLE IF NOT EXISTS flags (
    flag_id TEXT PRIMARY KEY, run_id TEXT, video_file TEXT, status TEXT, track_ids TEXT,
    start_s REAL, end_s REAL, top3 TEXT, best_similarity REAL, visibility REAL, track_frames INTEGER,
    folder TEXT, embedding BLOB, created_at TEXT,
    review_decision TEXT, review_species TEXT, reviewer TEXT, review_timestamp TEXT
);
CREATE TABLE IF NOT EXISTS species (
    name TEXT PRIMARY KEY, display_name TEXT, source TEXT, date_added TEXT, approved_by TEXT,
    n_images INTEGER, prototype BLOB, embedder TEXT, active INTEGER DEFAULT 1, notes TEXT
);
CREATE TABLE IF NOT EXISTS species_prototypes (
    species TEXT, k INTEGER, vec BLOB, embedder TEXT, PRIMARY KEY (species, k)
);
CREATE TABLE IF NOT EXISTS species_images (
    species TEXT, path TEXT, source TEXT, added_at TEXT, embedding BLOB, PRIMARY KEY (species, path)
);
"""


def to_blob(v: np.ndarray | None) -> bytes | None:
    """Serialise a float32 vector."""
    return None if v is None else np.asarray(v, np.float32).tobytes()


def from_blob(b: bytes | None) -> np.ndarray | None:
    """Deserialise a float32 vector."""
    return None if b is None else np.frombuffer(b, np.float32).copy()


class DB:
    """Small SQLite helper. One connection per instance; safe to create per request in Streamlit."""

    def __init__(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        self.conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """Transaction context manager."""
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def q(self, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
        """Run a query and return rows as dicts."""
        return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def x(self, sql: str, args: tuple = ()) -> None:
        """Execute and commit."""
        with self.tx() as c:
            c.execute(sql, args)

    def close(self) -> None:
        self.conn.close()

    # convenience -------------------------------------------------------------
    def flag_review(self, flag_id: str) -> dict[str, Any] | None:
        rows = self.q("SELECT * FROM flags WHERE flag_id=?", (flag_id,))
        return rows[0] if rows else None

    def set_review(self, flag_id: str, decision: str, species: str | None, reviewer: str, ts: str) -> None:
        """Record a biologist's decision on a flag."""
        self.x(
            "UPDATE flags SET review_decision=?, review_species=?, reviewer=?, review_timestamp=? WHERE flag_id=?",
            (decision, species, reviewer, ts, flag_id),
        )


def dumps(o: Any) -> str:
    return json.dumps(o, default=float)
