"""One-time download of openly licensed reference photos for the expected Nova Scotia species and the watch list.

Source: iNaturalist research-grade observations (public API), photos licensed CC0, CC-BY or CC-BY-SA only, from Nova
Scotia first (place 6853), then the rest of Canada / anywhere if a species has too few. Every photo's author, licence and
observation link is written to data/reference_web/attribution.csv (committed); the images themselves are not committed.

This is a SETUP step like scripts/setup_models.py: it is the only part of BlueSight besides the model download that uses
the internet. Analysis never does.

Images go to data/reference_web/<species>/. Species in config held_out_species (European green crab) are saved under
data/reference_web_heldout/ so the demo's "unfamiliar species" test stays honest; they are only used for evaluation.

Usage: python scripts/fetch_reference_photos.py [--per-species 30]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bluesight.config import load_config  # noqa: E402

API = "https://api.inaturalist.org/v1/observations"
UA = {"User-Agent": "BlueSight-hackathon-research-tool (offline fish survey app; one-time reference download)"}
LICENCES = "cc0,cc-by,cc-by-sa"
PLACES = [("Nova Scotia", 6853), ("Canada", 6712), ("anywhere", None)]


def get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def fetch_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def observations(scientific: str, place: int | None, n: int) -> list[dict]:
    q = {"taxon_name": scientific, "quality_grade": "research", "photo_license": LICENCES, "photos": "true",
         "per_page": min(200, n * 2), "order_by": "votes"}
    if place:
        q["place_id"] = place
    return get_json(API + "?" + urllib.parse.urlencode(q)).get("results", [])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-species", type=int, default=30)
    a = ap.parse_args()
    cfg = load_config()
    held = set(cfg.get("held_out_species") or [])
    species = list(cfg.get("species_candidates") or []) + [w for w in cfg.get("watch_list") or []
                                                            if w["name"] not in {s["name"] for s in cfg.get("species_candidates") or []}]
    base, held_base = ROOT / "data" / "reference_web", ROOT / "data" / "reference_web_heldout"
    base.mkdir(parents=True, exist_ok=True)
    rows = []
    for sp in species:
        dest = (held_base if sp["name"] in held else base) / sp["name"]
        dest.mkdir(parents=True, exist_ok=True)
        got, seen = 0, set()
        for pname, pid in PLACES:
            if got >= a.per_species:
                break
            try:
                obs = observations(sp["scientific"], pid, a.per_species)
            except Exception as exc:  # network trouble: report and move on
                print(f"  {sp['name']}: query failed ({exc})")
                continue
            time.sleep(1.0)  # be polite to the public API
            for o in obs:
                if got >= a.per_species:
                    break
                if (o.get("taxon") or {}).get("name", "").lower() != sp["scientific"].lower():
                    continue  # only exact species-level identifications
                ph = next((p for p in o.get("photos", []) if (p.get("license_code") or "") in LICENCES.split(",")), None)
                if not ph or ph["id"] in seen:
                    continue
                seen.add(ph["id"])
                url = ph["url"].replace("square", "medium")
                try:
                    img = cv2.imdecode(np.frombuffer(fetch_bytes(url), np.uint8), cv2.IMREAD_COLOR)
                except Exception:
                    continue
                if img is None or min(img.shape[:2]) < 120:
                    continue
                fn = dest / f"inat_{ph['id']}.jpg"
                cv2.imwrite(str(fn), img, [cv2.IMWRITE_JPEG_QUALITY, 90])
                got += 1
                rows.append({"species": sp["name"], "file": str(fn.relative_to(ROOT)), "licence": ph["license_code"],
                             "attribution": ph.get("attribution", ""), "observation": f"https://www.inaturalist.org/observations/{o['id']}",
                             "place": pname, "held_out": sp["name"] in held})
                time.sleep(0.2)
        print(f"{sp['name']}: {got} photos")
    with open(base / "attribution.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["species"])
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} photos; attribution in {base / 'attribution.csv'}")


if __name__ == "__main__":
    main()
