"""Results: headline cards, species table, before/after frame, timeline, annotated video, downloads."""
from __future__ import annotations

import json
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from bluesight import count as CNT
from bluesight import countcheck as CC
from bluesight import survey as SV
from bluesight.export import workbook_bytes
from bluesight.enhance import enhance_frame
from bluesight.io_video import read_frame_at, resize_width

from . import common as C
from . import theme as T
from .compare import before_after

LABEL_NOTES = {
    CNT.UNKNOWN_LABEL: "Seen, but too murky, small or brief to identify (the protocol's own column).",
    CNT.UNFAMILIAR_LABEL: "Doesn't match any registry species. Waiting for your review.",
}


def nice_label(label: str) -> str:
    cfg = C.cfg()
    if label.startswith("Unconfirmed: probably "):
        return "Probably " + SV.display_name(label.split("probably ", 1)[1].rstrip("?"), cfg) + " (unconfirmed)"
    if label in (CNT.UNKNOWN_LABEL, CNT.UNFAMILIAR_LABEL):
        return label
    n = SV.display_name(label, cfg)
    return n[:1].upper() + n[1:]


def survey_form(rep: dict, cfg: dict) -> dict:
    """Survey details typed in by staff (never fetched online). Saved per analysis and added to the Excel file."""
    db = C.db()
    sv = SV.get_survey(db, rep["run_id"])
    filled = sv.get("water_temp_c") is not None or sv.get("pole_visibility") not in (None, "Not recorded")
    with st.expander("Survey details: water temperature, pole visibility, juveniles" + (" ✓" if filled else " (add them)"),
                     expanded=False):
        with st.form(f"survey_{rep['run_id']}", border=False):
            a, b, c = st.columns(3)
            site = a.text_input("Site", sv.get("site") or rep["site"])
            date = b.text_input("Survey date", sv.get("date") or rep["date"], help="YYYY-MM-DD")
            obs = c.text_input("Observer", sv.get("observer") or C.reviewer())
            d, e, f = st.columns(3)
            has_t = d.checkbox("Water temperature recorded", value=sv.get("water_temp_c") is not None)
            temp = d.number_input("Water temperature (°C)", -2.0, 35.0, float(sv.get("water_temp_c") or 12.0), 0.1,
                                  disabled=False, help="From your field sheet or logger. Used for the watch-list range check.")
            pole = e.selectbox("Visibility from the pole", SV.POLE_CHOICES,
                               index=SV.POLE_CHOICES.index(sv["pole_visibility"]) if sv.get("pole_visibility") in SV.POLE_CHOICES else 0,
                               help="Read off the 2 m pole (black tape every 0.5 m), as in the protocol.")
            juv = f.selectbox("Juveniles present", ["Not recorded", "1 = present", "0 = absent"],
                              index={None: 0, 1: 1, 0: 2}.get(sv.get("juveniles"), 0))
            notes = st.text_area("Notes", sv.get("notes") or "", height=68)
            if st.form_submit_button("Save survey details", icon=":material/save:"):
                SV.save_survey(db, rep["run_id"], site=site, date=date, observer=obs,
                               water_temp_c=float(temp) if has_t else None, pole_visibility=pole,
                               juveniles={"1 = present": 1, "0 = absent": 0}.get(juv), notes=notes)
                st.toast("Survey details saved. They're included in the Excel download.", icon=":material/check_circle:")
                st.rerun()
    return SV.get_survey(db, rep["run_id"])


def show_alerts(items: list[dict]) -> None:
    for a in items:
        icon = {"watch": ":material/warning:", "range": ":material/thermostat:", "new": ":material/new_releases:"}[a["level"]]
        (st.error if a["level"] == "watch" else st.warning)(f"**{a['title']}.** {a['body']}", icon=icon)


