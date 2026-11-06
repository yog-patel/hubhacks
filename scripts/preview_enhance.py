"""Save before/after enhancement images with visibility scores.

Usage: python scripts/preview_enhance.py <video> [--times 60,420,841,1320] -> outputs/enhance_preview/
"""
import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bluesight.config import load_config, path  # noqa: E402
from bluesight.enhance import enhance_frame, visibility_components, visibility_score  # noqa: E402
from bluesight.io_video import read_frame_at, resize_width  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--times", default="61,420,841,1320,1800")
    a = ap.parse_args()
    cfg = load_config()
    out = path(cfg, "outputs_dir") / "enhance_preview"
    out.mkdir(parents=True, exist_ok=True)
    for t in [float(x) for x in a.times.split(",")]:
        f = read_frame_at(a.video, t)
        if f is None:
            print(f"cannot read t={t}")
            continue
        f, _ = resize_width(f, 1280)
        e = enhance_frame(f, cfg["enhance"])
        v, ve = visibility_score(f, cfg["enhance"]), visibility_score(e, cfg["enhance"])
        comp = visibility_components(f)
        for img, txt in ((f, f"ORIGINAL  t={t:.0f}s  visibility={v:.2f}"), (e, f"ENHANCED (gray-world + CLAHE)")):
            cv2.rectangle(img, (0, 0), (img.shape[1], 30), (0, 0, 0), -1)
            cv2.putText(img, txt, (8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)
        fn = out / f"{Path(a.video).stem.replace(' ', '_')}_{int(t)}s.jpg"
        cv2.imwrite(str(fn), np.hstack([f, e]), [cv2.IMWRITE_JPEG_QUALITY, 88])
        print(f"{fn}  visibility={v:.2f}  {({k: round(x, 3) for k, x in comp.items()})}")
