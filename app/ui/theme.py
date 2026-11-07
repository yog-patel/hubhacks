"""BlueSight design system: tokens, global CSS and small HTML components.

Tokens (all text colours >= 4.5:1 on every surface they are used on; computed, see DECISIONS.md D16):

    colour   ink #0F2230 · ink-2 #3E5466 · muted #566B7C · primary #0B5C7A · border #C9D6DF / strong #8197A6
             surfaces: bg #F4F7F9 · card #FFFFFF · tint #EAF1F5
             status (reserved; always icon + text, never colour alone):
               known #1B6B45 on #E6F4EC · uncertain #8A5300 on #FFF3DC
               unfamiliar #B42318 on #FDECEA · low visibility #4F5B66 on #EDF0F2
    type     12 caption-xs · 14 small · 16 body · 18 h4 · 22 h3 · 28 h2 · 34 h1 (system font stack: no web fonts,
             so the browser never contacts a font CDN)
    space    4 · 8 · 12 · 16 · 24 · 32 · 48 px
    radius   8 px controls · 12 px cards
"""
from __future__ import annotations

import html
from typing import Iterable

import streamlit as st

STATUS = {
    # key: (label, icon, fg, bg, plain-language explanation)
    "known": ("Known species", "✓", "#1B6B45", "#E6F4EC", "Matches a species in the registry; counted automatically."),
    "uncertain": ("Uncertain", "?", "#8A5300", "#FFF3DC", "Looks like a registry species, but not closely enough to count without you."),
    "unfamiliar": ("Unfamiliar", "!", "#B42318", "#FDECEA", "Does not match any species in the registry. Possibly new to the registry."),
    "unidentified_low_visibility": ("Low visibility", "◐", "#4F5B66", "#EDF0F2",
                                    "Too murky, too small or too brief to identify. Never flagged as a new species."),
    "rejected": ("Rejected", "✕", "#4F5B66", "#EDF0F2", "A reviewer marked this as not a fish."),
}

