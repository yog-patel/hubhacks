"""Markdown for EVALUATION.md's top sections: BASELINE vs FINAL, what improved and why, and the Phase-2 experiment log.

Every number is read from measured files:
  outputs/eval/experiments.json   (scripts/experiments.py)
  outputs/eval/baseline/          (v1 re-measured: evaluation.json, detectors.json, demo_rehearsal.json)
  outputs/eval/evaluation.json, outputs/eval/final_extra.json (FINAL, scripts/evaluate.py)
Only the keep/revert reasoning below is written by hand.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "outputs" / "eval"


def _load(p: Path):
    return json.loads(p.read_text()) if p.exists() else None


def _exp() -> dict:
    rows = _load(EVAL / "experiments.json") or []
    return {(r["id"], r["variant"]): r for r in rows}


def _m(E: dict, i: str, v: str, k: str, fmt: str = "{}") -> str:
    r = E.get((i, v))
    if r is None or r["metrics"].get(k) is None:
        return "–"
    return fmt.format(r["metrics"][k])


# (experiment id, what changed, baseline (id, variant), candidate (id, variant), metric keys, decision, why)
DET_KEYS = [("f1", "F1 {:.3f}"), ("precision", "P {:.3f}"), ("recall", "R {:.3f}"), ("count_at_1401", "count {}")]
TRK_KEYS = [("fragmentation_per_100_tracks", "frag {:.2f}/100"), ("jumps_per_100_tracks", "jumps {:.2f}/100"), ("count_at_1401", "count {}")]
IMG_KEYS = [("auc_known_vs_heldout", "AUC {:.3f}"), ("known_false_alarm_pct", "false alarms {:.1f}%"), ("held_unfamiliar_pct", "held-out unfamiliar {:.1f}%")]
VID_KEYS = [("auc_gt_fish_vs_nonfish", "video AUC {:.3f}")]
ROWS = [
    ("E1", "Enhancement for detection: **no enhancement** (raw luminance)", ("E1", "baseline CLAHE clip 3, grid 8"),
     ("E1", "raw luminance (no enhancement)"), DET_KEYS, "reverted",
     "Without CLAHE the faint fish vanish into the haze: almost no detections."),
    ("E1", "CLAHE clip 2 / grid 8", ("E1", "baseline CLAHE clip 3, grid 8"), ("E1", "CLAHE clip 2, grid 8"), DET_KEYS, "reverted",
     "Higher precision but the count at 14:01 halves."),
    ("E1", "CLAHE clip 4 / grid 8", ("E1", "baseline CLAHE clip 3, grid 8"), ("E1", "CLAHE clip 4, grid 8"), DET_KEYS, "reverted",
     "More noise detections, lower F1."),
    ("E1", "CLAHE clip 3 / grid 16", ("E1", "baseline CLAHE clip 3, grid 8"), ("E1", "CLAHE clip 3, grid 16"), DET_KEYS, "reverted",
     "Within noise of the baseline."),
    ("E1", "**CLAHE clip 2 / grid 4** (larger tiles, gentler clip)", ("E1", "baseline CLAHE clip 3, grid 8"), ("E1", "CLAHE clip 2, grid 4"),
     DET_KEYS, "**kept**", "Best F1 of all settings; its worst frame beats the baseline's mean; count closer to the manual 36."),
    ("E1", "Enhanced crops for identification (image level)", ("E1-ID", "raw crops"), ("E1-ID", "enhanced crops"), IMG_KEYS,
     "reverted", "Looks like a huge gain, but the image-level sets differ by background (known = pale mid-water crops, "
                 "held-out = sandy seabed), and enhancement exaggerates exactly that. The video-level check below shows the opposite."),
    ("E1", "Enhanced crops for identification (video tracks at 14:01)", ("E1-ID-video", "raw crops (as v1)"),
     ("E1-ID-video", "enhanced crops"), VID_KEYS, "reverted", "On real video tracks fish vs non-fish separation falls to chance."),
    ("E2", "Motion detector: background-size fix (`ctx_tol_s`)", ("E2", "motion baseline"),
     ("E2", "motion context fix (constant 16-frame background)"), DET_KEYS, "reverted", "Same F1, count further from 36 (DECISIONS D20)."),
    ("E2", "Confidence threshold `z_thresh` 2.0", ("E2", "motion baseline"), ("E2", "motion z_thresh=2"), DET_KEYS, "reverted",
     "Count rises to the manual figure only by adding false positives (precision 0.26)."),
    ("E2", "`z_thresh` 2.25", ("E2", "motion baseline"), ("E2", "motion z_thresh=2.25"), DET_KEYS, "reverted", "Lower F1."),
    ("E2", "`z_thresh` 2.75", ("E2", "motion baseline"), ("E2", "motion z_thresh=2.75"), DET_KEYS, "reverted",
     "Small F1 gain, count drops to 13; with CLAHE 2/4 it lowers F1 (combo table)."),
    ("E2", "`z_thresh` 3.0", ("E2", "motion baseline"), ("E2", "motion z_thresh=3"), DET_KEYS, "reverted", "Count drops to 14."),
    ("E2", "`min_area` 100 / 220", ("E2", "motion baseline"), ("E2", "motion min_area=220"), DET_KEYS, "reverted",
     "220: +0.006 F1 on top of CLAHE 2/4 (combo table), within noise; risks dropping small fish elsewhere."),
    ("E2", "`min_elongation` 1.2 / 1.6", ("E2", "motion baseline"), ("E2", "motion min_elongation=1.6"), DET_KEYS, "reverted",
     "1.6: higher precision but count 14; 1.2 adds round sediment specks (F1 0.42)."),
    ("E2", "noise floor `k` 0.5 / 2", ("E2", "motion baseline"), ("E2", "motion k=2"), DET_KEYS, "reverted",
     "k=2: count 9; k=0.5: F1 0.37."),
    ("E2", "background window ±6 / ±12 s", ("E2", "motion baseline"), ("E2", "motion window_s=12"), DET_KEYS, "reverted",
     "±12 s: same F1, count 15, 17% slower; ±6 s: F1 0.48."),
    ("E4", "ByteTrack `lost_track_buffer` 2–8 (v1 value 4)", ("E4", "baseline"), ("E4", "lost_track_buffer=8"), TRK_KEYS, "reverted",
     "**No effect at all**: supervision scales the buffer by frame_rate/30, so at 2 fps any value below 15 means 0 frames."),
    ("E4", "`lost_track_buffer` 30 / 45 (= 1 / 1.5 sampled frames)", ("E4", "baseline"), ("E4", "lost_track_buffer=45"), TRK_KEYS,
     "reverted", "Less fragmentation but more implausible jumps (two fish joined)."),
    ("E4", "`minimum_matching_threshold` 0.7 / 0.8 / 0.95", ("E4", "baseline"), ("E4", "minimum_matching_threshold=0.95"), TRK_KEYS,
     "reverted", "0.95 trades fragmentation for jumps; 0.7–0.8 triple fragmentation."),
    ("E4", "`box_expand` 2 / 2.5 / 4", ("E4", "baseline"), ("E4", "box_expand=2.5"), TRK_KEYS, "reverted (alone)",
     "Fewer jumps but more fragmentation on its own; used in the kept combination."),
    ("E4", "`min_assoc_size` 80–320", ("E4", "baseline"), ("E4", "min_assoc_size=200"), TRK_KEYS, "reverted (alone)",
     "200 cuts fragmentation 6×; 320 merges fish (jumps ×8)."),
    ("E4", "**`min_assoc_size` 200 + `box_expand` 2.5**", ("E4", "baseline"), ("E4", "min_assoc_size=200 + box_expand=2.5"), TRK_KEYS,
     "**kept**", "Fragmentation (one fish split into two IDs) drops 7.5×, implausible jumps (two fish merged) also drop, and more "
                 "real fish persist long enough to count at 14:01."),
    ("E5", "Crop selection: best 3 by size / normalised sharpness / occlusion", ("E5", "v1: Laplacian var x sqrt(area), all 5"),
     ("E5", "largest 3"), [("auc_fish_vs_nonfish", "AUC {:.3f}")], "reverted",
     "Only 5 fish and 12 non-fish tracks are labelled at 14:01 for this test; every rule is within one or two pairs of v1."),
    ("E6", "k-means prototypes, k=4 (image level)", ("E6", "baseline: 1 mean prototype"),
     ("E6", "k-means k=4, best of 5 restarts by inertia (deterministic, as shipped)"), IMG_KEYS, "reverted",
     "Image-level gain, but see the video-level row: it doesn't transfer."),
    ("E6", "k-means k=4 on video (each at its own tuned thresholds)", ("E6-video", "1 prototype(s) at its own re-tuned thresholds"),
     ("E6-video", "4 prototype(s) at its own re-tuned thresholds"), [("unfamiliar_pct", "clear tracks flagged unfamiliar {:.1f}%")],
     "reverted", "Doubles the 'possibly new species' flags on clear-water video, the costliest error for a biologist."),
    ("E6", "Image + BioCLIP text blend ('ray-finned fish', α 0.8)", ("E6", "baseline: 1 mean prototype"),
     ("E6", "image+text blend 'taxonomic' alpha=0.8"), IMG_KEYS, "reverted",
     "No gain; the species is unidentified, so there is no accurate name to embed."),
    ("E8", "Sampling 1 fps (MIN_FRAMES 3)", ("E8", "2 fps"), ("E8", "1 fps"), [("count_at_1401", "count {}"), ("frames", "{} frames")],
     "reverted", "Half the compute, but the count at 14:01 drops."),
    ("E8", "Sampling 1 fps with the same persistence in seconds (MIN_FRAMES 2)", ("E8", "2 fps"),
     ("E8", "1 fps, MIN_FRAMES=2 (persistence 2 s)"), [("count_at_1401", "count {}"), ("frames", "{} frames")], "see table",
     "Fair comparison for the energy question."),
    ("E8", "Sampling 0.5 / 3 fps", ("E8", "2 fps"), ("E8", "3 fps"), [("count_at_1401", "count {}"), ("frames", "{} frames")], "reverted",
     "0.5 fps counts nothing (tracks can't persist); 3 fps costs 50% more and counts fewer (more fragmentation)."),
]


def owl_rows(E: dict) -> list[str]:
    owl = [r for (i, v), r in E.items() if i == "E2-OWL" and "error" not in r["metrics"]]
    out = []
    for model in ("owlv2-base-patch16-ensemble", "owlv2-large-patch14-ensemble"):
        rs = [r for r in owl if r["variant"].startswith(model)]
        if not rs:
            continue
        best = max(rs, key=lambda r: (r["metrics"]["f1"], r["metrics"].get("tp", 0), r["metrics"]["detections"]))
        mot_s = (E.get(("E2", "motion baseline")) or {}).get("metrics", {}).get("s_per_frame_detect") or 0.35
        tps = max(r["metrics"].get("tp", 0) for r in rs)
        p = best["params"]
        out.append(f"| E2 | OWLv2 `{model}`: best of {len(rs)} settings (prompts {', '.join(chr(34) + x + chr(34) for x in p['prompts'])}; "
                   f"tiles {p['grid']}×{p['grid']}; score ≥ {p['score_threshold']}; NMS IoU {p['nms_iou']}) | "
                   f"motion: F1 {_m(E, 'E2', 'motion baseline', 'f1', '{:.3f}')} | F1 {best['metrics']['f1']:.3f} "
                   f"({best['metrics'].get('tp', 0)} of 36 fish found, {best['metrics']['detections']} detections); at most {tps} fish in any setting; "
                   f"{best['metrics']['s_per_frame']} s/frame | reverted | "
                   f"Open-vocabulary detection misses these faint, translucent fish and is "
                   f"{best['metrics']['s_per_frame'] / mot_s:.0f}× slower per frame than the motion detector. "
                   + ("The large model was run at 3×3 tiles only (all 5 prompts × 3 thresholds × 2 NMS); 4×4 was stopped to save GPU "
                      "time after 0 fish at 3×3 and 0 fish for base at 4×4. " if "large" in model else "")
                   + "Distillation was therefore not attempted: a teacher that can't see the fish gives no usable pseudo-labels. |")
    return out


def log_table() -> list[str]:
    E = _exp()
    L = ["| Exp | What changed | Before (BASELINE) | After | Kept? | Why |", "|---|---|---|---|---|---|"]
    for i, what, b, c, keys, dec, why in ROWS:
        before = ", ".join(_m(E, *b, k, f) for k, f in keys)
        after = ", ".join(_m(E, *c, k, f) for k, f in keys)
        if "–" in before + after and E.get(c) is None:
            continue
        L.append(f"| {i} | {what} | {before} | {after} | {dec} | {why} |")
    L += owl_rows(E)
    combo = [r for (i, v), r in E.items() if i == "E2-combo"]
    if combo:
        L += ["", "Combinations (E1 + E2 + E4) on the same tuning-half metrics:", "",
              "| Combination | F1 (mean / worst of 5 frames) | Precision | Recall | Count at 14:01 (manual 36) |", "|---|---|---|---|---|",
              f"| BASELINE | {_m(E, 'E1', 'baseline CLAHE clip 3, grid 8', 'f1', '{:.3f}')} / {_m(E, 'E1', 'baseline CLAHE clip 3, grid 8', 'f1_min', '{:.3f}')} | "
              f"{_m(E, 'E1', 'baseline CLAHE clip 3, grid 8', 'precision', '{:.3f}')} | {_m(E, 'E1', 'baseline CLAHE clip 3, grid 8', 'recall', '{:.3f}')} | "
              f"{_m(E, 'E1', 'baseline CLAHE clip 3, grid 8', 'count_at_1401')} |"]
        for r in combo:
            m = r["metrics"]
            L.append(f"| {r['variant']}{' **(FINAL)**' if r['variant'] == 'CLAHE 2/4 + tracker assoc 200, expand 2.5' else ''} | "
                     f"{m['f1']:.3f} / {m['f1_min']:.3f} | {m['precision']:.3f} | {m['recall']:.3f} | {m['count_at_1401']} |")
    return L


def method_notes() -> list[str]:
    return ["**How the experiments were measured** (tuning data only; the demo half was never used to choose anything):", "",
            "* **Detection F1**: mean precision/recall/F1 over the 5 exact video frames 25212–25216 (841.24–841.37 s), against the "
            "36 tally points the biologists placed at 14:01. The annotated instant was located by correlating the screenshot with the "
            "video (DECISIONS D19). Each frame gets an exact ±k-second background.",
            "* **Count at 14:01**: the protocol count the pipeline would report (best sampled frame within ±0.5 s, persistent tracks "
            "only) from a 46-s streamed window around 14:01, against the manual 36.",
            "* **Tracker** (no tracking ground truth exists): re-tracking the cached tuning-half detections. Proxies: *fragmentation*, "
            "a persistent track starting within 1.5 s and 150 px of where another ended (one fish split into two IDs, which inflates "
            "counts and review items); *implausible jumps*, a track moving > 250 px between samples (two fish merged into one ID).",
            "* **Identification**: image level as in v1 (T2-STAT2 13–14 min prototype crops, 21-min known crops, 39 held-out crops), "
            "plus a **video-level** check: tuning-half tracks that match a 14:01 tally point (fish) vs tracks that don't.",
            "* Small samples: one annotated instant, 36 points, 22 labelled video tracks. Differences of a few hundredths are noise; "
            "only changes that improved both metrics, or clearly improved one without hurting the other, were kept.", ""]


if __name__ == "__main__":
    print("\n".join(method_notes() + log_table()))


# ----------------------------------------------------------------------------- BASELINE vs FINAL
def _count(res: dict, t: str) -> dict:
    return next((c for c in res.get("counts", []) if c["time"] == t), {})


def _det(res_or_list, name: str = "motion (default)", t: str = "14:01") -> dict:
    lst = res_or_list.get("detectors", []) if isinstance(res_or_list, dict) else (res_or_list or [])
    return next((d for d in lst if d["detector"] == name and d["time"] == t), {})


def _fmt(v, f="{}"):
    return "–" if v is None or v == "" else f.format(v)


def top_sections(final: dict) -> list[str]:
    """Summary table, 'What improved and why', experiment log and the BASELINE block."""
    E = _exp()
    B = _load(EVAL / "baseline" / "evaluation.json") or {}
    Bdet = _load(EVAL / "baseline" / "detectors.json") or []
    Brt = _load(EVAL / "baseline" / "full_run_runtime.json") or {}
    Bdemo = _load(EVAL / "baseline" / "demo_rehearsal.json") or {}
    Frt = _load(EVAL / "full_run_runtime.json") or {}
    Fdemo = _load(EVAL / "demo_rehearsal.json") or {}
    Fx = _load(EVAL / "final_extra.json") or {}
    b14, f14, b22, f22 = _count(B, "14:01"), _count(final, "14:01"), _count(B, "22:00"), _count(final, "22:00")
    bd, fd = _det(Bdet), _det(final)
    ib, ia = B.get("image_after", {}), final.get("image_after", {})
    bt, ft = B.get("thresholds_after", {}), final.get("thresholds_after", {})
    bf1 = (E.get(("E1", "baseline CLAHE clip 3, grid 8")) or {}).get("metrics", {})
    ff1 = (E.get(("E2-combo", "CLAHE 2/4 + tracker assoc 200, expand 2.5")) or {}).get("metrics", {})
    btr = (E.get(("E4", "baseline")) or {}).get("metrics", {})
    ftr = Fx.get("tracker_final", {})

    def crab(d):
        if not d:
            return "–", "–"
        known = d.get("tracks_known_as_new_species", [])
        span = [t for t in known if t["end_s"] >= 1290 and t["start_s"] <= 1306]
        fi = d.get("first_review_item", {})
        return (f"{fi.get('status', '?')} ({fi.get('best_similarity', 0):.2f})", f"{len(known)} / {len(span)}")

    bc, fc = crab(Bdemo), crab(Fdemo)
    rb, rf = B.get("runs", {}), final.get("runs", {})
    en = Fx.get("energy", {})
    L = ["# EVALUATION", "",
         f"_Generated by `scripts/evaluate.py` on {final.get('generated', '?')}. Every number is measured. BASELINE = v1 re-measured on "
         "this machine before any v2 change; FINAL = v2 after Phase 2. Experiments: `scripts/experiments.py`, raw results "
         "`outputs/eval/experiments.json`._", "",
         "> All video results come from **one** video (`T1-STAT2 411.MP4`) and two manually counted instants. Choices were made on the "
         "**tuning half** (60–1074 s, the 14:01 count) and on the held-out photos. The 22:00 count (demo half) was looked at **once, after** "
         "the FINAL configuration was fixed. Treat all differences as indicative.", "",
         "## BASELINE vs FINAL", "",
         "| Metric | BASELINE (v1) | FINAL (v2) | Data |", "|---|---|---|---|",
         f"| Detection F1 at the annotated 14:01 instant (mean of 5 aligned frames) | {_fmt(bf1.get('f1'), '{:.3f}')} | **{_fmt(ff1.get('f1'), '{:.3f}')}** | tuning half, 36 tally points |",
         f"| … precision / recall | {_fmt(bf1.get('precision'), '{:.2f}')} / {_fmt(bf1.get('recall'), '{:.2f}')} | {_fmt(ff1.get('precision'), '{:.2f}')} / {_fmt(ff1.get('recall'), '{:.2f}')} | |",
         f"| v1's single-frame score at 841.00 s: detections / P / R / F1 | {_fmt(bd.get('detections'))} / {_fmt(bd.get('precision'))} / {_fmt(bd.get('recall'))} / {_fmt(bd.get('f1'))} | "
         f"{_fmt(fd.get('detections'))} / {_fmt(fd.get('precision'))} / {_fmt(fd.get('recall'))} / {_fmt(fd.get('f1'))} | same frame as v1 (≈0.3 s before the annotated instant) |",
         f"| Count at 14:01, full tuning-half run (manual 36) | {_fmt(b14.get('bluesight_counted_fish'))} ({_fmt(b14.get('pct_difference'))} % diff) | **{_fmt(f14.get('bluesight_counted_fish'))}** ({_fmt(f14.get('pct_difference'))} % diff) | tuning half |",
         f"| Count at 22:00 (manual 102), checked once after FINAL was fixed | {_fmt(b22.get('bluesight_counted_fish'))} ({_fmt(b22.get('pct_difference'))} % diff) | {_fmt(f22.get('bluesight_counted_fish'))} ({_fmt(f22.get('pct_difference'))} % diff) | demo half (not used for choices) |",
         f"| Track fragmentation (one fish split into two IDs) per 100 persistent tracks | {_fmt(btr.get('fragmentation_per_100_tracks'))} | {_fmt(ftr.get('fragmentation_per_100_tracks'))} | tuning half |",
         f"| Implausible jumps (two fish merged into one ID) per 100 persistent tracks | {_fmt(btr.get('jumps_per_100_tracks'))} | {_fmt(ftr.get('jumps_per_100_tracks'))} | tuning half |",
         f"| Image level: known recognised / false alarms | {_fmt(ib.get('known_correct_pct'), '{:.1f}')} % / {_fmt(ib.get('known_false_alarm_pct'), '{:.1f}')} % | {_fmt(ia.get('known_correct_pct'), '{:.1f}')} % / {_fmt(ia.get('known_false_alarm_pct'), '{:.1f}')} % | photos |",
         f"| Image level: held-out flagged / unfamiliar / mislabelled as known | {_fmt(ib.get('held_flagged_pct'), '{:.1f}')} / {_fmt(ib.get('held_unfamiliar_pct'), '{:.1f}')} / {_fmt(ib.get('held_mislabelled_known_pct'), '{:.1f}')} % | "
         f"{_fmt(ia.get('held_flagged_pct'), '{:.1f}')} / {_fmt(ia.get('held_unfamiliar_pct'), '{:.1f}')} / {_fmt(ia.get('held_mislabelled_known_pct'), '{:.1f}')} % | photos |",
         f"| Thresholds T_KNOWN / T_UNKNOWN / V_MIN | {bt.get('T_KNOWN')} / {bt.get('T_UNKNOWN')} / {bt.get('V_MIN')} | {ft.get('T_KNOWN')} / {ft.get('T_UNKNOWN')} / {ft.get('V_MIN')} | re-calibrated (§ threshold tuning) |",
         f"| Review items: tuning half / demo half | {rb.get('tuning', {}).get('review_items', '–')} / {rb.get('demo', {}).get('review_items', '–')} | {rf.get('tuning', {}).get('review_items', '–')} / {rf.get('demo', {}).get('review_items', '–')} | estimated reviewer time = items × 10 s |",
         f"| Demo: green crab (held out) review item #1 status (similarity) | {bc[0]} | {fc[0]} | demo window 21:20–22:35 |",
         f"| Demo: after approving the crab, tracks recognised as crab / inside the crab's time span | {bc[1]} | {fc[1]} | demo window |",
         f"| Full processing cost, s of compute per video minute (tuning / demo half) | {_fmt(Brt.get('tuning', {}).get('s_per_video_min'))} / {_fmt(Brt.get('demo', {}).get('s_per_video_min'))} | "
         f"{_fmt(Frt.get('tuning', {}).get('s_per_video_min'))} / {_fmt(Frt.get('demo', {}).get('s_per_video_min'))} | Apple M5, MPS |",
         f"| Energy per video minute, full processing (estimate, CPU+RAM only) | not measured in v1 | {_fmt(en.get('wh_per_video_min'), '{:.2f}')} Wh ({_fmt(en.get('co2_g_per_video_min'), '{:.2f}')} g CO2e) | CodeCarbon offline |",
         f"| External network connections during analysis runs | not measured in v1 | **{_fmt(Fx.get('external_connections_total'))}** over {_fmt(Fx.get('runs_with_guard'))} runs | network guard |",
         "", "## What improved and why", ""]
    L += Fx.get("what_improved", ["_(written after the FINAL runs)_"])
    L += ["", "## Phase 2 experiment log", ""] + method_notes() + log_table()
    L += ["", "## BASELINE (v1, re-measured 2026-11-07 before any change)", "",
          "`scripts/evaluate.py` and `scripts/rehearse_demo.py` were re-run with the v1 code and config. Every count, rate and threshold "
          "reproduced v1's own EVALUATION.md exactly (only cached re-run times differ). Raw files: `outputs/eval/baseline/`. "
          "The v1 report itself is in git history (`git show d31133e:EVALUATION.md`).", ""]
    return L
