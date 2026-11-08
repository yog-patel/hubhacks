"""Species registry: a gallery of species cards (example images, date added, approved by, 'new' badge)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from bluesight import survey as SV

from . import common as C
from . import theme as T


def page() -> None:
    T.header("", "Species", "What BlueSight knows, what to watch for, and a photo guide.")
    t1, t2, t3 = st.tabs(["Known to BlueSight", "Watch list", "Field guide"])
    with t1:
        gallery()
    with t2:
        watch_tab()
    with t3:
        expected_tab()


def watch_tab() -> None:
    cfg, db = C.cfg(), C.db()
    st.caption("These raise a red alert when seen. Add a usual temperature range to get a warning when the water is "
               "outside it. Leave it empty if unsure.")
    rows = SV.watch_list(db, cfg, include_inactive=True)
    df = pd.DataFrame([{"Common name": r["common"], "Scientific name": r["scientific"], "Group": r["grp"] or "fish",
                        "Why we watch it": r["reason"], "Min °C": r["temp_min_c"], "Max °C": r["temp_max_c"],
                        "Active": bool(r["active"])} for r in rows])
    if df.empty:
        df = pd.DataFrame(columns=["Common name", "Scientific name", "Group", "Why we watch it", "Min °C", "Max °C", "Active"])
    ed = st.data_editor(df, num_rows="dynamic", hide_index=True, width="stretch", key="watch_editor", column_config={
        "Group": st.column_config.SelectboxColumn(options=["fish", "invertebrate"], required=True),
        "Min °C": st.column_config.NumberColumn(min_value=-2.0, max_value=35.0, step=0.5, format="%.1f"),
        "Max °C": st.column_config.NumberColumn(min_value=-2.0, max_value=35.0, step=0.5, format="%.1f"),
        "Why we watch it": st.column_config.TextColumn(width="large"),
        "Active": st.column_config.CheckboxColumn("On"),
    })
    if st.button("Save watch list", icon=":material/save:", disabled=not C.reviewer(),
                 help="Type your name in the sidebar first." if not C.reviewer() else None):
        keep = set()
        for r in ed.to_dict("records"):
            name = str(r.get("Common name") or "").strip()
            if not name:
                continue
            key = SV.slug_name(name)
            keep.add(key)
            num = lambda v: None if v is None or pd.isna(v) else float(v)  # noqa: E731
            SV.save_watch(db, key, name, str(r.get("Scientific name") or ""), str(r.get("Group") or "fish"),
                          str(r.get("Why we watch it") or ""), num(r.get("Min °C")), num(r.get("Max °C")),
                          bool(r.get("Active", True)), C.reviewer())
        for r in rows:
            if r["name"] not in keep:
                SV.save_watch(db, r["name"], r["common"], r["scientific"], r["grp"], r["reason"], r["temp_min_c"],
                              r["temp_max_c"], False, C.reviewer())
        st.toast("Watch list saved.", icon=":material/check_circle:")
        st.rerun()


def expected_tab() -> None:
    cfg = C.cfg()
    st.caption("Nova Scotia species with open-licence photos. A visual aid only; BlueSight never counts from these.")
    inv = set(cfg.get("invertebrate_species") or [])
    try:
        ph = C.fieldguide()[0]
    except Exception:
        ph = {}
    sp = SV.expected_species(cfg) + [w for w in (cfg.get("watch_list") or [])
                                     if w["name"] not in {s["name"] for s in SV.expected_species(cfg)}]
    cols = st.columns(4, gap="small")
    for i, s in enumerate(sp):
        with cols[i % 4], st.container(border=True, key=f"fg_{s['name']}"):
            pics = ph.get(s["name"], [])
            if pics:
                st.image(pics[0]["path"], width="stretch", alt=f"Reference photo of {s['common']}")
            else:
                st.html('<div class="bs-noimg">No photo yet</div>')
            grp = "invertebrate" if s["name"] in inv or s.get("group") == "invertebrate" else "fish"
            st.html(f'<p class="bs-sp-name">{T.esc(s["common"][:1].upper() + s["common"][1:])}</p>'
                    f'<p class="bs-small"><i>{T.esc(s["scientific"])}</i>'
                    + (f'<br>{T.esc(pics[0]["attribution"])} · <a href="{T.esc(pics[0]["observation"])}">source</a>' if pics else "")
                    + '</p>')


def gallery() -> None:
    cfg = C.cfg()
    db = C.db()
    rows = C.registry(read_only=True).list_species()
    held = cfg.get("held_out_species") or []
    if not rows:
        T.empty_state("No species yet", "Name animals on the New animals page and they'll appear here.")
        return
    n_new = sum(1 for r in rows if r["source"] == "approved")
    st.html(f'<div class="bs-facts"><span><b>{len(rows)}</b> species</span>'
            f'<span><b>{sum(r["n_images"] or 0 for r in rows)}</b> pictures</span>'
            f'<span><b>{n_new}</b> named by you</span></div>')
    q = st.text_input("Find a species", placeholder="Search species…", key="reg_q", label_visibility="collapsed",
                      icon=":material/search:")
    if q.strip():
        rows = [r for r in rows if q.strip().lower() in (r["display_name"] or r["name"]).lower()]
        if not rows:
            st.info(f"No species matches “{q.strip()}”.")
    cols = st.columns(3, gap="medium")
    for i, r in enumerate(rows):
        imgs = [p["path"] for p in db.q("SELECT path FROM species_images WHERE species=? ORDER BY added_at DESC LIMIT 7",
                                         (r["name"],))]
        imgs = [p for p in imgs if Path(p).exists()]
        is_new = r["source"] == "approved"
        with cols[i % 3], st.container(border=True, key=f"spcard_{i}"):
            label = SV.display_name(r["name"], cfg)
            if imgs:
                st.image(imgs[0], width="stretch", alt=f"Reference image of {label}")
            else:
                st.html('<div class="bs-noimg">No image on this computer</div>')
            name = SV.display_name(r["name"], cfg)
            badges = (T.plain_badge("Named by you", "ok", "★") if is_new else
                      T.plain_badge("From survey photos", "info"))
            if not r["active"]:
                badges += " " + T.plain_badge("Inactive", "muted")
            st.html(f'<p class="bs-sp-name">{T.esc(name[:1].upper() + name[1:])}</p>'
                    f'<div>{badges}</div>'
                    f'<dl class="bs-meta"><dt>Added</dt><dd>{T.esc((r["date_added"] or "")[:10])}</dd>'
                    f'<dt>By</dt><dd>{T.esc(r["approved_by"] or "survey photos")}</dd>'
                    f'<dt>Pictures</dt><dd>{r["n_images"] or 0}</dd></dl>')
            if len(imgs) > 1:
                st.image(imgs[1:7], width=64, alt=[f"More reference images of {label}"] * len(imgs[1:7]))
    if held:
        st.caption("Kept out on purpose for the demo: " + ", ".join(h.replace("_", " ").capitalize() for h in held) + ".")