CSS = """
<style>
:root{
  --ink:#0F2230; --ink-2:#3E5466; --muted:#566B7C; --primary:#0B5C7A; --primary-hover:#084A63; --primary-tint:#E3EFF5;
  --bg:#F4F7F9; --card:#FFFFFF; --tint:#EAF1F5; --border:#C9D6DF; --border-strong:#8197A6;
  --s1:4px; --s2:8px; --s3:12px; --s4:16px; --s5:24px; --s6:32px; --s7:48px;
  --r-ctl:8px; --r-card:12px;
  --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
}
html, body, [data-testid="stApp"]{ font-family:var(--font); color:var(--ink); }
[data-testid="stMainBlockContainer"]{ max-width:1280px; padding-top:var(--s6); padding-bottom:var(--s7); }
/* type scale */
h1{ font-size:34px !important; line-height:1.2 !important; font-weight:650 !important; letter-spacing:-0.01em; }
h2{ font-size:28px !important; line-height:1.25 !important; font-weight:650 !important; }
h3{ font-size:22px !important; line-height:1.3 !important; font-weight:600 !important; }
h4{ font-size:18px !important; line-height:1.35 !important; font-weight:600 !important; }
p, li, label, [data-testid="stMarkdownContainer"]{ font-size:16px; line-height:1.55; }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p, .bs-small{ font-size:14px !important; color:var(--muted) !important;
  opacity:1 !important; line-height:1.5; }
[data-testid="stWidgetLabel"] p{ font-size:15px !important; font-weight:600; color:var(--ink) !important; }
/* image crops: same height, nothing stretched */
.st-key-crops [data-testid="stImage"] img{ height:120px; width:100%; object-fit:contain; background:var(--tint); border-radius:8px; }
[class*="st-key-upnext"] [data-testid="stImage"] img{ height:150px; width:100%; object-fit:cover; border-radius:8px; }
[class*="st-key-spcard"] [data-testid="stImage"]:first-of-type img{ border-radius:8px; }
/* visible keyboard focus everywhere (WCAG 2.4.7) */
button:focus-visible, a:focus-visible, input:focus-visible, [role="radio"]:focus-visible, [tabindex]:focus-visible{
  outline:3px solid var(--primary) !important; outline-offset:2px !important; }
/* buttons: >= 44 px targets (WCAG 2.5.5) */
.stButton button, .stDownloadButton button, [data-testid="stFormSubmitButton"] button{
  min-height:44px; font-weight:600; border-radius:var(--r-ctl); }
.st-key-decide .stButton button{ min-height:56px; font-size:17px; }
/* keyboard-shortcut hints inside buttons: Streamlit draws them at 60% opacity; full opacity keeps 4.5:1 */
button kbd[aria-label^="Shortcut"]{ opacity:1 !important; font-weight:700; border:1px solid currentColor; border-radius:4px;
  padding:0 5px; margin-left:8px; font-size:13px; line-height:1.5; background:transparent; }
/* bordered containers become cards */
[data-testid="stVerticalBlockBorderWrapper"]{ border-radius:var(--r-card) !important; background:var(--card); }
/* sidebar */
[data-testid="stSidebar"]{ border-right:1px solid var(--border); }
[data-testid="stSidebarNav"] a span{ font-size:16px; opacity:1 !important; color:var(--ink) !important; }
[data-testid="stSidebarNav"] a, [data-testid="stSidebarNavSeparator"], [data-testid="stNavSectionHeader"]{ opacity:1 !important; }
[data-testid="stNavSectionHeader"], [data-testid="stNavSectionHeader"] *{ color:var(--ink-2) !important; opacity:1 !important; }
/* page header */
.bs-eyebrow{ font-size:13px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; color:var(--primary); margin:0 0 var(--s1); }
.bs-lede{ font-size:17px; color:var(--ink-2); margin:0 0 var(--s5); max-width:72ch; }
/* badges */
.bs-badge{ display:inline-flex; align-items:center; gap:6px; padding:3px 10px; border-radius:999px; font-size:14px;
  font-weight:600; line-height:1.4; border:1px solid currentColor; white-space:nowrap; }
.bs-badge .ico{ font-weight:800; }
.bs-local{ display:flex; align-items:center; gap:10px; padding:10px 12px; border-radius:var(--r-card);
  background:#E6F4EC; color:#1B6B45; border:1px solid #9CCBB1; font-size:14px; line-height:1.4; }
.bs-local b{ color:#14522F; }
.bs-local .dot{ width:10px; height:10px; border-radius:50%; background:#1B6B45; flex:none; box-shadow:0 0 0 3px #CDE9D8; }
.bs-local.warn{ background:#FFF3DC; color:#8A5300; border-color:#E5C07A; } .bs-local.warn .dot{ background:#8A5300; box-shadow:0 0 0 3px #FBE3B5; }
/* metric cards */
.bs-cards{ display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:var(--s4); margin:var(--s2) 0 var(--s5); }
.bs-card{ background:var(--card); border:1px solid var(--border); border-radius:var(--r-card); padding:var(--s4) var(--s5); }
.bs-card .k{ font-size:14px; color:var(--ink-2); font-weight:600; margin-bottom:var(--s1); }
.bs-card .v{ font-size:34px; font-weight:700; color:var(--ink); line-height:1.15; font-variant-numeric:tabular-nums; }
.bs-card .v small{ font-size:16px; font-weight:600; color:var(--ink-2); margin-left:4px; }
.bs-card .d{ font-size:14px; color:var(--muted); margin-top:var(--s1); line-height:1.45; }
.bs-card.attn{ border-left:5px solid #8A5300; } .bs-card.ok{ border-left:5px solid #1B6B45; } .bs-card.info{ border-left:5px solid var(--primary); }
/* similarity bars */
.bs-sim{ margin:0 0 var(--s3); }
.bs-sim .row{ display:flex; justify-content:space-between; font-size:15px; margin-bottom:4px; gap:8px; }
.bs-sim .row b{ font-variant-numeric:tabular-nums; }
.bs-sim .track{ position:relative; height:12px; background:var(--tint); border-radius:6px; border:1px solid var(--border); }
.bs-sim .fill{ position:absolute; left:0; top:0; bottom:0; border-radius:6px; background:var(--primary); }
.bs-sim .tick{ position:absolute; top:-4px; bottom:-4px; width:2px; background:var(--ink); }
.bs-sim .legend{ font-size:13px; color:var(--muted); margin-top:2px; }
/* stepper */
.bs-steps{ display:flex; gap:var(--s2); flex-wrap:wrap; margin:var(--s3) 0 var(--s4) !important; padding:0 !important; list-style:none; }
.bs-steps li{ margin:0 !important; }
.bs-steps li{ flex:1 1 140px; display:flex; align-items:center; gap:10px; padding:10px 12px; border-radius:var(--r-ctl);
  border:1px solid var(--border); background:var(--card); font-size:15px; color:var(--muted); }
.bs-steps .n{ width:26px; height:26px; border-radius:50%; display:inline-flex; align-items:center; justify-content:center;
  font-size:14px; font-weight:700; border:2px solid var(--border-strong); color:var(--ink-2); flex:none; }
.bs-steps li.active{ border-color:var(--primary); color:var(--ink); background:var(--primary-tint); font-weight:600; }
.bs-steps li.active .n{ border-color:var(--primary); color:var(--primary); }
.bs-steps li.done{ color:var(--ink-2); } .bs-steps li.done .n{ background:#1B6B45; border-color:#1B6B45; color:#fff; }
.bs-steps .s{ display:block; font-size:13px; font-weight:400; color:var(--muted); }
/* empty state */
.bs-empty{ text-align:left; padding:var(--s6); border:1px dashed var(--border-strong); border-radius:var(--r-card); background:var(--card); }
.bs-empty h4{ margin:0 0 var(--s2); } .bs-empty p{ margin:0 0 var(--s2); color:var(--ink-2); }
/* species gallery */
.bs-sp-head{ display:flex; align-items:center; justify-content:space-between; gap:8px; flex-wrap:wrap; }
.bs-sp-name{ font-size:20px; font-weight:650; margin:0; }
.bs-meta{ margin:var(--s2) 0 !important; padding:0 !important; display:grid; grid-template-columns:max-content 1fr; white-space:nowrap; gap:2px 12px; font-size:14px; margin:var(--s2) 0; }
.bs-meta dt{ color:var(--muted); } .bs-meta dd{ margin:0; color:var(--ink); white-space:normal; overflow-wrap:anywhere; }
/* review */
.bs-progress{ display:flex; align-items:center; gap:var(--s3); font-size:15px; color:var(--ink-2); }
.bs-progress .bar{ flex:1; height:10px; border-radius:5px; background:var(--tint); border:1px solid var(--border); overflow:hidden; }
.bs-progress .bar span{ display:block; height:100%; background:#1B6B45; }
.bs-kbd{ display:inline-block; min-width:22px; padding:1px 6px; border:1px solid var(--border-strong); border-bottom-width:2px;
  border-radius:5px; font:600 13px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace; color:var(--ink); background:#fff; text-align:center; }
.bs-facts{ display:flex; flex-wrap:wrap; gap:var(--s2) var(--s4); font-size:15px; color:var(--ink-2); margin:var(--s2) 0 var(--s3); }
.bs-facts b{ color:var(--ink); }
table.bs-table{ border-collapse:collapse; width:100%; font-size:15px; }
table.bs-table th{ text-align:left; color:var(--ink-2); font-weight:600; border-bottom:2px solid var(--border); padding:8px 10px; }
table.bs-table td{ border-bottom:1px solid var(--border); padding:8px 10px; vertical-align:top; }
table.bs-table code{ font-size:13px; word-break:break-all; }
</style>
"""


