"""Review queue: one item at a time, most clearly unfamiliar first, with large buttons and keyboard shortcuts."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd
import streamlit as st

from bluesight import survey as SV
from bluesight.logs import get_logger

from . import common as C
from . import theme as T

log = get_logger("app")
ORDER = " ORDER BY (status='unfamiliar') DESC, best_similarity ASC"


def record_decision(flag: dict, decision: str, species: str | None) -> None:
    ts = dt.datetime.now().isoformat(timespec="seconds")
    who = C.reviewer()
    C.db().set_review(flag["flag_id"], decision, species, who, ts)
    fj = Path(flag["folder"]) / "flag.json"
    if fj.exists():
        d = json.loads(fj.read_text())
        d["review"] = {"decision": decision, "species": species, "reviewer": who, "timestamp": ts}
        fj.write_text(json.dumps(d, indent=2))
    log.info("review %s: %s %s by %s", flag["flag_id"], decision, species, who)


def title_for(f: dict, top3: list[dict]) -> str:
    if f["status"] == "unfamiliar":
        return "What is this?"
    if top3:
        return f"Is this a {top3[0]['species'].replace('_', ' ')}?"
    return "What is this?"


def page() -> None:
    cfg = C.cfg()
    db = C.db()
    th = cfg["identify"]
    T.header("", "New animals", "Animals BlueSight couldn't name. You decide; it learns straight away.", step=3)

    if st.session_state.get("watch_hit"):
        st.error(f"**Watch-list species confirmed.** {st.session_state.pop('watch_hit')}", icon=":material/warning:")
    run_ids = [r["run_id"] for r in db.q("SELECT run_id FROM runs ORDER BY started_at DESC")]
    if not run_ids:
        T.empty_state("Nothing here yet", "Analyze a video first.")
        return
    opts = run_ids + ["All analyses"]
    nice_run = {r["run_id"]: f"{r['video_file']} · {C.fmt_t(r['start_s'])}–{C.fmt_t(r['end_s'])}"
                for r in db.q("SELECT run_id, video_file, start_s, end_s FROM runs")}
    last = st.session_state.get("last_run")
    top_l, top_r = st.columns([3, 2], vertical_alignment="bottom")
    which = top_l.selectbox("Video", opts, index=opts.index(last) if last in opts else 0, key="review_run",
                            label_visibility="collapsed",
                            format_func=lambda r: "All videos" if r == "All analyses" else nice_run.get(r, r))
    where, args = ("", ()) if which == "All analyses" else (" AND run_id=?", (which,))
    pending = db.q("SELECT * FROM flags WHERE review_decision IS NULL" + where + ORDER, args)
    done_n = db.q("SELECT COUNT(*) n FROM flags WHERE review_decision IS NOT NULL" + where, args)[0]["n"]
    total = len(pending) + done_n
    pct = 100 * done_n / total if total else 100
    top_r.html(f'<div class="bs-progress" role="status" aria-live="polite"><b>'
               f'{done_n} of {total} done</b><div class="bar" aria-hidden="true"><span style="width:{pct:.0f}%"></span></div></div>')

    if not C.reviewer():
        st.warning("Type your name in the sidebar to start.", icon=":material/badge:")

    if not pending:
        T.empty_state("All done", "Re-run the video on Analyze to count the species you named.")
        _reviewed_table(where, args)
        return

    cur = int(st.session_state.get("review_cursor", 0)) % len(pending)
    f = pending[cur]
    top3 = json.loads(f["top3"] or "[]")
    best = top3[0] if top3 else None
    folder = Path(f["folder"])
    crops = sorted(folder.glob("crop_*.jpg"))
    species = [s["name"] for s in db.q("SELECT name FROM species WHERE active=1 ORDER BY name")]
    n_tracks = len(json.loads(f["track_ids"]))

    # ------------------------------------------------------------------ the focused card
    with st.container(border=True, key="review_card"):
        h1, h2 = st.columns([4, 1], vertical_alignment="center")
        h1.html(f'<div class="bs-item-head">{T.badge(f["status"])}'
                f'{T.visibility_badge(float(f["visibility"]), float(th["V_MIN"]))}'
                f'<span class="bs-small">{cur + 1} of {len(pending)}</span></div>'
                f'<p class="bs-item-title">{T.esc(title_for(f, top3))}</p>')
        h2.html(f'<p class="bs-when"><b>{C.fmt_t(f["start_s"])}–{C.fmt_t(f["end_s"])}</b>{T.esc(f["video_file"])}</p>')

        left, right = st.columns([3, 2], gap="large")
        with left:
            clip = folder / "clip.mp4"
            if clip.exists():
                st.video(str(clip))
            else:
                st.info("No clip saved; see the pictures below.")
        with right:
            st.html('<p class="bs-choice">Looks like</p>' +
                    T.similarity_bars(top3, float(th["T_KNOWN"]), float(th["T_UNKNOWN"])))
        if crops:
            st.html('<p class="bs-choice" style="margin-top:4px">Close-ups</p>')
            cols = st.container(key="crops").columns(5)
            for n, (c, p) in enumerate(zip(cols, crops), start=1):
                c.image(str(p), width="stretch", alt=f"View {n} of the flagged animal, cropped from the video")
        _field_guide_panel(f, cfg)

        st.divider()

        ok = bool(C.reviewer())
        b1, b2, b3 = st.container(key="decide").columns(3, gap="medium")
        with b1:
            st.html('<p class="bs-choice">New species</p>')
            name = st.selectbox("Species name", SV.species_choices(C.db(), cfg), index=None, accept_new_options=True,
                                key=f"n_{f['flag_id']}", placeholder="Pick from the Nova Scotia list, or type a name",
                                label_visibility="collapsed",
                                help="Nova Scotia species and the watch list. Any other name is reported as a possible "
                                     "new arrival.") or ""
            if st.button("Add new species", key=f"new_{f['flag_id']}", type="primary", icon=":material/add_circle:",
                         width="stretch", shortcut="N", disabled=not ok,
                         help="Add it to the species library. Its pictures become the reference."):
                if not name.strip():
                    st.error("Pick or type a name first.")
                else:
                    key = C.registry().add_images(name, crops, C.reviewer(), new_species=True, ref_tag=f"{f['flag_id']}_")
                    record_decision(f, "new_species", key)
                    watch = {w["name"]: w for w in SV.watch_list(C.db(), cfg)}
                    if key in watch:
                        st.session_state["watch_hit"] = f"{name.strip()} is on the watch list: {watch[key]['reason']}"
                    st.toast(f"Added {name.strip()}. Re-run the video to count it.", icon=":material/check_circle:")
                    st.rerun()
        with b2:
            st.html('<p class="bs-choice">Known species</p>')
            if species:
                ex = st.selectbox("Known species", species, key=f"e_{f['flag_id']}", label_visibility="collapsed",
                                  format_func=lambda s: SV.display_name(s, cfg).capitalize(),
                                  index=species.index(best["species"]) if best and best["species"] in species else 0)
            else:
                ex = None
                st.caption("No species yet.")
            if st.button("Confirm species", key=f"ex_{f['flag_id']}", icon=":material/check:", width="stretch",
                         shortcut="E", disabled=not (ok and ex),
                         help="Confirm the species. Its pictures are added to that species' reference."):
                C.registry().add_images(ex, crops, C.reviewer(), new_species=False, ref_tag=f"{f['flag_id']}_")
                record_decision(f, "existing_species", ex)
                st.toast(f"Confirmed: {ex.replace('_', ' ')}", icon=":material/check_circle:")
                st.rerun()
        with b3:
            st.html('<p class="bs-choice">Not an animal</p><p class="bs-small" style="margin:0 0 12px">Sand, pole, shadow</p>')
            if st.button("Mark as not an animal", key=f"rj_{f['flag_id']}", icon=":material/block:", width="stretch",
                         shortcut="X", disabled=not ok,
                         help="Left out of counts. Similar things are skipped next time."):
                record_decision(f, "reject", None)
                st.toast("Removed from the counts.", icon=":material/block:")
                st.rerun()
        n1, n2, _ = st.columns([1, 1, 3])
        if n1.button("Back", key="prev", icon=":material/arrow_back:", shortcut="K", width="stretch", disabled=len(pending) < 2):
            st.session_state["review_cursor"] = (cur - 1) % len(pending)
            st.rerun()
        if n2.button("Skip", key="next", icon=":material/redo:", shortcut="J", width="stretch",
                     disabled=len(pending) < 2):
            st.session_state["review_cursor"] = (cur + 1) % len(pending)
            st.rerun()

    # ------------------------------------------------------------------ up next
    rest = [(i, x) for i, x in enumerate(pending) if i != cur][:9]
    if rest:
        st.subheader(f"Next · {len(pending) - 1} more", anchor=False)
        cols = st.columns(3, gap="small")
        for j, (i, x) in enumerate(rest):
            t3 = json.loads(x["top3"] or "[]")
            with cols[j % 3], st.container(border=True, key=f"upnext_{j}"):
                cps = sorted(Path(x["folder"]).glob("crop_*.jpg"))
                if cps:
                    st.image(str(cps[0]), width="stretch",
                             alt=f"Best view of the item seen at {C.fmt_t(x['start_s'])}–{C.fmt_t(x['end_s'])}")
                st.html(f'<div class="bs-item-head">{T.badge(x["status"])}</div>'
                        f'<p class="bs-next-meta"><b>{C.fmt_t(x["start_s"])}–{C.fmt_t(x["end_s"])}</b></p>')
                if st.button("Open this one", key=f"go_{x['flag_id']}", width="stretch", type="tertiary"):
                    st.session_state["review_cursor"] = i
                    st.rerun()
    _reviewed_table(where, args)
    secs = cfg["evaluation"]["reviewer_seconds_per_item"]
    st.caption(f"About {max(1, round(len(pending) * secs / 60))} min left at {secs} s each.")


def _field_guide_panel(f: dict, cfg: dict) -> None:
    """Closest field-guide species (openly licensed photos) to help a reviewer name the animal. Display only."""
    if C.source() == "Mock data":
        return
    try:
        ph, names, protos = C.fieldguide()
    except Exception as exc:  # the review must keep working without the guide
        log.warning("field guide unavailable: %s", exc)
        return
    if not names:
        return
    from bluesight.db import from_blob
    from bluesight.fieldguide import lookalikes

    near = lookalikes(from_blob(f.get("embedding")), names, protos, 3)
    with st.expander("Compare with the field guide", icon=":material/menu_book:"):
        st.caption("Closest-looking Nova Scotia species from the photo guide. Just a visual aid, never used to count.")
        cols = st.columns(3)
        for c, n in zip(cols, near):
            p = ph[n["species"]][0]
            c.image(p["path"], width="stretch", alt=f"Reference photo of {SV.display_name(n['species'], cfg)}")
            c.html(f'<p class="bs-small"><b>{T.esc(SV.display_name(n["species"], cfg).capitalize())}</b>'
                   f'<br>{T.esc(p["attribution"])} · <a href="{T.esc(p["observation"])}">source</a></p>')


def _reviewed_table(where: str, args: tuple) -> None:
    done = C.db().q("SELECT flag_id, status, review_decision, review_species, reviewer, review_timestamp "
                    "FROM flags WHERE review_decision IS NOT NULL" + where + " ORDER BY review_timestamp DESC", args)
    if done:
        with st.expander(f"Your answers ({len(done)})"):
            df = pd.DataFrame(done).rename(columns={"flag_id": "Item", "status": "Was", "review_decision": "Decision",
                                                    "review_species": "Species", "reviewer": "Reviewer",
                                                    "review_timestamp": "When"})
            df["Decision"] = df["Decision"].map({"new_species": "New species", "existing_species": "Known species",
                                                 "reject": "Not an animal"}).fillna(df["Decision"])
            st.dataframe(df, hide_index=True, width="stretch")
