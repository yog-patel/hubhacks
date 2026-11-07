"""Review queue: one item at a time, most clearly unfamiliar first, with large buttons and keyboard shortcuts."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd
import streamlit as st

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
    T.header("Step 3 of 3", "Review queue",
             "BlueSight shows you what it couldn't identify on its own, most unfamiliar first. Nothing is added to the "
             "species registry without your decision, and approving updates the registry straight away (no retraining).")

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
    top_r.html(f'<div class="bs-progress" role="status" aria-live="polite"><b style="color:#0F2230;white-space:nowrap">'
               f'{done_n} of {total} reviewed</b><div class="bar" aria-hidden="true"><span style="width:{pct:.0f}%"></span></div></div>')

    if not C.reviewer():
        st.warning("Type your name in the sidebar first. It's saved with every decision you make.", icon=":material/badge:")

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
        h1.html(f'<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">{T.badge(f["status"])}'
                f'{T.visibility_badge(float(f["visibility"]), float(th["V_MIN"]))}'
                f'<span class="bs-small">Item {cur + 1} of {len(pending)} waiting</span></div>'
                f'<h3 style="margin:10px 0 0">{T.esc(title_for(f, top3))}</h3>')
        h2.html(f'<p class="bs-small" style="text-align:right;margin:0">{T.esc(f["video_file"])}<br>'
                f'<b style="color:#0F2230">{C.fmt_t(f["start_s"])}–{C.fmt_t(f["end_s"])}</b></p>')
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
            st.html('<h4 style="margin:0 0 10px">Closest registry matches</h4>' +
                    T.similarity_bars(top3, float(th["T_KNOWN"]), float(th["T_UNKNOWN"])))
        if crops:
            st.html('<h4 style="margin:4px 0 6px">Best views of this fish</h4>')
            cols = st.container(key="crops").columns(5)
            for n, (c, p) in enumerate(zip(cols, crops), start=1):
                c.image(str(p), width="stretch", alt=f"View {n} of the flagged animal, cropped from the video")

        st.divider()
        st.html(f'<h4 style="margin:0 0 4px">What is it?</h4><p class="bs-small" style="margin:0 0 8px">Shortcuts: '
                f'{T.kbd("N")} new species · {T.kbd("E")} existing species · {T.kbd("X")} reject · '
                f'{T.kbd("J")} skip · {T.kbd("K")} back</p>')
        ok = bool(C.reviewer())
        b1, b2, b3 = st.container(key="decide").columns(3, gap="medium")
        with b1:
            name = st.text_input("Species name", key=f"n_{f['flag_id']}", placeholder="e.g. European green crab")
            if st.button("New species", key=f"new_{f['flag_id']}", type="primary", icon=":material/add_circle:",
                         width="stretch", shortcut="N", disabled=not ok,
                         help="Add this fish to the registry as a new species. Its crops become reference images."):
                if not name.strip():
                    st.error("Type the species name first, then press New species.")
                else:
                    key = C.registry().add_images(name, crops, C.reviewer(), new_species=True, ref_tag=f"{f['flag_id']}_")
                    record_decision(f, "new_species", key)
                    st.toast(f"Added {name.strip()} to the registry. Re-run the video to count it.", icon=":material/check_circle:")
                    st.rerun()
        with b2:
            if species:
                ex = st.selectbox("Registry species", species, key=f"e_{f['flag_id']}", format_func=lambda s: s.replace("_", " "),
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
            st.html('<p class="bs-small" style="margin:0 0 6px">Sand, the pole, debris or a shadow?</p>')
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
        st.subheader(f"Up next ({len(pending) - 1} more)", anchor=False)
        cols = st.columns(3, gap="medium")
        for j, (i, x) in enumerate(rest):
            t3 = json.loads(x["top3"] or "[]")
            with cols[j % 3], st.container(border=True, key=f"upnext_{j}"):
                cps = sorted(Path(x["folder"]).glob("crop_*.jpg"))
                if cps:
                    st.image(str(cps[0]), width="stretch",
                             alt=f"Best view of the item seen at {C.fmt_t(x['start_s'])}–{C.fmt_t(x['end_s'])}")
                bm = (f'best match {t3[0]["similarity"]:.2f} ({T.esc(t3[0]["species"].replace("_", " "))})' if t3
                      else "no registry match")
                st.html(f'<div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">{T.badge(x["status"])}'
                        f'<b style="font-size:16px">{C.fmt_t(x["start_s"])}–{C.fmt_t(x["end_s"])}</b></div>'
                        f'<p class="bs-small" style="margin:6px 0 0">{bm} · visibility {x["visibility"]:.2f}</p>')
                if st.button("Review this one", key=f"go_{x['flag_id']}", width="stretch"):
                    st.session_state["review_cursor"] = i
                    st.rerun()
    _reviewed_table(where, args)
    secs = cfg["evaluation"]["reviewer_seconds_per_item"]
    st.caption(f"At about {secs} seconds per item, the {len(pending)} waiting items take roughly "
               f"{len(pending) * secs / 60:.0f} minute{'s' if len(pending) * secs >= 90 else ''} to review.")


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