def inject() -> None:
    """Add the global stylesheet (call once per page run)."""
    st.html(CSS)


def esc(s: object) -> str:
    return html.escape(str(s))


def header(eyebrow: str, title: str, lede: str | None = None) -> None:
    """Page header: small eyebrow label, H1 title, one-sentence lede."""
    st.html(f'<p class="bs-eyebrow">{esc(eyebrow)}</p>')
    st.title(title, anchor=False)
    if lede:
        st.html(f'<p class="bs-lede">{lede}</p>')


def badge(status: str, text: str | None = None) -> str:
    """Status badge HTML: icon + text + colour (never colour alone)."""
    label, ico, fg, bg, expl = STATUS.get(status, (status, "•", "#3E5466", "#EAF1F5", ""))
    return (f'<span class="bs-badge" style="color:{fg};background:{bg}" title="{esc(expl)}">'
            f'<span class="ico" aria-hidden="true">{ico}</span>{esc(text or label)}</span>')


def plain_badge(text: str, fg: str = "#0B5C7A", bg: str = "#E3EFF5", icon: str = "") -> str:
    ico = f'<span class="ico" aria-hidden="true">{icon}</span>' if icon else ""
    return f'<span class="bs-badge" style="color:{fg};background:{bg}">{ico}{esc(text)}</span>'


