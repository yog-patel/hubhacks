"""Count check: a person checks the AI's count on each 60-second subsample frame (assisted), or counts blind for QC."""
from __future__ import annotations

import json
import time
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import streamlit as st

from bluesight import countcheck as CC
from bluesight.config import path
from bluesight.io_video import read_frame_at, resize_width

from . import common as C
from . import theme as T

MODES = {"assisted": "Check the AI's marks", "blind": "Blind count (quality control)"}


def _video_path(cfg: dict, rep: dict) -> Path:
    v = Path(cfg["_root"]) / cfg["paths"]["videos_dir"] / rep["video_file"]
    return v if v.exists() else Path(cfg["_root"]) / "outputs" / "uploads" / rep["video_file"]


def frame_image(cfg: dict, rep: dict, t: float, width: int = 1280) -> np.ndarray | None:
    """Sampled frame at time t: the cached thumbnail when available, else decoded from the video."""
    rows = C.db().q("SELECT frame_idx FROM frames WHERE run_id=? AND abs(t_s-?)<0.002", (rep["run_id"], t))
    cdir = rep.get("cache_dir")
    if rows and cdir:
        p = Path(cdir) / "thumbs" / f"{rows[0]['frame_idx']:07d}.jpg"
        if p.exists():
            img = cv2.imread(str(p))
            if img is not None:
                return resize_width(img, width)[0]
    v = _video_path(cfg, rep)
    if v.exists():
        f = read_frame_at(v, t)
        if f is not None:
            return resize_width(f, width)[0]
    return None


def kind(label: str, invert: set[str]) -> str:
    """Plain-language category of an AI mark."""
    if label in invert:
        return "Invertebrate"
    if label.startswith("Unknown"):
        return "Too murky to identify"
    if label.startswith("Unconfirmed"):
        return "Probably a fish (unconfirmed)"
    if label.startswith("Unfamiliar"):
        return "Unfamiliar"
    return "Identified fish"


KIND_COLOURS = {"Identified fish": (0, 210, 255), "Probably a fish (unconfirmed)": (0, 140, 255),
                "Too murky to identify": (230, 200, 120), "Unfamiliar": (60, 60, 255), "Invertebrate": (200, 80, 200)}
KIND_SWATCH = {"Identified fish": "#ffd200", "Probably a fish (unconfirmed)": "#ff8c00", "Too murky to identify": "#78c8e6",
               "Unfamiliar": "#ff3c3c", "Invertebrate": "#c850c8"}


