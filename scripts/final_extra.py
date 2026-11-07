"""Measured extras for EVALUATION.md's FINAL column -> outputs/eval/final_extra.json.

* tracker fragmentation / implausible jumps on the FINAL tuning-half run (same proxies as experiment E4)
* energy per video minute for the FINAL full (uncached) half runs, from outputs/logs/energy.csv
* total external network connections recorded by the guard over all v2 runs
* the "What improved and why" text, with every number filled in from measured files

    python scripts/final_extra.py
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from bluesight.config import load_config  # noqa: E402
import experiments as X  # noqa: E402

EVAL = ROOT / "outputs" / "eval"


def main() -> None:
    cfg = load_config()
    out: dict = {}
    # tracker proxies on the FINAL tuning-half cache (its own tracker ids)
    from bluesight.pipeline import run_video  # noqa: F401  (ensures package import side effects)

    runs = json.loads((EVAL / "evaluation.json").read_text())["runs"]
    tune_id = runs["tuning"]["run_id"]
    caches = sorted(glob.glob(str(ROOT / "outputs" / "cache" / "T1_STAT2_411" / f"{tune_id.split('__')[1]}_*")),
                    key=lambda p: Path(p).stat().st_mtime)
    d = pd.read_csv(Path(caches[-1]) / "detections.csv").rename(columns={"t_s": "t", "track_id": "tid"})
    out["tracker_final"] = X.track_metrics(d[["t", "tid", "x1", "y1", "x2", "y2"]], int(cfg["identify"]["MIN_FRAMES"]))
    out["tracker_final"]["cache"] = Path(caches[-1]).name
    # energy + network
    e = pd.read_csv(ROOT / "outputs" / "logs" / "energy.csv")
    full = e[(e.cached_detection == 0) & e.run_id.isin([runs["tuning"]["run_id"], runs["demo"]["run_id"]])].drop_duplicates("run_id", keep="last")
    if len(full):
        mins = sum(runs[k]["window"]["duration_min"] for k in ("tuning", "demo") if runs[k]["run_id"] in set(full.run_id))
        out["energy"] = {"wh_total": round(float(full.energy_wh.sum()), 2), "co2_g_total": round(float(full.co2_g.sum()), 2),
                         "video_min": round(mins, 1), "wh_per_video_min": round(float(full.energy_wh.sum()) / mins, 3),
                         "co2_g_per_video_min": round(float(full.co2_g.sum()) / mins, 3),
                         "note": "CodeCarbon offline estimate, CPU (load model) + RAM; Apple GPU not measured"}
    out["external_connections_total"] = int(e.external_connections.fillna(0).sum())
    out["runs_with_guard"] = int(len(e))
    rt = json.loads((EVAL / "full_run_runtime.json").read_text())
    rtb = json.loads((EVAL / "baseline" / "full_run_runtime.json").read_text())
    out["rt"] = {k: v["s_per_video_min"] for k, v in rt.items()}
    out["rt_base"] = {k: v["s_per_video_min"] for k, v in rtb.items()}
    out["what_improved"] = what_improved(out)
    (EVAL / "final_extra.json").write_text(json.dumps(out, indent=1, default=float))
    print(json.dumps(out, indent=1, default=float))


def what_improved(x: dict) -> list[str]:
    """Plain-language summary, every number read from the measured files."""
    E = {(r["id"], r["variant"]): r["metrics"] for r in json.loads((EVAL / "experiments.json").read_text())}
    B = json.loads((EVAL / "baseline" / "evaluation.json").read_text())
    F = json.loads((EVAL / "evaluation.json").read_text())
    Bd = json.loads((EVAL / "baseline" / "demo_rehearsal.json").read_text())
    Fd = json.loads((EVAL / "demo_rehearsal.json").read_text())
    c = lambda res, t: next((r for r in res["counts"] if r["time"] == t), {})
    P = E[("FINAL-paired", "BASELINE vs FINAL detection on 13 consecutive frames 841.11-841.51 s")]
    bt, ft = E[("E4", "baseline")], x["tracker_final"]
    b14, f14, b22, f22 = c(B, "14:01"), c(F, "14:01"), c(B, "22:00"), c(F, "22:00")
    vb, vf = E[("E6-video", "1 prototype(s) at its own re-tuned thresholds")], E[("E6-video", "4 prototype(s) at its own re-tuned thresholds")]
    span = lambda d: [t for t in d["tracks_known_as_new_species"] if t["end_s"] >= 1290 and t["start_s"] <= 1306]
    nb, nf = len(Bd["tracks_known_as_new_species"]), len(Fd["tracks_known_as_new_species"])
    sb, sf = len(span(Bd)), len(span(Fd))
    rb, rf = B["runs"], F["runs"]
    return [
        f"1. **Detection: a modest, consistent gain, not a dramatic one.** Gentler, coarser contrast enhancement (CLAHE clip 2 on "
        f"4×4 tiles instead of clip 3 on 8×8) brings out the faint fish while amplifying sand texture and sunlight flicker less. "
        f"On 13 consecutive video frames around the annotated 14:01 instant (the same frames for both versions): mean F1 "
        f"{P['mean_baseline_f1']:.3f} → **{P['mean_final_f1']:.3f}**, precision {P['mean_baseline_precision']:.2f} → "
        f"{P['mean_final_precision']:.2f}, recall {P['mean_baseline_recall']:.2f} → {P['mean_final_recall']:.2f}. FINAL is better on "
        f"{P['final_better_frames']} frames and worse on {P['final_worse_frames']}. That is **not statistically significant** "
        f"(sign test p = {P['sign_test_p_two_sided']}), and the central 5 frames were also used to choose the setting.",
        f"2. **Each fish keeps one ID more reliably.** Tracking at 2 frames per second only works if boxes are enlarged for matching. "
        f"Enlarging small boxes to at least 200 px (was 120) and others less (×2.5, was ×3) cut split tracks from "
        f"{bt['fragmentation_per_100_tracks']:.2f} to **{ft['fragmentation_per_100_tracks']:.2f} per 100 tracks** on the tuning half. "
        f"Merged-fish jumps went from {bt['jumps_per_100_tracks']:.2f} to {ft['jumps_per_100_tracks']:.2f}.",
        f"3. **The biggest practical gains are in the review queue and the demo.** Review items fell from "
        f"{rb['tuning']['review_items']} to **{rf['tuning']['review_items']}** (tuning half) and from {rb['demo']['review_items']} to "
        f"**{rf['demo']['review_items']}** (demo half): less reviewer time for the same footage. In the demo window the held-out "
        f"green crab is still review item #1 and still 'unfamiliar' ({Fd['first_review_item']['best_similarity']:.2f}). After a "
        f"reviewer approves it, {nf} tracks are recognised as crab, against {nb} before. {sf} of them fall inside the crab's walk "
        f"(before: {sb}), so sand patches wrongly matched to the new species dropped from {nb - sb} to **{nf - sf}**. The demo half "
        "was never used to choose settings, so this is a held-out result.",
        f"4. **Counts at the two manually counted instants moved in opposite directions, so we don't claim a count improvement.** "
        f"14:01 (tuning half): {b14.get('bluesight_counted_fish')} → {f14.get('bluesight_counted_fish')} of 36. "
        f"22:00 (demo half, checked once afterwards): {b22.get('bluesight_counted_fish')} → **{f22.get('bluesight_counted_fish')}** of 102. "
        "A count at a single instant is dominated by which video frame happens to be sampled: one frame (33 ms) later, the detector "
        "found 17 instead of 27 objects at 14:01. BlueSight remains a pre-screen; it doesn't replace the manual count.",
        f"5. **Two tempting 'improvements' were rejected because they failed on real video.** Enhancing crops and using several "
        f"prototypes per species both looked much better on the screenshot photos, but those photos separate known from held-out "
        f"partly by background (pale water vs sandy seabed). On video tracks, enhanced crops dropped fish-vs-non-fish separation to "
        f"chance, and k-means prototypes raised clear-water 'possibly new species' flags from {vb['unfamiliar_pct']:.1f}% to "
        f"{vf['unfamiliar_pct']:.1f}%.",
        "6. **Found and documented, not hidden:** ByteTrack's `lost_track_buffer` does nothing at 2 fps (a scaling quirk in "
        "`supervision`); the motion detector's background alternates between 15 and 16 frames depending on frame-time rounding "
        "(measured, no gain from fixing); the 14:01 ground truth belongs to 841.31 s, not 841.00 s (found by correlating the screenshot "
        "with the video); and OWLv2, base or large, finds none of these fish.",
        f"7. **Cost:** sampling stays at 2 fps (1 fps undercounts even with the same persistence time) and no bigger model was added. "
        f"First-time processing measured {x.get('rt', {}).get('tuning', '–')} / {x.get('rt', {}).get('demo', '–')} s of compute per video "
        f"minute (tuning / demo half) vs {x.get('rt_base', {}).get('tuning', '–')} / {x.get('rt_base', {}).get('demo', '–')} in v1. "
        "Run-to-run timing varies with other load on the laptop, so treat differences of ±15% as noise. Energy: "
        f"{x.get('energy', {}).get('wh_per_video_min', '–')} Wh per video minute (CodeCarbon estimate, CPU+RAM only).",
    ]


if __name__ == "__main__":
    main()
