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
        return "Possibly a species not in the registry"
    if top3:
        return f"Probably {top3[0]['species'].replace('_', ' ')}?"
    return "Uncertain match"


def page() -> None:
    cfg = C.cfg()
    db = C.db()
    th = cfg["identify"]
    T.header("Step 3 of 3 · Review", "Review queue",
             "Here's everything BlueSight couldn't identify on its own, most unfamiliar first. Nothing joins the species "
             "registry without your decision, and an approval takes effect straight away (no retraining).", step=3)

    if st.session_state.get("watch_hit"):
        st.error(f"**Watch-list species confirmed.** {st.session_state.pop('watch_hit')}", icon=":material/warning:")
    run_ids = [r["run_id"] for r in db.q("SELECT run_id FROM runs ORDER BY started_at DESC")]
    if not run_ids:
        T.empty_state("Nothing to review yet", "Review items are created when you analyse a video.",
                      "Go to <b>Analyze</b> and run a video; unfamiliar and uncertain fish will appear here.")
        return
    opts = run_ids + ["All analyses"]
    last = st.session_state.get("last_run")
    top_l, top_r = st.columns([3, 2], vertical_alignment="bottom")
    which = top_l.selectbox("Show items from", opts, index=opts.index(last) if last in opts else 0, key="review_run",
                            format_func=lambda r: r if r == "All analyses" else r.replace("__", " · ").replace("_", " "))
    where, args = ("", ()) if which == "All analyses" else (" AND run_id=?", (which,))
    pending = db.q("SELECT * FROM flags WHERE review_decision IS NULL" + where + ORDER, args)
    done_n = db.q("SELECT COUNT(*) n FROM flags WHERE review_decision IS NOT NULL" + where, args)[0]["n"]
    total = len(pending) + done_n
    pct = 100 * done_n / total if total else 100
    top_r.html(f'<div class="bs-progress" role="status" aria-live="polite"><b>'
               f'{done_n} of {total} reviewed</b><div class="bar" aria-hidden="true"><span style="width:{pct:.0f}%"></span></div></div>')

    if not C.reviewer():
        st.warning("Add your name under **Reviewer** in the sidebar to start deciding. It's saved with every decision.",
                   icon=":material/badge:")

    if not pending:
        T.empty_state("All caught up", f"Every item from this analysis has been reviewed ({done_n} decisions).",
                      "Re-run the video on <b>Analyze</b> to count the species you approved.")
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
                f'<span class="bs-small">Item {cur + 1} of {len(pending)}</span></div>'
                f'<p class="bs-item-title">{T.esc(title_for(f, top3))}</p>')
        h2.html(f'<p class="bs-when"><b>{C.fmt_t(f["start_s"])}–{C.fmt_t(f["end_s"])}</b>{T.esc(f["video_file"])}</p>')
        st.html(f'<div class="bs-facts"><span>Seen in <b>{f["track_frames"]}</b> sampled frames</span>'
                f'<span><b>{n_tracks}</b> similar track{"s" if n_tracks != 1 else ""} grouped</span>'
                f'<span>Item ID <code>{T.esc(f["flag_id"])}</code></span></div>')
        left, right = st.columns([3, 2], gap="large")
        with left:
            clip = folder / "clip.mp4"
            if clip.exists():
                st.video(str(clip))
                st.caption("Evidence clip: the fish's track ±2 seconds, boxed in orange.")
            else:
                st.info("No clip was saved for this item; use the crops below.")
        with right:
            st.html('<p class="bs-choice">Closest registry matches</p>' +
                    T.similarity_bars(top3, float(th["T_KNOWN"]), float(th["T_UNKNOWN"])))
        if crops:
            st.html('<p class="bs-choice" style="margin-top:4px">Best views</p>')
            cols = st.container(key="crops").columns(5)
            for n, (c, p) in enumerate(zip(cols, crops), start=1):
                c.image(str(p), width="stretch", alt=f"View {n} of the flagged animal, cropped from the video")
        _field_guide_panel(f, cfg)

        st.divider()
        st.html(f'<div class="bs-sec"><h3>What is it?</h3><span class="hint">Keyboard: '
                f'{T.kbd("N")} new · {T.kbd("E")} existing · {T.kbd("X")} reject · '
                f'{T.kbd("J")} skip · {T.kbd("K")} back</span></div>')
        ok = bool(C.reviewer())
        b1, b2, b3 = st.container(key="decide").columns(3, gap="medium")
        with b1:
            st.html('<p class="bs-choice">A species not in the registry</p>')
            name = st.selectbox("Species name", SV.species_choices(C.db(), cfg), index=None, accept_new_options=True,
                                key=f"n_{f['flag_id']}", placeholder="Pick from the Nova Scotia list, or type a name",
                                help="The list holds the expected Nova Scotia species and the watch list. Type any other "
                                     "name to add it; species not on the list are reported as possible new arrivals.") or ""
            if st.button("New species", key=f"new_{f['flag_id']}", type="primary", icon=":material/add_circle:",
                         width="stretch", shortcut="N", disabled=not ok,
                         help="Add this fish to the registry as a new species. Its crops become reference images."):
                if not name.strip():
                    st.error("Type the species name first, then press New species.")
                else:
                    key = C.registry().add_images(name, crops, C.reviewer(), new_species=True, ref_tag=f"{f['flag_id']}_")
                    record_decision(f, "new_species", key)
                    watch = {w["name"]: w for w in SV.watch_list(C.db(), cfg)}
                    if key in watch:
                        st.session_state["watch_hit"] = f"{name.strip()} is on the watch list: {watch[key]['reason']}"
                    st.toast(f"Added {name.strip()} to the registry. Re-run the video to count it.", icon=":material/check_circle:")
                    st.rerun()
        with b2:
            st.html('<p class="bs-choice">A species we already know</p>')
            if species:
                ex = st.selectbox("Registry species", species, key=f"e_{f['flag_id']}", format_func=lambda s: SV.display_name(s, cfg).capitalize(),
                                  index=species.index(best["species"]) if best and best["species"] in species else 0)
            else:
                ex = None
                st.caption("The registry is empty.")
            if st.button("Existing species", key=f"ex_{f['flag_id']}", icon=":material/check:", width="stretch",
                         shortcut="E", disabled=not (ok and ex),
                         help="Confirm it is this registry species. Its crops are added to that species' reference images."):
                C.registry().add_images(ex, crops, C.reviewer(), new_species=False, ref_tag=f"{f['flag_id']}_")
                record_decision(f, "existing_species", ex)
                st.toast(f"Confirmed as {ex.replace('_', ' ')}. Reference images updated.", icon=":material/check_circle:")
                st.rerun()
        with b3:
            st.html('<p class="bs-choice">Not a fish</p><p class="bs-small" style="margin:0 0 12px">'
                    'Sand, the survey pole, debris or a shadow? Rejected items are left out of the counts.</p>')
            if st.button("Reject: not a fish", key=f"rj_{f['flag_id']}", icon=":material/block:", width="stretch",
                         shortcut="X", disabled=not ok,
                         help="Exclude it from counts. Similar items are rejected automatically on the next run."):
                record_decision(f, "reject", None)
                st.toast("Rejected. It won't be counted, and similar items will be filtered next time.", icon=":material/block:")
                st.rerun()
        n1, n2, _ = st.columns([1, 1, 3])
        if n1.button("Back", key="prev", icon=":material/arrow_back:", shortcut="K", width="stretch", disabled=len(pending) < 2):
            st.session_state["review_cursor"] = (cur - 1) % len(pending)
            st.rerun()
        if n2.button("Skip for now", key="next", icon=":material/arrow_forward:", shortcut="J", width="stretch",
                     disabled=len(pending) < 2):
            st.session_state["review_cursor"] = (cur + 1) % len(pending)
            st.rerun()

    # ------------------------------------------------------------------ up next
    rest = [(i, x) for i, x in enumerate(pending) if i != cur][:9]
    if rest:
        st.subheader(f"Up next · {len(pending) - 1} more", anchor=False)
        cols = st.columns(3, gap="small")
        for j, (i, x) in enumerate(rest):
            t3 = json.loads(x["top3"] or "[]")
            with cols[j % 3], st.container(border=True, key=f"upnext_{j}"):
                cps = sorted(Path(x["folder"]).glob("crop_*.jpg"))
                if cps:
                    st.image(str(cps[0]), width="stretch",
                             alt=f"Best view of the item seen at {C.fmt_t(x['start_s'])}–{C.fmt_t(x['end_s'])}")
                bm = (f'best match {t3[0]["similarity"]:.2f} ({T.esc(t3[0]["species"].replace("_", " "))})' if t3
                      else "no registry match")
                st.html(f'<div class="bs-item-head">{T.badge(x["status"])}</div>'
                        f'<p class="bs-next-meta"><b>{C.fmt_t(x["start_s"])}–{C.fmt_t(x["end_s"])}</b><br>'
                        f'{bm} · visibility {x["visibility"]:.2f}</p>')
                if st.button("Open", key=f"go_{x['flag_id']}", width="stretch", type="tertiary",
                             icon=":material/arrow_outward:"):
                    st.session_state["review_cursor"] = i
                    st.rerun()
    _reviewed_table(where, args)
    secs = cfg["evaluation"]["reviewer_seconds_per_item"]
    st.caption(f"At about {secs} seconds per item, the {len(pending)} waiting items take roughly "
               f"{len(pending) * secs / 60:.0f} minute{'s' if len(pending) * secs >= 90 else ''} to review.")


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
    with st.expander("Compare with the field guide (reference photos)", icon=":material/menu_book:"):
        st.caption("The three Nova Scotia field-guide species whose photos look most like this animal. A visual aid only: "
                   "web photos (often fish in a hand) differ from murky video, so BlueSight never labels or counts from them.")
        cols = st.columns(3)
        for c, n in zip(cols, near):
            p = ph[n["species"]][0]
            c.image(p["path"], width="stretch", alt=f"Reference photo of {SV.display_name(n['species'], cfg)}")
            c.html(f'<p class="bs-small"><b>{T.esc(SV.display_name(n["species"], cfg).capitalize())}</b> · look-alike score '
                   f'{n["similarity"]:.2f}<br>{T.esc(p["attribution"])} · <a href="{T.esc(p["observation"])}">source</a></p>')


def _reviewed_table(where: str, args: tuple) -> None:
    done = C.db().q("SELECT flag_id, status, review_decision, review_species, reviewer, review_timestamp "
                    "FROM flags WHERE review_decision IS NOT NULL" + where + " ORDER BY review_timestamp DESC", args)
    if done:
        with st.expander(f"Your decisions ({len(done)})"):
            df = pd.DataFrame(done).rename(columns={"flag_id": "Item", "status": "Was", "review_decision": "Decision",
                                                    "review_species": "Species", "reviewer": "Reviewer",
                                                    "review_timestamp": "When"})
            df["Decision"] = df["Decision"].map({"new_species": "New species", "existing_species": "Existing species",
                                                 "reject": "Rejected"}).fillna(df["Decision"])
            st.dataframe(df, hide_index=True, width="stretch")
