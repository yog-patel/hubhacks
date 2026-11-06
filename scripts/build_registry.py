"""Build the species registry (prototypes) from data/reference_images/ and outputs/registry/.

Held-out species are excluded. Usage: python scripts/build_registry.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bluesight.config import load_config, path  # noqa: E402
from bluesight.db import DB  # noqa: E402
from bluesight.registry import Registry  # noqa: E402

if __name__ == "__main__":
    cfg = load_config()
    reg = Registry(cfg, DB(path(cfg, "db_path")))
    built = reg.build_from_folders()
    print("registry:", built)
    print("held out (excluded):", cfg.get("held_out_species"))
