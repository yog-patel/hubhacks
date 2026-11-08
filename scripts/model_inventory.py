"""Inventory of every model AquaLens can use: name, version (revision), source, licence, local path, size, SHA-256.

    python scripts/model_inventory.py      # -> outputs/model_inventory.json (+ prints a markdown table)

Reads only local files under models/ (no network). Licences are those published on each model card.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bluesight.config import ROOT, load_config, path  # noqa: E402

KNOWN = {
    "imageomics/bioclip": {"role": "Species embedder (default)", "licence": "MIT", "loaded_by": "open_clip_torch",
                           "runs_on": "GPU (MPS/CUDA) or CPU"},
    "google/owlv2-base-patch16-ensemble": {"role": "Open-vocabulary detector (optional, not default)", "licence": "Apache-2.0",
                                           "loaded_by": "transformers", "runs_on": "GPU (MPS/CUDA) or CPU"},
    "google/owlv2-large-patch14-ensemble": {"role": "Open-vocabulary detector, large (experiment only)", "licence": "Apache-2.0",
                                            "loaded_by": "transformers", "runs_on": "GPU (MPS/CUDA) or CPU"},
    "facebook/dinov2-small": {"role": "Embedder fallback (if BioCLIP fails)", "licence": "Apache-2.0",
                              "loaded_by": "transformers", "runs_on": "GPU (MPS/CUDA) or CPU"},
}
WEIGHT_EXT = {".safetensors", ".bin", ".pt", ".pth", ".ckpt"}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    cfg = load_config()
    hub = path(cfg, "model_cache_dir") / "hub"
    in_use = {cfg["embedder"]["bioclip_model"].replace("hf-hub:", ""): cfg["embedder"]["name"] == "bioclip",
              cfg["embedder"]["dinov2_model"]: cfg["embedder"]["name"] == "dinov2",
              cfg["detector"]["owlv2"]["model"]: cfg["detector"]["name"] == "owlv2"}
    models = []
    for d in sorted(hub.glob("models--*")):
        mid = d.name[len("models--"):].replace("--", "/")
        rev = (d / "refs" / "main").read_text().strip() if (d / "refs" / "main").exists() else "?"
        snap = d / "snapshots" / rev
        files = sorted(p for p in snap.rglob("*") if p.is_file() or p.is_symlink())
        size = sum(p.stat().st_size for p in (d / "blobs").glob("*"))
        weights = [p for p in files if p.suffix in WEIGHT_EXT]
        main = max(weights, key=lambda p: p.stat().st_size) if weights else None
        k = KNOWN.get(mid, {"role": "unknown", "licence": "check model card", "loaded_by": "?", "runs_on": "?"})
        models.append({
            "name": mid, "role": k["role"], "version": f"revision {rev[:12]}", "revision": rev,
            "source": f"https://huggingface.co/{mid} (downloaded once)", "licence": k["licence"], "loaded_by": k["loaded_by"],
            "runs_on": k["runs_on"], "in_use": bool(in_use.get(mid, False)),
            "local_path": str(snap.relative_to(ROOT)), "size_mb": round(size / 1e6, 1),
            "weights_file": main.name if main else None, "sha256": sha256(main.resolve()) if main else "",
            "all_weight_files": [{"file": p.name, "sha256": sha256(p.resolve()), "mb": round(p.stat().st_size / 1e6, 1)} for p in weights],
        })
        print(f"hashed {mid}")
    algos = [
        {"name": "AquaLens motion detector", "role": "Fish detector (default)", "version": cfg["detector"]["motion"] and
         f"z={cfg['detector']['motion']['z_thresh']}, window ±{cfg['detector']['motion']['window_s']} s",
         "licence": "project code", "loaded_by": "bluesight.detect (OpenCV + PyTorch median)", "runs_on": "GPU (MPS/CUDA) or CPU",
         "local_path": "src/bluesight/detect.py", "weights": "none (no neural network)"},
        {"name": "ByteTrack", "role": "Tracker", "version": "supervision 0.26.1", "licence": "MIT", "loaded_by": "supervision",
         "runs_on": "CPU", "local_path": ".venv (supervision package)", "weights": "none (algorithm)"},
    ]
    out = {"generated_at": dt.datetime.now().isoformat(timespec="seconds"), "models": models, "algorithms": algos}
    f = ROOT / "outputs" / "model_inventory.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out, indent=1))
    print("| Model | Role | In use | Version | Licence | Loaded by | Local path | Size | SHA-256 (main weights) |")
    print("|---|---|---|---|---|---|---|---|---|")
    for m in models:
        print(f"| `{m['name']}` | {m['role']} | {'yes' if m['in_use'] else 'no'} | {m['version']} | {m['licence']} | {m['loaded_by']} | "
              f"`{m['local_path']}` | {m['size_mb']} MB | `{m['weights_file']}` `{m['sha256']}` |")


if __name__ == "__main__":
    main()
