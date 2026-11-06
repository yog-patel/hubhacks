"""Logging to outputs/logs/ so nothing fails silently."""
from __future__ import annotations

import logging
from pathlib import Path

_CONFIGURED = False


def get_logger(name: str = "bluesight", logs_dir: str | Path | None = None) -> logging.Logger:
    """Return a logger that writes to stderr and outputs/logs/bluesight.log."""
    global _CONFIGURED
    logger = logging.getLogger("bluesight")
    if not _CONFIGURED:
        from .config import ROOT

        d = Path(logs_dir) if logs_dir else ROOT / "outputs" / "logs"
        d.mkdir(parents=True, exist_ok=True)
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        fh = logging.FileHandler(d / "bluesight.log", encoding="utf-8")
        fh.setFormatter(fmt)
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        logger.addHandler(fh)
        logger.addHandler(sh)
        logger.setLevel(logging.INFO)
        _CONFIGURED = True
    return logger.getChild(name) if name != "bluesight" else logger
