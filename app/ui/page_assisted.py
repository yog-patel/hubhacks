"""Verify counts: AI-assisted counting on the protocol subsample frames.

The pipeline pre-marks every fish it counted on a subsample frame; the biologist clicks to add a missed fish or
to remove a wrong mark, then saves. The verified count is exact, the time per frame is measured, and every
correction is exported as point labels for retraining FishSpotter.
"""
from __future__ import annotations

import time

import cv2
import numpy as np
import pandas as pd
import streamlit as st

from bluesight import assisted as A
from bluesight.config import path
from bluesight.logs import get_logger

from . import common as C
from . import theme as T

log = get_logger("app")

# zoom views: the whole frame or one ninth of it; (x0, y0, w, h) as fractions of the frame
REGIONS = {"Whole frame": (0.0, 0.0, 1.0, 1.0)}
for _r, _rn in enumerate(("Top", "Middle", "Bottom")):
    for _c, _cn in enumerate(("left", "centre", "right")):
        REGIONS[f"{_rn} {_cn}"] = (_c / 3, _r / 3, 1 / 3, 1 / 3)


@st.cache_data(show_spinner=False, max_entries=8)
def frame_at(video: str, frame_idx: int, width: int) -> np.ndarray | None:
    """Exact sampled frame (by index) resized to the detection width."""
    cap = cv2.VideoCapture(video)
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_idx))
    ok, fr = cap.read()
    cap.release()
    if not ok:
        return None
    h, w = fr.shape[:2]
    return cv2.resize(fr, (width, int(round(h * width / w))), interpolation=cv2.INTER_AREA)


NOT_COUNTED = "transient (not counted)"  # how the pipeline stores uncounted detections in the database


def run_dets(run_id: str) -> list[dict]:
    rows = C.db().q("SELECT frame_idx, t_s, x1, y1, x2, y2, label FROM detections WHERE run_id=?", (run_id,))
    for r in rows:
        if r["label"] == NOT_COUNTED:
            r["label"] = None
    return rows


def manual_counts(cfg: dict) -> list[dict]:
    """The biologists' own counts (data/ground_truth/manual_counts.csv), shown as a reference where they exist."""
    f = path(cfg, "ground_truth_dir") / "manual_counts.csv"
    return pd.read_csv(f).to_dict("records") if f.exists() else []


def ai_counts_for(dets: list[dict], points: list[float], window: float) -> dict[float, int]:
    return {float(p): len(A.protocol_frame(dets, p, window)[1]) for p in points}


