"""BlueSight AI - Streamlit app.  Run:  streamlit run app/streamlit_app.py

Pages: Analyze, Results, Review queue, Species registry. Everything runs on this device.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bluesight.config import load_config, path, resolve_device  # noqa: E402
from bluesight.db import DB  # noqa: E402
from bluesight.enhance import enhance_frame, visibility_score  # noqa: E402
from bluesight.io_video import VIDEO_EXTS, read_frame_at, resize_width, video_info  # noqa: E402
from bluesight.logs import get_logger  # noqa: E402
from bluesight.registry import Registry  # noqa: E402

log = get_logger("app")
st.set_page_config(page_title="BlueSight AI", page_icon="🐟", layout="wide")


# ----------------------------------------------------------------------------- setup
@st.cache_resource
def base_config() -> dict:
    return load_config()


def config_for(source: str) -> dict:
    """Real outputs, or the mock outputs from scripts/make_mock_data.py."""
    cfg = copy.deepcopy(base_config())
    if source == "Mock data":
        for k, v in {"db_path": "outputs/mock/bluesight.db", "runs_dir": "outputs/mock/runs",
                     "flags_dir": "outputs/mock/flags", "registry_dir": "outputs/mock/registry"}.items():
            cfg["paths"][k] = v
    return cfg


@st.cache_resource
def embedder_resource():
    from bluesight.embed import get_embedder

    return get_embedder(base_config())


class MockEmbedder:
    """Mean-colour embedder so mock approvals never load a model."""

    name, version = "mock", "mock"

    def embed_images(self, ims):
        v = np.array([[*im.reshape(-1, 3).mean(0), 1.0, 0, 0, 0, 0] for im in ims], np.float32)
        return v / np.linalg.norm(v, axis=1, keepdims=True)


def get_registry(cfg: dict, db: DB, source: str) -> Registry:
    return Registry(cfg, db, MockEmbedder() if source == "Mock data" else embedder_resource())


st.sidebar.title("🐟 BlueSight AI")
st.sidebar.caption("See more. Disturb less. Protect better.")
page = st.sidebar.radio("Page", ["Analyze", "Results", "Review queue", "Species registry"])
source = st.sidebar.radio("Data", ["Real outputs", "Mock data"], help="Mock data: run scripts/make_mock_data.py first")
reviewer = st.sidebar.text_input("Reviewer name", value=st.session_state.get("reviewer", ""), placeholder="e.g. A. Biologist")
st.session_state["reviewer"] = reviewer
cfg = config_for(source)
db = DB(path(cfg, "db_path"))
offline = os.environ.get("HF_HUB_OFFLINE") == "1"
st.sidebar.markdown(f"**Compute:** `{resolve_device(cfg)}` on this device  \n**Offline models:** {'✅ yes' if offline else '⚠️ no'}  \n"
                    "No cloud or hosted AI APIs are used.")
pending = db.q("SELECT COUNT(*) n FROM flags WHERE review_decision IS NULL")[0]["n"]
st.sidebar.metric("Items awaiting review", pending)


def list_runs() -> list[dict]:
    rows = db.q("SELECT * FROM runs ORDER BY started_at DESC")
    return [r for r in rows if r["report_path"] and Path(r["report_path"]).exists()]


def run_label(r: dict) -> str:
    return f"{r['video_file']}  [{r['start_s']:.0f}-{r['end_s']:.0f} s]  ({r['started_at']})"


def fmt_t(s: float) -> str:
    return f"{int(s // 60)}:{s % 60:04.1f}"


# ----------------------------------------------------------------------------- Analyze
def page_analyze() -> None:
    st.header("Analyze a survey video")
    vdir = path(cfg, "videos_dir")
    vids = sorted(p for p in vdir.glob("*") if p.suffix.lower() in VIDEO_EXTS) if vdir.exists() else []
    up = st.file_uploader("…or upload a video", type=[e.strip(".") for e in VIDEO_EXTS])
    if up is not None:
        dest = path(cfg, "outputs_dir") / "uploads" / up.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            dest.write_bytes(up.getbuffer())
        vids = [dest] + vids
    if not vids:
        st.info("No videos found in data/videos/. Upload one above.")
        return
    video = st.selectbox("Video", vids, format_func=lambda p: p.name)
    info = video_info(video)
    c1, c2, c3 = st.columns(3)
    c1.metric("Length", fmt_t(info.duration_s))
    c2.metric("Resolution", f"{info.width}×{info.height}")
    c3.metric("Frame rate", f"{info.fps:.2f} fps")

    st.subheader("1 · Enhancement and visibility")
    t = st.slider("Preview time (s)", 0.0, float(info.duration_s - 1), float(min(420.0, info.duration_s / 3)), 1.0)
    frame = read_frame_at(video, t)
    if frame is not None:
        small, _ = resize_width(frame, 960)
        enh = enhance_frame(small, cfg["enhance"])
        v = visibility_score(small, cfg["enhance"])
        vmin = cfg["identify"]["V_MIN"]
        a, b = st.columns(2)
        a.image(cv2.cvtColor(small, cv2.COLOR_BGR2RGB), caption=f"Original, t={fmt_t(t)}", width="stretch")
        b.image(cv2.cvtColor(enh, cv2.COLOR_BGR2RGB), caption="Enhanced (gray-world colour correction + CLAHE)", width="stretch")
        st.progress(min(1.0, v), text=f"Visibility score {v:.2f}  (V_MIN = {vmin:.2f}: "
                                         f"{'too murky to identify species; fish here are NOT flagged as new' if v < vmin else 'OK to identify'})")

    st.subheader("2 · Run the analysis")
    p = cfg["protocol"]
    mode = st.radio("Analysis window", ["Protocol window (skip 1st minute, analyse 15 min)", "Custom", "Whole video (minus first/last minute)"],
                    horizontal=True)
    start, dur = None, None
    if mode == "Custom":
        cc1, cc2 = st.columns(2)
        start = cc1.number_input("Start (s)", 0.0, float(info.duration_s), float(p["trim_start_s"]), 10.0)
        dur = cc2.number_input("Duration (s)", 10.0, float(info.duration_s), 120.0, 10.0)
    elif mode.startswith("Whole"):
        start, dur = float(p["trim_start_s"]), float(info.duration_s)
    force = st.checkbox("Ignore cache (re-detect from scratch)", value=False)
    if st.button("▶ Analyze", type="primary"):
        from bluesight.pipeline import run_video

        bar = st.progress(0.0, text="starting…")
        t0 = time.time()
        try:
            rep = run_video(video, cfg, start, dur, lambda f, m: bar.progress(min(1.0, f), text=m), force)
        except Exception as exc:
            log.exception("analysis failed")
            st.error(f"Analysis failed: {exc} (details in outputs/logs/bluesight.log)")
            return
        bar.progress(1.0, text="done")
        st.success(f"Finished in {time.time() - t0:.1f} s. Ran on this device: {rep['ran_on']}. Offline: yes.")
        st.caption("Detections and embeddings were reused from cache." if rep["cached_detection"] else
                   f"Full processing cost: {rep['full_processing_s_per_video_min']} s per minute of video.")
        st.session_state["last_run"] = rep["run_id"]
        show_report(rep)


# ----------------------------------------------------------------------------- Results
def show_report(rep: dict) -> None:
    w = rep["window"]
    st.markdown(f"**{rep['video_file']}** · site {rep['site']} · {rep['date']} · window {fmt_t(w['start_s'])}–{fmt_t(w['end_s'])} "
                f"({w['duration_min']} min, {rep['protocol']['n_subsamples'] if 'protocol' in rep else len(rep['subsamples'])} subsamples)")
    c = st.columns(5)
    c[0].metric("MeanCount, total fish", f"{rep['MeanCount_total_fish']:.1f}")
    c[1].metric("Mean visibility", f"{rep['visibility']['mean']:.2f}")
    c[2].metric("Footage too murky", f"{100 * rep['visibility']['fraction_below_v_min']:.0f} %",
                help="Share of sampled frames below V_MIN. Fish there may be missed or unidentified; it is never reported as zero fish.")
    c[3].metric("Review items", rep["review_items"])
    c[4].metric("Runtime", f"{rep['runtime_s']:.0f} s", help=rep.get("ran_on", ""))
    if rep["visibility"]["fraction_below_v_min"] > 0:
        st.warning(f"{100 * rep['visibility']['fraction_below_v_min']:.0f}% of this footage is below the visibility threshold. "
                   "Counts there are lower bounds, not zeros.")
    st.subheader("Counts per species")
    sp = pd.DataFrame(rep["species"])
    if len(sp):
        sp = sp.rename(columns={"label": "Species / column", "MeanCount": "MeanCount (protocol subsamples)",
                                "MeanCount_all_sampled_frames": "MeanCount (all sampled frames)", "n_tracks": "tracks",
                                "confidence": "confidence (mean similarity)"})
        st.dataframe(sp, hide_index=True, width="stretch")
    st.caption("MeanCount follows Coastal Action's protocol: a count every 60 s, a fish counts if visible within ±0.5 s. "
               "MaxN = most individuals in any single sampled frame. 'Unknown/Unable to ID due to visibility' is the protocol's own column. "
               f"Transient detections that never moved consistently (not counted): {rep.get('transient_detections_per_frame_not_counted', 0)} per frame.")
    if rep.get("protocol_window"):
        pw = rep["protocol_window"]
        st.info(f"Protocol 15-min window {fmt_t(pw['start_s'])}–{fmt_t(pw['end_s'])}: MeanCount total fish = **{pw['MeanCount_total_fish']}** "
                f"over {pw['n_subsamples']} subsamples{'' if pw['complete'] else ' (window only partly inside this run)'}.")
    st.subheader("Subsample frames (protocol spreadsheet format)")
    st.dataframe(pd.DataFrame(rep["subsamples"]), hide_index=True, width="stretch")
    rid = rep["run_id"]
    fr = pd.DataFrame(db.q("SELECT t_s, visibility FROM frames WHERE run_id=? ORDER BY t_s", (rid,)))
    if len(fr):
        st.subheader("Visibility over time")
        fr["V_MIN"] = rep["thresholds"]["V_MIN"]
        st.line_chart(fr.set_index("t_s"), height=200)
    if rep.get("annotated_video") and Path(rep["annotated_video"]).exists():
        st.subheader("Annotated video (sampled frames)")
        st.video(str(rep["annotated_video"]))
        st.caption("Green = known species · yellow = uncertain · red = unfamiliar (flagged) · grey = unidentified (low visibility / short track)")
    run_dir = Path(rep["annotated_video"]).parent if rep.get("annotated_video") else None
    if run_dir and (run_dir / "report.csv").exists():
        d1, d2, d3 = st.columns(3)
        d1.download_button("⬇ report.csv (subsamples)", (run_dir / "report.csv").read_bytes(), f"{rid}_report.csv", "text/csv")
        if (run_dir / "species_summary.csv").exists():
            d2.download_button("⬇ species_summary.csv", (run_dir / "species_summary.csv").read_bytes(), f"{rid}_species.csv", "text/csv")
        d3.download_button("⬇ report.json", (run_dir / "report.json").read_bytes(), f"{rid}_report.json", "application/json")
    with st.expander("Run details"):
        st.json({k: rep.get(k) for k in ("ran_on", "offline", "runtime_s", "timings_s", "full_processing_s_per_video_min",
                                          "models", "thresholds", "sample_fps", "n_sampled_frames", "n_tracks", "track_status_counts",
                                          "registry_species", "cached_detection")})


def page_results() -> None:
    st.header("Results")
    runs = list_runs()
    if not runs:
        st.info("No analyses yet. Run one on the Analyze page.")
        return
    labels = [run_label(r) for r in runs]
    default = next((i for i, r in enumerate(runs) if r["run_id"] == st.session_state.get("last_run")), 0)
    r = runs[st.selectbox("Analysis", range(len(runs)), index=default, format_func=lambda i: labels[i])]
    show_report(json.loads(Path(r["report_path"]).read_text()))


# ----------------------------------------------------------------------------- Review
def record_decision(flag: dict, decision: str, species: str | None) -> None:
    ts = dt.datetime.now().isoformat(timespec="seconds")
    db.set_review(flag["flag_id"], decision, species, reviewer.strip(), ts)
    fj = Path(flag["folder"]) / "flag.json"
    if fj.exists():
        d = json.loads(fj.read_text())
        d["review"] = {"decision": decision, "species": species, "reviewer": reviewer.strip(), "timestamp": ts}
        fj.write_text(json.dumps(d, indent=2))
    log.info("review %s: %s %s by %s", flag["flag_id"], decision, species, reviewer)


def page_review() -> None:
    st.header("Review queue")
    st.caption("Most clearly unfamiliar first. Nothing enters the species registry without your approval. "
               "Approving saves the crops as reference images and rebuilds that species' prototype immediately (no retraining).")
    if not reviewer.strip():
        st.warning("Enter your name in the sidebar to record decisions.")
    flags = db.q("SELECT * FROM flags WHERE review_decision IS NULL ORDER BY (status='unfamiliar') DESC, best_similarity ASC")
    if not flags:
        st.success("Nothing awaiting review.")
    reg = None
    species = [s["name"] for s in db.q("SELECT name FROM species WHERE active=1 ORDER BY name")]
    vid_len = {}
    for f in flags[:40]:
        top3 = json.loads(f["top3"] or "[]")
        best = top3[0] if top3 else None
        title = ("🔴 Unfamiliar: possibly a species not in the registry" if f["status"] == "unfamiliar"
                 else f"🟡 Uncertain: probably {best['species'].replace('_', ' ')}?" if best else "🟡 Uncertain")
        with st.container(border=True):
            st.markdown(f"**{title}** · `{f['flag_id']}`")
            st.caption(f"{f['video_file']} · {fmt_t(f['start_s'])}–{fmt_t(f['end_s'])} · visibility {f['visibility']:.2f} · "
                       f"{f['track_frames']} sampled frames · {len(json.loads(f['track_ids']))} track(s) merged")
            left, mid, right = st.columns([3, 3, 2])
            folder = Path(f["folder"])
            clip = folder / "clip.mp4"
            if clip.exists():
                left.video(str(clip))
            else:
                left.info("no clip")
            crops = sorted(folder.glob("crop_*.jpg"))
            if crops:
                mid.image([str(c) for c in crops], width=110)
            right.markdown("**Top-3 matches**")
            for m in top3:
                right.progress(max(0.0, min(1.0, m["similarity"])), text=f"{m['species'].replace('_', ' ')}: {m['similarity']:.2f}")
            b1, b2, b3 = st.columns(3)
            with b1:
                name = st.text_input("New species name", key=f"n_{f['flag_id']}", placeholder="e.g. European green crab")
                if st.button("➕ New species", key=f"new_{f['flag_id']}", disabled=not (reviewer.strip() and name.strip())):
                    reg = reg or get_registry(cfg, db, source)
                    key = reg.add_images(name, crops, reviewer, new_species=True, ref_tag=f"{f['flag_id']}_")
                    record_decision(f, "new_species", key)
                    st.toast(f"Added new species '{name}' to the registry")
                    st.rerun()
            with b2:
                ex = st.selectbox("Existing species", species, key=f"e_{f['flag_id']}",
                                  index=species.index(best["species"]) if best and best["species"] in species else 0) if species else None
                if st.button("✔ Existing species", key=f"ex_{f['flag_id']}", disabled=not (reviewer.strip() and ex)):
                    reg = reg or get_registry(cfg, db, source)
                    reg.add_images(ex, crops, reviewer, new_species=False, ref_tag=f"{f['flag_id']}_")
                    record_decision(f, "existing_species", ex)
                    st.toast(f"Confirmed as {ex}; prototype updated")
                    st.rerun()
            with b3:
                st.write("")
                st.write("")
                if st.button("✖ Reject / not a fish", key=f"rj_{f['flag_id']}", disabled=not reviewer.strip()):
                    record_decision(f, "reject", None)
                    st.toast("Rejected; excluded from counts on the next run")
                    st.rerun()
    if len(flags) > 40:
        st.caption(f"{len(flags) - 40} more items not shown.")
    done = db.q("SELECT flag_id, video_file, status, review_decision, review_species, reviewer, review_timestamp "
                "FROM flags WHERE review_decision IS NOT NULL ORDER BY review_timestamp DESC")
    if done:
        with st.expander(f"Reviewed items ({len(done)})"):
            st.dataframe(pd.DataFrame(done), hide_index=True, width="stretch")
    runs = db.q("SELECT run_id, video_file, end_s - start_s AS secs FROM runs")
    if runs:
        n_items = db.q("SELECT run_id, COUNT(*) n FROM flags GROUP BY run_id")
        nmap = {r["run_id"]: r["n"] for r in n_items}
        sec = cfg["evaluation"]["reviewer_seconds_per_item"]
        st.caption("Estimated reviewer time: " + "; ".join(
            f"{r['run_id']}: {nmap.get(r['run_id'], 0)} items × {sec} s = {nmap.get(r['run_id'], 0) * sec / 60:.1f} min "
            f"for {r['secs'] / 60:.0f} min of video" for r in runs))


# ----------------------------------------------------------------------------- Registry
def page_registry() -> None:
    st.header("Species registry")
    st.caption("One prototype per species = the mean embedding of its reference images. Held-out species are never "
               "pre-loaded; a species only appears here from the provided labelled photos or a reviewer's approval.")
    held = cfg.get("held_out_species") or []
    if held:
        st.caption("Held out for testing the unfamiliar-fish flag: " + ", ".join(held))
    rows = Registry(cfg, db, MockEmbedder()).list_species()
    if not rows:
        st.info("Registry is empty. Run `python scripts/build_registry.py`.")
        return
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    for r in rows:
        with st.container(border=True):
            st.markdown(f"### {r['display_name'] or r['name']}")
            st.caption(f"key `{r['name']}` · source: {r['source']} · added {r['date_added']} · approved by **{r['approved_by']}** · "
                       f"{r['n_images']} reference images")
            imgs = [p["path"] for p in db.q("SELECT path FROM species_images WHERE species=? ORDER BY added_at DESC LIMIT 8", (r["name"],))]
            imgs = [p for p in imgs if Path(p).exists()]
            if imgs:
                st.image(imgs, width=120)


{"Analyze": page_analyze, "Results": page_results, "Review queue": page_review, "Species registry": page_registry}[page]()
