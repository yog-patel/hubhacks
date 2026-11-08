"""Fish detectors behind a common streaming interface.

* ``MotionDetector`` (default): the camera is stationary, so anything that is not part of the
  per-pixel temporal median background, relative to that pixel's own temporal variability, is a
  candidate organism. Normalising by the per-pixel MAD suppresses flickering sunlight caustics on
  the sand. Elongated blobs are kept (fish shape + movement are two of the protocol's four cues).
* ``OWLv2Detector``: open-vocabulary detector (google/owlv2-base-patch16-ensemble, Apache-2.0)
  prompted with "a photo of a fish", run on tiles. Kept for comparison; it measured worse on
  this footage (see EVALUATION.md).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator

import cv2
import numpy as np

from .enhance import enhanced_luminance
from .logs import get_logger

log = get_logger("detect")


@dataclass
class Frame:
    """A sampled video frame. ``small`` is the detection-resolution copy, ``full`` the original."""

    idx: int
    t: float
    full: np.ndarray
    small: np.ndarray
    scale: float  # small / full
    visibility: float = 1.0
    extra: dict = field(default_factory=dict)


class Detector(ABC):
    """Detects organisms in a stream of frames. Boxes are (N, 5): x1, y1, x2, y2, score in ``small`` pixels."""

    name: str = "detector"
    version: str = ""

    @abstractmethod
    def detect_stream(self, frames: Iterable[Frame]) -> Iterator[tuple[Frame, np.ndarray]]:
        """Yield (frame, boxes) for every input frame, in order."""


# ------------------------------------------------------------------ motion
class MotionDetector(Detector):
    """Robust temporal-novelty detector for a stationary camera."""

    def __init__(self, cfg: dict[str, Any], enhance_cfg: dict[str, Any], device: str = "cpu") -> None:
        self.c = cfg
        self.ecfg = enhance_cfg
        self.device = device
        self.name = "motion"
        self.ctx_tol = float(cfg.get("ctx_tol_s", 1e-6))
        self.version = (
            f"motion-z{cfg['z_thresh']}-w{cfg['window_s']}-k{cfg['k']}-a{cfg['min_area']}-e{cfg['min_elongation']}"
            + (f"-ct{self.ctx_tol:g}" if self.ctx_tol > 1e-5 else "")
        )
        try:
            import torch

            self.torch = torch
        except ImportError:  # numpy fallback
            self.torch = None

    def _lum(self, small: np.ndarray) -> np.ndarray:
        b = int(self.c.get("blur", 5))
        return cv2.GaussianBlur(enhanced_luminance(small, self.ecfg), (b, b), 0)

    def _median_mad(self, stack: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        if self.torch is not None:
            t = self.torch.from_numpy(stack).to(self.device).float()
            med = t.median(dim=0).values
            mad = (t - med).abs().median(dim=0).values
            return med.cpu().numpy(), mad.cpu().numpy()
        med = np.median(stack, 0)
        return med, np.median(np.abs(stack - med), 0)

    def detect_lum(self, lum: np.ndarray, context: list[np.ndarray]) -> np.ndarray:
        """Detect in one luminance frame given background context frames (all same size)."""
        stack = np.stack(context + [lum]).astype(np.float32)
        med, mad = self._median_mad(stack)
        z = np.abs(lum.astype(np.float32) - med) / (mad * 1.4826 + float(self.c["k"]))
        m = (z > float(self.c["z_thresh"])).astype(np.uint8) * 255
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        m = cv2.dilate(m, np.ones((9, 9), np.uint8))
        n, lab, st, _ = cv2.connectedComponentsWithStats(m)
        out = []
        for i in range(1, n):
            x, y, w, h, a = st[i]
            if a < self.c["min_area"] or a > self.c["max_area"]:
                continue
            if max(w, h) / max(1, min(w, h)) < float(self.c["min_elongation"]):
                continue
            zmax = float(z[y : y + h, x : x + w][lab[y : y + h, x : x + w] == i].max())
            out.append([x, y, x + w, y + h, min(1.0, zmax / 6.0)])
        return np.array(out, np.float32).reshape(-1, 5)

    def detect_stream(self, frames: Iterable[Frame]) -> Iterator[tuple[Frame, np.ndarray]]:
        W, step = float(self.c["window_s"]), float(self.c["step_s"])
        # Frame times are rounded frame indices, so "8 s later" is 7.975 s or 8.008 s. With a 1e-6 tolerance the
        # +W frame is dropped for half the frames, so the background stack alternates between odd and even sizes
        # (and torch.median takes the LOWER middle for even sizes). ``ctx_tol_s`` keeps the stack size constant.
        tol = self.ctx_tol
        buf: deque[tuple[Frame, np.ndarray]] = deque()
        pending = 0  # index into buf of the next frame to emit

        def ctx_for(i: int) -> list[np.ndarray]:
            t0 = buf[i][0].t
            out = []
            for j, (f, lum) in enumerate(buf):
                if j == i:
                    continue
                dt = f.t - t0
                if abs(dt) <= W + tol and abs(dt / step - round(dt / step)) < 0.26 and round(dt / step) != 0:
                    out.append(lum)
            return out

        for fr in frames:
            buf.append((fr, self._lum(fr.small)))
            while pending < len(buf) and buf[-1][0].t - buf[pending][0].t >= W + (tol if tol > 1e-5 else 0.0) - 1e-6:
                f, lum = buf[pending]
                yield f, self.detect_lum(lum, ctx_for(pending))
                pending += 1
                while buf and pending > 0 and f.t - buf[0][0].t > W + (tol if tol > 1e-5 else 1e-6):
                    buf.popleft()
                    pending -= 1
        while pending < len(buf):
            f, lum = buf[pending]
            ctx = ctx_for(pending)
            yield f, (self.detect_lum(lum, ctx) if len(ctx) >= 4 else np.zeros((0, 5), np.float32))
            pending += 1


# ------------------------------------------------------------------ OWLv2
class OWLv2Detector(Detector):
    """Open-vocabulary OWLv2 run on grid tiles of each frame."""

    def __init__(self, cfg: dict[str, Any], device: str) -> None:
        import torch
        from transformers import Owlv2ForObjectDetection, Owlv2Processor

        self.torch = torch
        self.c = cfg
        self.device = device
        self.processor = Owlv2Processor.from_pretrained(cfg["model"])
        self.model = Owlv2ForObjectDetection.from_pretrained(cfg["model"]).to(device).eval()
        self.name = "owlv2"
        self.version = cfg["model"]

    def detect_image(self, img: np.ndarray) -> np.ndarray:
        """Detect in a single BGR image (tiled)."""
        from torchvision.ops import nms

        H, W = img.shape[:2]
        g = int(self.c.get("grid", 3))
        th, tw = H // g, W // g
        boxes = []
        for gy in range(g):
            for gx in range(g):
                tile = cv2.cvtColor(img[gy * th : (gy + 1) * th, gx * tw : (gx + 1) * tw], cv2.COLOR_BGR2RGB)
                inp = self.processor(text=[self.c["prompts"]], images=tile, return_tensors="pt").to(self.device)
                with self.torch.no_grad():
                    out = self.model(**inp)
                s = max(th, tw)
                r = self.processor.post_process_object_detection(
                    out, threshold=float(self.c["score_threshold"]), target_sizes=self.torch.tensor([[s, s]])
                )[0]
                for b, sc in zip(r["boxes"].cpu().numpy(), r["scores"].cpu().numpy()):
                    boxes.append([b[0] + gx * tw, b[1] + gy * th, b[2] + gx * tw, b[3] + gy * th, sc])
        if not boxes:
            return np.zeros((0, 5), np.float32)
        a = np.array(boxes, np.float32)
        keep = nms(self.torch.from_numpy(a[:, :4]), self.torch.from_numpy(a[:, 4]), 0.5).numpy()
        return a[keep]

    def detect_stream(self, frames: Iterable[Frame]) -> Iterator[tuple[Frame, np.ndarray]]:
        for fr in frames:
            yield fr, self.detect_image(fr.small)


def fuse_boxes(motion: np.ndarray, spotter: np.ndarray, cfg: dict[str, Any]) -> np.ndarray:
    """Combine motion and FishSpotter boxes for one frame.

    * Large motion boxes (area >= ``large_area``: crabs, big fish) are kept; spotter peaks inside them are dropped.
    * Small motion boxes that contain a spotter peak are replaced by the spotter boxes (splits merged schools).
    * Motion boxes with no spotter peak inside are kept (a moving fish the spotter missed).
    * All other spotter boxes are kept (fish that hold still are invisible to motion).
    """
    if not len(spotter):
        return motion
    if not len(motion):
        return spotter
    cx, cy = (spotter[:, 0] + spotter[:, 2]) / 2, (spotter[:, 1] + spotter[:, 3]) / 2
    area = (motion[:, 2] - motion[:, 0]) * (motion[:, 3] - motion[:, 1])
    inside = (cx[None] >= motion[:, :1]) & (cx[None] <= motion[:, 2:3]) & (cy[None] >= motion[:, 1:2]) & (cy[None] <= motion[:, 3:4])
    large = area >= float(cfg["large_area"])
    keep_spot = ~(inside & large[:, None]).any(0)
    keep_motion = large | ~inside.any(1)
    return np.concatenate([motion[keep_motion], spotter[keep_spot]]).astype(np.float32)


class FusedDetector(Detector):
    """Motion detector + FishSpotter on the same sampled frames, fused per frame with ``fuse_boxes``."""

    def __init__(self, cfg: dict[str, Any], device: str) -> None:
        from .config import ROOT
        from .spotter import FishSpotter
        from .enhance import enhance_frame

        self.motion = MotionDetector(cfg["detector"]["motion"], cfg["enhance"], device)
        self.spotter = FishSpotter(cfg["fishspotter"], device, ROOT)
        self.fcfg = cfg["fishspotter"]
        self.ecfg = cfg["enhance"] if cfg["fishspotter"].get("enhance_input", True) else None
        self._enh = enhance_frame
        self.name = "fused"
        self.version = f"fused[{self.motion.version}+{self.spotter.version}+L{self.fcfg['large_area']}]"

    def detect_stream(self, frames: Iterable[Frame]) -> Iterator[tuple[Frame, np.ndarray]]:
        for fr, mboxes in self.motion.detect_stream(frames):
            img = self._enh(fr.small, self.ecfg) if self.ecfg is not None else fr.small
            yield fr, fuse_boxes(mboxes, self.spotter.detect(img), self.fcfg)


def get_detector(cfg: dict[str, Any], name: str | None = None) -> Detector:
    """Build the configured detector."""
    from .config import resolve_device

    name = name or cfg["detector"]["name"]
    device = resolve_device(cfg)
    if name == "motion":
        return MotionDetector(cfg["detector"]["motion"], cfg["enhance"], device)
    if name == "fused":
        return FusedDetector(cfg, device)
    if name == "owlv2":
        return OWLv2Detector(cfg["detector"]["owlv2"], device)
    raise ValueError(f"unknown detector {name}")
