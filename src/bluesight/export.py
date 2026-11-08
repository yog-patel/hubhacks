"""Excel workbook in Coastal Action's video-analysis layout (openpyxl, MIT).

Sheets:
* Subsamples - one row per 60-second subsample, with the protocol's columns: Total Fish Count, Invertebrate count,
  Total species observed, one column per species, "Unknown/Unable to ID due to visibility", image clarity and Notes. When a person checked a subsample in the app, their count is used and marked.
* Summary    - video ID, site, date, analysis window, MeanCount (AI and checked), MaxN, species richness, visibility,
  water temperature, juveniles, QC agreement, alerts, models and runtime.
* Species    - MaxN, MeanCount, confidence and tracks per species or category.
"""
from __future__ import annotations

import io
from typing import Any

from . import count as CNT
from .survey import display_name, clarity_word

NON_SPECIES = ("total_fish_count", "invertebrate_count", "subsample_t_s", "time", "visibility", "frame_t_s",
               "frame_idx", "density_count", "estimates_disagree")


def _species_cols(report: dict[str, Any]) -> list[str]:
    cols: list[str] = []
    for s in report.get("subsamples", []):
        for k in s:
            if k not in NON_SPECIES and k not in cols:
                cols.append(k)
    order = lambda c: (c == CNT.UNKNOWN_LABEL, c == CNT.UNFAMILIAR_LABEL, c.startswith("Unconfirmed"), c)  # noqa: E731
    return sorted(cols, key=order)


def _col_title(c: str, cfg: dict[str, Any]) -> str:
    if c in (CNT.UNKNOWN_LABEL, CNT.UNFAMILIAR_LABEL):
        return c
    if c.startswith("Unconfirmed: probably "):
        return "Unconfirmed: probably " + display_name(c.split("probably ", 1)[1].rstrip("?"), cfg) + "?"
    return display_name(c, cfg).capitalize()


