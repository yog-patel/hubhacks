"""BlueSight AI: see more, disturb less, protect better.

Importing this package switches every model library to offline mode BEFORE any of them is imported.
``huggingface_hub`` reads these variables once, at import time, so setting them later (for example in
``load_config()``) is too late if anything imported it first. Set ``BLUESIGHT_ALLOW_DOWNLOADS=1`` only for the
one-time model download.
"""
import os as _os
from pathlib import Path as _Path

__version__ = "0.2.0"

_ROOT = _Path(__file__).resolve().parents[2]
_os.environ.setdefault("HF_HOME", str(_ROOT / "models" / "hf"))
_os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
_os.environ["DO_NOT_TRACK"] = "1"
_os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
if _os.environ.get("BLUESIGHT_ALLOW_DOWNLOADS") != "1":
    _os.environ["HF_HUB_OFFLINE"] = "1"
    _os.environ["TRANSFORMERS_OFFLINE"] = "1"