@st.cache_data(show_spinner=False)
def timeline_data(db_path: str, run_id: str, generated_at: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    from bluesight.db import DB

    d = DB(db_path)
    fr = pd.DataFrame(d.q("SELECT t_s, visibility FROM frames WHERE run_id=? ORDER BY t_s", (run_id,)))
    det = pd.DataFrame(d.q("SELECT t_s, label FROM detections WHERE run_id=?", (run_id,)))
    d.close()
    if fr.empty:
        return fr, fr
    if det.empty:
        cnt = pd.DataFrame({"t_s": fr.t_s, "counted": 0})
    else:
        det["counted"] = det.label.ne("transient (not counted)") & det.label.notna()
        cnt = det.groupby("t_s").counted.sum().reindex(fr.t_s, fill_value=0).reset_index()
    cnt["minute"] = cnt.t_s / 60.0
    fr["minute"] = fr.t_s / 60.0
    return cnt, fr


def timeline(cnt: pd.DataFrame, fr: pd.DataFrame, v_min: float, subsamples: list[float]) -> tuple[alt.Chart, alt.Chart]:
    """Two charts stacked on the same time axis (never a dual y-axis): fish counted per frame, and visibility.
    Both use the same fixed x domain, so they line up exactly."""
    P = T.chart_palette()
    dom = [float(fr.minute.min()), float(fr.minute.max())]
    x = alt.X("minute:Q", title="Video time (minutes)", scale=alt.Scale(domain=dom, zero=False, nice=False),
              axis=alt.Axis(grid=False, labelFontSize=13, titleFontSize=14, titleColor=P["text"], labelColor=P["text"]))
    hover = alt.selection_point(fields=["minute"], nearest=True, on="pointerover", clear="pointerout", empty=False)
    base_c = alt.Chart(cnt)
    area = base_c.mark_area(color=P["count"], opacity=0.18, interpolate="step-after").encode(x=x, y="counted:Q")
    line = base_c.mark_line(color=P["count"], strokeWidth=2, interpolate="step-after").encode(
        x=x, y=alt.Y("counted:Q", title="Fish counted in frame",
                     axis=alt.Axis(labelFontSize=13, titleFontSize=14, titleColor=P["text"], labelColor=P["text"],
                                   gridColor=P["grid"], tickCount=4)))
    pts = base_c.mark_point(size=60, filled=True, color=P["count"]).encode(
        x=x, y="counted:Q", opacity=alt.condition(hover, alt.value(1), alt.value(0)),
        tooltip=[alt.Tooltip("t_s:Q", title="Seconds", format=".1f"), alt.Tooltip("counted:Q", title="Fish counted")]
    ).add_params(hover)
    sub = pd.DataFrame({"minute": [s / 60 for s in subsamples]})
    sub = sub[(sub.minute >= dom[0]) & (sub.minute <= dom[1])]
    subs = alt.Chart(sub).mark_rule(color=P["sub"], strokeDash=[2, 3]).encode(x="minute:Q")
    top = (subs + area + line + pts).properties(height=190, title=alt.Title(
        "Fish counted per sampled frame", subtitle="Dotted lines: the protocol's 60-second subsample points",
        fontSize=15, subtitleFontSize=13, subtitleColor=P["muted"], color=P["text"], anchor="start"))

    base_v = alt.Chart(fr)
    low = base_v.transform_filter(alt.datum.visibility < v_min).mark_bar(color=P["low"], width=alt.RelativeBandSize(1)).encode(
        x=x, y=alt.datum(0), y2=alt.datum(1))
    vline = base_v.mark_line(color=P["vis"], strokeWidth=2).encode(
        x=x, y=alt.Y("visibility:Q", title="Visibility (0–1)", scale=alt.Scale(domain=[0, 1]),
                     axis=alt.Axis(labelFontSize=13, titleFontSize=14, titleColor=P["text"], labelColor=P["text"],
                                   gridColor=P["grid"], tickCount=3)))
    vhover = alt.selection_point(fields=["minute"], nearest=True, on="pointerover", clear="pointerout", empty=False)
    vpts = base_v.mark_point(size=60, filled=True, color=P["vis"]).encode(
        x=x, y="visibility:Q", opacity=alt.condition(vhover, alt.value(1), alt.value(0)),
        tooltip=[alt.Tooltip("t_s:Q", title="Seconds", format=".1f"), alt.Tooltip("visibility:Q", title="Visibility", format=".2f")]
    ).add_params(vhover)
    rule = alt.Chart(pd.DataFrame({"v": [v_min]})).mark_rule(color=P["rule"], strokeDash=[6, 4], strokeWidth=1.5).encode(y="v:Q")
    rule_lbl = alt.Chart(pd.DataFrame({"v": [v_min], "t": [f"identification threshold {v_min:.2f}"]})).mark_text(
        align="left", dx=4, dy=-7, fontSize=12, color=P["rule"]).encode(y="v:Q", x=alt.value(0), text="t:N")
    bot = (low + vline + vpts + rule + rule_lbl).properties(height=150, title=alt.Title(
        "Visibility", subtitle="Grey bands: too murky to identify species; fish there are counted as 'Unable to ID'",
        fontSize=15, subtitleFontSize=13, subtitleColor=P["muted"], color=P["text"], anchor="start"))
    font = "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Arial, sans-serif"
    def done(c: alt.Chart) -> alt.Chart:
        # configure() first: it replaces the whole config, so view/axis settings must come after it
        return c.configure(font=font, background="transparent").configure_view(stroke=None).configure_axis(
            domainColor=P["grid"], tickColor=P["grid"])
    return done(top), done(bot)


def pct(f: float) -> str:
    """Share as a percentage; small non-zero shares are never rounded down to a misleading 0."""
    p = 100 * float(f)
    return "0" if p == 0 else ("<1" if p < 1 else f"{p:.0f}")


def species_table(rep: dict) -> pd.DataFrame:
    sp = pd.DataFrame(rep["species"])
    if sp.empty:
        return sp
    order = {CNT.UNFAMILIAR_LABEL: 2, CNT.UNKNOWN_LABEL: 3}
    sp["_o"] = [order.get(l, 1 if l.startswith("Unconfirmed") else 0) for l in sp.label]
    sp = sp.sort_values(["_o", "MeanCount"], ascending=[True, False])
    out = pd.DataFrame({
        "Species or category": [nice_label(l) for l in sp.label],
        "MaxN": sp.MaxN,
        "MeanCount": sp.MeanCount,
        "Mean (all frames)": sp.MeanCount_all_sampled_frames,
        "Confidence": sp.confidence,
        "Tracks": sp.n_tracks,
        "Verified": sp.verified_tracks,
    })
    return out


def page() -> None:
    cfg = C.cfg()
    T.header("Step 2 of 3 · Results", "Survey results",
             "Counts follow Coastal Action's protocol: one subsample every 60 seconds, and a fish counts if it is visible "
             "within half a second of the subsample point.", step=2)
    runs = C.list_runs()
    if not runs:
        T.empty_state("No results yet", "Results appear here after you analyse a video.",
                      "Go to <b>Analyze</b>, pick a video and press <b>Analyze video</b>.")
        st.page_link(C.PAGES["analyze"], label="Go to Analyze", icon=":material/play_arrow:")
        return
    labels = [C.run_label(r) for r in runs]
    default = next((i for i, r in enumerate(runs) if r["run_id"] == st.session_state.get("last_run")), 0)
    idx = st.selectbox("Analysis", range(len(runs)), index=default, format_func=lambda i: labels[i], key="results_run")
    rep = C.load_report(runs[idx])
    st.session_state["last_run"] = rep["run_id"]
    w = rep["window"]
    th = rep["thresholds"]
    vis = rep["visibility"]
    pending = C.db().q("SELECT COUNT(*) n FROM flags WHERE run_id=? AND review_decision IS NULL", (rep["run_id"],))[0]["n"]
    known_species = [r for r in rep["species"] if r["label"] in rep.get("registry_species", []) and r["n_tracks"] > 0]
    maxn_total = max((s.get("total_fish_count", 0) for s in rep["subsamples"]), default=0)

    st.html(f'<div class="bs-facts"><span>Site <b>{T.esc(rep["site"])}</b></span><span>Date <b>{T.esc(rep["date"])}</b></span>'
            f'<span>Window <b>{C.fmt_t(w["start_s"])}–{C.fmt_t(w["end_s"])}</b> ({w["duration_min"]:.1f} min)</span>'
            f'<span>Subsamples <b>{rep.get("protocol", {}).get("n_subsamples", len(rep.get("subsamples", [])))}</b></span>'
            f'<span>Runtime <b>{rep.get("runtime_s", 0):.0f} s</b></span></div>')
    T.cards([
        {"k": "Fish counted", "v": f"{rep['MeanCount_total_fish']:.1f}", "tone": "info",
         "d": f"MeanCount: mean fish per 60-s subsample · busiest subsample {maxn_total}"},
        {"k": "Species found", "v": len(known_species), "tone": "info",
         "d": ", ".join(nice_label(s["label"]) for s in known_species) or "no registry species matched"},
        {"k": "Items to review", "v": pending, "tone": "attn" if pending else "ok",
         "d": "waiting in the review queue" if pending else "all reviewed"},
        {"k": "Footage with low visibility", "v": pct(vis["fraction_below_v_min"]), "unit": "%",
         "tone": "attn" if vis["fraction_below_v_min"] > 0.25 else "ok", "d": f"below {th['V_MIN']:.2f} · mean visibility {vis['mean']:.2f}"},
    ])
    if vis["fraction_below_v_min"] >= 0.005:
        st.warning(f"{100 * vis['fraction_below_v_min']:.0f}% of this footage is too murky to identify species. Fish seen there are "
                   "counted in 'Unknown/Unable to ID due to visibility', so treat totals as a lower bound, not as zero fish.",
                   icon=":material/visibility_off:")

    sv = survey_form(rep, cfg)
    al = SV.alerts(rep, C.db(), cfg, sv)
    show_alerts(al)
    chk_rows = CC.checks(C.db(), rep["run_id"])
    chk = CC.summary(rep, chk_rows)
    if chk["n_checked"]:
        st.info(f"A person checked **{chk['n_checked']} of {chk['n_subsamples']}** subsamples: MeanCount with checks "
                f"**{chk['MeanCount_checked']:.1f}** (AI alone {chk['MeanCount_ai']:.1f}).", icon=":material/fact_check:")

    # ------------------------------------------------------------------ species table
    st.subheader("Counts by species", anchor=False)
    tab = species_table(rep)
    if tab.empty:
        T.empty_state("No fish counted in this window", "No detections lasted long enough to count.",
                      "Check the visibility chart below; murky footage often explains an empty window.")
    else:
        st.dataframe(tab, hide_index=True, width="stretch", column_config={
            "Species or category": st.column_config.TextColumn(width="large"),
            "MaxN": st.column_config.NumberColumn(help="Most individuals seen in any single sampled frame.", format="%d"),
            "MeanCount": st.column_config.NumberColumn(help="Protocol MeanCount: mean count over the 60-second subsamples.", format="%.2f"),
            "Mean (all frames)": st.column_config.NumberColumn(help="Mean count over every sampled frame (2 per second).", format="%.2f"),
            "Confidence": st.column_config.ProgressColumn(help="Mean similarity of these tracks to the species prototype (0–1). "
                                                          "Blank for the visibility column: nothing was identified.",
                                                          min_value=0.0, max_value=1.0, format="%.2f"),
            "Tracks": st.column_config.NumberColumn(help="Individual fish tracks (each fish keeps one ID)."),
            "Verified": st.column_config.NumberColumn(help="Tracks whose species a biologist confirmed in review."),
        })
        notes = [f"<b>{T.esc(k)}</b>: {v}" for k, v in LABEL_NOTES.items() if k in set(r["label"] for r in rep["species"])]
        st.html('<p class="bs-small">' + "<br>".join(notes + [
            f"Moving blobs that never formed a steady track are not counted ({rep.get('transient_detections_per_frame_not_counted', 0)} per frame on average)."
        ]) + "</p>")

    # ------------------------------------------------------------------ timeline
    st.subheader("Fish and visibility over time", anchor=False)
    cnt, fr = timeline_data(str(C.db().path), rep["run_id"], rep["generated_at"])
    if len(fr):
        c_top, c_bot = timeline(cnt, fr, float(th["V_MIN"]), [s["subsample_t_s"] for s in rep["subsamples"]])
        peak = int(cnt.counted.max()) if len(cnt) else 0
        st.altair_chart(c_top, width="stretch", height=300, theme=None,
                        alt=f"Line chart of fish counted per sampled frame over the analysis window; peak {peak} fish.")
        st.altair_chart(c_bot, width="stretch", height=250, theme=None,
                        alt=f"Line chart of visibility (0 to 1) over the analysis window, mean {vis['mean']:.2f}, "
                            f"with the identification threshold {th['V_MIN']:.2f} marked.")
        with st.expander("Show this chart as a table"):
            st.dataframe(cnt.merge(fr, on=["t_s", "minute"]).rename(columns={"t_s": "Seconds", "counted": "Fish counted",
                                                                               "visibility": "Visibility"}).drop(columns="minute"),
                         hide_index=True, width="stretch", height=260)
    else:
        st.info("No per-frame data stored for this analysis. Re-run it on the Analyze page.")

    # ------------------------------------------------------------------ before / after + annotated video
    left, right = st.columns(2, gap="large")
    with left:
        st.subheader("Original and enhanced", anchor=False)
        video = Path(cfg["_root"]) / cfg["paths"]["videos_dir"] / rep["video_file"]
        if not video.exists():
            video = Path(cfg["_root"]) / "outputs" / "uploads" / rep["video_file"]
        if video.exists():
            t = st.slider("Moment", float(w["start_s"]), float(w["end_s"]), float(w["start_s"] + (w["end_s"] - w["start_s"]) / 4),
                          1.0, key=f"res_t_{rep['run_id']}", format="%.0f s")
            fr0 = read_frame_at(video, t)
            if fr0 is not None:
                small, _ = resize_width(fr0, 960)
                before_after(small, enhance_frame(small, cfg["enhance"]), "Original", "Enhanced")
        else:
            st.info("The original video isn't on this computer any more, so the comparison can't be shown.")
    with right:
        st.subheader("Annotated video", anchor=False)
        ann = rep.get("annotated_video")
        if ann and Path(ann).exists():
            st.video(str(ann))
            st.html('<p class="bs-small">Plays the sampled frames (2 per second). Box colours and labels: '
                    '<b>green</b> known species (name shown) · <b>yellow</b> "?" uncertain · <b>red</b> "NEW?" unfamiliar · '
                    '<b>grey</b> no label: too murky or brief to identify.</p>')
        else:
            st.info("No annotated video for this analysis.")

    # ------------------------------------------------------------------ downloads
    st.subheader("Download", anchor=False)
    run_dir = Path(rep["annotated_video"]).parent if rep.get("annotated_video") else None
    if run_dir and (run_dir / "report.csv").exists():
        rid = rep["run_id"]
        try:
            xlsx = workbook_bytes(rep, cfg, sv, chk_rows, chk if chk["n_checked"] else None, al)
            st.download_button("Download Excel report (protocol layout)", xlsx, f"{rid}.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary",
                               icon=":material/table_view:",
                               help="One row per 60-second subsample with the protocol's columns, plus a summary sheet "
                                    "(MeanCount, MaxN, species, visibility, temperature, checks, alerts).")
        except Exception as exc:  # shown, and the CSV downloads still work
            st.warning(f"Couldn't build the Excel file ({exc}). The CSV downloads below still work.")
        d1, d2, d3 = st.columns(3)
        d1.download_button("Subsample counts (CSV)", (run_dir / "report.csv").read_bytes(), f"{rid}_subsamples.csv", "text/csv",
                           icon=":material/download:", help="One row per 60-second subsample, in the protocol spreadsheet layout.")
        if (run_dir / "species_summary.csv").exists():
            d2.download_button("Species summary (CSV)", (run_dir / "species_summary.csv").read_bytes(), f"{rid}_species.csv",
                               "text/csv", icon=":material/download:")
        d3.download_button("Full report (JSON)", (run_dir / "report.json").read_bytes(), f"{rid}_report.json", "application/json",
                           icon=":material/download:")
    with st.expander("Subsample table (protocol spreadsheet layout)"):
        st.dataframe(pd.DataFrame(rep["subsamples"]), hide_index=True, width="stretch")
    with st.expander("Run details: models, thresholds, timings"):
        st.code(json.dumps({k: rep.get(k) for k in ("ran_on", "offline", "network", "energy", "runtime_s", "timings_s",
                                          "full_processing_s_per_video_min", "models", "thresholds", "sample_fps",
                                          "n_sampled_frames", "n_tracks", "track_status_counts", "registry_species",
                                          "cached_detection")}, indent=2, default=str), language=None)
