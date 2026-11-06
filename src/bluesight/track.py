"""ByteTrack (via the `supervision` library) so each fish keeps one ID and is never double counted."""
from __future__ import annotations

from typing import Any

import numpy as np


def expand_boxes(boxes: np.ndarray, factor: float, min_size: float = 0.0) -> np.ndarray:
    """Scale (N, 4) boxes about their centres (and to at least ``min_size`` px per side). Used only
    for association: at 2 fps a small fish moves more than its own length between samples, so raw
    boxes rarely overlap."""
    if len(boxes) == 0:
        return boxes.copy()
    c = (boxes[:, :2] + boxes[:, 2:4]) / 2
    half = np.maximum((boxes[:, 2:4] - boxes[:, :2]) / 2 * factor, min_size / 2)
    return np.concatenate([c - half, c + half], axis=1)


def iou_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Pairwise IoU of (N, 4) and (M, 4) boxes."""
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    x1 = np.maximum(a[:, None, 0], b[None, :, 0]); y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2]); y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area = lambda z: (z[:, 2] - z[:, 0]) * (z[:, 3] - z[:, 1])
    return inter / (area(a)[:, None] + area(b)[None, :] - inter + 1e-9)


class Tracker:
    """Thin wrapper over ``supervision.ByteTrack`` returning a track id per input detection (-1 = untracked)."""

    def __init__(self, cfg: dict[str, Any], frame_rate: float) -> None:
        import supervision as sv

        self.sv = sv
        self.expand = float(cfg.get("box_expand", 1.0))
        self.min_size = float(cfg.get("min_assoc_size", 0.0))
        self.seen: set[int] = set()
        self._prev_untracked = np.zeros((0, 4))
        self._prev_idx = np.zeros(0, dtype=int)
        self.bt = sv.ByteTrack(
            track_activation_threshold=float(cfg["track_activation_threshold"]),
            lost_track_buffer=int(cfg["lost_track_buffer"]),
            minimum_matching_threshold=float(cfg["minimum_matching_threshold"]),
            frame_rate=max(1, int(round(frame_rate))),
        )

    def update(self, boxes: np.ndarray) -> tuple[np.ndarray, list[tuple[int, int]]]:
        """Associate (N, 5) boxes with tracks.

        Returns:
            ids: int array of N track ids (-1 if untracked).
            backfill: [(index in the PREVIOUS frame's boxes, track id)] - ByteTrack only reports a new
                track from its second frame, so its first detection is recovered here.
        """
        ids = np.full(len(boxes), -1, dtype=np.int64)
        exp = expand_boxes(boxes[:, :4], self.expand, self.min_size) if len(boxes) else np.zeros((0, 4))
        dets = self.sv.Detections(
            xyxy=exp.astype(np.float32) if len(boxes) else np.zeros((0, 4), np.float32),
            confidence=boxes[:, 4].astype(np.float32) if len(boxes) else np.zeros(0, np.float32),
            class_id=np.zeros(len(boxes), dtype=int),
            data={"det_idx": np.arange(len(boxes))},
        )
        out = self.bt.update_with_detections(dets)
        if len(out):
            ids[out.data["det_idx"]] = out.tracker_id
        backfill: list[tuple[int, int]] = []
        new = [i for i in range(len(ids)) if ids[i] >= 0 and int(ids[i]) not in self.seen]
        if new and len(self._prev_untracked):
            M = iou_matrix(exp[new], self._prev_untracked)
            used: set[int] = set()
            for r in np.argsort(-M.max(1)):
                j = int(np.argmax(M[r]))
                if M[r, j] > 0.1 and j not in used:
                    used.add(j)
                    backfill.append((int(self._prev_idx[j]), int(ids[new[r]])))
        self.seen.update(int(t) for t in ids if t >= 0)
        un = ids < 0
        self._prev_untracked = exp[un] if len(exp) else np.zeros((0, 4))
        self._prev_idx = np.nonzero(un)[0]
        return ids, backfill
