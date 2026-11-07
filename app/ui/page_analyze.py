"""Analyze: choose or drop in a video, preview enhancement + visibility, run the pipeline with clear steps."""
from __future__ import annotations

import json
import time
from pathlib import Path

import cv2
import streamlit as st

from bluesight.config import path
from bluesight.enhance import enhance_frame, visibility_score
from bluesight.io_video import VIDEO_EXTS, read_frame_at, resize_width, video_info
from bluesight.logs import get_logger

from . import common as C
from . import theme as T
from .compare import before_after

log = get_logger("app")


@st.cache_data(show_spinner=False, max_entries=64)
def preview_frame(video: str, t: float, enhance_cfg_json: str) -> tuple:
    frame = read_frame_at(video, t)
    if frame is None:
        return None, None, None
    small, _ = resize_width(frame, 960)
    ecfg = json.loads(enhance_cfg_json)
    return small, enhance_frame(small, ecfg), visibility_score(small, ecfg)


def stage_of(frac: float, msg: str) -> tuple[set[int], set[int]]:
    """Map the pipeline's progress messages onto the five user-facing steps."""
    m = msg.lower()
    if m.startswith("detect+track") or frac < 0.66:
        return {0, 1, 2}, set()
    if "embedding" in m or "evidence" in m or frac < 0.9:
        return {3}, {0, 1, 2}
    if frac < 1.0:
        return {4}, {0, 1, 2, 3}
    return set(), {0, 1, 2, 3, 4}


def page() -> None:
    cfg = C.cfg()
    T.header("Step 1 of 3", "Analyze a survey video",
             "BlueSight enhances the footage, finds and follows each fish, compares it with the species registry and "
             "counts it using Coastal Action's protocol. Anything it is unsure about goes to your review queue.")
    st.html(C.local_badge())

    vdir = path(cfg, "videos_dir")
    vids = sorted(p for p in vdir.glob("*") if p.suffix.lower() in VIDEO_EXTS) if vdir.exists() else []
    up_dir = path(cfg, "outputs_dir") / "uploads"
    vids += sorted(p for p in up_dir.glob("*") if p.suffix.lower() in VIDEO_EXTS) if up_dir.exists() else []

    with st.container(border=True):
        st.subheader("Choose the footage", anchor=False)
        up = st.file_uploader("Drag and drop a survey video here, or browse", type=[e.strip(".") for e in VIDEO_EXTS],
                              help="MP4, MOV, AVI, MKV or M4V. The file is copied to outputs/uploads/ on this computer; "
                                   "it is never sent anywhere.")
        if up is not None:
            dest = up_dir / up.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                dest.write_bytes(up.getbuffer())
            st.session_state["video_pick"] = str(dest)
            if dest not in vids:
                vids.append(dest)
        if not vids:
            T.empty_state("No survey videos yet",
                          "BlueSight looks for videos in <code>data/videos/</code>. None were found.",
                          "Drop a video above, or add one to the project folder and run "
                          "<code>python scripts/prepare_resources.py</code>.")
            return
        names = [str(v) for v in vids]
        default = names.index(st.session_state["video_pick"]) if st.session_state.get("video_pick") in names else 0
        video = Path(st.selectbox("Video", names, index=default, format_func=lambda p: Path(p).name, key="video_select"))
        try:
            info = video_info(video)
        except IOError:
            st.error(f"Can't open {video.name}. The file may be damaged or in a format OpenCV can't read. "
                     "Try re-exporting it as H.264 or HEVC MP4.")
            return
        st.html(f'<div class="bs-facts"><span>Length <b>{C.fmt_t(info.duration_s)}</b></span>'
                f'<span>Resolution <b>{info.width}×{info.height}</b></span><span>Frame rate <b>{info.fps:.2f} fps</b></span>'
                f'<span>Analysed at <b>{cfg["sampling"]["fps"]:g} frames per second</b></span></div>')

    # ------------------------------------------------------------------ enhancement preview
    with st.container(border=True):
        st.subheader("Check the water clarity", anchor=False)
        st.caption("Pick a moment in the video. BlueSight corrects the green cast and boosts local contrast before looking "
                   "for fish, and scores visibility from 0 (opaque) to 1 (clear).")
        vmin = float(cfg["identify"]["V_MIN"])
        t = st.slider("Preview moment (seconds into the video)", 0.0, float(max(1.0, info.duration_s - 1)),
                      float(min(420.0, info.duration_s / 3)), 1.0, key="preview_t",
                      help="Try 420 (7:00, very hazy) and 1297 (21:37, a green crab beside the pole).")
        small, enh, v = preview_frame(str(video), float(t), json.dumps(cfg["enhance"], sort_keys=True))
        if small is None:
            st.error("Couldn't read a frame at that moment. Try a slightly earlier time.")
        else:
            left, right = st.columns([3, 2], gap="large")
            with left:
                before_after(small, enh, "Original", "Enhanced")
            with right:
                st.html(f'<p class="bs-small" style="margin:0">Moment {C.fmt_t(t)}</p>'
                        f'<div style="font-size:44px;font-weight:700;line-height:1.1;font-variant-numeric:tabular-nums">{v:.2f}'
                        f'<span style="font-size:18px;color:#3E5466;font-weight:600"> / 1 visibility</span></div>')
                st.progress(min(1.0, v))
                if v < vmin:
                    st.html(T.visibility_badge(v, vmin) +
                            f'<p style="margin-top:10px">Below the identification threshold ({vmin:.2f}). Fish seen here are '
                            '<b>counted as "Unable to ID due to visibility"</b> and are <b>never flagged as a new species</b>.</p>')
                else:
                    st.html(T.visibility_badge(v, vmin) +
                            f'<p style="margin-top:10px">Clear enough to identify species (threshold {vmin:.2f}).</p>')

    # ------------------------------------------------------------------ run
    with st.container(border=True):
        st.subheader("Run the analysis", anchor=False)
        p = cfg["protocol"]
        mode = st.radio("Which part of the video?",
                        ["Protocol window", "Custom window", "Whole video"], horizontal=True, key="window_mode",
                        captions=[f"Skip the first {p['trim_start_s'] // 60:.0f} min, analyse {p['analysis_duration_s'] // 60:.0f} min",
                                  "Choose a start and length", "Everything except the first and last minute"])
        start, dur = None, None
        if mode == "Custom window":
            c1, c2 = st.columns(2)
            start = c1.number_input("Start (seconds)", 0.0, float(info.duration_s), 1280.0, 5.0, key="win_start")
            dur = c2.number_input("Length (seconds)", 10.0, float(info.duration_s), 75.0, 5.0, key="win_dur")
            st.caption(f"Analyses {C.fmt_t(start)} to {C.fmt_t(min(info.duration_s, start + dur))}.")
        elif mode == "Whole video":
            start, dur = float(p["trim_start_s"]), float(info.duration_s)
        with st.expander("Advanced"):
            force = st.checkbox("Re-detect from scratch (ignore saved detections)", value=False,
                                help="Normally detections are reused, so re-running after a review takes seconds. "
                                     "Re-detecting a 15-minute window takes about 15–20 minutes on an Apple M5.")
        steps = st.empty()
        steps.html(T.stepper())
        go = st.button("Analyze video", type="primary", icon=":material/play_arrow:", key="run_btn")
        status = st.empty()
        if go:
            from bluesight.pipeline import run_video

            bar = status.progress(0.0, text="Starting…")
            t0 = time.time()

            def cb(f: float, m: str) -> None:
                a, d = stage_of(f, m)
                steps.html(T.stepper(a, d))
                bar.progress(min(1.0, f), text=f"{m} · {time.time() - t0:.0f} s")

            try:
                rep = run_video(video, cfg, start, dur, cb, force)
            except Exception as exc:  # shown to the user and logged
                log.exception("analysis failed")
                status.error(f"The analysis stopped: {exc}. Nothing was saved for this window. Details are in "
                             "outputs/logs/bluesight.log.")
                return
            steps.html(T.stepper((), range(5)))
            status.empty()
            st.session_state["last_run"] = rep["run_id"]
            st.session_state["just_ran"] = rep["run_id"]
            show_summary(rep, time.time() - t0)
        elif st.session_state.get("just_ran"):
            run = next((r for r in C.list_runs() if r["run_id"] == st.session_state["just_ran"]), None)
            if run:
                show_summary(C.load_report(run), None)


