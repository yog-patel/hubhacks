"""Frame enhancement (CLAHE + gray-world colour correction) and a 0..1 visibility score."""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np

_CLAHE_CACHE: dict[tuple[float, int], cv2.CLAHE] = {}


def _clahe(clip: float, grid: int) -> cv2.CLAHE:
    key = (clip, grid)
    if key not in _CLAHE_CACHE:
        _CLAHE_CACHE[key] = cv2.createCLAHE(clipLimit=clip, tileGridSize=(grid, grid))
    return _CLAHE_CACHE[key]


def gray_world(img: np.ndarray) -> np.ndarray:
    """Simple underwater colour correction: scale channels so their means match (gray-world)."""
    f = img.astype(np.float32)
    means = f.reshape(-1, 3).mean(0) + 1e-6
    f *= means.mean() / means
    return np.clip(f, 0, 255).astype(np.uint8)


def enhance_frame(img: np.ndarray, cfg: dict[str, Any] | None = None) -> np.ndarray:
    """Return an enhanced copy of a BGR frame: gray-world colour correction then CLAHE on L*.

    Args:
        img: BGR uint8 frame.
        cfg: the ``enhance`` config section (defaults used if None).
    """
    cfg = cfg or {}
    out = gray_world(img) if cfg.get("white_balance", True) else img
    lab = cv2.cvtColor(out, cv2.COLOR_BGR2LAB)
    lab[:, :, 0] = _clahe(float(cfg.get("clahe_clip", 3.0)), int(cfg.get("clahe_grid", 8))).apply(lab[:, :, 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def enhanced_luminance(img: np.ndarray, cfg: dict[str, Any] | None = None) -> np.ndarray:
    """CLAHE-enhanced L* channel (uint8), the input used by the motion detector."""
    cfg = cfg or {}
    l = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)[:, :, 0]
    return _clahe(float(cfg.get("clahe_clip", 3.0)), int(cfg.get("clahe_grid", 8))).apply(l)


def _lin(x: float, lo: float, hi: float) -> float:
    return float(np.clip((x - lo) / (hi - lo), 0.0, 1.0))


def visibility_components(img: np.ndarray) -> dict[str, float]:
    """Raw visibility cues for a BGR frame (computed at 960 px width for speed).

    Returns:
        contrast: RMS contrast of luminance (0..1 scale)
        sharpness: log10 of the variance of the Laplacian
        haze: mean dark-channel value (He et al. dark channel prior; higher = hazier)
    """
    h, w = img.shape[:2]
    if w > 960:
        img = cv2.resize(img, (960, int(h * 960 / w)), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    contrast = float(gray.std())
    sharp = float(np.log10(cv2.Laplacian(gray * 255.0, cv2.CV_32F).var() + 1.0))
    dark = cv2.erode(img.min(axis=2), np.ones((15, 15), np.uint8))
    haze = float(dark.mean() / 255.0)
    return {"contrast": contrast, "sharpness": sharp, "haze": haze}


def visibility_score(img: np.ndarray, cfg: dict[str, Any] | None = None) -> float:
    """Per-frame visibility in 0..1 from contrast, sharpness and haze (1 = clear water).

    Args:
        img: BGR frame (the original, not the enhanced one).
        cfg: the ``enhance`` config section with *_range and weights.
    """
    cfg = cfg or {}
    c = visibility_components(img)
    cr = cfg.get("contrast_range", [0.02, 0.12])
    sr = cfg.get("sharpness_range", [1.5, 4.0])
    hr = cfg.get("haze_range", [0.25, 0.65])
    w = cfg.get("weights", {"contrast": 0.4, "sharpness": 0.3, "haze": 0.3})
    s = (
        w["contrast"] * _lin(c["contrast"], *cr)
        + w["sharpness"] * _lin(c["sharpness"], *sr)
        + w["haze"] * (1.0 - _lin(c["haze"], *hr))
    )
    return float(np.clip(s / sum(w.values()), 0.0, 1.0))
