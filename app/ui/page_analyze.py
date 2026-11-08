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
    T.header("", "Analyze a video", "Pick a survey video and press Analyze.", step=1)

    vdir = path(cfg, "videos_dir")
    vids = sorted(p for p in vdir.glob("*") if p.suffix.lower() in VIDEO_EXTS) if vdir.exists() else []
    up_dir = path(cfg, "outputs_dir") / "uploads"
    vids += sorted(p for p in up_dir.glob("*") if p.suffix.lower() in VIDEO_EXTS) if up_dir.exists() else []

    hero = st.container(border=True, key="hero")     # filled below, after the upload box has had a chance to add a video
    clarity = st.container()
    with st.expander("Add a video from this computer", icon=":material/upload:"):
        up = st.file_uploader("Add a video", type=[e.strip(".") for e in VIDEO_EXTS], label_visibility="collapsed",
                              help="MP4, MOV, AVI, MKV or M4V. Copied to this computer only.")
    if up is not None:
        dest = up_dir / up.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            dest.write_bytes(up.getbuffer())
        st.session_state["video_pick"] = str(dest)
        if dest not in vids:
            vids.append(dest)
    if len(vids) > 1:
        batch_section(cfg, vids)
    if not vids:
        with hero:
            T.empty_state("No videos yet", "Add a survey video with the box below to get started.")
        return

    with hero:
        names = [str(v) for v in vids]
        default = names.index(st.session_state["video_pick"]) if st.session_state.get("video_pick") in names else 0
        still, ctl = st.columns([3, 2], gap="large")
        with ctl:
            video = Path(st.selectbox("Video", names, index=default, format_func=lambda p: Path(p).name,
                                      key="video_select", label_visibility="collapsed"))
            try:
                info = video_info(video)
            except IOError:
                st.error(f"Can't open {video.name}. Re-export it as an MP4 (H.264 or HEVC) and add it again.")
                return
            st.html(f'<div class="bs-facts"><span>Length<b>{C.fmt_t(info.duration_s)}</b></span>'
                    f'<span>Quality<b>{"4K" if info.width >= 3800 else f"{info.height}p"}</b></span>'
                    f'<span>Site<b>{T.esc(video.stem.split(" ")[0])}</b></span></div>')
            p = cfg["protocol"]
            mode = st.segmented_control("How much of the video?", ["Protocol window", "Custom window", "Whole video"],
                                        default="Protocol window", key="window_mode",
                                        format_func={"Protocol window": "Standard", "Custom window": "A part",
                                                     "Whole video": "Whole"}.get,
                                        help=f"Standard: skip the first {p['trim_start_s'] // 60:.0f} min (settling "
                                             f"sediment), then {p['analysis_duration_s'] // 60:.0f} min, as in the protocol."
                                        ) or "Protocol window"
            start, dur = None, None
            if mode == "Custom window":
                c1, c2 = st.columns(2)
                start = c1.number_input("Start (s)", 0.0, float(info.duration_s), 1280.0, 5.0, key="win_start")
                dur = c2.number_input("Length (s)", 10.0, float(info.duration_s), 75.0, 5.0, key="win_dur")
                st.caption(f"{C.fmt_t(start)} to {C.fmt_t(min(info.duration_s, start + dur))}")
            elif mode == "Whole video":
                start, dur = float(p["trim_start_s"]), float(info.duration_s)
            go = st.button("Analyze video", type="primary", icon=":material/play_arrow:", key="run_btn", width="stretch")
            st.html(C.local_badge(compact=True))
            with st.expander("Advanced"):
                force = st.checkbox("Start fresh (ignore saved work)", value=False,
                                    help="Normally saved work is reused, so a re-run takes seconds. Fresh: about 10 "
                                         "minutes per 15 minutes of video on a laptop.")
        with still:
            t_still = 1297.0 if info.duration_s > 1300 else info.duration_s / 3
            small, _, _ = preview_frame(str(video), t_still, json.dumps(cfg["enhance"], sort_keys=True))
            if small is not None:
                st.image(cv2.cvtColor(small, cv2.COLOR_BGR2RGB), width="stretch",
                         alt=f"Still from {video.name} at {C.fmt_t(t_still)}")
        steps = st.empty()
        status = st.empty()
        if go:
            from bluesight.pipeline import run_video

            steps.html(T.stepper())
            bar = status.progress(0.0, text="Starting…")
            t0 = time.time()

            def cb(f: float, m: str) -> None:
                a, d = stage_of(f, m)
                steps.html(T.stepper(a, d))
                bar.progress(min(1.0, f), text=f"{time.time() - t0:.0f} s")

            try:
                rep = run_video(video, cfg, start, dur, cb, force)
            except Exception as exc:  # shown to the user and logged
                log.exception("analysis failed")
                status.error(f"The analysis stopped ({exc}). Nothing was saved. Try again; if it stops again, "
                             "send outputs/logs/bluesight.log to your tech contact.")
                return
            steps.empty()
            status.empty()
            st.session_state["last_run"] = rep["run_id"]
            st.session_state["just_ran"] = rep["run_id"]
            show_summary(rep, time.time() - t0)
        elif st.session_state.get("just_ran"):
            run = next((r for r in C.list_runs() if r["run_id"] == st.session_state["just_ran"]), None)
            if run:
                show_summary(C.load_report(run), None)

    # ------------------------------------------------------------------ water clarity (optional)
    with clarity:
        st.subheader("How clear is the water?", anchor=False)
        vmin = float(cfg["identify"]["V_MIN"])
        t = st.slider("Moment in the video (seconds)", 0.0, float(max(1.0, info.duration_s - 1)),
                      float(min(420.0, info.duration_s / 3)), 1.0, key="preview_t",
                      help="Try 420 (very hazy) and 1297 (a green crab by the pole).")
        small, enh, v = preview_frame(str(video), float(t), json.dumps(cfg["enhance"], sort_keys=True))
        if small is None:
            st.error("No frame at that moment. Move the slider a little earlier.")
        else:
            left, right = st.columns([3, 2], gap="large")
            with left:
                before_after(small, enh, "Original", "Cleaned up")
            with right:
                word, tone, _ = T.visibility_word(v, vmin)
                fill = {"ok": "var(--ok-fg)", "warn": "var(--warn-fg)"}.get(tone, "var(--mute-fg)")
                st.html(f'<div class="bs-readout"><p class="lbl">Water at {C.fmt_t(t)}</p>'
                        f'<div class="num">{word}</div></div>'
                        f'<div class="bs-meter" role="img" aria-label="water clarity {v:.2f} of 1">'
                        f'<div class="fill" style="width:{min(1.0, v) * 100:.0f}%;background:{fill}"></div>'
                        f'<div class="mark" style="left:{vmin * 100:.0f}%" title="below this mark: too murky to name species"></div></div>'
                        + ('<p class="bs-small">Fish here are counted as “too murky to name”, never as a new species.</p>'
                           if v < vmin else '<p class="bs-small">Clear enough to name species.</p>'))


