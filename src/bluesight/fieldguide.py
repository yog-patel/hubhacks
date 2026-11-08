"""Field guide: openly licensed reference photos of the expected Nova Scotia species and the watch list.

The photos (scripts/fetch_reference_photos.py, iNaturalist CC0 / CC-BY / CC-BY-SA, credited in
data/reference_web/attribution.csv) are a VISUAL AID for reviewers only. They are never used to label or count anything:
measured on the survey video, the real European green crab's closest web species was "blue crab" (0.85, above the
auto-label threshold) and the web green-crab photos ranked 12th (EVALUATION.md v5), so photos of fish held in a hand do
not transfer to murky video.
"""
from __future__ import annotations

import csv
import glob
from pathlib import Path
from typing import Any

import numpy as np

from .identify import mean_embedding


def photos(root: str | Path) -> dict[str, list[dict[str, str]]]:
    """species -> list of {file, licence, attribution, observation} (only files present on this computer)."""
    f = Path(root) / "data" / "reference_web" / "attribution.csv"
    out: dict[str, list[dict[str, str]]] = {}
    if not f.exists():
        return out
    with open(f, newline="") as fh:
        for r in csv.DictReader(fh):
            p = Path(root) / r["file"]
            if p.exists():
                out.setdefault(r["species"], []).append({**r, "path": str(p)})
    return out


def prototypes(root: str | Path, embedder, cache_dir: str | Path) -> tuple[list[str], np.ndarray]:
    """Mean BioCLIP embedding per field-guide species (cached in outputs/cache/fieldguide_<embedder>.npz)."""
    import cv2

    ph = photos(root)
    names = sorted(ph)
    key = Path(cache_dir) / f"fieldguide_{embedder.version.replace('/', '_').replace(':', '_')}.npz"
    sig = "|".join(f"{n}:{len(ph[n])}" for n in names)
    if key.exists():
        z = np.load(key, allow_pickle=True)
        if str(z["sig"]) == sig:
            return list(z["names"]), z["protos"]
    protos = []
    for n in names:
        ims = [cv2.imread(r["path"]) for r in ph[n]]
        protos.append(mean_embedding(embedder.embed_images([i for i in ims if i is not None])))
    P = np.stack(protos) if protos else np.zeros((0, 1), np.float32)
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    np.savez(key, names=np.array(names), protos=P, sig=sig)
    return names, P


def lookalikes(emb: np.ndarray | None, names: list[str], protos: np.ndarray, k: int = 3) -> list[dict[str, Any]]:
    """The k field-guide species whose photos look most like an embedding (for display only)."""
    if emb is None or not len(names):
        return []
    s = protos @ np.asarray(emb, np.float32)
    return [{"species": names[i], "similarity": float(s[i])} for i in np.argsort(-s)[:k]]