def draw_marks(img: np.ndarray, marks: list[dict], removed: set[int], scale: float, invert: set[str]) -> np.ndarray:
    """Number every AI mark, coloured by category; removed marks are crossed out in grey."""
    out = img.copy()
    for m in marks:
        x1, y1, x2, y2 = (int(m[k] * scale) for k in ("x1", "y1", "x2", "y2"))
        pad = 4
        x1, y1, x2, y2 = x1 - pad, y1 - pad, x2 + pad, y2 + pad
        gone = m["mark"] in removed
        col = (150, 150, 150) if gone else KIND_COLOURS[kind(m["label"], invert)]
        cv2.rectangle(out, (x1, y1), (x2, y2), col, 2)
        if gone:
            cv2.line(out, (x1, y1), (x2, y2), col, 2)
            cv2.line(out, (x1, y2), (x2, y1), col, 2)
        label = str(m["mark"])
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
        cv2.rectangle(out, (x1, max(0, y1 - th - 6)), (x1 + tw + 6, y1), col, -1)
        cv2.putText(out, label, (x1 + 3, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 2)
    return out


def page() -> None:
    cfg = C.cfg()
    db = C.db()
    CC.ensure(db)
    T.header("Quality control", "Count check",
             "Check the AI's count on each 60-second subsample, the same frames the protocol asks you to count. "
             "Remove marks that aren't fish and add any it missed: a few clicks instead of a full manual count. "
             "Your corrections replace the AI's numbers in the report and are saved as training data.")
    runs = C.list_runs()
    if not runs:
        T.empty_state("Nothing to check yet", "Subsample frames appear here after you analyse a video.",
                      "Go to <b>Analyze</b> and run a video first.")
        return
    labels = [C.run_label(r) for r in runs]
    default = next((i for i, r in enumerate(runs) if r["run_id"] == st.session_state.get("last_run")), 0)
    idx = st.selectbox("Analysis", range(len(runs)), index=default, format_func=lambda i: labels[i], key="check_run")
    rep = C.load_report(runs[idx])
    st.session_state["last_run"] = rep["run_id"]
    subs = rep.get("subsamples", [])
    if not subs:
        st.info("This analysis has no subsamples.")
        return
    rows = CC.checks(db, rep["run_id"])
    s = CC.summary(rep, rows)
    agree = s["blind_agreement_pct"]
    T.cards([
        {"k": "Subsamples checked", "v": f"{s['n_checked']} of {s['n_subsamples']}", "tone": "ok" if s["n_checked"] == s["n_subsamples"] else "attn",
         "d": "checked by a person (the rest keep the AI's count)"},
        {"k": "MeanCount", "v": f"{s['MeanCount_checked']:.1f}", "tone": "info",
         "d": f"with your checks · AI alone {s['MeanCount_ai']:.1f}"},
        {"k": "Blind-count agreement", "v": "—" if agree is None else f"{agree:.0f}", "unit": "" if agree is None else "%",
         "tone": "info" if agree is None else ("ok" if agree >= CC.AGREEMENT_TARGET else "attn"),
         "d": "protocol target 95% · do a few blind counts to measure it" if agree is None
              else f"over {s['n_blind']} frames · {s['blind_frames_within_6pct']} within 6% · target 95%"},
        {"k": "Corrections so far", "v": s["marks_removed"] + s["fish_added"], "tone": "info",
         "d": f"{s['marks_removed']} wrong marks removed · {s['fish_added']} missed fish added"},
    ])

    done = {(round(r["subsample_t_s"], 3), r["mode"]) for r in rows}
    mode = st.radio("How do you want to count?", list(MODES), format_func=MODES.get, horizontal=True, key="check_mode",
                    captions=["Fast: the AI's marks are shown, you fix them", "The AI's marks are hidden; compare afterwards"])
    opts = list(range(len(subs)))

    def fmt(i: int) -> str:
        tick = "✓ " if (round(subs[i]["subsample_t_s"], 3), mode) in done else ""
        return f"{tick}Subsample {i + 1} · {subs[i]['time']}"
    first_open = next((i for i in opts if (round(subs[i]["subsample_t_s"], 3), mode) not in done), 0)
    cur = st.session_state.get("check_cursor", first_open)
    cur = min(max(0, int(cur)), len(subs) - 1)
    pick = st.selectbox("Subsample", opts, index=cur, format_func=fmt, key=f"check_pick_{mode}_{rep['run_id']}_{cur}")
    sub = subs[pick]
    dets = db.q("SELECT t_s, label FROM detections WHERE run_id=? AND abs(t_s-?)<=0.6", (rep["run_id"], sub["subsample_t_s"]))
    ft = CC.frame_time_for(sub, dets, float(cfg["protocol"]["count_window_s"]))
    marks = CC.ai_marks(db, rep["run_id"], ft)
    invert = set(cfg.get("invertebrate_species") or [])
    ai_fish = sum(1 for m in marks if m["label"] not in invert)
    ai_inv = len(marks) - ai_fish
    key = f"{rep['run_id']}_{pick}_{mode}"
    st.session_state.setdefault(f"t0_{key}", time.time())
    prev = next((r for r in rows if round(r["subsample_t_s"], 3) == round(sub["subsample_t_s"], 3) and r["mode"] == mode), None)

    img = frame_image(cfg, rep, ft)
    scale = (img.shape[1] / float(rep.get("process_width", cfg["sampling"]["process_width"]))) if img is not None else 1.0
    title = "Fix the AI’s marks" if mode == "assisted" else "Count the fish you can see"
    with st.container(border=True, key="check_card"):
        h1, h2 = st.columns([4, 1], vertical_alignment="center")
        h1.html(f'<div class="bs-item-head">{T.visibility_badge(float(sub.get("visibility", 0)), float(cfg["identify"]["V_MIN"]))}'
                f'<span class="bs-small">Subsample {pick + 1} of {len(subs)}</span></div>'
                f'<p class="bs-item-title">{title}</p>')
        h2.html(f'<p class="bs-when"><b>{C.fmt_t(ft)}</b>{T.esc(rep["video_file"])}</p>')
        left, right = st.columns([3, 1], gap="large")
        with right:
            if mode == "assisted":
                rm_default = [] if prev is None else json.loads(prev["removed"] or "[]")
                kinds: dict[str, list[int]] = {}
                for m in marks:
                    kinds.setdefault(kind(m["label"], invert), []).append(m["mark"])
                drop = st.multiselect("Remove a whole category", list(kinds), key=f"kd_{key}",
                                      format_func=lambda k: f"{k} ({len(kinds[k])})", placeholder="e.g. too murky",
                                      help="Quick way to clear many wrong marks at once, e.g. on sand.")
                rm_default = sorted(set(rm_default) | {i for k in drop for i in kinds[k]})
                removed = st.multiselect("Marks that are NOT fish", [m["mark"] for m in marks], default=rm_default,
                                         key=f"rm_{key}_{'_'.join(sorted(drop))}", placeholder="Pick mark numbers to remove",
                                         help="Sand, the pole, a shadow, a bubble, or the same fish counted twice.")
                missed = st.number_input("Fish the AI missed", 0, 500, int(prev["missed_fish"]) if prev else 0, 1, key=f"ms_{key}",
                                         help="Only fish you can confirm with two cues: shape, fins/eye, colour flash or swimming.")
                kept_fish = sum(1 for m in marks if m["label"] not in invert and m["mark"] not in set(removed))
                kept_inv = sum(1 for m in marks if m["label"] in invert and m["mark"] not in set(removed))
                inv = st.number_input("Invertebrates (crabs, shrimp, snails)", 0, 500,
                                      int(prev["human_invert"]) if prev else kept_inv, 1, key=f"iv_{key}")
                human = kept_fish + int(missed)
                st.html(f'<div class="bs-readout"><p class="lbl">Your count</p><div class="num">{human}<span> fish</span></div>'
                        f'<p class="bs-small">AI marked {ai_fish} fish · you removed {len(removed)} · added {int(missed)}</p></div>')
            else:
                removed, missed = [], 0
                human = st.number_input("Fish you can count", 0, 500, int(prev["human_fish"]) if prev else 0, 1, key=f"hb_{key}")
                inv = st.number_input("Invertebrates", 0, 500, int(prev["human_invert"]) if prev else 0, 1, key=f"ib_{key}")
            notes = st.text_input("Notes (optional)", prev["notes"] if prev else "", key=f"nt_{key}",
                                  placeholder="e.g. school at top left, only 5 clear")
            ok = bool(C.reviewer())
            if not ok:
                st.warning("Add your name under **Reviewer** in the sidebar to save.", icon=":material/badge:")
            if st.button("Save and next", type="primary", icon=":material/check:", width="stretch", disabled=not ok,
                         key=f"save_{key}"):
                spent = time.time() - st.session_state.pop(f"t0_{key}", time.time())
                CC.save_check(db, rep["run_id"], sub["subsample_t_s"], ft, mode, C.reviewer(), ai_fish, ai_inv,
                              list(removed), int(missed), int(human), int(inv), notes, round(spent, 1))
                if mode == "blind":
                    d = CC.pct_difference(ai_fish, int(human))
                    st.toast(f"Saved. AI counted {ai_fish}, you counted {int(human)}: {d:.0f}% difference "
                             f"({'within' if d < CC.PCT_DIFF_LIMIT else 'over'} the protocol's 6%).", icon=":material/check_circle:")
                else:
                    st.toast(f"Saved: {int(human)} fish on subsample {pick + 1}.", icon=":material/check_circle:")
                st.session_state["check_cursor"] = min(pick + 1, len(subs) - 1)
                st.rerun()
        with left:
            if img is None:
                st.info("The frame isn't available on this computer (the original video was moved).")
            else:
                shown = draw_marks(img, marks, set(removed), scale, invert) if mode == "assisted" else img
                st.image(cv2.cvtColor(shown, cv2.COLOR_BGR2RGB), width="stretch",
                         alt=f"Subsample frame at {C.fmt_t(ft)}" + (f" with {len(marks)} numbered AI marks" if mode == "assisted" else ""))
                if mode == "assisted":
                    present = {kind(m["label"], invert) for m in marks}
                    st.html('<p class="bs-small">' + " · ".join(
                        f'<span style="display:inline-block;width:10px;height:10px;border:2px solid {KIND_SWATCH[k]};'
                        f'margin-right:4px"></span>{T.esc(k)}' for k in KIND_SWATCH if k in present) + " · grey ✕ = removed</p>")
                st.caption(("Numbered boxes are the AI's marks. Click the image's expand icon to zoom. "
                            if mode == "assisted" else "") +
                           "Protocol rule: count a fish only if you can confirm it with two cues; uncertain movement is not counted.")
                ctx = []
                for dt_ in (-1.0, -0.5, 0.5, 1.0):
                    im = frame_image(cfg, rep, round(ft + dt_, 3), 320)
                    if im is not None:
                        ctx.append((dt_, im))
                if ctx:
                    with st.expander("Context: half a second and one second either side"):
                        cols = st.columns(len(ctx))
                        for c, (d, im) in zip(cols, ctx):
                            c.image(cv2.cvtColor(im, cv2.COLOR_BGR2RGB), caption=f"{d:+.1f} s", width="stretch")

    if rows:
        with st.expander(f"Checked subsamples ({len(rows)})"):
            df = pd.DataFrame(rows)
            df["time"] = df.subsample_t_s.map(C.fmt_t)
            df["difference %"] = [round(CC.pct_difference(a, h), 1) for a, h in zip(df.ai_fish, df.human_fish)]
            st.dataframe(df[["time", "mode", "reviewer", "ai_fish", "human_fish", "difference %", "missed_fish",
                             "human_invert", "seconds_spent", "notes"]].rename(columns={
                "time": "Subsample", "mode": "Mode", "reviewer": "Reviewer", "ai_fish": "AI fish", "human_fish": "Your fish",
                "missed_fish": "Added", "human_invert": "Invertebrates", "seconds_spent": "Seconds", "notes": "Notes"}),
                hide_index=True, width="stretch")
        if any(r["mode"] == "assisted" for r in rows):
            if st.button("Save corrections as training data", icon=":material/model_training:",
                         help="Writes the checked frames and corrected boxes to outputs/training_labels/ for a future "
                              "detector trained on Nova Scotia footage. Stays on this computer."):
                pw = int(rep.get("process_width", cfg["sampling"]["process_width"]))
                folder = CC.export_training_labels(db, rep, path(cfg, "outputs_dir") / "training_labels",
                                                   lambda t: frame_image(cfg, rep, t, pw))
                st.success(f"Saved to {folder}.")