def visibility_badge(v: float, v_min: float) -> str:
    """Visibility score with a word label, so it does not rely on colour."""
    if v < v_min:
        return plain_badge(f"Visibility {v:.2f} · too murky", "#4F5B66", "#EDF0F2", "◐")
    if v < v_min + 0.15:
        return plain_badge(f"Visibility {v:.2f} · fair", "#8A5300", "#FFF3DC", "◑")
    return plain_badge(f"Visibility {v:.2f} · good", "#1B6B45", "#E6F4EC", "●")


def cards(items: Iterable[dict]) -> None:
    """Headline metric cards: dicts with k (label), v (value), optional unit, d (detail), tone (ok/attn/info)."""
    out = []
    for c in items:
        unit = f"<small>{esc(c['unit'])}</small>" if c.get("unit") else ""
        out.append(f'<div class="bs-card {c.get("tone", "")}" role="group" aria-label="{esc(c["k"])}">'
                   f'<div class="k">{esc(c["k"])}</div><div class="v">{esc(c["v"])}{unit}</div>'
                   f'<div class="d">{c.get("d", "")}</div></div>')
    st.html('<div class="bs-cards">' + "".join(out) + "</div>")


def similarity_bars(top3: list[dict], t_known: float, t_unknown: float) -> str:
    """Top-3 matches as labelled bars with the two thresholds marked (value shown as text, too)."""
    if not top3:
        return '<p class="bs-small">The registry is empty, so there is nothing to compare against.</p>'
    rows = []
    for m in top3:
        s = max(0.0, min(1.0, float(m["similarity"])))
        verdict = "close match" if s >= t_known else ("partial match" if s >= t_unknown else "no match")
        rows.append(
            f'<div class="bs-sim"><div class="row"><span>{esc(m["species"].replace("_", " ").capitalize())}</span>'
            f'<span><b>{s:.2f}</b> · {verdict}</span></div>'
            f'<div class="track" role="img" aria-label="similarity {s:.2f} of 1">'
            f'<div class="fill" style="width:{s * 100:.1f}%"></div>'
            f'<div class="tick" style="left:{t_unknown * 100:.1f}%" title="T_UNKNOWN {t_unknown}"></div>'
            f'<div class="tick" style="left:{t_known * 100:.1f}%" title="T_KNOWN {t_known}"></div></div></div>')
    rows.append(f'<p class="legend">Black marks: {t_unknown:.2f} = partial match, {t_known:.2f} = counted automatically.</p>')
    return "".join(rows)


STEPS = [("Enhance", "colour + contrast"), ("Detect", "find moving organisms"), ("Track", "one ID per fish"),
         ("Identify", "compare with registry"), ("Count", "MeanCount, MaxN")]


def stepper(active: Iterable[int] = (), done: Iterable[int] = ()) -> str:
    """Pipeline progress steps. Enhance/Detect/Track run together frame by frame, so they light up together."""
    active, done = set(active), set(done)
    li = []
    for i, (name, sub) in enumerate(STEPS):
        cls = "done" if i in done else ("active" if i in active else "")
        state = "finished" if i in done else ("in progress" if i in active else "waiting")
        n = "✓" if i in done else str(i + 1)
        li.append(f'<li class="{cls}" aria-label="{name}: {state}"><span class="n" aria-hidden="true">{n}</span>'
                  f'<span>{name}<span class="s">{sub}</span></span></li>')
    return '<ol class="bs-steps">' + "".join(li) + "</ol>"


def empty_state(title: str, body: str, hint: str | None = None) -> None:
    """What this is + why it's empty + how to start."""
    h = f'<p class="bs-small">{hint}</p>' if hint else ""
    st.html(f'<div class="bs-empty"><h4>{esc(title)}</h4><p>{body}</p>{h}</div>')


def kbd(k: str) -> str:
    return f'<span class="bs-kbd">{esc(k)}</span>'
