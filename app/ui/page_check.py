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

MODES = {"assisted": "Fix the AI's marks", "blind": "Count without hints"}


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
        return "Crab or shrimp"
    if label.startswith("Unknown"):
        return "Too murky"
    if label.startswith("Unconfirmed"):
        return "Maybe a fish"
    if label.startswith("Unfamiliar"):
        return "New animal"
    return "Fish"


KIND_COLOURS = {"Fish": (0, 210, 255), "Maybe a fish": (0, 140, 255),
                "Too murky": (230, 200, 120), "New animal": (60, 60, 255), "Crab or shrimp": (200, 80, 200)}
KIND_SWATCH = {"Fish": "#ffd200", "Maybe a fish": "#ff8c00", "Too murky": "#78c8e6",
               "New animal": "#ff3c3c", "Crab or shrimp": "#c850c8"}


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


def density_map(rep: dict, ft: float) -> np.ndarray | None:
    """The counting model's per-patch density for a subsample frame (None if the model was not run)."""
    d = rep.get("density") or {}
    f = d.get("maps")
    if not f or not Path(f).exists():
        return None
    z = np.load(f)
    k = f"{ft:.3f}"
    return z[k].astype(np.float32) if k in z.files else None


def overlay_density(img: np.ndarray, d: np.ndarray) -> np.ndarray:
    """Blend a cyan glow where the counting model places fish."""
    h, w = img.shape[:2]
    m = cv2.resize(d, (w, h), interpolation=cv2.INTER_CUBIC)
    m = cv2.GaussianBlur(np.clip(m, 0, None), (0, 0), 6)
    m = np.clip(m / (np.percentile(m, 99.7) + 1e-6), 0, 1)[..., None]
    glow = np.zeros_like(img)
    glow[..., 0], glow[..., 1] = 255, 220
    return (img * (1 - 0.65 * m) + glow * 0.65 * m).astype(np.uint8)


