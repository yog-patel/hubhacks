"""Configuration loading. All paths, thresholds and model names come from config.yaml."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config.yaml"


def load_config(path: str | os.PathLike | None = None) -> dict[str, Any]:
    """Load config.yaml and make sure offline model-cache env vars are set.

    Args:
        path: optional override of the config file location.

    Returns:
        The parsed configuration dictionary.
    """
    p = Path(path) if path else CONFIG_PATH
    with open(p, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    cfg["_root"] = str(ROOT)
    cfg["_config_path"] = str(p)
    os.environ.setdefault("HF_HOME", str(ROOT / cfg["paths"]["model_cache_dir"]))
    if cfg.get("runtime", {}).get("offline", True) and os.environ.get("BLUESIGHT_ALLOW_DOWNLOADS") != "1":
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
    return cfg


def path(cfg: dict[str, Any], key: str) -> Path:
    """Resolve a configured path (``cfg['paths'][key]``) against the project root."""
    return Path(cfg["_root"]) / cfg["paths"][key]


def save_identify_thresholds(updates: dict[str, float], path_: str | os.PathLike | None = None) -> None:
    """Rewrite threshold values in the identify section of config.yaml, keeping comments.

    Args:
        updates: mapping such as {"T_KNOWN": 0.8}.
        path_: config file to edit (defaults to the project config).
    """
    p = Path(path_) if path_ else CONFIG_PATH
    lines = p.read_text(encoding="utf-8").splitlines()
    in_identify = False
    for i, line in enumerate(lines):
        if line.startswith("identify:"):
            in_identify = True
            continue
        if in_identify and line and not line.startswith(" "):
            in_identify = False
        if in_identify:
            stripped = line.strip()
            for key, val in updates.items():
                if stripped.startswith(f"{key}:"):
                    indent = line[: len(line) - len(line.lstrip())]
                    comment = ""
                    if "#" in line:
                        comment = "  #" + line.split("#", 1)[1]
                    lines[i] = f"{indent}{key}: {val}{comment}"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def resolve_device(cfg: dict[str, Any]) -> str:
    """Pick the compute device: CUDA, Apple MPS, or CPU."""
    import torch

    want = cfg.get("runtime", {}).get("device", "auto")
    if want != "auto":
        return want
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"
