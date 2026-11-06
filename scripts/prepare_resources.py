"""Phase 0: discover the provided resources and build the working data layout.

* finds every video / image / document in the project (originals are never modified)
* extracts "Subsample Photos.zip" into data/raw_photos/ (gitignored)
* links videos into data/videos/ and documents into docs/instructions/ (symlinks)
* turns the biologists' annotations in the photos into crops:
    - red circles drawn around organisms     -> one crop per circle
    - red tally dots placed on schooling fish -> one crop per dot
* photos of the survey video itself become ground truth (data/ground_truth/), not reference images
* proposes a species label for every crop with BioCLIP zero-shot (data/proposed_labels.csv)
* sorts crops into data/reference_images/<species>/, data/held_out/<species>/ or data/unsorted/
* writes data/manifest.csv

Usage:
    python scripts/prepare_resources.py [--held-out a,b] [--skip-labels]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bluesight.config import ROOT, load_config, path  # noqa: E402
from bluesight.logs import get_logger  # noqa: E402

log = get_logger("prepare")

VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".m4v"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".heic"}
DOC_EXTS = {".pdf", ".docx", ".doc", ".txt", ".md", ".pptx", ".xlsx", ".csv"}
IGNORE_DIRS = {".git", ".venv", "outputs", "data", "src", "app", "scripts", "tests", "models", "docs"}
PROJECT_DOCS = {"CLAUDE.md", "README.md", "RESOURCES.md", "DECISIONS.md", "EVALUATION.md", "DEMO.md", "requirements.txt"}


def discover(root: Path) -> dict[str, list[Path]]:
    """Recursively list resources by type, skipping generated/code folders."""
    found: dict[str, list[Path]] = {"video": [], "image": [], "doc": [], "archive": []}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if any(part in IGNORE_DIRS for part in rel.parts[:-1]) or rel.parts[0] in IGNORE_DIRS:
            continue
        if not p.is_file() or p.name.startswith("."):
            continue
        ext = p.suffix.lower()
        if ext in VIDEO_EXTS:
            found["video"].append(p)
        elif ext in IMAGE_EXTS:
            found["image"].append(p)
        elif ext in DOC_EXTS and p.name not in PROJECT_DOCS and rel.parts[0] != "config.yaml":
            found["doc"].append(p)
        elif ext == ".zip":
            found["archive"].append(p)
    return found


def safe_link(src: Path, dst: Path) -> str:
    """Create a relative symlink dst -> src (copy if symlinks fail). Returns 'symlink' or 'copy'."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_symlink() or dst.exists():
        dst.unlink()
    try:
        rel = Path(*([".."] * (len(dst.relative_to(ROOT).parts) - 1))) / src.relative_to(ROOT)
        dst.symlink_to(rel)
        return "symlink"
    except OSError:
        shutil.copy2(src, dst)
        return "copy"


# ---------------------------------------------------------------- annotation parsing
def red_mask(img: np.ndarray) -> np.ndarray:
    """Pixels drawn in annotation red."""
    b, g, r = [img[:, :, i].astype(np.int16) for i in range(3)]
    return ((r > 150) & (g < 100) & (b < 100) & (r - g > 90)).astype(np.uint8)


def find_red_annotations(img: np.ndarray) -> tuple[list[tuple[int, int, int, int]], list[tuple[int, int]]]:
    """Return (circle bounding boxes, dot centres) of red annotation marks."""
    m = red_mask(img)
    n, _, st, cen = cv2.connectedComponentsWithStats(m, connectivity=8)
    circles, dots = [], []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        fill = a / float(w * h)
        if w >= 25 and h >= 20 and fill < 0.35:
            circles.append((int(x), int(y), int(w), int(h)))
        elif a <= 30 and w <= 8 and h <= 8:
            dots.append((int(round(cen[i][0])), int(round(cen[i][1]))))
    # drop dots that sit inside circles (stray pixels of the ellipse outline) or near red text
    dots = [d for d in dots if not any(x <= d[0] <= x + w and y <= d[1] <= y + h for x, y, w, h in circles)]
    return circles, dots


