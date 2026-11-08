"""Build the fish-counting training set from the biologists' dot annotations.

Every fish the biologists counted carries a tally dot:

* T1-STAT2 (the survey video) 14:01 and 22:00: black dots. The clean video frame each screenshot shows is found by
  correlating the screenshot with every video frame in a +/-1.5 s window (as in DECISIONS D19). The dots are pure
  black (max channel < 30); at 22:00 this reproduces the handwritten count in all 12 grid cells (102 fish).
* T2-STAT2 (another station; no video) 13, 14 and 21 min: red dots on VLC screenshots. Red marks and the black grid
  are painted out (OpenCV inpainting) so the model never sees annotation ink.

Regions nobody annotated are excluded from training ("ignore" mask): the VLC control bar, and red circles (single
organisms, mostly crabs, not tallied as fish).

Output: outputs/density/dataset.npz with images at 1920x1080, dot coordinates and ignore masks.
Usage:  python scripts/density_data.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bluesight.config import load_config, path  # noqa: E402

W, H = 1920, 1080
VIDEO = "T1-STAT2 411.MP4"
T1 = [("T1-STAT 2_Sept 10 _count @ 14min_enhanced.png", 841.0, 36),
      ("T1-STAT 2_Sept 10 _count @ 22min_enhanced.png", 1320.0, 102)]
T2 = [("T2_STAT 2_Sept 10_count@ 13min.png", None), ("T2_STAT 2_Sept 10_count@ 14min.png", 46),
      ("T2_STAT 2_Sept 10_count@ 21min.png", None)]


def black_dots(img: np.ndarray, thr: int = 30, max_y: int = 712) -> np.ndarray:
    """Pure-black tally dots in the top two grid rows (where every handwritten count is), off the grid lines and the
    pole. At 22:00 this reproduces the handwritten count of all 12 cells exactly (102)."""
    mx = img.max(axis=2)
    lines = grid_lines(img)
    n, _, st, cen = cv2.connectedComponentsWithStats((mx < thr).astype(np.uint8), connectivity=8)
    keep = []
    for i in range(1, n):
        x, y = cen[i]
        if not (1 <= st[i][4] <= 40 and st[i][2] <= 8 and st[i][3] <= 8) or y >= max_y:
            continue
        if lines[int(y), int(x)] or (955 < x < 1015 and y > 240):
            continue
        keep.append(cen[i])
    return np.array(keep, np.float32).reshape(-1, 2)


def grid_lines(img: np.ndarray) -> np.ndarray:
    """Mask of the long black grid lines drawn on the screenshots."""
    dark = (img.max(axis=2) < 60).astype(np.uint8)
    h = cv2.morphologyEx(dark, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (120, 1)))
    v = cv2.morphologyEx(dark, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 120)))
    return cv2.dilate(h | v, np.ones((11, 11), np.uint8))


def red_mask(img: np.ndarray) -> np.ndarray:
    b, g, r = [img[..., i].astype(int) for i in range(3)]
    return ((r > 150) & (r - g > 90) & (r - b > 90)).astype(np.uint8)


def red_dots_and_circles(img: np.ndarray) -> tuple[np.ndarray, list[tuple[int, int, int, int]]]:
    m = red_mask(img)
    n, _, st, cen = cv2.connectedComponentsWithStats(m, connectivity=8)
    dots, circles = [], []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if w > 60 and h > 40:
            circles.append((x, y, w, h))
        elif a <= 30 and w <= 7 and h <= 7:
            dots.append(cen[i])
    dots = [d for d in dots if not any(x <= d[0] <= x + w and y <= d[1] <= y + h for x, y, w, h in circles)]
    return np.array(dots, np.float32).reshape(-1, 2), circles


def vlc_bar(img: np.ndarray) -> tuple[int, int, int, int] | None:
    """Bounding box of VLC's floating control bar (bright, low-texture strip in the bottom quarter)."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h = img.shape[0]
    rows = np.where((g[int(h * 0.8):] > 200).mean(axis=1) > 0.25)[0]
    if not len(rows):
        return None
    y0 = int(h * 0.8) + rows.min() - 10
    cols = np.where((g[y0 + 10:y0 + 40] > 200).mean(axis=0) > 0.5)[0]
    if not len(cols):
        return None
    return int(cols.min()) - 10, y0, int(cols.max()) + 10, h


def highpass(g: np.ndarray) -> np.ndarray:
    g = g.astype(np.float32)
    return g - cv2.GaussianBlur(g, (0, 0), 6)


