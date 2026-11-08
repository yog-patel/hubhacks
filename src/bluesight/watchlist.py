"""Invasive / unexpected species watch list.

The list lives in config.yaml (``watch_list``) and is edited by staff; nothing is fetched online. A registry species
matches a watch-list entry by its key, common name, scientific name or an alias (case, spaces, underscores and
hyphens ignored). The app raises a prominent alert whenever a matching species is approved in review or recognised
in an analysis.
"""
from __future__ import annotations

import re
from typing import Any


def _norm(s: str) -> str:
    return re.sub(r"[\s_\-]+", " ", str(s).strip().lower())


def entries(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Watch-list entries from config (empty list if none)."""
    return list((cfg.get("watch_list") or {}).get("species") or [])


def match(cfg: dict[str, Any], name: str | None) -> dict[str, Any] | None:
    """The watch-list entry a species name/key refers to, or None."""
    if not name:
        return None
    n = _norm(name)
    for e in entries(cfg):
        names = [e.get("key", ""), e.get("common", ""), e.get("scientific", "")] + list(e.get("aliases") or [])
        if n in {_norm(x) for x in names if x}:
            return e
    return None


def hits(cfg: dict[str, Any], db, run_id: str) -> list[dict[str, Any]]:
    """Watch-list species recognised (status known) in a run: entry, track count, first and last time seen."""
    rows = db.q("SELECT species, COUNT(*) n, MIN(start_s) first_s, MAX(end_s) last_s FROM tracks "
                "WHERE run_id=? AND status='known' AND species IS NOT NULL GROUP BY species", (run_id,))
    out = []
    for r in rows:
        e = match(cfg, r["species"])
        if e:
            out.append({"entry": e, "species": r["species"], "tracks": int(r["n"]), "first_s": float(r["first_s"]),
                        "last_s": float(r["last_s"])})
    return out