def page() -> None:
    cfg = C.cfg()
    T.header("Step 2b · AI-assisted count", "Verify counts",
             "AquaLens pre-marks the fish it counted on each protocol subsample frame. Click a fish it missed to add it, "
             "click a wrong mark to remove it, then save. The verified count goes into the report.")
    runs = C.list_runs()
    if not runs:
        T.empty_state("Nothing to verify yet", "Verified counts start from an analysis.",
                      "Go to <b>Analyze</b>, pick a video and press <b>Analyze video</b>.")
        st.page_link(C.PAGES["analyze"], label="Go to Analyze", icon=":material/play_arrow:")
        return
    labels = [C.run_label(r) for r in runs]
    default = next((i for i, r in enumerate(runs) if r["run_id"] == st.session_state.get("last_run")), 0)
    idx = st.selectbox("Analysis", range(len(runs)), index=default, format_func=lambda i: labels[i], key="assist_run")
    run = runs[idx]
    rep = C.load_report(run)
    st.session_state["last_run"] = rep["run_id"]
    run_id = rep["run_id"]
    window = float(cfg["protocol"]["count_window_s"])
    points = [float(s["subsample_t_s"]) for s in rep["subsamples"]]
    dets = run_dets(run_id)
    saved = A.load_saved(C.db(), run_id)
    ai_counts = ai_counts_for(dets, points, window)
    video = str(path(cfg, "videos_dir") / rep["video_file"])
    width = int(cfg["sampling"]["process_width"])
    radius = float(cfg["assisted"]["click_radius_px"])

    sm = A.summary(saved, points, ai_counts)
    cards = [{"k": "Frames verified", "v": f"{sm['n_verified']} / {sm['n_points']}", "tone": "ok" if sm["n_verified"] == sm["n_points"] else "attn",
              "d": "protocol subsamples, one every 60 s"}]
    if sm["n_verified"]:
        cards += [
            {"k": "Verified MeanCount", "v": f"{sm['MeanCount_verified']:.1f}", "tone": "info",
             "d": f"AI alone on the same frames: {sm['MeanCount_ai_same_frames']:.1f}"},
            {"k": "AI marks kept", "v": f"{sm['ai_kept_pct']:.0f}", "unit": "%", "tone": "info",
             "d": f"the AI pre-marked {sm['ai_found_pct']:.0f}% of the fish you confirmed"},
            {"k": "Time per frame", "v": f"{sm['median_seconds_per_frame']:.0f}", "unit": "s", "tone": "ok",
             "d": "median, measured while you verified"},
        ]
    T.cards(cards)

    # extra moments (e.g. an instant the biologists counted by hand): saved ones + ones added this session
    w = rep["window"]
    extra_key = f"assist_extra_{run_id}"
    extras = sorted(set(st.session_state.get(extra_key, [])) | {p for p in saved if p not in points})
    all_pts = points + [p for p in extras if p not in points]
    gt = {float(r["time_s"]): r for r in manual_counts(cfg) if r.get("video_file") == rep["video_file"]}

    def pt_label(i: int) -> str:
        p = all_pts[i]
        tick = "✓ " if p in saved else ""
        tag = "" if p in points else " · extra"
        return f"{tick}{C.fmt_t(p)}{tag}"

    pend = st.session_state.pop(f"assist_pt_next_{run_id}", None)  # a jump requested on the previous run
    if pend is not None and 0 <= pend < len(all_pts):
        st.session_state[f"assist_pt_{run_id}"] = pend
    pi = st.segmented_control("Subsample", range(len(all_pts)), format_func=pt_label, default=0, key=f"assist_pt_{run_id}",
                              help="✓ = verified and saved. The frame used is the one the protocol count uses (within ±0.5 s).")
    pi = 0 if pi is None else pi
    with st.expander("Verify another moment", icon=":material/add_circle:"):
        st.caption("Pick any time inside this analysis, for example an instant the team has already counted by hand, "
                   "to compare. Extra moments are saved but not added to the protocol MeanCount.")
        e1, e2 = st.columns([3, 1], vertical_alignment="bottom")
        hint = next((t for t in gt if w["start_s"] <= t <= w["end_s"]), w["start_s"])
        t_new = e1.number_input("Video time (seconds)", min_value=float(w["start_s"]), max_value=float(w["end_s"]),
                                value=float(hint), step=1.0, key=f"assist_newt_{run_id}")
        if e2.button("Add moment", icon=":material/add:", width="stretch"):
            st.session_state[extra_key] = sorted(set(st.session_state.get(extra_key, [])) | {float(round(t_new, 1))})
            st.session_state[f"assist_pt_next_{run_id}"] = len(points) + [p for p in sorted(set(st.session_state[extra_key]) | set(extras)) if p not in points].index(float(round(t_new, 1)))
            st.rerun()
    point = all_pts[pi]
    ref = next((r for t, r in gt.items() if abs(t - point) <= 1.0), None)
    frame_t, ai_marks = A.protocol_frame(dets, point, window)
    if frame_t is None:
        st.info("No sampled frame near this subsample.", icon=":material/info:")
        return
    fidx = next(int(d["frame_idx"]) for d in dets if abs(float(d["t_s"]) - frame_t) < 1e-3)
    skey = f"assist_session_{run_id}_{point}"
    if skey not in st.session_state:
        s = A.new_session(run_id, point, frame_t, ai_marks)
        if point in saved:  # re-open a saved frame with the verified marks
            import json

            s.marks = [A.Mark(**m) for m in json.loads(saved[point]["marks"])]
            s.ai_count = int(saved[point]["ai_count"])
        st.session_state[skey] = s
        st.session_state[skey + "_t0"] = time.time()
        st.session_state[skey + "_last"] = None
    s: A.Session = st.session_state[skey]

    with st.spinner("Loading frame…"):
        frame = frame_at(video, fidx, width)
    if frame is None:
        st.error(f"Could not read frame {fidx} from {rep['video_file']}.", icon=":material/error:")
        return

    T.section("This frame", hint=f"video time {C.fmt_t(frame_t)} ({frame_t:.2f} s)")
    cs = [{"k": "Count", "v": s.final_count, "tone": "info", "d": f"AquaLens pre-marked {s.ai_count}"},
          {"k": "Your corrections", "v": f"+{s.added} / −{len(s.removed_ai)}", "tone": "attn" if (s.added or s.removed_ai) else "",
           "d": "fish added / wrong marks removed"}]
    if ref is not None:
        inv = ref.get("invertebrates")
        inv_txt = f" + {int(inv)} invertebrate" if isinstance(inv, (int, float)) and inv == inv and inv > 0 else ""
        cs.append({"k": "Biologists' hand count", "v": int(ref["total_fish"]), "tone": "ok",
                   "d": f"fish{inv_txt}, counted manually at {C.fmt_t(float(ref['time_s']))}"})
    T.cards(cs)

    region = st.segmented_control("Zoom", list(REGIONS), default="Whole frame", key=f"assist_zoom_{run_id}",
                                 help="Faint fish are easier to see in a zoomed ninth of the frame. Clicks work in every view.")
    region = region or "Whole frame"
    _, b1, b2, b3 = st.columns([3, 1.2, 1.2, 1.8], vertical_alignment="bottom")
    if b1.button("Undo removal", icon=":material/undo:", disabled=not s.removed_ai, width="stretch"):
        A.undo_remove(s)
        st.rerun()
    if b2.button("Reset", icon=":material/restart_alt:", width="stretch", help="Back to AquaLens's marks"):
        st.session_state.pop(skey, None)
        st.rerun()
    who = C.reviewer()
    if b3.button("Save verified count", type="primary", icon=":material/check:", width="stretch", disabled=not who,
                 help=None if who else "Type your name in the sidebar first"):
        secs = time.time() - st.session_state.get(skey + "_t0", time.time())
        A.save(C.db(), s, who, secs, frame, path(cfg, "training_dir"), rep["video_file"])
        log.info("assisted count %s @%.0fs: ai %d -> %d (+%d -%d) by %s in %.0fs", run_id, point, s.ai_count,
                 s.final_count, s.added, len(s.removed_ai), who, secs)
        st.toast(f"Saved: {s.final_count} fish at {C.fmt_t(point)}", icon=":material/check_circle:")
        if pi + 1 < len(all_pts):
            st.session_state[f"assist_pt_next_{run_id}"] = pi + 1
        st.rerun()

    fx, fy, fw, fh = REGIONS[region]
    H, W = frame.shape[:2]
    x0, y0, rw, rh = int(fx * W), int(fy * H), int(fw * W), int(fh * H)
    k = 1.0 if region == "Whole frame" else 2.0  # upscale the zoomed region so rings stay crisp
    view = frame[y0:y0 + rh, x0:x0 + rw]
    if k != 1.0:
        view = cv2.resize(view, None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC)
    shown = A.draw(view, s, 14 if k == 1.0 else 18, offset=(x0, y0), scale=k)
    from streamlit_image_coordinates import streamlit_image_coordinates

    click = streamlit_image_coordinates(cv2.cvtColor(shown, cv2.COLOR_BGR2RGB), width="stretch",
                                        key=f"assist_img_{run_id}_{point}_{region}", cursor="crosshair",
                                        image_format="JPEG", jpeg_quality=92)
    st.caption("Cyan ring = counted by AquaLens · magenta ring with a dot = added by you. "
               "Click empty water where you see a fish to add it; click a ring to remove it."
               + ("" if who else " Type your name in the sidebar to save."))
    if click and click.get("unix_time") != st.session_state.get(skey + "_last"):
        st.session_state[skey + "_last"] = click.get("unix_time")
        sx = rw / float(click.get("width") or rw)
        sy = rh / float(click.get("height") or rh)
        A.toggle(s, x0 + click["x"] * sx, y0 + click["y"] * sy, radius * (1.0 if k == 1.0 else 0.6))
        st.rerun()

    T.section("All subsamples", hint="AI count vs verified count; unverified rows keep the AI count")
    rows = pd.DataFrame([{"Time": C.fmt_t(r["subsample_t_s"]), "AI count": r["ai_count"],
                          "Verified count": r["final_count"], "Added": r["added"], "Removed": r["removed"],
                          "Seconds": None if r["seconds"] is None else round(r["seconds"])} for r in sm["rows"]])
    st.dataframe(rows, hide_index=True, width="stretch")
    if sm["n_verified"]:
        csv = pd.DataFrame([{"video_file": rep["video_file"], "subsample_t_s": r["subsample_t_s"], "time": C.fmt_t(r["subsample_t_s"]),
                             "ai_count": r["ai_count"], "verified_count": r["final_count"], "verified": r["verified"]} for r in sm["rows"]])
        st.download_button("Verified counts (CSV)", csv.to_csv(index=False).encode(), f"{run_id}_verified_counts.csv", "text/csv",
                           icon=":material/download:")
