"""Counting per species: MaxN and MeanCount, following Coastal Action's protocol.

Protocol (DRAFT FFH Video Analysis Protocol): analyse a 15-min window, subsample systematically
every 60 s (15 frames); a fish visible within ~0.5 s of the subsample point counts; MeanCount is
the mean count over the subsample frames. MaxN (max individuals in any one frame) is also given.
Counting at a subsample point uses detections from ONE instant per sampled frame, so tracked fish
are never double counted.
"""
from __future__ import annotations

from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from .identify import KNOWN, LOW_VIS, REJECTED, UNCERTAIN, UNFAMILIAR

UNKNOWN_LABEL = "Unknown/Unable to ID due to visibility"  # the protocol's own column name
UNFAMILIAR_LABEL = "Unfamiliar (flagged for review)"


def count_label(status: str, species: str | None, persistent: bool = True) -> str | None:
    """Column a detection is counted under (None = not counted).

    ``persistent=False`` marks detections that never formed a track of MIN_FRAMES samples. The
    protocol only counts organisms recognisable by at least two cues (shape AND swimming
    behaviour); a blob that does not move consistently fails the behaviour cue, so it is reported
    as a transient detection but not counted.
    """
    if not persistent and status != KNOWN:
        return None
    if status == KNOWN and species:
        return species
    if status == UNCERTAIN and species:
        return f"Unconfirmed: probably {species}?"
    if status == UNFAMILIAR:
        return UNFAMILIAR_LABEL
    if status == REJECTED:
        return None
    return UNKNOWN_LABEL


def per_frame_counts(times: Sequence[float], det_times: Iterable[float], det_labels: Iterable[str | None]) -> pd.DataFrame:
    """Counts per sampled frame (rows = every sampled time, even with no fish) per label (columns)."""
    df = pd.DataFrame({"t_s": list(det_times), "label": list(det_labels)}).dropna()
    base = pd.DataFrame(index=pd.Index(sorted(set(times)), name="t_s"))
    if df.empty:
        return base
    tab = df.groupby(["t_s", "label"]).size().unstack(fill_value=0)
    return base.join(tab).fillna(0).astype(int)


def maxn(counts: pd.DataFrame) -> dict[str, int]:
    """MaxN: the most individuals of each label visible in any single sampled frame."""
    return {c: int(counts[c].max()) for c in counts.columns}


def meancount(counts: pd.DataFrame) -> dict[str, float]:
    """MeanCount: mean per-frame count of each label across the given frames (zeros included)."""
    return {c: float(counts[c].mean()) for c in counts.columns}


def subsample_points(start_s: float, end_s: float, interval_s: float) -> list[float]:
    """Systematic subsample times: start, start+interval, ... while < end (15 points for 15 min / 60 s)."""
    n = int(np.floor((end_s - start_s) / interval_s + 1e-9))
    return [start_s + i * interval_s for i in range(max(n, 1))]


def protocol_counts(counts: pd.DataFrame, points: Sequence[float], window_s: float) -> pd.DataFrame:
    """Count at each subsample point = the sampled frame within +/- window/2 holding the most
    individuals (the protocol allows a fish seen within ~0.5 s of the point). Rows = points."""
    rows = []
    times = counts.index.to_numpy(dtype=float)
    for p in points:
        sel = np.abs(times - p) <= window_s / 2 + 1e-6
        if not sel.any():  # no sampled frame in the window: take the nearest one
            sel = np.abs(times - p) == np.abs(times - p).min()
        sub = counts[sel]
        tot = sub.sum(axis=1)
        rows.append(sub.loc[tot.idxmax()] if len(sub) else pd.Series(dtype=int))
    out = pd.DataFrame(rows, index=pd.Index(points, name="subsample_t_s")).fillna(0).astype(int)
    return out


def protocol_frame_times(counts: pd.DataFrame, points: Sequence[float], window_s: float) -> list[float]:
    """The sampled frame time ``protocol_counts`` used for each subsample point (for the count check page)."""
    out = []
    times = counts.index.to_numpy(dtype=float)
    for p in points:
        if len(times) == 0:
            out.append(float(p))
            continue
        sel = np.abs(times - p) <= window_s / 2 + 1e-6
        if not sel.any():
            sel = np.abs(times - p) == np.abs(times - p).min()
        sub = counts[sel]
        out.append(float(sub.sum(axis=1).idxmax()) if len(sub.columns) else float(times[sel][0]))
    return out


def visibility_summary(vis: Sequence[float], v_min: float) -> dict[str, float]:
    """Share of footage below V_MIN, so poor visibility is never reported as zero fish."""
    v = np.asarray(vis, float)
    if v.size == 0:
        return {"mean": 0.0, "min": 0.0, "max": 0.0, "fraction_below_v_min": 1.0}
    return {"mean": float(v.mean()), "min": float(v.min()), "max": float(v.max()),
            "fraction_below_v_min": float((v < v_min).mean())}
