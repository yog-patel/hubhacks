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
    T.header("Step 1 of 3 · Analyze", "Analyze a survey video",
             "Choose a video, check how clear the water is, then run it. BlueSight finds and follows each fish, matches it "
             "against the species registry and counts it with Coastal Action's protocol. Anything it's unsure about "
             "goes to your review queue.", step=1)

    vdir = path(cfg, "videos_dir")
    vids = sorted(p for p in vdir.glob("*") if p.suffix.lower() in VIDEO_EXTS) if vdir.exists() else []
    up_dir = path(cfg, "outputs_dir") / "uploads"
    vids += sorted(p for p in up_dir.glob("*") if p.suffix.lower() in VIDEO_EXTS) if up_dir.exists() else []

    with st.container(border=True):
        T.section("Choose the footage", "1")
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
        st.html(f'<div class="bs-facts" style="margin-bottom:0"><span>Length <b>{C.fmt_t(info.duration_s)}</b></span>'
                f'<span>Resolution <b>{info.width}×{info.height}</b></span><span>Frame rate <b>{info.fps:.2f} fps</b></span>'
                f'<span>Analysed at <b>{cfg["sampling"]["fps"]:g} frames per second</b></span></div>')

    if len(vids) > 1:
        batch_section(cfg, vids)

    # ------------------------------------------------------------------ enhancement preview
    with st.container(border=True):
        T.section("Check the water clarity", "2", "optional")
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
                _, tone, _ = T.visibility_word(v, vmin)
                fill = {"ok": "var(--ok-fg)", "warn": "var(--warn-fg)"}.get(tone, "var(--mute-fg)")
                st.html(f'<div class="bs-readout"><p class="lbl">Visibility at {C.fmt_t(t)}</p>'
                        f'<div class="num">{v:.2f}<span> / 1</span></div></div>'
                        f'<div class="bs-meter" role="img" aria-label="visibility {v:.2f} of 1, threshold {vmin:.2f}">'
                        f'<div class="fill" style="width:{min(1.0, v) * 100:.0f}%;background:{fill}"></div>'
                        f'<div class="mark" style="left:{vmin * 100:.0f}%" title="identification threshold {vmin:.2f}"></div></div>')
                if v < vmin:
                    st.html(T.visibility_badge(v, vmin) +
                            f'<p style="margin-top:10px">Below the identification threshold ({vmin:.2f}). Fish seen here are '
                            '<b>counted as "Unable to ID due to visibility"</b> and are <b>never flagged as a new species</b>.</p>')
                else:
                    st.html(T.visibility_badge(v, vmin) +
                            f'<p style="margin-top:10px">Clear enough to identify species (threshold {vmin:.2f}).</p>')

    # ------------------------------------------------------------------ run
    with st.container(border=True):
        T.section("Run the analysis", "3")
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
        b_col, n_col = st.columns([1, 3], vertical_alignment="center")
        go = b_col.button("Analyze video", type="primary", icon=":material/play_arrow:", key="run_btn")
        n_col.html(C.local_badge())
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


def batch_section(cfg: dict, vids: list[Path]) -> None:
    """Analyse several videos one after another with the protocol window (e.g. a whole survey day)."""
    with st.expander(f"Analyze several videos at once ({len(vids)} available)", icon=":material/video_library:"):
        st.caption("Each video gets the protocol window (skip 1 min, analyse 15 min). Leave the computer running; about "
                   "15–20 minutes per video on a laptop GPU, faster on a desktop GPU.")
        pick = st.multiselect("Videos", [str(v) for v in vids], format_func=lambda p: Path(p).name, key="batch_pick")
        if st.button("Analyze selected videos", disabled=not pick, icon=":material/playlist_play:", key="batch_go"):
            from bluesight.pipeline import run_video

            done = []
            bar = st.progress(0.0, text="Starting…")
            for i, v in enumerate(pick):
                def cb(f: float, m: str, i=i, v=v) -> None:
                    bar.progress(min(1.0, (i + f) / len(pick)), text=f"{Path(v).name} ({i + 1}/{len(pick)}): {m}")
                try:
                    rep = run_video(v, cfg, None, None, cb)
                    done.append({"Video": Path(v).name, "MeanCount": rep["MeanCount_total_fish"],
                                 "Review items": rep["review_items"], "Runtime (s)": rep["runtime_s"], "Status": "done"})
                except Exception as exc:  # keep going with the next video
                    log.exception("batch: %s failed", v)
                    done.append({"Video": Path(v).name, "Status": f"failed: {exc}"})
            bar.progress(1.0, text="All done")
            st.dataframe(done, hide_index=True, width="stretch")
            st.success("Finished. Open Results to see each video, or Count check to verify the counts.")


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
    c1, c2, c3 = st.columns(3)
    c1.page_link(C.PAGES["check"], label="Check the counts", icon=":material/rule:")
    c2.page_link(C.PAGES["review"], label="Open the review queue", icon=":material/fact_check:")
    c3.page_link(C.PAGES["results"], label="See full results", icon=":material/bar_chart:")
