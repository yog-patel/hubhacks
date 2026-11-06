"""Image embedders behind a common interface: BioCLIP (default) with a DINOv2 fallback."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Sequence

import cv2
import numpy as np

from .logs import get_logger

log = get_logger("embed")


def _l2(x: np.ndarray) -> np.ndarray:
    return x / (np.linalg.norm(x, axis=-1, keepdims=True) + 1e-12)


class Embedder(ABC):
    """Turns image crops into L2-normalised embedding vectors."""

    name: str = "embedder"
    version: str = ""

    @abstractmethod
    def embed_images(self, images_bgr: Sequence[np.ndarray]) -> np.ndarray:
        """Embed BGR uint8 crops. Returns an (N, D) float32 array of unit vectors."""

    def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        """Embed text prompts (only for vision-language models)."""
        raise NotImplementedError(f"{self.name} has no text encoder")

    @property
    def supports_text(self) -> bool:
        return False


class BioCLIPEmbedder(Embedder):
    """BioCLIP (imageomics/bioclip, MIT licence) via open_clip, run locally."""

    def __init__(self, model_id: str, device: str, batch_size: int = 64) -> None:
        import open_clip
        import torch

        self.torch = torch
        self.device = device
        self.batch_size = batch_size
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(model_id)
        self.model = self.model.to(device).eval()
        self.tokenizer = open_clip.get_tokenizer(model_id)
        self.name = "bioclip"
        self.version = model_id

    @property
    def supports_text(self) -> bool:
        return True

    def embed_images(self, images_bgr: Sequence[np.ndarray]) -> np.ndarray:
        from PIL import Image

        out = []
        for i in range(0, len(images_bgr), self.batch_size):
            batch = [
                self.preprocess(Image.fromarray(cv2.cvtColor(im, cv2.COLOR_BGR2RGB)))
                for im in images_bgr[i : i + self.batch_size]
            ]
            with self.torch.no_grad():
                feats = self.model.encode_image(self.torch.stack(batch).to(self.device))
            out.append(feats.float().cpu().numpy())
        if not out:
            return np.zeros((0, 512), np.float32)
        return _l2(np.concatenate(out)).astype(np.float32)

    def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        with self.torch.no_grad():
            feats = self.model.encode_text(self.tokenizer(list(texts)).to(self.device))
        return _l2(feats.float().cpu().numpy()).astype(np.float32)

    def logit_scale(self) -> float:
        """The model's learned temperature, used for zero-shot softmax."""
        return float(self.model.logit_scale.exp().item())


class DINOv2Embedder(Embedder):
    """DINOv2-small (Apache-2.0) via transformers; CLS token as the embedding."""

    def __init__(self, model_id: str, device: str, batch_size: int = 64) -> None:
        import torch
        from transformers import AutoImageProcessor, AutoModel

        self.torch = torch
        self.device = device
        self.batch_size = batch_size
        self.processor = AutoImageProcessor.from_pretrained(model_id)
        self.model = AutoModel.from_pretrained(model_id).to(device).eval()
        self.name = "dinov2"
        self.version = model_id

    def embed_images(self, images_bgr: Sequence[np.ndarray]) -> np.ndarray:
        out = []
        for i in range(0, len(images_bgr), self.batch_size):
            rgb = [cv2.cvtColor(im, cv2.COLOR_BGR2RGB) for im in images_bgr[i : i + self.batch_size]]
            inp = self.processor(images=rgb, return_tensors="pt").to(self.device)
            with self.torch.no_grad():
                feats = self.model(**inp).last_hidden_state[:, 0]
            out.append(feats.float().cpu().numpy())
        if not out:
            return np.zeros((0, 384), np.float32)
        return _l2(np.concatenate(out)).astype(np.float32)


_EMBEDDER: Embedder | None = None


def get_embedder(cfg: dict[str, Any]) -> Embedder:
    """Build (once) the configured embedder, falling back to DINOv2 if BioCLIP fails to load."""
    global _EMBEDDER
    if _EMBEDDER is not None:
        return _EMBEDDER
    from .config import resolve_device

    ecfg = cfg["embedder"]
    device = resolve_device(cfg)
    if ecfg.get("name", "bioclip") == "bioclip":
        try:
            _EMBEDDER = BioCLIPEmbedder(ecfg["bioclip_model"], device, ecfg.get("batch_size", 64))
            log.info("Embedder: BioCLIP (%s) on %s", ecfg["bioclip_model"], device)
            return _EMBEDDER
        except Exception as exc:
            log.error("BioCLIP failed to load (%s); falling back to DINOv2", exc)
    _EMBEDDER = DINOv2Embedder(ecfg["dinov2_model"], device, ecfg.get("batch_size", 64))
    log.info("Embedder: DINOv2 (%s) on %s", ecfg["dinov2_model"], device)
    return _EMBEDDER
