"""registry: prototypes, held-out exclusion, approval adds a species immediately (fake embedder)."""
import copy

import cv2
import numpy as np
import pytest

from bluesight.db import DB
from bluesight.registry import Registry, compute_prototype, slugify


class FakeEmbedder:
    """Embeds an image as the unit vector of its mean colour (B, G, R) + a constant."""

    name = "fake"
    version = "fake-v1"

    def embed_images(self, ims):
        out = np.array([[*im.reshape(-1, 3).mean(0), 1.0] for im in ims], np.float32)
        return out / np.linalg.norm(out, axis=1, keepdims=True)


def write(p, colour):
    p.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(p), np.full((20, 20, 3), colour, np.uint8))


@pytest.fixture
def setup(tmp_path):
    cfg = {"_root": str(tmp_path), "paths": {"reference_dir": "ref", "registry_dir": "reg"},
           "held_out_species": ["mystery_fish"], "embedder": {"name": "fake", "bioclip_model": "fake-v1"}}
    for i in range(3):
        write(tmp_path / "ref" / "blue_fish" / f"{i}.png", (200, 10, 10))
        write(tmp_path / "ref" / "red_crab" / f"{i}.png", (10, 10, 200))
        write(tmp_path / "ref" / "mystery_fish" / f"{i}.png", (10, 200, 10))
    db = DB(tmp_path / "t.db")
    reg = Registry(cfg, db, FakeEmbedder())
    return cfg, db, reg, tmp_path


def test_prototype_is_normalised_mean():
    e = np.array([[1, 0], [0, 1]], np.float32)
    p = compute_prototype(e)
    assert np.allclose(p, [0.70710677, 0.70710677])
    with pytest.raises(ValueError):
        compute_prototype(np.zeros((0, 2)))


def test_build_excludes_held_out(setup):
    cfg, db, reg, _ = setup
    built = reg.build_from_folders()
    assert built == {"blue_fish": 3, "red_crab": 3}
    names, P = reg.prototypes()
    assert names == ["blue_fish", "red_crab"]
    assert np.allclose(np.linalg.norm(P, axis=1), 1.0)


def test_approval_adds_species_and_rebuilds_prototype(setup):
    cfg, db, reg, tmp = setup
    reg.build_from_folders()
    crops = [tmp / "flag" / f"crop_{i}.jpg" for i in range(2)]
    for c in crops:
        write(c, (10, 200, 10))
    key = reg.add_images("Mystery Fish", crops, approved_by="Dr. Reviewer", new_species=True)
    assert key == "mystery_fish"
    names, P = reg.prototypes()
    assert "mystery_fish" in names
    row = [s for s in reg.list_species() if s["name"] == "mystery_fish"][0]
    assert row["approved_by"] == "Dr. Reviewer" and row["n_images"] == 2 and row["source"] == "approved"
    assert (tmp / "reg" / "mystery_fish").is_dir() and len(list((tmp / "reg" / "mystery_fish").iterdir())) == 2
    # the new prototype now matches a green crop best
    g = FakeEmbedder().embed_images([np.full((5, 5, 3), (10, 200, 10), np.uint8)])[0]
    assert names[int(np.argmax(P @ g))] == "mystery_fish"


def test_adding_to_existing_species_updates_prototype(setup):
    cfg, db, reg, tmp = setup
    reg.build_from_folders()
    before = dict(zip(*reg.prototypes()))["blue_fish"].copy()
    c = tmp / "x" / "c.jpg"
    write(c, (255, 255, 255))
    reg.add_images("blue_fish", [c], approved_by="R", new_species=False)
    after = dict(zip(*reg.prototypes()))["blue_fish"]
    assert not np.allclose(before, after)
    assert [s for s in reg.list_species() if s["name"] == "blue_fish"][0]["n_images"] == 4


def test_approval_requires_a_name_and_known_target(setup):
    cfg, db, reg, tmp = setup
    reg.build_from_folders()
    with pytest.raises(ValueError):
        reg.add_images("x", [], approved_by="  ", new_species=True)
    with pytest.raises(ValueError):
        reg.add_images("not_there", [], approved_by="R", new_species=False)
    assert slugify(" Atlantic  Silverside ") == "atlantic_silverside"
