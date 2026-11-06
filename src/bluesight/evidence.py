"""Evidence package per flagged item: clip.mp4 (track +/- 2 s, fish boxed), crop_1..5.jpg, flag.json."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np

from .io_video import VideoWriter, resize_width
from .logs import get_logger

log = get_logger("evidence")


def interpolate_box(track_boxes: Sequence[tuple[float, Sequence[float]]], t: float) -> list[float] | None:
    """Linear interpolation of a track's box at time t (None outside the track's span)."""
    if not track_boxes or t < track_boxes[0][0] - 0.26 or t > track_boxes[-1][0] + 0.26:
        return None
    times = [tb[0] for tb in track_boxes]
    j = int(np.searchsorted(times, t))
    if j <= 0:
        return list(track_boxes[0][1])
    if j >= len(times):
        return list(track_boxes[-1][1])
    (t0, b0), (t1, b1) = track_boxes[j - 1], track_boxes[j]
    a = (t - t0) / max(t1 - t0, 1e-6)
    return [float(x0 + a * (x1 - x0)) for x0, x1 in zip(b0, b1)]


def write_clip(video_path: str, out_path: Path, tracks: dict[int, list[tuple[float, list[float]]]],
               start_s: float, end_s: float, cfg: dict[str, Any], label: str) -> float:
    """Write the evidence clip: video from start_s to end_s with every track in ``tracks`` boxed.

    Boxes are in full-resolution pixels. Returns the clip duration in seconds.
    """
    ecfg = cfg["evidence"]
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    out_fps = 10.0  # every 3rd frame: watchable and 3x cheaper to encode
    stride = max(1, int(round(fps / out_fps)))
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, start_s) * 1000)
    writer = None
    n = 0
    i = 0
    t = max(0.0, start_s)
    while t <= end_s:
        if i % stride == 0:
            ok, frame = cap.read()
            if not ok:
                break
            t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            small, s = resize_width(frame, int(ecfg["clip_width"]))
            for tid, tb in tracks.items():
                b = interpolate_box(tb, t)
                if b is not None:
                    x1, y1, x2, y2 = [int(v * s) for v in b]
                    pad = 6
                    cv2.rectangle(small, (x1 - pad, y1 - pad), (x2 + pad, y2 + pad), (0, 165, 255), 2)
                    cv2.putText(small, label, (x1 - pad, max(12, y1 - pad - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 165, 255), 1)
            cv2.putText(small, f"t={t:7.1f}s", (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
            if writer is None:
                writer = VideoWriter(out_path, out_fps, small.shape[1], small.shape[0])
            writer.write(small)
            n += 1
        else:
            if not cap.grab():
                break
            t += 1.0 / fps
        i += 1
    cap.release()
    if writer is not None:
        writer.close()
    return n / out_fps


def write_flag_package(folder: Path, flag: dict[str, Any], crops: Sequence[np.ndarray], video_path: str,
                       tracks: dict[int, list[tuple[float, list[float]]]], cfg: dict[str, Any]) -> Path:
    """Create outputs/flags/<flag_id>/ with clip.mp4, crop_1..5.jpg and flag.json."""
    folder.mkdir(parents=True, exist_ok=True)
    for i, c in enumerate(crops[:5], start=1):
        cv2.imwrite(str(folder / f"crop_{i}.jpg"), c, [cv2.IMWRITE_JPEG_QUALITY, 92])
    m = float(cfg["evidence"]["clip_margin_s"])
    start = max(0.0, flag["start_time_s"] - m)
    end = min(flag["end_time_s"] + m, start + float(cfg["evidence"]["max_clip_s"]))
    try:
        label = "unfamiliar?" if flag["status"] == "unfamiliar" else f"probably {flag['top3'][0]['species']}?"
        write_clip(video_path, folder / "clip.mp4", tracks, start, end, cfg, label)
    except Exception as exc:  # evidence without a clip is still reviewable; log loudly
        log.error("clip failed for %s: %s", flag["flag_id"], exc)
    (folder / "flag.json").write_text(json.dumps(flag, indent=2, default=float))
    return folder