def align(shot: np.ndarray, video: Path, t0: float, span: float = 1.5) -> tuple[float, np.ndarray, float]:
    """Find the video frame the screenshot shows (max correlation of high-pass detail, annotations masked)."""
    small = cv2.resize(shot, (960, 540), interpolation=cv2.INTER_AREA)
    mask = cv2.resize(((shot.max(axis=2) < 60) | (grid_lines(shot) > 0)).astype(np.uint8), (960, 540)) == 0
    a = highpass(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))[mask]
    a = (a - a.mean()) / (a.std() + 1e-6)
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS)
    cap.set(cv2.CAP_PROP_POS_FRAMES, int((t0 - span) * fps))
    best = (-1.0, None, None)
    scores = []
    for _ in range(int(2 * span * fps)):
        idx = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
        ok, fr = cap.read()
        if not ok:
            break
        b = highpass(cv2.cvtColor(cv2.resize(fr, (960, 540), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY))[mask]
        c = float(((b - b.mean()) / (b.std() + 1e-6) * a).mean())
        scores.append(c)
        if c > best[0]:
            best = (c, idx / fps, fr)
    cap.release()
    s = np.array(scores)
    margin = float(best[0] - np.median(s))
    print(f"  aligned at {best[1]:.3f} s (corr {best[0]:.3f}, median {np.median(s):.3f}, margin {margin:.3f})")
    return best[1], cv2.resize(best[2], (W, H), interpolation=cv2.INTER_AREA), margin


def main() -> None:
    cfg = load_config()
    photos = {p.name: p for p in path(cfg, "raw_photos_dir").rglob("*.png")}
    video = path(cfg, "videos_dir") / VIDEO
    out_dir = path(cfg, "outputs_dir") / "density"
    out_dir.mkdir(parents=True, exist_ok=True)
    items = []
    for name, t0, want in T1:
        shot = cv2.imread(str(photos[name]))
        sx, sy = W / shot.shape[1], H / shot.shape[0]
        pts = black_dots(shot)
        print(f"{name}: {len(pts)} dots (handwritten total {want})")
        t, frame, margin = align(shot, video, t0)
        ign = np.zeros((H, W), bool)
        bar = vlc_bar(shot)
        if bar:
            x0, y0, x1, y1 = bar
            ign[int(y0 * sy):, int(x0 * sx):int(x1 * sx)] = True
        items.append({"name": f"T1-STAT2@{t:.2f}s", "image": frame, "points": pts * [sx, sy], "ignore": ign,
                      "source": name, "time_s": t, "align_margin": margin})
    for name, want in T2:
        shot = cv2.imread(str(photos[name]))
        sx, sy = W / shot.shape[1], H / shot.shape[0]
        pts, circles = red_dots_and_circles(shot)
        print(f"{name}: {len(pts)} red dots, {len(circles)} circles" + (f" (handwritten total {want})" if want else ""))
        ink = cv2.dilate(red_mask(shot), np.ones((5, 5), np.uint8)) | grid_lines(shot)
        clean = cv2.inpaint(shot, ink, 3, cv2.INPAINT_TELEA)
        ign = np.zeros(shot.shape[:2], bool)
        for x, y, w, h in circles:
            ign[max(0, y - 10):y + h + 10, max(0, x - 10):x + w + 10] = True
        bar = vlc_bar(shot)
        if bar:
            x0, y0, x1, y1 = bar
            ign[y0:, x0:x1] = True
        items.append({"name": f"T2-STAT2 {name.split('@')[1].strip().replace('.png', '')}",
                      "image": cv2.resize(clean, (W, H), interpolation=cv2.INTER_AREA), "points": pts * [sx, sy],
                      "ignore": cv2.resize(ign.astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST) > 0,
                      "source": name, "time_s": None, "align_margin": None})
    np.savez_compressed(out_dir / "dataset.npz", images=np.stack([i["image"] for i in items]),
                        ignore=np.stack([i["ignore"] for i in items]),
                        points=np.array([i["points"] for i in items], dtype=object),
                        meta=json.dumps([{k: v for k, v in i.items() if k not in ("image", "points", "ignore")} | {"n": len(i["points"])}
                                         for i in items]))
    for i in items:
        vis = i["image"].copy()
        for x, y in i["points"]:
            cv2.circle(vis, (int(x), int(y)), 6, (0, 0, 255), 2)
        vis[i["ignore"]] = (vis[i["ignore"]] * 0.4).astype(np.uint8)
        cv2.imwrite(str(out_dir / f"check_{i['name'].replace(' ', '_').replace('@', '_')}.jpg"), vis, [cv2.IMWRITE_JPEG_QUALITY, 80])
    print("wrote", out_dir / "dataset.npz", [(i["name"], len(i["points"])) for i in items])


if __name__ == "__main__":
    main()
