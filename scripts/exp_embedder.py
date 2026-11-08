"""E11: BioCLIP vs BioCLIP 2 for identification. Dev tool; every number measured.

Same image-level sets and threshold tuning as E1/E6 (prototype = T2-STAT2 13+14 min crops; known test = 21 min crops;
held out = green crab + unconfirmed benthic organisms), plus the demo window's real crab track (t353) and the
14:01 video tracks labelled by tally points, if those caches exist. Thresholds are re-tuned per model on the
held-out photos (similarity scales differ between models).

    python scripts/exp_embedder.py
"""
from __future__ import annotations

import glob
import pickle
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bluesight.config import ROOT, load_config, resolve_device  # noqa: E402
from bluesight.embed import BioCLIPEmbedder  # noqa: E402
from bluesight.identify import mean_embedding  # noqa: E402
from experiments import image_metrics_auc, image_sets, log_result  # noqa: E402

MODELS = ["hf-hub:imageomics/bioclip", "hf-hub:imageomics/bioclip-2"]
DEMO_CACHE = "outputs/cache/T1_STAT2_411/1280-1355s_*"


def crab_track_similarity(E, proto: np.ndarray) -> dict:
    """Similarity of the demo window's crab (track 353) and of all other eligible tracks to the fish prototype."""
    dirs = sorted(glob.glob(str(ROOT / DEMO_CACHE)))
    if not dirs:
        return {}
    crops = pickle.loads((Path(dirs[0]) / "crops.pkl").read_bytes())
    sims = {}
    for t, lst in crops.items():
        if len(lst) < 3:
            continue
        ims = [cv2.imdecode(np.frombuffer(j, np.uint8), cv2.IMREAD_COLOR) for j, _ in lst]
        sims[t] = float(mean_embedding(E.embed_images(ims)) @ proto)
    others = np.array([v for k, v in sims.items() if k != 353])
    c = sims.get(353)
    return {"demo_crab_t353_similarity": None if c is None else round(c, 3),
            "demo_crab_rank_most_unfamiliar": None if c is None else int((others < c).sum()) + 1,
            "demo_tracks_compared": int(len(others) + (c is not None))}


def main() -> None:
    cfg = load_config()
    device = resolve_device(cfg)
    for mid in MODELS:
        t0 = time.time()
        E = BioCLIPEmbedder(mid, device, 32)
        load_s = time.time() - t0
        t0 = time.time()
        sims = image_sets(E)
        n = sum(len(v) for v in sims["_emb"].values())
        per_crop_ms = 1000 * (time.time() - t0) / max(1, n)
        m = image_metrics_auc(sims)
        proto = sims["_emb"]["proto"].mean(0)
        proto /= np.linalg.norm(proto)
        m.update(crab_track_similarity(E, proto))
        m.update(load_s=round(load_s, 1), ms_per_crop=round(per_crop_ms, 1),
                 params_m=round(sum(p.numel() for p in E.model.visual.parameters()) / 1e6, 1))
        log_result({"id": "E11", "variant": mid, "what": "embedder comparison (image level + demo crab track)", "metrics": m})
        del E
        import torch

        if device == "mps":
            torch.mps.empty_cache()


if __name__ == "__main__":
    main()
