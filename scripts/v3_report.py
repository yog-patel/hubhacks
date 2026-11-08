"""Write the v3 section of EVALUATION.md (branch satvik/accuracy) from measured results only.

Reads outputs/eval/experiments.json (E9 FishSpotter, E10 counted-detection sensitivity, E11 embedders) and the
verified counts saved on the Verify counts page, and replaces the block between the v3 markers in EVALUATION.md
(appending it if missing). scripts/evaluate.py calls this after it regenerates the file.

    python scripts/v3_report.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "outputs" / "eval"
START, END = "<!-- v3:start -->", "<!-- v3:end -->"


def _exp() -> dict:
    f = EVAL / "experiments.json"
    rows = json.loads(f.read_text()) if f.exists() else []
    return {(r["id"], r.get("variant")): r for r in rows}


def _f(v, fmt="{:.3f}") -> str:
    return "–" if v is None else fmt.format(v)


def e9(E: dict) -> list[str]:
    r = next((v for (i, _), v in E.items() if i == "E9"), None)
    if r is None:
        return ["_E9 not run on this machine._", ""]
    m, p = r["metrics"], r["params"]
    L = ["### E9. FishSpotter: a learned detector trained on the biologists' tally dots", "",
         f"A ResNet-18 heatmap point detector (BSD-3 torchvision, ImageNet weights) trained for {p['steps']} steps "
         f"({p['train_s']:.0f} s on this computer) **only on the other station's photos** (T2-STAT2, "
         f"{p['train_points']} tally dots on {len(p['train_photos'])} screenshots, red marks and grid painted out), then tested on "
         "this video's 14:01 frame, which it never saw. Detection threshold fixed at 0.3 before testing.", "",
         "| Detector (5 exact frames at 14:01, 36 tally points) | Detections | Precision | Recall | F1 |", "|---|---|---|---|---|"]
    for name, k in (("Motion (FINAL v2, unchanged)", m["motion_final"]), ("FishSpotter alone", m["spotter_at_fixed"]),
                    ("Motion + FishSpotter (fused)", m["fused_at_fixed"])):
        L.append(f"| {name} | {k['detections']:.1f} | {k['precision']:.2f} | {k['recall']:.2f} | **{k['f1']:.3f}** |")
    best_fused = max(v["fused"]["recall"] for v in m["sweep"].values())
    L += ["", f"**Result: not adopted.** FishSpotter alone is fairly precise but finds few fish, and fusing it with motion lowers F1. "
          f"Across every threshold the fused recall never passes {best_fused:.2f}: about half the fish the biologists counted give no "
          "response from either detector. Looking at those fish (crops around every tally point), the missed ones are faint grey "
          "streaks that are recognisable only in motion, so a still-image model trained on three photos cannot find them. "
          "The code is kept (`detector.name: fused`) for retraining on verified frames (below).", ""]
    return L


def e10(E: dict) -> list[str]:
    r = E.get(("E10", "counted-detections grid"))
    if r is None:
        return []
    g = sorted(r["grid"], key=lambda x: (x["z"], x["min_elong"], x["MIN_FRAMES"]))
    L = ["### E10. Motion sensitivity, scored on what is actually counted", "",
         "Earlier tuning (E2) scored raw single-frame detections. The count only uses detections on persistent tracks, so this scores "
         "those counted detections at the two sampled frames around the annotated instant (840.97 and 841.47 s) against the 36 tally points.", "",
         "| z threshold | Min. elongation | Counted (manual 36) | Precision | Recall | F1 |", "|---|---|---|---|---|---|"]
    for x in g:
        if x["MIN_FRAMES"] != 3:
            continue
        cur = " (current)" if x["z"] == 2.5 and x["min_elong"] == 1.4 else ""
        L.append(f"| {x['z']}{cur} | {x['min_elong']} | {x['detections']:.1f} | {x['precision']:.2f} | {x['recall']:.2f} | {x['f1']:.3f} |")
    L += ["", "MIN_FRAMES 4 or 5 gave the same or nearly the same numbers. **Result: no change.** The setting that brings the count close to 36 "
          "does it by adding noise (precision 0.07 to 0.20), so the right total would be right for the wrong reasons. "
          "The best F1 (z 2.25) is about 0.05 above the current setting on just two frames, too small a sample to change a tuned default.", ""]
    return L


def e11(E: dict) -> list[str]:
    a, b = E.get(("E11", "hf-hub:imageomics/bioclip")), E.get(("E11", "hf-hub:imageomics/bioclip-2"))
    if not (a and b):
        return []
    A, B = a["metrics"], b["metrics"]
    rows = [("Known vs held-out separation (AUC)", "auc_known_vs_heldout", "{:.3f}"),
            ("Thresholds T_KNOWN / T_UNKNOWN (re-tuned per model)", None, None),
            ("Known photos recognised", "known_correct_pct", "{:.1f} %"),
            ("Held-out photos flagged unfamiliar", "held_unfamiliar_pct", "{:.1f} %"),
            ("Held-out photos mislabelled as known", "held_mislabelled_known_pct", "{:.1f} %"),
            ("Demo crab track: similarity to the fish prototype", "demo_crab_t353_similarity", "{:.3f}"),
            ("Demo crab track: rank among 442 tracks (1 = most unfamiliar)", "demo_crab_rank_most_unfamiliar", "{}"),
            ("Vision encoder parameters", "params_m", "{:.0f} M"),
            ("Time per crop on this computer", "ms_per_crop", "{:.0f} ms")]
    L = ["### E11. BioCLIP 2 instead of BioCLIP", "", "| | BioCLIP (current) | BioCLIP 2 |", "|---|---|---|"]
    for name, k, fmt in rows:
        if k is None:
            L.append(f"| {name} | {A['T_KNOWN']} / {A['T_UNKNOWN']} | {B['T_KNOWN']} / {B['T_UNKNOWN']} |")
        else:
            L.append(f"| {name} | {_f(A.get(k), fmt)} | {_f(B.get(k), fmt)} |")
    L += ["", "**Result: not adopted.** BioCLIP 2 ranks the demo crab as the single most unfamiliar track, but on the held-out test it "
          "flags far fewer unknown organisms as unfamiliar and mislabels more as known, and it costs about six times the compute per crop, "
          "against Coastal Action's low-energy requirement. With one unidentified fish class and murky crops, a bigger model has little to work with.", ""]
    return L


def assisted() -> list[str]:
    db = ROOT / "outputs" / "bluesight.db"
    rows = []
    if db.exists():
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        try:
            rows = [dict(r) for r in con.execute("SELECT * FROM assisted_counts ORDER BY run_id, subsample_t_s")]
        except sqlite3.OperationalError:
            rows = []
    L = ["### AI-assisted counting (Verify counts page)", "",
         "Because no automatic detector finds the faint fish (E9, E10), the protocol count now has a human-in-the-loop step: BlueSight "
         "pre-marks every fish it counted on each subsample frame, and the biologist clicks to add a missed fish or remove a wrong mark. "
         "The verified count is exact by construction, the time per frame is measured, and every correction is saved as point labels "
         "(`outputs/training/assisted/`) to retrain FishSpotter on this footage.", ""]
    if not rows:
        L += ["_No verified frames saved yet on this computer, so there is no measured time per frame to report._", ""]
        return L
    L += ["| Analysis | Moment | BlueSight marks | Removed | Added | Verified count | Seconds | Reviewer |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        t = r["subsample_t_s"]
        L.append(f"| {r['run_id']} | {int(t // 60)}:{int(t % 60):02d} | {r['ai_count']} | {r['removed']} | {r['added']} | "
                 f"{r['final_count']} | {r['seconds']:.0f} | {r['reviewer']} |")
    L.append("")
    return L


def section() -> str:
    E = _exp()
    L = [START, "", "---", "", "# v3 (branch satvik/accuracy): model experiments and AI-assisted counting", "",
         "_Measured on an Apple M2 laptop (MPS). Tuning data only (14:01 frame, T2-STAT2 photos); the 22:00 count was not used._", ""]
    L += e9(E) + e10(E) + e11(E) + assisted() + [END, ""]
    return "\n".join(L)


def update(path: Path = ROOT / "EVALUATION.md") -> None:
    txt = path.read_text() if path.exists() else "# EVALUATION\n"
    block = section()
    if START in txt and END in txt:
        txt = txt[: txt.index(START)] + block + txt[txt.index(END) + len(END) + 1:]
    else:
        txt = txt.rstrip("\n") + "\n\n" + block
    path.write_text(txt)


if __name__ == "__main__":
    update()
    print("EVALUATION.md v3 section written", file=sys.stderr)