def workbook_bytes(report: dict[str, Any], cfg: dict[str, Any], survey: dict[str, Any] | None = None,
                   checks: list[dict[str, Any]] | None = None, check_summary: dict[str, Any] | None = None,
                   alerts: list[dict[str, Any]] | None = None) -> bytes:
    """Build the .xlsx file for one analysis and return its bytes."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    survey, checks, alerts = survey or {}, checks or [], alerts or []
    invert = set(cfg.get("invertebrate_species") or [])
    by_sub = {}
    for r in checks:
        k = round(r["subsample_t_s"], 3)
        if k not in by_sub or r["mode"] == "assisted":
            by_sub[k] = r
    wb = Workbook()
    head = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor="1F4E79")
    wrap = Alignment(wrap_text=True, vertical="top")

    # ---------------------------------------------------------------- Subsamples
    ws = wb.active
    ws.title = "Subsamples"
    sp = _species_cols(report)
    named = [c for c in sp if c not in (CNT.UNKNOWN_LABEL, CNT.UNFAMILIAR_LABEL) and not c.startswith("Unconfirmed")]
    headers = (["Video ID", "Site", "Date", "Sub-sample #", "Video time", "Image clarity",
                "Clarity score (0-1)", "Total Fish Count", "Invertebrate count", "Total species observed"]
               + [_col_title(c, cfg) for c in sp] + ["Counting-model estimate", "Counted by", "Notes"])
    ws.append(headers)
    for i, s in enumerate(report.get("subsamples", []), start=1):
        chk = by_sub.get(round(s["subsample_t_s"], 3))
        fish = chk["human_fish"] if chk else s["total_fish_count"]
        inv = chk["human_invert"] if chk else s.get("invertebrate_count", 0)
        n_species = sum(1 for c in named if s.get(c, 0) > 0)
        note = []
        if chk:
            note.append(f"{chk['mode']} check by {chk['reviewer'] or 'reviewer'}: AI counted {chk['ai_fish']} fish")
            if chk.get("notes"):
                note.append(chk["notes"])
        if s.get("estimates_disagree") and not chk:
            note.append("AI estimates disagree: check this frame")
        if s.get("visibility", 1) < float(report["thresholds"]["V_MIN"]):
            note.append("low visibility: species ID not attempted")
        ws.append([report["video_file"], survey.get("site") or report["site"], survey.get("date") or report["date"], i,
                   s["time"], clarity_word(s.get("visibility", 0), cfg), s.get("visibility"), fish, inv, n_species]
                  + [s.get(c, 0) for c in sp] + [s.get("density_count")]
                  + [f"{chk['reviewer']} (checked)" if chk else "BlueSight (AI, not checked)", "; ".join(note)])

    # ---------------------------------------------------------------- Summary
    ss = wb.create_sheet("Summary")
    pw = report.get("protocol_window") or {}
    known = [r for r in report.get("species", []) if r["label"] in report.get("registry_species", []) and r["n_tracks"] > 0
             and r["label"] not in invert]
    vis = report.get("visibility", {})
    cs = check_summary or {}
    rows = [
        ("Video ID", report["video_file"]), ("Site", survey.get("site") or report["site"]),
        ("Date", survey.get("date") or report["date"]),
        ("Analysis window", f"{report['window']['start_s']:.0f}-{report['window']['end_s']:.0f} s "
                            f"({report['window']['duration_min']:.1f} min)"),
        ("Sub-samples", f"{len(report.get('subsamples', []))} (one every {report['protocol']['subsample_interval_s']} s)"),
        ("MeanCount, total fish (AI)", round(report.get("MeanCount_total_fish", 0), 2)),
        ("MeanCount, total fish (with checks)", round(cs["MeanCount_checked"], 2) if cs else "no subsamples checked"),
        ("MeanCount, counting model (second opinion)", (report.get("density") or {}).get("MeanCount_density", "not run")),
        ("Sub-samples checked by a person", f"{cs.get('n_checked', 0)} of {len(report.get('subsamples', []))}"),
        ("QC: blind-count agreement", f"{cs['blind_agreement_pct']:.0f}% over {cs['n_blind']} frames (target 95%)"
         if cs.get("blind_agreement_pct") is not None else "not done"),
        ("Protocol 15-min window MeanCount", pw.get("MeanCount_total_fish", "window not fully analysed")),
        ("MaxN (any single sampled frame)", max((s.get("total_fish_count", 0) for s in report.get("subsamples", [])), default=0)),
        ("Species richness (identified fish species)", len(known)),
        ("Species identified", ", ".join(display_name(r["label"], cfg) for r in known) or "none"),
        ("Mean clarity score (0-1)", round(vis.get("mean", 0), 2)),
        ("Image clarity (from the video)", clarity_word(vis.get("mean", 0), cfg)),
        ("Visibility from pole (staff reading)", survey.get("pole_visibility") or "not recorded"),
        ("Footage too murky to identify species", f"{100 * vis.get('fraction_below_v_min', 0):.0f}%"),
        ("Water temperature (°C)", survey.get("water_temp_c") if survey.get("water_temp_c") is not None else "not recorded"),
        ("Juveniles present (1/0)", survey.get("juveniles") if survey.get("juveniles") is not None else "not recorded"),
        ("Observer", survey.get("observer") or ""), ("Survey notes", survey.get("notes") or ""),
        ("Alerts", " | ".join(a["title"] for a in alerts) or "none"),
        ("Models", f"detector {report['models']['detector']}; embedder {report['models']['embedder']}"),
        ("Ran on", report.get("ran_on", "")), ("Runtime (s)", report.get("runtime_s")),
        ("External network connections during the run", (report.get("network") or {}).get("external_connection_attempts", "n/a")),
        ("Method", "Coastal Action DRAFT FFH Video Analysis Protocol: 15-min window, a subsample every 60 s, a fish counts "
                   "if visible within 0.5 s of the subsample point. Image clarity is measured from the video and is "
                   "not a distance; the pole reading is entered by staff."),
    ]
    for r in rows:
        ss.append(list(r))

    # ---------------------------------------------------------------- Species
    sps = wb.create_sheet("Species")
    sps.append(["Species or category", "Group", "MaxN", "MeanCount (sub-samples)", "Mean over all sampled frames",
                "Confidence (0-1)", "Tracks", "Confirmed by reviewer"])
    for r in report.get("species", []):
        grp = "invertebrate" if r["label"] in invert else ("" if r["label"].startswith(("Unknown", "Unfamiliar", "Unconfirmed")) else "fish")
        sps.append([_col_title(r["label"], cfg), grp, r["MaxN"], r["MeanCount"], r["MeanCount_all_sampled_frames"],
                    r["confidence"], r["n_tracks"], r["verified_tracks"]])

    for sheet in (ws, ss, sps):
        for c in sheet[1] if sheet is not ss else []:
            c.font, c.fill, c.alignment = head, fill, wrap
        for i, col in enumerate(sheet.columns, start=1):
            width = max(len(str(c.value or "")) for c in col)
            sheet.column_dimensions[get_column_letter(i)].width = min(60, max(10, width + 2))
        sheet.freeze_panes = "A2" if sheet is not ss else None
    for c in ss["A"]:
        c.font = Font(bold=True)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
