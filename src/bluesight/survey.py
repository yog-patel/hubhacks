"""Survey details, the species watch list and protocol visibility categories.

* Survey details (water temperature, observer, pole reading, juveniles, notes) are typed in by staff and stored per
  analysis in SQLite. Nothing is fetched from the internet.
* The watch list holds invasive, range-expanding or otherwise unexpected species. It is seeded from config.yaml and
  edited in the app. A watch-list species in a survey raises an alert; so does a species outside its usual water
  temperature range (when staff have entered both the range and the survey temperature), and any approved species
  that is not on the expected Nova Scotia species list at all.
* The protocol records horizontal visibility in four categories read off the 2 m visibility pole. BlueSight's 0-1
  score measures image clarity (how hard fish are to spot), NOT distance: in T1-STAT2 the whole pole is visible even at
  a score of 0.27 (DECISIONS.md D25). So the pole category is entered by staff, and the score is reported as a clarity
  word next to it.
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Any

from .db import DB

SURVEY_SCHEMA = """
CREATE TABLE IF NOT EXISTS surveys (
    run_id TEXT PRIMARY KEY, site TEXT, date TEXT, water_temp_c REAL, observer TEXT, pole_visibility TEXT,
    juveniles INTEGER, notes TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS watch_list (
    name TEXT PRIMARY KEY, common TEXT, scientific TEXT, grp TEXT, reason TEXT,
    temp_min_c REAL, temp_max_c REAL, active INTEGER DEFAULT 1, updated_by TEXT, updated_at TEXT
);
"""
POLE_CHOICES = ["Not recorded", "<0.5 m", "0.5–1.0 m", "1.0–1.5 m", ">1.5 m"]


def ensure(db: DB) -> None:
    """Create the survey and watch-list tables if they do not exist."""
    db.conn.executescript(SURVEY_SCHEMA)
    db.conn.commit()


def now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


# ------------------------------------------------------------------------------------------ visibility
def clarity_word(score: float, cfg: dict[str, Any]) -> str:
    """Plain word for the image-clarity score: 'too murky to identify', 'fair' or 'good'."""
    v_min = float(cfg["identify"]["V_MIN"])
    if score < v_min:
        return "too murky to identify"
    return "fair" if score < v_min + 0.15 else "good"


# ------------------------------------------------------------------------------------------ survey details
def get_survey(db: DB, run_id: str) -> dict[str, Any]:
    """Saved survey details for an analysis ({} if none)."""
    ensure(db)
    rows = db.q("SELECT * FROM surveys WHERE run_id=?", (run_id,))
    return rows[0] if rows else {}


def save_survey(db: DB, run_id: str, **fields: Any) -> None:
    """Insert or update survey details for an analysis."""
    ensure(db)
    cur = get_survey(db, run_id)
    cur.update({k: v for k, v in fields.items()})
    cols = ["site", "date", "water_temp_c", "observer", "pole_visibility", "juveniles", "notes"]
    db.x("INSERT OR REPLACE INTO surveys(run_id, " + ", ".join(cols) + ", updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
         (run_id, *[cur.get(c) for c in cols], now()))


# ------------------------------------------------------------------------------------------ species lists
def expected_species(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """The expected Nova Scotia nearshore species list (config species_candidates)."""
    return list(cfg.get("species_candidates") or [])


def watch_list(db: DB, cfg: dict[str, Any], include_inactive: bool = False) -> list[dict[str, Any]]:
    """Watch-list species: config seed entries, overridden or extended by edits made in the app."""
    ensure(db)
    seeded = {w["name"]: w for w in (cfg.get("watch_list") or [])}
    for name, w in seeded.items():
        if not db.q("SELECT 1 FROM watch_list WHERE name=?", (name,)):
            rng = w.get("temp_range_c") or [None, None]
            db.x("INSERT INTO watch_list(name, common, scientific, grp, reason, temp_min_c, temp_max_c, active, updated_by,"
                 " updated_at) VALUES (?,?,?,?,?,?,?,1,'config.yaml',?)",
                 (name, w.get("common"), w.get("scientific"), w.get("group", "fish"), w.get("reason", ""),
                  rng[0], rng[1], now()))
    rows = db.q("SELECT * FROM watch_list" + ("" if include_inactive else " WHERE active=1") + " ORDER BY common")
    return rows


def save_watch(db: DB, name: str, common: str, scientific: str, grp: str, reason: str,
               tmin: float | None, tmax: float | None, active: bool, who: str) -> None:
    """Add or edit a watch-list entry (made in the app by a named person)."""
    ensure(db)
    db.x("INSERT OR REPLACE INTO watch_list(name, common, scientific, grp, reason, temp_min_c, temp_max_c, active, updated_by,"
         " updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
         (name, common, scientific, grp, reason, tmin, tmax, int(active), who, now()))


def slug_name(name: str) -> str:
    """Registry key for a typed name ('European green crab' -> 'european_green_crab')."""
    import re

    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def display_name(name: str, cfg: dict[str, Any]) -> str:
    """Common name for a registry key, from the species lists, else the key made readable."""
    for s in expected_species(cfg) + list(cfg.get("watch_list") or []):
        if s["name"] == name:
            return s.get("common") or name.replace("_", " ")
    return name.replace("_", " ")


def species_choices(db: DB, cfg: dict[str, Any]) -> list[str]:
    """Names a reviewer can pick when naming an animal: registry, expected list and watch list (common names)."""
    names = [display_name(r["name"], cfg) for r in db.q("SELECT name FROM species WHERE active=1")]
    names += [s.get("common") or s["name"] for s in expected_species(cfg)]
    names += [w["common"] or w["name"] for w in watch_list(db, cfg)]
    out: list[str] = []
    for n in names:
        n = n[:1].upper() + n[1:]
        if n.lower() not in {o.lower() for o in out}:
            out.append(n)
    return sorted(out, key=str.lower)


def alerts(report: dict[str, Any], db: DB, cfg: dict[str, Any], survey: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Watch-list, temperature-range and not-on-the-list alerts for one analysis.

    Only species actually counted (known, or confirmed by a reviewer) raise alerts; flagged-but-unreviewed items
    are already in the review queue.
    """
    survey = survey or {}
    seen = {r["label"]: r for r in report.get("species", []) if r.get("n_tracks", 0) > 0 or r.get("MaxN", 0) > 0}
    seen = {k: v for k, v in seen.items() if not k.startswith(("Unconfirmed", "Unknown", "Unfamiliar"))}
    approved = db.q("SELECT DISTINCT review_species FROM flags WHERE run_id=? AND review_species IS NOT NULL",
                    (report["run_id"],))
    for a in approved:
        seen.setdefault(a["review_species"], {"label": a["review_species"], "MaxN": None})
    watch = {w["name"]: w for w in watch_list(db, cfg)}
    expected = {s["name"] for s in expected_species(cfg)} | set(watch) | set(cfg.get("expected_extra") or [])
    temp = survey.get("water_temp_c")
    out = []
    for name in seen:
        nice = display_name(name, cfg)
        if name in watch:
            w = watch[name]
            out.append({"level": "watch", "species": name, "title": f"Watch-list species recorded: {nice}",
                        "body": w.get("reason") or "On Coastal Action's watch list."})
            lo, hi = w.get("temp_min_c"), w.get("temp_max_c")
            if temp is not None and ((lo is not None and temp < lo) or (hi is not None and temp > hi)):
                out.append({"level": "range", "species": name, "title": f"{nice} outside its usual temperature range",
                            "body": f"Water temperature {temp:g} °C; usual range {lo if lo is not None else '?'}–"
                                    f"{hi if hi is not None else '?'} °C (watch list)."})
        elif name not in expected:
            out.append({"level": "new", "species": name, "title": f"Not on the expected species list: {nice}",
                        "body": "A reviewer confirmed this animal, but it is not on the Nova Scotia species list in "
                                "config.yaml. It could be a new arrival worth reporting, or the list may need updating."})
    return out


def as_json(o: Any) -> str:
    return json.dumps(o, default=str)
