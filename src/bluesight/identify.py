"""Per-TRACK species identification against registry prototypes, with a visibility gate."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

import cv2
import numpy as np

KNOWN = "known"
UNCERTAIN = "uncertain"
UNFAMILIAR = "unfamiliar"
LOW_VIS = "unidentified_low_visibility"
REJECTED = "rejected"
FLAG_STATUSES = (UNFAMILIAR, UNCERTAIN)


@dataclass
class Thresholds:
    """Decision thresholds (all from config.yaml ``identify``)."""

    T_KNOWN: float
    T_UNKNOWN: float
    V_MIN: float
    MIN_FRAMES: int
    MIN_AREA: float

    @classmethod
    def from_cfg(cls, cfg: dict[str, Any]) -> "Thresholds":
        c = cfg["identify"]
        return cls(float(c["T_KNOWN"]), float(c["T_UNKNOWN"]), float(c["V_MIN"]), int(c["MIN_FRAMES"]), float(c["MIN_AREA"]))

    def as_dict(self) -> dict[str, float]:
        return {"T_KNOWN": self.T_KNOWN, "T_UNKNOWN": self.T_UNKNOWN, "V_MIN": self.V_MIN,
                "MIN_FRAMES": self.MIN_FRAMES, "MIN_AREA": self.MIN_AREA}


@dataclass
class TrackResult:
    """Outcome of identifying one track."""

    status: str
    species: str | None
    best_similarity: float
    top3: list[dict[str, float | str]] = field(default_factory=list)


def crop_quality(crop: np.ndarray, touches_edge: bool = False) -> float:
    """Score a crop for "sharpest, largest, least occluded": Laplacian variance x sqrt(area),
    halved when the box touches the frame edge (likely cut off)."""
    if crop is None or crop.size == 0:
        return 0.0
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    sharp = float(cv2.Laplacian(g, cv2.CV_32F).var())
    q = sharp * np.sqrt(g.shape[0] * g.shape[1])
    return q * (0.5 if touches_edge else 1.0)


def select_best(items: Sequence[tuple[float, Any]], k: int) -> list[Any]:
    """Return the payloads of the k highest-quality (quality, payload) items."""
    return [p for _, p in sorted(items, key=lambda qp: -qp[0])[:k]]


def mean_embedding(embs: np.ndarray) -> np.ndarray:
    """Average unit vectors and renormalise."""
    m = np.asarray(embs, np.float32).mean(0)
    return m / (np.linalg.norm(m) + 1e-12)


def top_matches(emb: np.ndarray, names: Sequence[str], protos: np.ndarray, k: int = 3) -> list[dict[str, Any]]:
    """Cosine similarity to every prototype; the top k SPECIES as [{species, similarity}].

    ``names`` may repeat a species (several prototypes per species); a species' similarity is its best prototype's.
    """
    if len(names) == 0:
        return []
    sims = protos @ (emb / (np.linalg.norm(emb) + 1e-12))
    best: dict[str, float] = {}
    for n, s in zip(names, sims.tolist()):
        if n not in best or s > best[n]:
            best[n] = float(s)
    return [{"species": n, "similarity": v} for n, v in sorted(best.items(), key=lambda x: -x[1])[:k]]


def decide_status(best: float, visibility: float, track_len: int, box_area: float, th: Thresholds) -> str:
    """The decision rule. Poor visibility / short / tiny tracks are NEVER flagged as new species."""
    if visibility < th.V_MIN or track_len < th.MIN_FRAMES or box_area < th.MIN_AREA:
        return LOW_VIS
    if best >= th.T_KNOWN:
        return KNOWN
    if best >= th.T_UNKNOWN:
        return UNCERTAIN
    return UNFAMILIAR


def classify_track(
    emb: np.ndarray | None,
    visibility: float,
    track_len: int,
    box_area: float,
    names: Sequence[str],
    protos: np.ndarray,
    th: Thresholds,
) -> TrackResult:
    """Identify a track from its averaged best-crop embedding.

    Returns status (known / uncertain / unfamiliar / unidentified_low_visibility), the top-1
    species (for known and uncertain), the best similarity and the top-3 matches.
    """
    top3 = top_matches(emb, names, protos, 3) if emb is not None else []
    best = top3[0]["similarity"] if top3 else 0.0
    if emb is None:
        visibility = min(visibility, -1.0)  # nothing to identify -> treat as not identifiable
    status = decide_status(best, visibility, track_len, box_area, th)
    species = top3[0]["species"] if status in (KNOWN, UNCERTAIN) and top3 else None
    return TrackResult(status, species, best, top3)


def merge_flagged(keys: Sequence[Any], embs: np.ndarray, sim_thresh: float, order: Sequence[float] | None = None) -> list[list[Any]]:
    """Greedily merge flagged tracks whose embeddings are very similar into review items.

    Args:
        keys: track identifiers.
        embs: (N, D) unit embeddings.
        sim_thresh: cosine similarity to a group's centroid needed to join it.
        order: optional priority (higher first), e.g. unfamiliarity; groups are seeded in this order.
    Returns:
        List of groups (lists of keys), in seeding order.
    """
    idx = list(range(len(keys)))
    if order is not None:
        idx.sort(key=lambda i: -order[i])
    groups: list[list[int]] = []
    cents: list[np.ndarray] = []
    for i in idx:
        e = embs[i]
        best_g, best_s = -1, -1.0
        for g, c in enumerate(cents):
            s = float(c @ e)
            if s > best_s:
                best_g, best_s = g, s
        if best_g >= 0 and best_s >= sim_thresh:
            groups[best_g].append(i)
            cents[best_g] = mean_embedding(embs[groups[best_g]])
        else:
            groups.append([i])
            cents.append(e / (np.linalg.norm(e) + 1e-12))
    return [[keys[i] for i in g] for g in groups]


def auto_reject(status: str, emb: np.ndarray | None, best_similarity: float, rejected: np.ndarray | None, reject_sim: float) -> bool:
    """True if a FLAGGED track looks like something a reviewer already rejected as "not a fish".

    Only uncertain/unfamiliar tracks can be auto-rejected, and only when they are more similar to a
    rejected item than to any species. Known species are never touched and nothing is ever
    auto-accepted, so a species still only enters the registry by human approval.
    """
    if rejected is None or emb is None or len(rejected) == 0 or status not in FLAG_STATUSES:
        return False
    ns = float((rejected @ emb).max())
    return ns >= reject_sim and ns > best_similarity