def show_summary(rep: dict, secs: float | None) -> None:
    net = rep.get("network") or {}
    ext = net.get("external_connection_attempts")
    en = rep.get("energy") or {}
    took = f"{secs:.0f} s" if secs is not None else f"{rep['runtime_s']:.0f} s"
    msg = (f"**Finished in {took}** on this computer ({rep['ran_on']}). "
           + ("Saved detections were reused, so only identification and counting were repeated. " if rep["cached_detection"] else
              f"Processing cost {rep['full_processing_s_per_video_min']} s per minute of video. ")
           + (f"External network connections during the run: **{ext}**. " if ext is not None else "")
           + (f"Estimated energy: {en['energy_wh']:.2f} Wh." if en.get("energy_wh") is not None else ""))
    st.success(msg)
    pend = rep.get("review_items_packaged", rep.get("review_items", 0))
    T.cards([
        {"k": "Fish counted", "v": f"{rep['MeanCount_total_fish']:.1f}", "d": "MeanCount: mean fish per 60-s subsample", "tone": "info"},
        {"k": "Items for you to review", "v": pend, "d": "unfamiliar or uncertain", "tone": "attn" if pend else "ok"},
        {"k": "Footage too murky", "v": f"{100 * rep['visibility']['fraction_below_v_min']:.0f}", "unit": "%",
         "d": "of sampled frames below the visibility threshold"},
    ])
    c1, c2 = st.columns(2)
    c1.page_link(C.PAGES["results"], label="See full results", icon=":material/bar_chart:")
    c2.page_link(C.PAGES["review"], label="Open the review queue", icon=":material/fact_check:")
