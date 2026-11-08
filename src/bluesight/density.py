"""Fish counting by density estimation (trained on the biologists' tally dots).

A frozen DINOv2-small backbone (Apache-2.0, already used as the fallback embedder) turns a 1920x1080 frame into a
grid of 14x14-pixel patch features; a small convolutional head (about 0.5 M parameters) predicts how many fish each
patch holds. The frame's count is the sum. Unlike the motion detector it also sees fish that hold still, and it is
trained on exactly what the protocol counts: the fish the biologists tallied.

Training data and evaluation: scripts/density_data.py, scripts/train_density.py, EVALUATION.md (v4).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch
from torch import nn

PATCH = 14
TILE = 518   # 37 patches
STRIDE = 448  # 32 patches
MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)


class Head(nn.Module):
    """Patch features (B, C, h, w) -> non-negative fish density per patch (B, 1, h, w)."""

    def __init__(self, c_in: int = 384, width: int = 128) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv2d(c_in, width, 3, padding=1), nn.GELU(),
            nn.Conv2d(width, width // 2, 3, padding=1), nn.GELU(),
            nn.Conv2d(width // 2, 1, 1))

    def forward(self, f: torch.Tensor) -> torch.Tensor:
        return nn.functional.softplus(self.net(f))


class Backbone:
    """Frozen DINOv2-small, run on overlapping tiles so any frame size works with bounded memory."""

    def __init__(self, device: str, model_name: str = "facebook/dinov2-small") -> None:
        from transformers import AutoModel

        self.device = device
        self.model = AutoModel.from_pretrained(model_name).to(device).eval()
        self.version = model_name

    @torch.no_grad()
    def features(self, bgr: np.ndarray, scale: float = 1.0) -> np.ndarray:
        """(C, H/14, W/14) float16 patch features of a BGR frame (optionally rescaled first)."""
        if scale != 1.0:
            bgr = cv2.resize(bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        rgb = (cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0 - MEAN) / STD
        H, W = rgb.shape[:2]
        hp, wp = -(-H // PATCH), -(-W // PATCH)
        pad = np.zeros((max(hp * PATCH, TILE), max(wp * PATCH, TILE), 3), np.float32)
        pad[:H, :W] = rgb
        Hp, Wp = pad.shape[:2]
        acc = np.zeros((384, Hp // PATCH, Wp // PATCH), np.float32)
        cnt = np.zeros((1, Hp // PATCH, Wp // PATCH), np.float32)
        ys = list(range(0, max(1, Hp - TILE + 1), STRIDE)) + [Hp - TILE]
        xs = list(range(0, max(1, Wp - TILE + 1), STRIDE)) + [Wp - TILE]
        tiles, where = [], []
        for y in sorted(set(ys)):
            for x in sorted(set(xs)):
                tiles.append(pad[y:y + TILE, x:x + TILE].transpose(2, 0, 1))
                where.append((y // PATCH, x // PATCH))
        n = TILE // PATCH
        for i in range(0, len(tiles), 8):
            batch = torch.from_numpy(np.stack(tiles[i:i + 8])).to(self.device)
            out = self.model(pixel_values=batch).last_hidden_state[:, 1:, :]  # drop CLS
            out = out.reshape(len(batch), n, n, -1).permute(0, 3, 1, 2).float().cpu().numpy()
            for f, (py, px) in zip(out, where[i:i + 8]):
                acc[:, py:py + n, px:px + n] += f
                cnt[:, py:py + n, px:px + n] += 1
        return (acc / np.maximum(cnt, 1))[:, :hp, :wp].astype(np.float16)


def dot_map(points: np.ndarray, shape_hw: tuple[int, int], scale: float = 1.0) -> np.ndarray:
    """Count of dots per patch cell (sums to the number of dots)."""
    hp, wp = shape_hw
    m = np.zeros((hp, wp), np.float32)
    for x, y in np.asarray(points, np.float32).reshape(-1, 2) * scale:
        r, c = int(y // PATCH), int(x // PATCH)
        if 0 <= r < hp and 0 <= c < wp:
            m[r, c] += 1
    return m


class DensityCounter:
    """Load a trained head and count fish in frames."""

    def __init__(self, weights: str | Path, device: str) -> None:
        ck = torch.load(weights, map_location="cpu", weights_only=False)
        self.cfg: dict[str, Any] = ck["cfg"]
        self.loo = ck.get("loo")
        self.heads = []
        for st in ck.get("states") or [ck["state"]]:  # an ensemble of seeds (averaged), as evaluated
            h = Head(c_in=self.cfg.get("c_in", 384), width=self.cfg.get("width", 128))
            h.load_state_dict(st)
            self.heads.append(h.to(device).eval())
        self.device = device
        self.mu, self.sd = ck["mu"], ck["sd"]
        self.backbone = Backbone(device)
        self.version = f"density-dinov2s-{ck.get('tag', 'v1')}"

    @torch.no_grad()
    def density(self, bgr_1920: np.ndarray, zmap: np.ndarray | None = None) -> np.ndarray:
        """Per-patch fish density (h, w) for a 1920-wide frame (zmap: motion_zmap of it, if the model uses motion)."""
        if self.cfg.get("variant") == "clahe":
            from .enhance import enhance_frame
            from .config import load_config

            bgr_1920 = enhance_frame(bgr_1920, load_config()["enhance"])
        f = self.backbone.features(bgr_1920, self.cfg.get("scale", 1.0)).astype(np.float32)
        if self.cfg.get("motion"):
            f = np.concatenate([f, motion_channels(zmap, f.shape[1:])])
        f = (f - self.mu[:, None, None]) / self.sd[:, None, None]
        x = torch.from_numpy(f)[None].to(self.device)
        d = torch.stack([h(x)[0, 0] for h in self.heads]).mean(0).cpu().numpy()
        return d / float(self.cfg.get("target_scale", 1.0))

    def count_at(self, video: str | Path, t_s: float, cfg: dict[str, Any]) -> tuple[float, np.ndarray]:
        """Fish count and density map for the video frame at t_s."""
        cap = cv2.VideoCapture(str(video))
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t_s * (cap.get(cv2.CAP_PROP_FPS) or 30.0))))
        ok, fr = cap.read()
        cap.release()
        if not ok:
            raise IOError(f"cannot read frame at {t_s:.2f} s")
        small = cv2.resize(fr, (1920, int(round(fr.shape[0] * 1920 / fr.shape[1]))), interpolation=cv2.INTER_AREA)
        z = motion_zmap(video, t_s, cfg) if self.cfg.get("motion") else None
        d = self.density(small, z)
        return float(d.sum()), d


def motion_zmap(video: str | Path, t_s: float, cfg: dict[str, Any], width: int = 1920,
                window_s: float = 8.0, step_s: float = 1.0) -> np.ndarray | None:
    """Robust temporal z-score of the frame at t_s against the per-pixel median of frames t +/- window (1 s steps).

    The same signal the motion detector thresholds; here it is kept continuous and given to the counter as extra input,
    because faint fish are often only recognisable by moving (the protocol's "swimming behaviour" cue).
    """
    from .enhance import enhanced_luminance

    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    def lum_at(t: float) -> np.ndarray | None:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t * fps)))
        ok, fr = cap.read()
        if not ok:
            return None
        h = int(round(fr.shape[0] * width / fr.shape[1]))
        small = cv2.resize(fr, (width, h), interpolation=cv2.INTER_AREA)
        return cv2.GaussianBlur(enhanced_luminance(small, cfg["enhance"]), (5, 5), 0).astype(np.float32)

    cur = lum_at(t_s)
    if cur is None:
        cap.release()
        return None
    ctx = [x for d in np.arange(step_s, window_s + 1e-6, step_s) for x in (lum_at(t_s - d), lum_at(t_s + d)) if x is not None]
    cap.release()
    stack = np.stack(ctx + [cur])
    med = np.median(stack, 0)
    mad = np.median(np.abs(stack - med), 0)
    return (np.abs(cur - med) / (mad * 1.4826 + float(cfg["detector"]["motion"]["k"]))).astype(np.float16)


def motion_channels(z: np.ndarray | None, grid_hw: tuple[int, int]) -> np.ndarray:
    """3 motion channels per patch (mean log-z, max log-z, share of pixels above z 2.5) + an 'available' flag."""
    hp, wp = grid_hw
    if z is None:
        return np.zeros((4, hp, wp), np.float32)
    z = z.astype(np.float32)
    H, W = hp * (z.shape[0] // hp), wp * (z.shape[1] // wp)
    zz = cv2.resize(z, (wp * 8, hp * 8), interpolation=cv2.INTER_AREA if z.shape[1] > wp * 8 else cv2.INTER_LINEAR)
    blocks = np.log1p(zz).reshape(hp, 8, wp, 8)
    hi = (zz > 2.5).astype(np.float32).reshape(hp, 8, wp, 8)
    return np.stack([blocks.mean((1, 3)), blocks.max((1, 3)), hi.mean((1, 3)), np.ones((hp, wp), np.float32)])
