"""Does adding openly licensed web photos (scripts/fetch_reference_photos.py) help or hurt identification on survey data?

Measured (BioCLIP, the app's embedder; thresholds from config):
1. Web photos among themselves: leave-one-out nearest-prototype species accuracy (sanity check of the photos).
2. Held-out survey crops (39: the green crab + 38 circled organisms, none in the registry): share flagged vs mislabelled
   as a known species, with and without web species in the registry. Mislabelling an unfamiliar animal is the costly error.
3. Known survey crops (T2-STAT2 21 min schooling fish; prototype from 13-14 min): still recognised as the schooling fish?
4. Survey-video tracks (protocol window + demo window): how many would be auto-labelled as a web species (>= T_KNOWN).
5. Transfer test: does the real green crab in the video match the web green-crab photos (held out from the registry)?

Writes outputs/eval/web_refs.json.  Usage: python scripts/eval_web_refs.py
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bluesight.config import load_config, path  # noqa: E402
from bluesight.embed import get_embedder  # noqa: E402
from bluesight.identify import mean_embedding  # noqa: E402


def embed_files(E, files: list[str]) -> np.ndarray:
    ims = [cv2.imread(f) for f in files]
    return E.embed_images([i for i in ims if i is not None])


def decide(best: np.ndarray, tk: float, tu: float) -> dict:
    return {"known": float((best >= tk).mean()), "uncertain": float(((best >= tu) & (best < tk)).mean()),
            "unfamiliar": float((best < tu).mean())}


def main() -> None:
    cfg = load_config()
    tk, tu = float(cfg["identify"]["T_KNOWN"]), float(cfg["identify"]["T_UNKNOWN"])
    E = get_embedder(cfg)
    web = {}
    for d in sorted(glob.glob(str(ROOT / "data" / "reference_web" / "*"))):
        fs = sorted(glob.glob(d + "/*.jpg"))
        if fs:
            web[Path(d).name] = embed_files(E, fs)
    crab_web = embed_files(E, sorted(glob.glob(str(ROOT / "data" / "reference_web_heldout" / "european_green_crab" / "*.jpg"))))
    res: dict = {"T_KNOWN": tk, "T_UNKNOWN": tu, "n_web": {k: len(v) for k, v in web.items()}}

    # 1. web LOO accuracy
    names = list(web)
    correct = total = 0
    for i, n in enumerate(names):
        for j in range(len(web[n])):
            protos = np.stack([mean_embedding(np.delete(web[m], j, 0)) if m == n else mean_embedding(web[m]) for m in names])
            correct += int(np.argmax(protos @ web[n][j]) == i)
            total += 1
    res["web_loo_accuracy"] = correct / total

    # survey crops
    lab = pd.read_csv(ROOT / "data" / "proposed_labels.csv")
    dots = lab[lab.label == "small_schooling_fish"]
    proto_files = [ROOT / c for c in dots.crop if "13min" in c or "14min" in c]
    test_files = [ROOT / c for c in dots.crop if "21min" in c]
    held_files = [ROOT / c for c in lab[lab.label.isin(cfg["held_out_species"])].crop]
    P_fish = mean_embedding(embed_files(E, [str(p) for p in proto_files]))
    K = embed_files(E, [str(p) for p in test_files])
    Hh = embed_files(E, [str(p) for p in held_files])
    web_protos = np.stack([mean_embedding(web[n]) for n in names])
    for tag, protos, pnames in [("schooling_only", P_fish[None], ["small_schooling_fish"]),
                                ("with_web", np.vstack([P_fish[None], web_protos]), ["small_schooling_fish"] + names)]:
        hs, ks = Hh @ protos.T, K @ protos.T
        res[tag] = {"held_out": decide(hs.max(1), tk, tu),
                    "held_out_top_species": pd.Series([pnames[i] for i in hs.argmax(1)]).value_counts().to_dict(),
                    "known_crops": decide(ks.max(1), tk, tu),
                    "known_crops_still_schooling_fish": float((ks.argmax(1) == 0).mean())}
    res["web_only_best_similarity_on_known_crops"] = float((K @ web_protos.T).max(1).mean())

    # 4. video tracks
    tracks = []
    for f in glob.glob(str(path(cfg, "cache_dir") / "T1_STAT2_411" / "*" / "emb_hf_hub_imageomics_bioclip.npz")):
        z = np.load(f)
        tracks += [z[k] for k in z.files]
    T = np.stack(tracks)
    tw = T @ web_protos.T
    res["video_tracks"] = {"n": len(T), "web_best_mean": float(tw.max(1).mean()),
                           "auto_labelled_as_web_species": float((tw.max(1) >= tk).mean()),
                           "uncertain_as_web_species": float(((tw.max(1) >= tu) & (tw.max(1) < tk)).mean()),
                           "top_web_species": pd.Series([names[i] for i in tw.argmax(1)]).value_counts().head(5).to_dict(),
                           "schooling_fish_best_mean": float((T @ P_fish).mean())}

    # 5. real crab vs web crab photos
    crab_dir = sorted(glob.glob(str(path(cfg, "flags_dir") / "*_1280-1355s_t353")))
    if crab_dir and len(crab_web):
        C = embed_files(E, sorted(glob.glob(crab_dir[0] + "/crop_*.jpg")))
        c = mean_embedding(C)
        allp = np.vstack([web_protos, mean_embedding(crab_web)[None], P_fish[None]])
        alln = names + ["european_green_crab (web, held out)", "small_schooling_fish"]
        sims = allp @ c
        order = np.argsort(-sims)
        res["video_crab_vs_web"] = {"similarity_to_web_green_crab": float(sims[len(names)]),
                                    "rank_of_green_crab": int(np.where(order == len(names))[0][0]) + 1,
                                    "top3": [(alln[i], round(float(sims[i]), 3)) for i in order[:3]]}
    out = path(cfg, "outputs_dir") / "eval"
    out.mkdir(parents=True, exist_ok=True)
    (out / "web_refs.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