def clean_crop(img: np.ndarray, x0: int, y0: int, x1: int, y1: int) -> np.ndarray:
    """Crop and inpaint the red annotation pixels away."""
    H, W = img.shape[:2]
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
    crop = img[y0:y1, x0:x1].copy()
    m = cv2.dilate(red_mask(crop), np.ones((3, 3), np.uint8))
    if m.any():
        crop = cv2.inpaint(crop, m, 3, cv2.INPAINT_TELEA)
    return crop


def parse_photo_name(name: str) -> dict[str, str]:
    """Pull transect, station, date and timestamp out of names like 'T2_STAT 2_Sept 10_count@ 9min.png'."""
    out: dict[str, str] = {}
    m = re.search(r"T(\d)[-_ ]*STAT ?(\d)", name)
    if m:
        out["site"] = f"T{m.group(1)}-STAT{m.group(2)}"
    m = re.search(r"Sept (\d+)", name)
    if m:
        out["date"] = f"2025-09-{int(m.group(1)):02d}"
    m = re.search(r"@ ?(\d+)\s*(?:min)?\s*(?:(\d+)\s*sec)?", name)
    if m:
        out["time_s"] = str(int(m.group(1)) * 60 + int(m.group(2) or 0))
    if "green crab" in name.lower():
        out["filename_label"] = "european_green_crab"
    return out


def video_site(video_name: str) -> str | None:
    m = re.search(r"T(\d)[-_ ]*STAT ?(\d)", video_name)
    return f"T{m.group(1)}-STAT{m.group(2)}" if m else None


# ---------------------------------------------------------------- zero-shot labels
def zero_shot(cfg: dict, crops: list[np.ndarray]) -> tuple[list[str], list[float], list[list[tuple[str, float]]]]:
    """BioCLIP zero-shot over species candidates + background prompts."""
    from bluesight.embed import get_embedder

    emb = get_embedder(cfg)
    if not emb.supports_text:
        raise RuntimeError("Zero-shot labelling needs BioCLIP (text encoder); DINOv2 fallback cannot do it")
    names, texts = [], []
    for sp in cfg["species_candidates"]:
        names.append(sp["name"])
        texts.append([f"a photo of {sp['scientific']}.", f"a photo of {sp['common']}.",
                      f"an underwater photo of a {sp['common']}."])
    for bg in cfg["background_prompts"]:
        names.append("background:" + bg)
        texts.append([f"a photo of {bg}."])
    T = []
    for group in texts:
        t = emb.embed_texts(group).mean(0)
        T.append(t / np.linalg.norm(t))
    T = np.stack(T)
    I = emb.embed_images(crops)
    logits = emb.logit_scale() * I @ T.T
    P = np.exp(logits - logits.max(1, keepdims=True))
    P /= P.sum(1, keepdims=True)
    labels, confs, tops = [], [], []
    for row in P:
        order = np.argsort(-row)
        labels.append(names[order[0]])
        confs.append(float(row[order[0]]))
        tops.append([(names[j], float(row[j])) for j in order[:3]])
    return labels, confs, tops