def page() -> None:
    cfg = C.cfg()
    db = C.db()
    CC.ensure(db)
    T.header("", "Check the counts", "One frame per minute, like the protocol. Fix what the AI got wrong.", step=2)
    runs = C.list_runs()
    if not runs:
        T.empty_state("Nothing to check yet", "Analyze a video first.")
        return
    labels = [C.run_label(r) for r in runs]
    default = next((i for i, r in enumerate(runs) if r["run_id"] == st.session_state.get("last_run")), 0)
    idx = st.selectbox("Video", range(len(runs)), index=default, format_func=lambda i: labels[i], key="check_run",
                       label_visibility="collapsed")
    rep = C.load_report(runs[idx])
    st.session_state["last_run"] = rep["run_id"]
    subs = rep.get("subsamples", [])
    if not subs:
        st.info("No check points in this analysis.")
        return
    rows = CC.checks(db, rep["run_id"])
    s = CC.summary(rep, rows)
    agree = s["blind_agreement_pct"]
    T.stats([
        {"k": f"of {s['n_subsamples']} check points done", "v": s["n_checked"],
         "tone": "ok" if s["n_checked"] == s["n_subsamples"] else ""},
        {"k": "fish per check point" + (", with your checks" if s["n_checked"] else ", AI only"), "v": f"{s['MeanCount_checked']:.1f}",
         "tip": f"Protocol MeanCount. AI alone: {s['MeanCount_ai']:.1f}"},
        {"k": "agreement in no-hint counts (target 95%)", "v": "–" if agree is None else f"{agree:.0f}",
         "unit": "" if agree is None else "%", "tone": "" if agree is None else ("ok" if agree >= CC.AGREEMENT_TARGET else "attn")},
    ])

    done = {(round(r["subsample_t_s"], 3), r["mode"]) for r in rows}
    mode = st.segmented_control("Mode", list(MODES), format_func=MODES.get, default="assisted", key="check_mode",
                                label_visibility="collapsed") or "assisted"
    opts = list(range(len(subs)))

    def fmt(i: int) -> str:
        tick = "✓ " if (round(subs[i]["subsample_t_s"], 3), mode) in done else ""
        flag = "  ⚑ check first" if subs[i].get("estimates_disagree") else ""
        return f"{tick}Check point {i + 1} · {subs[i]['time']}{flag}"
    order = sorted(opts, key=lambda i: (not subs[i].get("estimates_disagree"), i))
    first_open = next((i for i in order if (round(subs[i]["subsample_t_s"], 3), mode) not in done), 0)
    cur = st.session_state.get("check_cursor", first_open)
    cur = min(max(0, int(cur)), len(subs) - 1)
    pick = st.selectbox("Check point", opts, index=cur, format_func=fmt, key=f"check_pick_{mode}_{rep['run_id']}_{cur}",
                        label_visibility="collapsed")
    tiles = "".join(
        f'<i class="{" ".join(c for c in ("done" if (round(x["subsample_t_s"], 3), mode) in done else "", "flag" if x.get("estimates_disagree") else "", "cur" if i == pick else "") if c)}" '
        f'title="{x["time"]}">{i + 1}</i>' for i, x in enumerate(subs))
    if len(subs) > 1:
        st.html(f'<div class="bs-strip" style="--n:{len(subs)}" role="img" aria-label="check point progress">{tiles}</div>'
                '<p class="bs-strip-key">Green = done · orange outline = the two AI counts disagree, check these first</p>')
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
    dmap = density_map(rep, ft)
    scale = (img.shape[1] / float(rep.get("process_width", cfg["sampling"]["process_width"]))) if img is not None else 1.0
    title = f"Check point {pick + 1} of {len(subs)}"
    with st.container(border=True, key="check_card"):
        h1, h2 = st.columns([4, 1], vertical_alignment="center")
        h1.html(f'<div class="bs-item-head">{T.visibility_badge(float(sub.get("visibility", 0)), float(cfg["identify"]["V_MIN"]))}'
                + (T.plain_badge("Check first", "warn", "⚑") if sub.get("estimates_disagree") else "") + '</div>'
                f'<p class="bs-item-title">{title}</p>')
        h2.html(f'<p class="bs-when"><b>{C.fmt_t(ft)}</b>{T.esc(rep["video_file"])}</p>')
        left, right = st.columns([5, 2], gap="large")
        with right:
            if mode == "assisted":
                rm_default = [] if prev is None else json.loads(prev["removed"] or "[]")
                kinds: dict[str, list[int]] = {}
                for m in marks:
                    kinds.setdefault(kind(m["label"], invert), []).append(m["mark"])
                st.html('<p class="bs-choice" style="margin:0 0 4px">Remove a whole group</p>')
                drop = [k for k in kinds if st.checkbox(f"{k} · {len(kinds[k])}", key=f"kd_{key}_{k}",
                                                        help="Untick to bring them back")]
                rm_default = sorted(set(rm_default) | {i for k in drop for i in kinds[k]})
                removed = st.multiselect("Remove by number", [m["mark"] for m in marks], default=rm_default,
                                         key=f"rm_{key}_{'_'.join(sorted(drop))}", placeholder="Box numbers that aren't fish",
                                         help="Sand, the pole, a shadow, a bubble, or the same fish twice.")
                missed = st.number_input("Fish it missed", 0, 500, int(prev["missed_fish"]) if prev else 0, 1, key=f"ms_{key}",
                                         help="Only fish you're sure of: shape, fins, a flash of colour or swimming.")
                kept_fish = sum(1 for m in marks if m["label"] not in invert and m["mark"] not in set(removed))
                kept_inv = sum(1 for m in marks if m["label"] in invert and m["mark"] not in set(removed))
                inv = st.number_input("Crabs, shrimp, snails", 0, 500,
                                      int(prev["human_invert"]) if prev else kept_inv, 1, key=f"iv_{key}")
                human = kept_fish + int(missed)
                st.html(f'<div class="bs-readout"><p class="lbl">Your count</p><div class="num">{human}<span> fish</span></div>'
                        f'<p class="bs-small">AI boxes {ai_fish} − {len(removed)} removed + {int(missed)} added'
                        + (f'<br>Second AI count: {sub["density_count"]:.0f}' if sub.get("density_count") is not None else "")
                        + '</p></div>')
            else:
                removed, missed = [], 0
                human = st.number_input("Fish you can see", 0, 500, int(prev["human_fish"]) if prev else 0, 1, key=f"hb_{key}")
                inv = st.number_input("Crabs, shrimp, snails", 0, 500, int(prev["human_invert"]) if prev else 0, 1, key=f"ib_{key}")
            notes = st.text_input("Note", prev["notes"] if prev else "", key=f"nt_{key}", placeholder="Optional")
            ok = bool(C.reviewer())
            if not ok:
                st.warning("Type your name in the sidebar to save.", icon=":material/badge:")
            if st.button("Save and next", type="primary", icon=":material/check:", width="stretch", disabled=not ok,
                         key=f"save_{key}"):
                spent = time.time() - st.session_state.pop(f"t0_{key}", time.time())
                CC.save_check(db, rep["run_id"], sub["subsample_t_s"], ft, mode, C.reviewer(), ai_fish, ai_inv,
                              list(removed), int(missed), int(human), int(inv), notes, round(spent, 1))
                if mode == "blind":
                    d = CC.pct_difference(ai_fish, int(human))
                    st.toast(f"AI {ai_fish}, you {int(human)}: {d:.0f}% apart "
                             f"({'OK' if d < CC.PCT_DIFF_LIMIT else 'over the 6% limit'})", icon=":material/check_circle:")
                else:
                    st.toast(f"Saved: {int(human)} fish", icon=":material/check_circle:")
                st.session_state["check_cursor"] = min(pick + 1, len(subs) - 1)
                st.rerun()
        with left:
            if img is None:
                st.info("This frame isn't on this computer any more.")
            else:
                shown = draw_marks(img, marks, set(removed), scale, invert) if mode == "assisted" else img
                if mode == "assisted" and dmap is not None and st.toggle(
                        "Show where fish are likely", key=f"hm_{key}",
                        help="Blue glow from the second AI count. Helps you spot faint fish the boxes missed."):
                    shown = overlay_density(shown, dmap)
                st.image(cv2.cvtColor(shown, cv2.COLOR_BGR2RGB), width="stretch",
                         alt=f"Subsample frame at {C.fmt_t(ft)}" + (f" with {len(marks)} numbered AI marks" if mode == "assisted" else ""))
                if mode == "assisted":
                    present = {kind(m["label"], invert) for m in marks}
                    st.html('<p class="bs-small">' + " · ".join(
                        f'<span style="display:inline-block;width:10px;height:10px;border:2px solid {KIND_SWATCH[k]};'
                        f'margin-right:4px"></span>{T.esc(k)}' for k in KIND_SWATCH if k in present) + " · grey ✕ removed</p>")
                ctx = []
                for dt_ in (-1.0, -0.5, 0.5, 1.0):
                    im = frame_image(cfg, rep, round(ft + dt_, 3), 320)
                    if im is not None:
                        ctx.append((dt_, im))
                if ctx:
                    with st.expander("Frames just before and after"):
                        cols = st.columns(len(ctx))
                        for c, (d, im) in zip(cols, ctx):
                            c.image(cv2.cvtColor(im, cv2.COLOR_BGR2RGB), caption=f"{d:+.1f} s", width="stretch")

    if rows:
        with st.expander(f"Your checks ({len(rows)})"):
            df = pd.DataFrame(rows)
            df["time"] = df.subsample_t_s.map(C.fmt_t)
            df["difference %"] = [round(CC.pct_difference(a, h), 1) for a, h in zip(df.ai_fish, df.human_fish)]
            st.dataframe(df[["time", "mode", "reviewer", "ai_fish", "human_fish", "difference %", "missed_fish",
                             "human_invert", "seconds_spent", "notes"]].rename(columns={
                "time": "Check point", "mode": "Mode", "reviewer": "Reviewer", "ai_fish": "AI fish", "human_fish": "Your fish",
                "missed_fish": "Added", "human_invert": "Crabs/shrimp", "seconds_spent": "Seconds", "notes": "Notes"}),
                hide_index=True, width="stretch")
        if any(r["mode"] == "assisted" for r in rows):
            if st.button("Use my checks to improve the AI", icon=":material/model_training:",
                         help="Saves the checked frames and your corrections as training data (stays on this computer)."):
                pw = int(rep.get("process_width", cfg["sampling"]["process_width"]))
                folder = CC.export_training_labels(db, rep, path(cfg, "outputs_dir") / "training_labels",
                                                   lambda t: frame_image(cfg, rep, t, pw))
                st.success(f"Saved to {folder}.")
