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
        return "Maybe " + SV.display_name(label.split("probably ", 1)[1].rstrip("?"), cfg)
    if label == CNT.UNKNOWN_LABEL:
        return "Too murky to name"
    if label == CNT.UNFAMILIAR_LABEL:
        return "New animal (waiting for you)"
    n = SV.display_name(label, cfg)
    return n[:1].upper() + n[1:]


def survey_form(rep: dict, cfg: dict) -> dict:
    """Survey details typed in by staff (never fetched online). Saved per analysis and added to the Excel file."""
    db = C.db()
    sv = SV.get_survey(db, rep["run_id"])
    filled = sv.get("water_temp_c") is not None or sv.get("pole_visibility") not in (None, "Not recorded")
    with st.expander(("Survey details ✓" if filled else "Add survey details") + " · temperature, pole, juveniles",
                     icon=":material/edit_note:", expanded=False):
        with st.form(f"survey_{rep['run_id']}", border=False):
            a, b, c = st.columns(3)
            site = a.text_input("Site", sv.get("site") or rep["site"])
            date = b.text_input("Survey date", sv.get("date") or rep["date"], help="YYYY-MM-DD")
            obs = c.text_input("Observer", sv.get("observer") or C.reviewer())
            d, e, f = st.columns(3)
            has_t = d.checkbox("I have the water temperature", value=sv.get("water_temp_c") is not None)
            temp = d.number_input("Water temperature (°C)", -2.0, 35.0, float(sv.get("water_temp_c") or 12.0), 0.1,
                                  help="From your field sheet. Used for the watch-list check.")
            pole = e.selectbox("Visibility (pole reading)", SV.POLE_CHOICES,
                               index=SV.POLE_CHOICES.index(sv["pole_visibility"]) if sv.get("pole_visibility") in SV.POLE_CHOICES else 0,
                               help="Read off the 2 m pole (black tape every 0.5 m), as in the protocol.")
            juv = f.selectbox("Juveniles present", ["Not recorded", "1 = present", "0 = absent"],
                              index={None: 0, 1: 1, 0: 2}.get(sv.get("juveniles"), 0))
            notes = st.text_area("Notes", sv.get("notes") or "", height=68)
            if st.form_submit_button("Save survey details", icon=":material/save:"):
                SV.save_survey(db, rep["run_id"], site=site, date=date, observer=obs,
                               water_temp_c=float(temp) if has_t else None, pole_visibility=pole,
                               juveniles={"1 = present": 1, "0 = absent": 0}.get(juv), notes=notes)
                st.toast("Saved. Included in the Excel file.", icon=":material/check_circle:")
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
    x = alt.X("minute:Q", title="Time in the video", scale=alt.Scale(domain=dom, zero=False, nice=False),
              axis=alt.Axis(grid=False, labelFontSize=13, titleFontSize=14, titleColor=P["text"], labelColor=P["text"],
                            tickCount=8, labelExpr="floor(datum.value) + ':' + (floor((datum.value % 1) * 60) < 10 ? '0' : '') + floor((datum.value % 1) * 60)"))
    hover = alt.selection_point(fields=["minute"], nearest=True, on="pointerover", clear="pointerout", empty=False)
    base_c = alt.Chart(cnt)
    area = base_c.mark_area(color=P["count"], opacity=0.18, interpolate="step-after").encode(x=x, y="counted:Q")
    line = base_c.mark_line(color=P["count"], strokeWidth=2, interpolate="step-after").encode(
        x=x, y=alt.Y("counted:Q", title="Fish",
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
        "Fish seen in each frame", subtitle="Dotted lines: the 1-minute check points",
        fontSize=15, subtitleFontSize=13, subtitleColor=P["muted"], color=P["text"], anchor="start"))

    base_v = alt.Chart(fr)
    low = base_v.transform_filter(alt.datum.visibility < v_min).mark_bar(color=P["low"], width=alt.RelativeBandSize(1)).encode(
        x=x, y=alt.datum(0), y2=alt.datum(1))
    vline = base_v.mark_line(color=P["vis"], strokeWidth=2).encode(
        x=x, y=alt.Y("visibility:Q", title="Clarity", scale=alt.Scale(domain=[0, 1]),
                     axis=alt.Axis(labelFontSize=13, titleFontSize=14, titleColor=P["text"], labelColor=P["text"],
                                   gridColor=P["grid"], tickCount=3)))
    vhover = alt.selection_point(fields=["minute"], nearest=True, on="pointerover", clear="pointerout", empty=False)
    vpts = base_v.mark_point(size=60, filled=True, color=P["vis"]).encode(
        x=x, y="visibility:Q", opacity=alt.condition(vhover, alt.value(1), alt.value(0)),
        tooltip=[alt.Tooltip("t_s:Q", title="Seconds", format=".1f"), alt.Tooltip("visibility:Q", title="Visibility", format=".2f")]
    ).add_params(vhover)
    rule = alt.Chart(pd.DataFrame({"v": [v_min]})).mark_rule(color=P["rule"], strokeDash=[6, 4], strokeWidth=1.5).encode(y="v:Q")
    rule_lbl = alt.Chart(pd.DataFrame({"v": [v_min], "t": ["below: too murky to name species"]})).mark_text(
        align="left", dx=4, dy=-7, fontSize=12, color=P["rule"]).encode(y="v:Q", x=alt.value(0), text="t:N")
    bot = (low + vline + vpts + rule + rule_lbl).properties(height=150, title=alt.Title(
        "Water clarity", subtitle="Grey = too murky to name species",
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
    return pd.DataFrame({
        "Species": [nice_label(l) for l in sp.label],
        "Average per check point": sp.MeanCount,
        "Most at once": sp.MaxN,
        "Match": sp.confidence,
        "Fish followed": sp.n_tracks,
        "Confirmed by you": sp.verified_tracks,
    })


def checkpoint_chart(rep: dict, chk_rows: list[dict]) -> alt.Chart:
    """One bar per 1-minute check point: the count used in the report (yours if checked, else the AI's), plus the second
    AI count as a dot."""
    P = T.chart_palette()
    by = {}
    for r in chk_rows:
        k = round(r["subsample_t_s"], 3)
        if k not in by or r["mode"] == "assisted":
            by[k] = r
    rows = []
    for i, s in enumerate(rep["subsamples"], start=1):
        c = by.get(round(s["subsample_t_s"], 3))
        rows.append({"point": i, "time": s["time"], "count": c["human_fish"] if c else s["total_fish_count"],
                     "who": "Checked by you" if c else "AI", "second": s.get("density_count"),
                     "flag": "⚑" if s.get("estimates_disagree") and not c else ""})
    df = pd.DataFrame(rows)
    x = alt.X("point:O", title="Check point (one per minute)", axis=alt.Axis(labelAngle=0, labelColor=P["text"],
                                                                            titleColor=P["text"], labelFontSize=13))
    bars = alt.Chart(df).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3, size=min(48, max(14, 600 // max(1, len(df))))).encode(
        x=x, y=alt.Y("count:Q", title="Fish", axis=alt.Axis(labelColor=P["text"], titleColor=P["text"], gridColor=P["grid"])),
        color=alt.Color("who:N", scale=alt.Scale(domain=["AI", "Checked by you"], range=[P["sub"], P["count"]]),
                        legend=None),
        tooltip=["time", alt.Tooltip("count:Q", title="Fish"), alt.Tooltip("who:N", title="Counted by"),
                 alt.Tooltip("second:Q", title="Second AI count", format=".0f")])
    layers = bars
    if df["second"].notna().any():
        layers = layers + alt.Chart(df.dropna(subset=["second"])).mark_point(shape="diamond", size=70, filled=True,
                                                                            color=P["rule"]).encode(
            x=x, y="second:Q", tooltip=["time", alt.Tooltip("second:Q", title="Second AI count", format=".0f")])
    layers = layers + alt.Chart(df).mark_text(dy=-8, fontSize=14, color=P["rule"]).encode(x=x, y="count:Q", text="flag:N")
    return layers.properties(height=230).configure(background="transparent",
                                                   font="-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Arial, sans-serif"
                                                   ).configure_view(stroke=None)


def page() -> None:
    cfg = C.cfg()
    T.header("", "Report", None, step=4)
    runs = C.list_runs()
    if not runs:
        T.empty_state("No report yet", "Analyze a video first.")
        st.page_link(C.PAGES["analyze"], label="Go to Analyze", icon=":material/play_arrow:")
        return
    labels = [C.run_label(r) for r in runs]
    default = next((i for i, r in enumerate(runs) if r["run_id"] == st.session_state.get("last_run")), 0)
    idx = st.selectbox("Video", range(len(runs)), index=default, format_func=lambda i: labels[i], key="results_run",
                       label_visibility="collapsed")
    rep = C.load_report(runs[idx])
    st.session_state["last_run"] = rep["run_id"]
    w = rep["window"]
    th = rep["thresholds"]
    vis = rep["visibility"]
    known_species = [r for r in rep["species"] if r["label"] in rep.get("registry_species", []) and r["n_tracks"] > 0]
    chk_rows = CC.checks(C.db(), rep["run_id"])
    chk = CC.summary(rep, chk_rows)
    sv = SV.get_survey(C.db(), rep["run_id"])
    al = SV.alerts(rep, C.db(), cfg, sv)

    st.html(f'<div class="bs-facts"><span>Site <b>{T.esc(sv.get("site") or rep["site"])}</b></span>'
            f'<span>Date <b>{T.esc(sv.get("date") or rep["date"])}</b></span>'
            f'<span>Video <b>{C.fmt_t(w["start_s"])}–{C.fmt_t(w["end_s"])}</b></span></div>')
    show_alerts(al)
    checked = chk["n_checked"] > 0
    mean = chk["MeanCount_checked"] if checked else rep["MeanCount_total_fish"]
    most = max((s.get("total_fish_count", 0) for s in rep["subsamples"]), default=0)
    names = ", ".join(nice_label(r["label"]).lower() for r in known_species) or "none yet"
    murky = pct(vis["fraction_below_v_min"])
    st.html(f'<p class="bs-summary">An average of <b title="Protocol MeanCount">{mean:.1f} fish</b> per check point'
            f'{"" if checked else " (AI count, not yet checked)"}, and at most <b title="Protocol MaxN">{most}</b> at one moment. '
            f'Species named: <b>{T.esc(names)}</b>. '
            + (f'<b class="w">{murky}%</b> of the video was too murky to name species.' if vis["fraction_below_v_min"] > 0
               else 'The water was clear enough to name species throughout.') + '</p>')
    if not checked:
        n = len(rep["subsamples"])
        st.page_link(C.PAGES["check"], label=f"Confirm these counts: check {n} frame{'s' if n != 1 else ''}",
                     icon=":material/rule:")

    # ------------------------------------------------------------------ check points
    st.subheader("Fish at each check point", anchor=False)
    if (rep.get("density") or {}).get("MeanCount_density") is not None:
        st.html('<p class="bs-key"><span class="sw" style="background:var(--border-strong)"></span>AI count'
                '<span class="sw" style="background:var(--primary)"></span>Checked by you'
                '<span class="dm">◆</span>Second AI count<span class="fl">⚑</span>The two disagree</p>')
    st.altair_chart(checkpoint_chart(rep, chk_rows), width="stretch", theme=None,
                    alt="Bar chart of fish counted at each one-minute check point")

    # ------------------------------------------------------------------ species
    st.subheader("Species", anchor=False)
    tab = species_table(rep)
    if tab.empty:
        T.empty_state("No fish counted here", "The water may have been too murky. See the clarity chart below.")
    else:
        st.dataframe(tab[["Species", "Average per check point", "Most at once", "Match"]], hide_index=True, width="stretch",
                     column_config={
                         "Species": st.column_config.TextColumn(width="large"),
                         "Average per check point": st.column_config.NumberColumn(format="%.1f", help="Protocol MeanCount"),
                         "Most at once": st.column_config.NumberColumn(format="%d", help="Protocol MaxN"),
                         "Match": st.column_config.ProgressColumn(help="How closely these fish match the species' pictures",
                                                                  min_value=0.0, max_value=1.0, format=" "),
                     })

    sv = survey_form(rep, cfg)

    # ------------------------------------------------------------------ downloads
    run_dir = Path(rep["annotated_video"]).parent if rep.get("annotated_video") else None
    if run_dir and (run_dir / "report.csv").exists():
        rid = rep["run_id"]
        try:
            xlsx = workbook_bytes(rep, cfg, sv, chk_rows, chk if chk["n_checked"] else None, al)
            st.download_button("Download Excel report", xlsx, f"{rid}.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary",
                               icon=":material/table_view:", help="Your protocol spreadsheet layout, one row per check point.")
        except Exception as exc:  # shown, and the CSV downloads still work
            st.warning(f"Couldn't build the Excel file ({exc}). Use the other formats below.")

    # ------------------------------------------------------------------ through the video
    st.subheader("Through the video", anchor=False)
    cnt, fr = timeline_data(str(C.db().path), rep["run_id"], rep["generated_at"])
    if len(fr):
        c_top, c_bot = timeline(cnt, fr, float(th["V_MIN"]), [s["subsample_t_s"] for s in rep["subsamples"]])
        st.altair_chart(c_top, width="stretch", height=300, theme=None, alt="Fish seen in each frame over time")
        st.altair_chart(c_bot, width="stretch", height=250, theme=None, alt="Water clarity over time")
    left, right = st.columns(2, gap="large")
    with left:
        video = Path(cfg["_root"]) / cfg["paths"]["videos_dir"] / rep["video_file"]
        if not video.exists():
            video = Path(cfg["_root"]) / "outputs" / "uploads" / rep["video_file"]
        if video.exists():
            t = st.slider("Before and after clean-up", float(w["start_s"]), float(w["end_s"]),
                          float(w["start_s"] + (w["end_s"] - w["start_s"]) / 4), 1.0, key=f"res_t_{rep['run_id']}", format="%.0f s")
            fr0 = read_frame_at(video, t)
            if fr0 is not None:
                small, _ = resize_width(fr0, 960)
                before_after(small, enhance_frame(small, cfg["enhance"]), "Original", "Cleaned up")
    with right:
        ann = rep.get("annotated_video")
        if ann and Path(ann).exists():
            st.html('<p class="bs-choice">What the AI saw</p><p class="bs-key"><span class="sw" style="background:#3CC850"></span>Named'
                    '<span class="sw" style="background:#FFC800"></span>Not sure<span class="sw" style="background:#FF5000"></span>New'
                    '<span class="sw" style="background:#A0A0A0"></span>Too murky</p>')
            st.video(str(ann))

    # ------------------------------------------------------------------ more
    with st.expander("Other formats and technical details", icon=":material/folder_open:"):
        if run_dir and (run_dir / "report.csv").exists():
            d1, d2, d3 = st.columns(3)
            rid = rep["run_id"]
            d1.download_button("Check points (CSV)", (run_dir / "report.csv").read_bytes(), f"{rid}_subsamples.csv",
                               "text/csv", icon=":material/download:")
            if (run_dir / "species_summary.csv").exists():
                d2.download_button("Species (CSV)", (run_dir / "species_summary.csv").read_bytes(), f"{rid}_species.csv",
                                   "text/csv", icon=":material/download:")
            d3.download_button("Everything (JSON)", (run_dir / "report.json").read_bytes(), f"{rid}_report.json",
                               "application/json", icon=":material/download:")
        if not tab.empty:
            st.dataframe(tab, hide_index=True, width="stretch")
        st.dataframe(pd.DataFrame(rep["subsamples"]), hide_index=True, width="stretch")
        st.code(json.dumps({k: rep.get(k) for k in ("ran_on", "offline", "network", "energy", "runtime_s", "timings_s",
                                                    "models", "thresholds", "sample_fps", "n_sampled_frames", "n_tracks",
                                                    "track_status_counts", "registry_species", "cached_detection")},
                           indent=2, default=str), language=None)
