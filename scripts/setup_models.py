"""One-time model download (the ONLY step that uses the internet). Skips models already in models/hf/.

Usage:  python scripts/setup_models.py        (run by the Start BlueSight launchers on first start)

To set up a computer that should never go online for this, copy the models/ folder from a computer where this has
run; nothing is downloaded when the models are already there.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["BLUESIGHT_ALLOW_DOWNLOADS"] = "1"
os.environ.setdefault("HF_HOME", str(ROOT / "models" / "hf"))
sys.path.insert(0, str(ROOT / "src"))


def have(repo: str) -> bool:
    hub = Path(os.environ["HF_HOME"]) / "hub" / ("models--" + repo.replace("/", "--"))
    if not hub.exists():
        return False
    return any(hub.rglob("*.safetensors")) or any(hub.rglob("*.bin"))


def main() -> int:
    wanted = {"imageomics/bioclip": "BioCLIP (species matching, MIT)", "facebook/dinov2-small": "DINOv2-small (fallback, Apache-2.0)"}
    for repo, what in wanted.items():
        if have(repo):
            print(f"  ok   {what} already on this computer")
            continue
        print(f"  get  {what} ...", flush=True)
        if repo == "imageomics/bioclip":
            import open_clip

            open_clip.create_model_and_transforms("hf-hub:imageomics/bioclip")
        else:
            from transformers import AutoModel

            AutoModel.from_pretrained(repo)
    print("Models ready. From now on BlueSight runs offline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