def batch_section(cfg: dict, vids: list[Path]) -> None:
    """Analyse several videos one after another with the protocol window (e.g. a whole survey day)."""
    with st.expander(f"Analyze several videos at once ({len(vids)} available)", icon=":material/video_library:"):
        st.caption("Standard 15 minutes each. About 10 minutes per video on a laptop.")
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
                    done.append({"Video": Path(v).name, "Fish per check (avg)": rep["MeanCount_total_fish"],
                                 "New animals": rep["review_items"], "Time (s)": rep["runtime_s"], "Status": "done"})
                except Exception as exc:  # keep going with the next video
                    log.exception("batch: %s failed", v)
                    done.append({"Video": Path(v).name, "Status": f"failed: {exc}"})
            bar.progress(1.0, text="All done")
            st.dataframe(done, hide_index=True, width="stretch")
            st.success("All done. Check the counts next.")


def show_summary(rep: dict, secs: float | None) -> None:
    net = rep.get("network") or {}
    ext = net.get("external_connection_attempts")
    took = f"{secs:.0f} s" if secs is not None else f"{rep['runtime_s']:.0f} s"
    st.success(f"Done in {took}" + (f" · {ext} internet connections" if ext is not None else "") + " · nothing left this computer",
               icon=":material/check_circle:")
    pend = rep.get("review_items_packaged", rep.get("review_items", 0))
    st.html(f'<p class="bs-summary">The AI counted an average of <b>{rep["MeanCount_total_fish"]:.1f} fish</b> per check point '
            f'and found <b>{pend} animal{"s" if pend != 1 else ""}</b> it couldn\'t name. '
            f'<b class="w">{100 * rep["visibility"]["fraction_below_v_min"]:.0f}%</b> of the video was too murky to name species.</p>')
    c1, c2, c3 = st.columns(3)
    c1.page_link(C.PAGES["check"], label="Check the counts", icon=":material/rule:")
    c2.page_link(C.PAGES["review"], label="New animals", icon=":material/pets:")
    c3.page_link(C.PAGES["results"], label="Report", icon=":material/bar_chart:")