def _vote(rows: list[dict]) -> dict[str, int]:
    """Count zero-shot proposals in a group of crops (for reporting only)."""
    out: dict[str, int] = {}
    for r in rows:
        out[r["proposed"]] = out.get(r["proposed"], 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--held-out", default=None, help="comma-separated species to hold out (overrides config)")
    ap.add_argument("--skip-labels", action="store_true", help="reuse data/proposed_labels.csv")
    args = ap.parse_args()
    cfg = load_config()
    found = discover(ROOT)
    log.info("found %d videos, %d images, %d docs, %d archives",
             len(found["video"]), len(found["image"]), len(found["doc"]), len(found["archive"]))

    manifest: list[dict[str, str]] = []
    # videos and documents -> symlinks
    for v in found["video"]:
        how = safe_link(v, path(cfg, "videos_dir") / v.name)
        manifest.append({"original": str(v.relative_to(ROOT)), "role": "video", "species": "",
                         "derived": f"{cfg['paths']['videos_dir']}/{v.name}", "notes": how})
    for d in found["doc"]:
        how = safe_link(d, path(cfg, "instructions_dir") / d.name)
        manifest.append({"original": str(d.relative_to(ROOT)), "role": "instruction", "species": "",
                         "derived": f"{cfg['paths']['instructions_dir']}/{d.name}", "notes": how})

    # photos: extract archives (never modifying them) + loose images
    raw_dir = path(cfg, "raw_photos_dir")
    photos: list[tuple[Path, str]] = []  # (extracted path, original description)
    for z in found["archive"]:
        with zipfile.ZipFile(z) as zf:
            for member in zf.namelist():
                if Path(member).suffix.lower() in IMAGE_EXTS and not Path(member).name.startswith("."):
                    target = raw_dir / member
                    if not target.exists():
                        zf.extract(member, raw_dir)
                    photos.append((target, f"{z.relative_to(ROOT)}::{member}"))
    for im in found["image"]:
        photos.append((im, str(im.relative_to(ROOT))))

    video_sites = {video_site(v.name): v.name for v in found["video"] if video_site(v.name)}
    gt_dir = path(cfg, "ground_truth_dir")
    gt_dir.mkdir(parents=True, exist_ok=True)
    crops_dir = ROOT / "data" / "crops"
    if crops_dir.exists():
        shutil.rmtree(crops_dir)
    crops_dir.mkdir(parents=True)

    crop_rows: list[dict] = []
    crop_imgs: list[np.ndarray] = []
    for p, orig in photos:
        img = cv2.imread(str(p))
        if img is None:
            log.error("cannot read image %s", p)
            continue
        meta = parse_photo_name(p.name)
        same_video = meta.get("site") in video_sites and meta.get("date") == cfg["survey"]["default_date"]
        circles, dots = find_red_annotations(img)
        role = "ground_truth_frame" if same_video else "annotated_photo"
        manifest.append({"original": orig, "role": role, "species": meta.get("filename_label", ""),
                         "derived": str(p.relative_to(ROOT)),
                         "notes": f"site={meta.get('site')} date={meta.get('date')} t={meta.get('time_s')}s "
                                  f"red_circles={len(circles)} red_dots={len(dots)}"})
        if same_video and not meta.get("filename_label"):
            safe_link(p, gt_dir / p.name)
            continue  # frames of the survey video are evaluation data, never reference images
        for k, (x, y, w, h) in enumerate(circles):
            crop = clean_crop(img, x + 3, y + 3, x + w - 3, y + h - 3)
            crop_rows.append({"source": orig, "photo": p.name, "kind": "circle", "x": x + w // 2, "y": y + h // 2,
                              "site": meta.get("site", ""), "filename_label": meta.get("filename_label", ""),
                              "id": f"{p.stem.replace(' ', '_').replace('@', '')}_c{k}"})
            crop_imgs.append(crop)
        for k, (cx, cy) in enumerate(dots):
            crop = clean_crop(img, cx - 45, cy - 28, cx + 45, cy + 28)
            crop_rows.append({"source": orig, "photo": p.name, "kind": "dot", "x": cx, "y": cy,
                              "site": meta.get("site", ""), "filename_label": meta.get("filename_label", ""),
                              "id": f"{p.stem.replace(' ', '_').replace('@', '')}_d{k}"})
            crop_imgs.append(crop)
    for row, crop in zip(crop_rows, crop_imgs):
        fp = crops_dir / f"{row['id']}.jpg"
        cv2.imwrite(str(fp), crop, [cv2.IMWRITE_JPEG_QUALITY, 95])
        row["crop"] = str(fp.relative_to(ROOT))
    log.info("extracted %d annotation crops (%d circles, %d dots)", len(crop_rows),
             sum(r["kind"] == "circle" for r in crop_rows), sum(r["kind"] == "dot" for r in crop_rows))

    # zero-shot label proposals
    labels_csv = path(cfg, "proposed_labels")
    if args.skip_labels and labels_csv.exists():
        prev = {r["crop"]: r for r in csv.DictReader(open(labels_csv))}
        for r in crop_rows:
            q = prev.get(r["crop"], {})
            r.update({k: q.get(k, "") for k in ("proposed", "confidence", "top3")})
            r["confidence"] = float(r["confidence"] or 0)
    else:
        labels, confs, tops = zero_shot(cfg, crop_imgs)
        for r, l, c, t in zip(crop_rows, labels, confs, tops):
            r["proposed"], r["confidence"] = l, c
            r["top3"] = "; ".join(f"{n}={v:.2f}" for n, v in t)

    # final label. Priority: filename label > annotation-type label > zero-shot (only if trusted).
    # Zero-shot proposals proved unreliable on these murky crops (sand patches got 0.9+ "mummichog"),
    # so by default they are recorded for review but NOT used for the registry (see DECISIONS.md).
    min_conf = float(cfg["labels"]["min_confidence"])
    trust_zero_shot = bool(cfg["labels"].get("trust_zero_shot", False))
    ann = cfg["labels"].get("annotation_labels", {})
    for r in crop_rows:
        if r["filename_label"]:
            r["label"], r["label_source"] = r["filename_label"], "filename"
        elif r["kind"] in ann:
            r["label"], r["label_source"] = ann[r["kind"]], f"annotation_{r['kind']}"
        elif trust_zero_shot and not r["proposed"].startswith("background:") and r["confidence"] >= min_conf:
            r["label"], r["label_source"] = r["proposed"], "bioclip_zero_shot"
        else:
            r["label"], r["label_source"] = "", "low_confidence"

    with open(labels_csv, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["crop", "source", "kind", "site", "proposed", "confidence", "top3",
                                           "filename_label", "label", "label_source"])
        w.writeheader()
        for r in crop_rows:
            w.writerow({k: (f"{r[k]:.3f}" if k == "confidence" else r.get(k, "")) for k in w.fieldnames})

    # sort into reference / held-out / unsorted
    held = [s for s in (args.held_out.split(",") if args.held_out else cfg.get("held_out_species") or []) if s]
    for key in ("reference_dir", "held_out_dir", "unsorted_dir"):
        d = path(cfg, key)
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
    counts: dict[str, int] = {}
    for r in crop_rows:
        src = ROOT / r["crop"]
        if not r["label"]:
            dst, role = path(cfg, "unsorted_dir") / src.name, "unsorted"
        elif r["label"] in held:
            dst, role = path(cfg, "held_out_dir") / r["label"] / src.name, "held_out"
        else:
            dst, role = path(cfg, "reference_dir") / r["label"] / src.name, "reference_image"
        safe_link(src, dst)
        counts[r["label"] or "(unsorted)"] = counts.get(r["label"] or "(unsorted)", 0) + 1
        manifest.append({"original": r["source"], "role": role, "species": r["label"],
                         "derived": str(dst.relative_to(ROOT)),
                         "notes": f"{r['kind']} crop; label_source={r['label_source']}; "
                                  f"proposed={r['proposed']} ({r['confidence']:.2f})"})

    with open(path(cfg, "manifest"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["original", "role", "species", "derived", "notes"])
        w.writeheader()
        w.writerows(manifest)
    summary = {"videos": [str(v.relative_to(ROOT)) for v in found["video"]],
               "docs": [str(d.relative_to(ROOT)) for d in found["doc"]],
               "photos": len(photos), "crops": len(crop_rows), "per_label": counts, "held_out": held,
               "zero_shot_by_kind": {k: _vote([r for r in crop_rows if r["kind"] == k]) for k in ("dot", "circle")}}
    (ROOT / "data" / "resources_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
