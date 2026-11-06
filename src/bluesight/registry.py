"""Species registry: one prototype (mean embedding) per known species, persisted in SQLite.

Sources of reference images:
* data/reference_images/<species>/  - built from the provided photos (held-out species excluded)
* outputs/registry/<species>/       - crops approved by a biologist in the review queue

A species only ever enters the registry from the provided labelled references or from a human
approval in the app. Prototypes are rebuilt immediately; nothing is retrained.
"""
from __future__ import annotations

import datetime as dt
import re
import shutil
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np

from .config import path
from .db import DB, from_blob, to_blob
from .identify import mean_embedding
from .logs import get_logger

log = get_logger("registry")
IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}


def slugify(name: str) -> str:
    """Folder-safe species key: 'Atlantic Silverside' -> 'atlantic_silverside'."""
    s = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    if not s:
        raise ValueError("species name is empty")
    return s


def compute_prototype(embs: np.ndarray) -> np.ndarray:
    """Prototype = normalised mean of unit embeddings."""
    if len(embs) == 0:
        raise ValueError("cannot build a prototype from zero images")
    return mean_embedding(embs)


def now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


class Registry:
    """Read/write access to the species registry."""

    def __init__(self, cfg: dict[str, Any], db: DB, embedder=None) -> None:
        self.cfg = cfg
        self.db = db
        self._embedder = embedder

    @property
    def embedder(self):
        if self._embedder is None:
            from .embed import get_embedder

            self._embedder = get_embedder(self.cfg)
        return self._embedder

    # ------------------------------------------------------------- queries
    def prototypes(self) -> tuple[list[str], np.ndarray]:
        """Active species names and an (S, D) prototype matrix for the current embedder."""
        rows = self.db.q(
            "SELECT name, prototype FROM species WHERE active=1 AND prototype IS NOT NULL AND embedder=? ORDER BY name",
            (self.embedder_name(),),
        )
        if not rows:
            return [], np.zeros((0, 1), np.float32)
        return [r["name"] for r in rows], np.stack([from_blob(r["prototype"]) for r in rows])

    def embedder_name(self) -> str:
        if self._embedder is not None:
            return self._embedder.version
        e = self.cfg["embedder"]
        return e["bioclip_model"] if e.get("name") == "bioclip" else e["dinov2_model"]

    def list_species(self) -> list[dict[str, Any]]:
        return self.db.q("SELECT name, display_name, source, date_added, approved_by, n_images, active, notes "
                         "FROM species ORDER BY active DESC, name")

    def images(self, species: str) -> list[str]:
        return [r["path"] for r in self.db.q("SELECT path FROM species_images WHERE species=? ORDER BY added_at", (species,))]

    # ------------------------------------------------------------- building
    def _embed_paths(self, paths: Sequence[Path]) -> np.ndarray:
        ims = []
        for p in paths:
            im = cv2.imread(str(p))
            if im is None:
                raise IOError(f"cannot read reference image {p}")
            ims.append(im)
        return self.embedder.embed_images(ims)

    def rebuild_prototype(self, species: str) -> int:
        """Recompute one species' prototype from all its stored image embeddings. Returns n images."""
        rows = self.db.q("SELECT embedding FROM species_images WHERE species=?", (species,))
        embs = np.stack([from_blob(r["embedding"]) for r in rows]) if rows else np.zeros((0, 1))
        if len(embs) == 0:
            self.db.x("UPDATE species SET prototype=NULL, n_images=0 WHERE name=?", (species,))
            return 0
        self.db.x("UPDATE species SET prototype=?, n_images=?, embedder=? WHERE name=?",
                  (to_blob(compute_prototype(embs)), len(embs), self.embedder.version, species))
        return len(embs)

    def build_from_folders(self) -> dict[str, int]:
        """(Re)build every species from data/reference_images/ and outputs/registry/.

        Held-out species in data/reference_images are skipped (they live in data/held_out/ anyway).
        Approval metadata (who/when) of app-approved species is preserved.
        """
        held = set(self.cfg.get("held_out_species") or [])
        built: dict[str, int] = {}
        sources = [(path(self.cfg, "reference_dir"), "reference"), (path(self.cfg, "registry_dir"), "approved")]
        prev = {r["name"]: r for r in self.db.q("SELECT * FROM species")}
        with self.db.tx() as c:
            c.execute("DELETE FROM species_images")
        for root, source in sources:
            if not root.exists():
                continue
            for d in sorted(p for p in root.iterdir() if p.is_dir()):
                name = d.name
                if source == "reference" and name in held:
                    log.info("skipping held-out species %s", name)
                    continue
                imgs = sorted(p for p in d.iterdir() if p.suffix.lower() in IMG_EXTS)
                if not imgs:
                    continue
                embs = self._embed_paths(imgs)
                p0 = prev.get(name, {})
                approved_by = p0.get("approved_by") or ("Coastal Action photo annotations" if source == "reference" else "unknown")
                with self.db.tx() as c:
                    c.execute(
                        "INSERT INTO species(name, display_name, source, date_added, approved_by, n_images, embedder, active, notes) "
                        "VALUES (?,?,?,?,?,?,?,1,?) ON CONFLICT(name) DO UPDATE SET n_images=excluded.n_images, embedder=excluded.embedder",
                        (name, p0.get("display_name") or name.replace("_", " "), p0.get("source") or source,
                         p0.get("date_added") or now(), approved_by, len(imgs), self.embedder.version, p0.get("notes")),
                    )
                    for p, e in zip(imgs, embs):
                        c.execute("INSERT OR REPLACE INTO species_images(species, path, source, added_at, embedding) VALUES (?,?,?,?,?)",
                                  (name, str(p), source, now(), to_blob(e)))
                built[name] = built.get(name, 0) + len(imgs)
        for name in built:
            self.rebuild_prototype(name)
        log.info("registry built: %s", built)
        return built

    # ------------------------------------------------------------- approvals
    def add_images(self, species_name: str, crop_paths: Sequence[str | Path], approved_by: str,
                   new_species: bool, notes: str | None = None, ref_tag: str = "") -> str:
        """Add biologist-approved crops to a species (creating it if ``new_species``) and rebuild its prototype.

        Crops are copied to outputs/registry/<species>/. Returns the species key.
        """
        if not approved_by.strip():
            raise ValueError("an approver name is required")
        key = slugify(species_name)
        exists = bool(self.db.q("SELECT 1 FROM species WHERE name=?", (key,)))
        if new_species and exists:
            log.info("species %s already exists; adding images to it", key)
        if not new_species and not exists:
            raise ValueError(f"unknown species {key}")
        dest = path(self.cfg, "registry_dir") / key
        dest.mkdir(parents=True, exist_ok=True)
        copied = []
        for i, p in enumerate(crop_paths):
            target = dest / f"{ref_tag}{Path(p).stem}_{i}{Path(p).suffix}"
            shutil.copy2(p, target)
            copied.append(target)
        embs = self._embed_paths(copied)
        with self.db.tx() as c:
            if not exists:
                c.execute(
                    "INSERT INTO species(name, display_name, source, date_added, approved_by, n_images, embedder, active, notes) "
                    "VALUES (?,?,?,?,?,?,?,1,?)",
                    (key, species_name.strip(), "approved", now(), approved_by.strip(), 0, self.embedder.version, notes),
                )
            for p, e in zip(copied, embs):
                c.execute("INSERT OR REPLACE INTO species_images(species, path, source, added_at, embedding) VALUES (?,?,?,?,?)",
                          (key, str(p), f"approved by {approved_by.strip()}", now(), to_blob(e)))
        n = self.rebuild_prototype(key)
        log.info("species %s now has %d reference images (approved by %s)", key, n, approved_by)
        return key
