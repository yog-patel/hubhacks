"""FishSpotter: a small learned point detector for tiny mid-water fish.

The motion detector misses fish that hold still and merges fish in a school into one blob. FishSpotter
learns what a fish *looks like* from the biologists' own tally dots (one dot per counted fish): a
ResNet-18 backbone (ImageNet weights, BSD-3 torchvision) with a light feature pyramid predicts a
heatmap at 1/4 resolution, and every local peak above a threshold is one fish. Boxes have a fixed
size (fish at this survey's scale are all about the same size).

It runs on the 1920-px detection frame, on CUDA / Apple MPS / CPU, and is fused with the motion
detector (``FusedDetector`` in detect.py) so large organisms such as crabs are still found by motion.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np

MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)
STRIDE = 4


def build_model(pretrained: bool = True):
    """ResNet-18 (to layer3) + 3-level top-down pyramid -> 1-channel heatmap logits at stride 4."""
    import torch
    import torch.nn as nn
    import torchvision

    class Net(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            w = torchvision.models.ResNet18_Weights.IMAGENET1K_V1 if pretrained else None
            r = torchvision.models.resnet18(weights=w)
            self.stem = nn.Sequential(r.conv1, r.bn1, r.relu, r.maxpool)
            self.l1, self.l2, self.l3 = r.layer1, r.layer2, r.layer3
            self.lat1, self.lat2, self.lat3 = nn.Conv2d(64, 64, 1), nn.Conv2d(128, 64, 1), nn.Conv2d(256, 64, 1)
            self.head = nn.Sequential(nn.Conv2d(64, 64, 3, padding=1), nn.ReLU(inplace=True),
                                      nn.Conv2d(64, 64, 3, padding=1), nn.ReLU(inplace=True), nn.Conv2d(64, 1, 1))
            nn.init.constant_(self.head[-1].bias, -4.0)  # start with "no fish anywhere" (focal-loss prior)

        def forward(self, x):
            up = nn.functional.interpolate
            c1 = self.l1(self.stem(x))
            c2 = self.l2(c1)
            c3 = self.l3(c2)
            p = self.lat3(c3)
            p = up(p, size=c2.shape[-2:], mode="nearest") + self.lat2(c2)
            p = up(p, size=c1.shape[-2:], mode="nearest") + self.lat1(c1)
            return self.head(p)

    return Net()


def to_tensor(img_bgr: np.ndarray):
    """BGR uint8 HxWx3 -> normalised 1x3xHxW float tensor (H, W padded to a multiple of 32)."""
    import torch

    h, w = img_bgr.shape[:2]
    ph, pw = (-h) % 32, (-w) % 32
    if ph or pw:
        img_bgr = cv2.copyMakeBorder(img_bgr, 0, ph, 0, pw, cv2.BORDER_REFLECT)
    x = (img_bgr[:, :, ::-1].astype(np.float32) / 255.0 - MEAN) / STD
    return torch.from_numpy(np.ascontiguousarray(x.transpose(2, 0, 1)))[None]


def peaks(heat: np.ndarray, thresh: float, min_dist: int = 2) -> np.ndarray:
    """Local maxima of a probability heatmap above ``thresh`` -> (N, 3) x, y, score in heatmap cells."""
    k = 2 * min_dist + 1
    mx = cv2.dilate(heat, np.ones((k, k), np.uint8))
    ys, xs = np.where((heat >= mx) & (heat >= thresh))
    return np.c_[xs, ys, heat[ys, xs]].astype(np.float32)


class FishSpotter:
    """Load trained weights and turn a frame into fish boxes."""

    def __init__(self, cfg: dict[str, Any], device: str = "cpu", root: Path | None = None) -> None:
        import torch

        self.torch = torch
        self.c = cfg
        self.device = device
        wpath = Path(cfg["weights"])
        if root is not None and not wpath.is_absolute():
            wpath = root / wpath
        if not wpath.exists():
            raise FileNotFoundError(f"FishSpotter weights not found: {wpath} (train with scripts/train_spotter.py)")
        self.net = build_model(pretrained=False)
        state = torch.load(wpath, map_location="cpu")
        self.net.load_state_dict(state["model"])
        self.net.to(device).eval()
        self.trained_on = state.get("trained_on", "?")
        self.version = f"fishspotter-{wpath.stem}-t{cfg['score_threshold']}"

    def heatmap(self, img_bgr: np.ndarray) -> np.ndarray:
        """Fish-probability heatmap at stride 4 (cropped to the image)."""
        with self.torch.no_grad():
            x = to_tensor(img_bgr).to(self.device)
            p = self.torch.sigmoid(self.net(x))[0, 0].float().cpu().numpy()
        h, w = img_bgr.shape[:2]
        return p[: (h + STRIDE - 1) // STRIDE, : (w + STRIDE - 1) // STRIDE]

    def detect(self, img_bgr: np.ndarray) -> np.ndarray:
        """(N, 5) boxes x1, y1, x2, y2, score in input pixels."""
        pk = peaks(self.heatmap(img_bgr), float(self.c["score_threshold"]))
        if not len(pk):
            return np.zeros((0, 5), np.float32)
        cx, cy = (pk[:, 0] + 0.5) * STRIDE, (pk[:, 1] + 0.5) * STRIDE
        bw, bh = float(self.c["box_w"]) / 2, float(self.c["box_h"]) / 2
        return np.c_[cx - bw, cy - bh, cx + bw, cy + bh, pk[:, 2]].astype(np.float32)
