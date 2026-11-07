"""Species registry: a gallery of species cards (example images, date added, approved by, 'new' badge)."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from . import common as C
from . import theme as T


def page() -> None:
    cfg = C.cfg()
    db = C.db()
    T.header("Reference library", "Species registry",
             "The species BlueSight can recognise. Each one is described by the average of its reference images, so adding "
             "images in the review queue takes effect immediately. Nothing is retrained.")
    rows = C.registry(read_only=True).list_species()
    held = cfg.get("held_out_species") or []
    if not rows:
        T.empty_state("The registry is empty",
                      "BlueSight can't recognise any species yet, so every fish will go to the review queue.",
                      "Build it from the labelled photos with <code>python scripts/build_registry.py</code>, or approve a "
                      "species in the review queue.")
        return
    n_new = sum(1 for r in rows if r["source"] == "approved")
    st.html(f'<div class="bs-facts"><span><b>{len(rows)}</b> species</span>'
            f'<span><b>{sum(r["n_images"] or 0 for r in rows)}</b> reference images</span>'
            f'<span><b>{n_new}</b> added through review</span></div>')
    q = st.text_input("Find a species", placeholder="Type part of a name", key="reg_q", label_visibility="collapsed")
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
            label = (r["display_name"] or r["name"]).replace("_", " ")
            if imgs:
                st.image(imgs[0], width="stretch", alt=f"Reference image of {label}")
            else:
                st.html('<div style="aspect-ratio:4/3;background:#EAF1F5;border-radius:8px;display:flex;align-items:center;'
                        'justify-content:center;color:#566B7C;font-size:14px">No image on this computer</div>')
            name = (r["display_name"] or r["name"]).replace("_", " ")
            badges = (T.plain_badge("New · added in review", "#1B6B45", "#E6F4EC", "★") if is_new else
                      T.plain_badge("From labelled photos", "#0B5C7A", "#E3EFF5"))
            if not r["active"]:
                badges += " " + T.plain_badge("Inactive", "#4F5B66", "#EDF0F2")
            st.html(f'<div class="bs-sp-head"><p class="bs-sp-name">{T.esc(name[:1].upper() + name[1:])}</p></div>'
                    f'<div style="margin-top:6px">{badges}</div>'
                    f'<dl class="bs-meta"><dt>Added</dt><dd>{T.esc((r["date_added"] or "")[:10])}</dd>'
                    f'<dt>Approved by</dt><dd>{T.esc(r["approved_by"] or "—")}</dd>'
                    f'<dt>Reference images</dt><dd>{r["n_images"] or 0}</dd>'
                    f'<dt>Registry key</dt><dd><code>{T.esc(r["name"])}</code></dd></dl>')
            if len(imgs) > 1:
                st.image(imgs[1:7], width=64, alt=[f"More reference images of {label}"] * len(imgs[1:7]))
    if held:
        st.caption("Held out on purpose, to test that unfamiliar species get flagged: "
                   + ", ".join(h.replace("_", " ").capitalize() for h in held)
                   + ". They are never loaded from the labelled photos; they only appear here if a reviewer approves them.")
