"""Write the manual ground truth for T1-STAT2 411.MP4 found in the subsample photos.

Two gridded screenshots of this video (VLC timebar reads "/35:47", the video length) carry
the biologists' counts: a black tally dot on every counted fish plus a handwritten number per
grid cell. The handwritten totals were transcribed by reading the images (cell by cell):

* 14:01  "T1-STAT 2_Sept 10 _count @ 14min_enhanced.png": 13+9+5+5+3+1 = 36 fish
* 22:00  "T1-STAT 2_Sept 10 _count @ 22min_enhanced.png": 13+25+12+7+14+10+3+8+8+2 = 102 fish,
         plus 1 European green crab circled in "..._count @ 22 _marked green crab.png"

For 14:01 the tally dots are also extracted as point labels (their per-cell counts reproduce the
handwritten numbers exactly). At 22:00 dot extraction also picks up sand texture, so only the
count is used there.

Usage: python scripts/extract_ground_truth.py
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bluesight.config import ROOT, load_config, path  # noqa: E402

VIDEO = "T1-STAT2 411.MP4"
ROWS = [
    # time_s, total_fish, invertebrates, source photo, cell tallies (transcribed)
    (841.0, 36, None, "T1-STAT 2_Sept 10 _count @ 14min_enhanced.png", "13+9+5+5+3+1"),
    (1320.0, 102, 1, "T1-STAT 2_Sept 10 _count @ 22min_enhanced.png", "13+25+12+7+14+10+3+8+8+2"),
]


def tally_dots(img: np.ndarray, max_y: int = 712, pole_x: tuple[int, int] = (945, 1015)) -> list[list[float]]:
    """Small dark marks in the top two grid rows (where all handwritten counts are)."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    bg = cv2.medianBlur(g, 15).astype(np.float32)
    dark = ((bg - g.astype(np.float32)) > 35).astype(np.uint8)
    n, _, st, cen = cv2.connectedComponentsWithStats(dark)
    pts = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        cx, cy = cen[i]
        if 4 <= a <= 40 and w <= 8 and h <= 8 and cy < max_y and not (pole_x[0] < cx < pole_x[1]):
            pts.append([float(cx), float(cy)])
    return pts


def main() -> None:
    cfg = load_config()
    gt_dir = path(cfg, "ground_truth_dir")
    gt_dir.mkdir(parents=True, exist_ok=True)
    photos = {p.name: p for p in path(cfg, "raw_photos_dir").rglob("*.png")}
    with open(gt_dir / "manual_counts.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["video_file", "time_s", "total_fish", "invertebrates", "source_photo", "cell_tallies", "notes"])
        for t, n, inv, src, cells in ROWS:
            w.writerow([VIDEO, t, n, "" if inv is None else inv, src, cells,
                        "transcribed from the biologists' gridded screenshot"])
    img = cv2.imread(str(photos[ROWS[0][3]]))
    pts = tally_dots(img)
    scale = 3840.0 / img.shape[1]  # screenshot (~1917 px wide) -> 4K video pixels
    out = {"video_file": VIDEO, "time_s": 841.0, "n_points": len(pts), "coords": "video pixels (3840x2160)",
           "points": [[round(x * scale, 1), round(y * scale, 1)] for x, y in pts],
           "source_photo": ROWS[0][3]}
    (gt_dir / "points_841s.json").write_text(json.dumps(out, indent=1))
    print(f"manual_counts.csv written; {len(pts)} tally points at 14:01 (handwritten total 36)")


if __name__ == "__main__":
    main()
