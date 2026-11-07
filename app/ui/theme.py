"""BlueSight design system: tokens, global CSS and small HTML components.

Light and dark mode
    Streamlit draws its own widgets from `.streamlit/config.toml` ([theme.light] / [theme.dark]) and sets
    `color-scheme` on the app root. Every BlueSight token below is written with CSS `light-dark()`, so custom
    components switch together with Streamlit's widgets, with no JavaScript and no rerun.

Tokens (text colours >= 4.5:1 on every surface they sit on, in both modes; see DECISIONS.md D24)
    ink / ink-2 / muted       body text, secondary text, captions
    primary / primary-ink     accent for controls / accent used as text
    bg / card / tint          page, raised surface, sunken surface
    status (always icon + text, never colour alone):
      known (green) · uncertain (amber) · unfamiliar (red) · low visibility (grey)
    type     Headings h1/h2 use a book serif (Iowan Old Style / New York / Georgia: system fonts, nothing is
             downloaded). Everything else uses the system sans. 13 · 14 · 16 · 18 · 22 · 30 · 38 px.
    space    4 · 8 · 12 · 16 · 24 · 32 · 48 px
    radius   8 px controls · 14 px cards
"""
from __future__ import annotations

import html
from typing import Iterable

import streamlit as st

STATUS = {
    # key: (label, icon, tone, plain-language explanation)
    "known": ("Known species", "✓", "ok", "Matches a species in the registry; counted automatically."),
    "uncertain": ("Uncertain", "?", "warn", "Looks like a registry species, but not closely enough to count without you."),
    "unfamiliar": ("Unfamiliar", "!", "bad", "Does not match any species in the registry. Possibly new to the registry."),
    "unidentified_low_visibility": ("Low visibility", "◐", "muted",
                                    "Too murky, too small or too brief to identify. Never flagged as a new species."),
    "rejected": ("Rejected", "✕", "muted", "A reviewer marked this as not a fish."),
}

CSS = """
<style>
:root{
  /* light value, dark value */
  --ink:        light-dark(#0D1B24, #E3EBEF);
  --ink-2:      light-dark(#3B4D59, #B4C3CC);
  --muted:      light-dark(#586A76, #93A5B1);
  --primary:    light-dark(#0A6680, #1F7C96);
  --primary-ink:light-dark(#0A6680, #5BB8D3);
  --primary-tint:light-dark(#E2EEF3, #12303B);
  --bg:         light-dark(#F5F7F8, #0B141A);
  --card:       light-dark(#FFFFFF, #111D25);
  --tint:       light-dark(#EDF2F5, #17242E);
  --border:     light-dark(#D5DEE3, #25343F);
  --border-strong: light-dark(#92A4AF, #4A5F6D);
  --shadow:     light-dark(0 1px 2px rgba(13,27,36,.05), 0 0 0 transparent);

  --ok-fg:   light-dark(#1B6B45, #7AD6A2);  --ok-bg:   light-dark(#E6F4EC, #13281E);  --ok-bd:   light-dark(#A8D4BA, #24503A);
  --warn-fg: light-dark(#8A5300, #F2BF6C);  --warn-bg: light-dark(#FFF3DC, #2B2313);  --warn-bd: light-dark(#E8C88A, #574420);
  --bad-fg:  light-dark(#B42318, #FF9385);  --bad-bg:  light-dark(#FDECEA, #321B19);  --bad-bd:  light-dark(#ECAAA2, #613129);
  --mute-fg: light-dark(#4F5B66, #B1BCC4);  --mute-bg: light-dark(#EDF0F2, #1C262D);  --mute-bd: light-dark(#C5CDD3, #34424C);
  --info-fg: light-dark(#0A6680, #6CC4DD);  --info-bg: light-dark(#E2EEF3, #12303B);  --info-bd: light-dark(#A9CAD7, #22505F);

  --s1:4px; --s2:8px; --s3:12px; --s4:16px; --s5:24px; --s6:32px; --s7:48px;
  --r-ctl:8px; --r-card:14px;
  --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  --serif: "Iowan Old Style", "New York", ui-serif, "Palatino Linotype", Palatino, Georgia, serif;
  --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
html, body, [data-testid="stApp"]{ font-family:var(--sans); }
[data-testid="stMainBlockContainer"]{ max-width:1240px; padding-top:var(--s6); padding-bottom:var(--s7); }
[data-testid="stHeader"]{ background:transparent; }

/* ---------- type ---------- */
h1{ font-family:var(--serif) !important; font-size:38px !important; line-height:1.15 !important; font-weight:600 !important;
    letter-spacing:-0.015em; padding:0 !important; }
h2{ font-family:var(--serif) !important; font-size:30px !important; line-height:1.2 !important; font-weight:600 !important; }
h3{ font-size:20px !important; line-height:1.3 !important; font-weight:650 !important; letter-spacing:-0.005em; }
h4{ font-size:17px !important; line-height:1.35 !important; font-weight:650 !important; }
p, li, label, [data-testid="stMarkdownContainer"]{ font-size:16px; line-height:1.55; }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p, .bs-small{
  font-size:14px !important; color:var(--muted) !important; opacity:1 !important; line-height:1.5; }
[data-testid="stWidgetLabel"] p{ font-size:14px !important; font-weight:600; color:var(--ink-2) !important; }
code{ font-family:var(--mono); }

/* ---------- surfaces ---------- */
[data-testid="stVerticalBlockBorderWrapper"]{ border-radius:var(--r-card) !important; background:var(--card);
  box-shadow:var(--shadow); }
[data-testid="stExpander"] details{ border-radius:var(--r-ctl) !important; }
hr{ border-color:var(--border) !important; }

/* section heading inside a card: small title + optional hint on one line */
.bs-sec{ display:flex; align-items:baseline; gap:12px; flex-wrap:wrap; margin:0 0 var(--s3); }
.bs-sec .num{ font:600 13px/1 var(--mono); color:var(--primary-ink); border:1px solid var(--info-bd); background:var(--info-bg);
  border-radius:6px; padding:4px 7px; }
.bs-sec h3{ margin:0 !important; padding:0 !important; }
.bs-sec .hint{ font-size:14px; color:var(--muted); }

/* ---------- images ---------- */
.st-key-crops [data-testid="stImage"] img{ height:118px; width:100%; object-fit:contain; background:var(--tint);
  border-radius:10px; border:1px solid var(--border); }
[class*="st-key-upnext"] [data-testid="stImage"] img{ height:120px; width:100%; object-fit:cover; border-radius:10px; }
[class*="st-key-spcard"] [data-testid="stImage"]:first-of-type img{ border-radius:10px; aspect-ratio:4/3; object-fit:cover; }

/* ---------- focus + targets (WCAG 2.4.7, 2.5.5) ---------- */
button:focus-visible, a:focus-visible, input:focus-visible, [role="radio"]:focus-visible, [tabindex]:focus-visible{
  outline:3px solid var(--primary-ink) !important; outline-offset:2px !important; }
.stButton button, .stDownloadButton button, [data-testid="stFormSubmitButton"] button{
  min-height:44px; font-weight:600; border-radius:var(--r-ctl); }
.st-key-decide .stButton button{ min-height:52px; font-size:16px; }
.st-key-run_btn button{ min-height:52px; padding:0 28px; font-size:16px; }
button kbd[aria-label^="Shortcut"]{ opacity:1 !important; font-weight:700; border:1px solid currentColor; border-radius:4px;
  padding:0 5px; margin-left:8px; font-size:12px; line-height:1.5; background:transparent; }

/* ---------- sidebar ---------- */
[data-testid="stSidebarNav"] a span{ font-size:15px; opacity:1 !important; color:var(--ink) !important; }
[data-testid="stSidebarNav"] a, [data-testid="stSidebarNavSeparator"], [data-testid="stNavSectionHeader"]{ opacity:1 !important; }
[data-testid="stNavSectionHeader"], [data-testid="stNavSectionHeader"] *{ color:var(--muted) !important; opacity:1 !important;
  font-size:12px !important; font-weight:700 !important; letter-spacing:.08em; text-transform:uppercase; }
.bs-side-foot{ font-size:13px; color:var(--muted); line-height:1.5; margin-top:var(--s2); }
.bs-side-foot b{ color:var(--ink-2); font-weight:600; }

/* ---------- page header ---------- */
.bs-eyebrow{ display:flex; align-items:center; gap:10px; font-size:13px; font-weight:600; color:var(--muted); margin:0 0 var(--s2); }
.bs-eyebrow .dots{ display:inline-flex; gap:4px; }
.bs-eyebrow .dots i{ width:18px; height:4px; border-radius:2px; background:var(--border); display:block; }
.bs-eyebrow .dots i.on{ background:var(--primary-ink); }
.bs-lede{ font-size:17px; line-height:1.6; color:var(--ink-2); margin:var(--s2) 0 var(--s5); max-width:68ch; }

/* ---------- badges / pills ---------- */
.bs-badge{ display:inline-flex; align-items:center; gap:6px; padding:2px 10px; border-radius:999px; font-size:13.5px;
  font-weight:600; line-height:1.5; border:1px solid; white-space:nowrap; vertical-align:middle; }
.bs-badge .ico{ font-weight:800; }
.t-ok{ color:var(--ok-fg); background:var(--ok-bg); border-color:var(--ok-bd); }
.t-warn{ color:var(--warn-fg); background:var(--warn-bg); border-color:var(--warn-bd); }
.t-bad{ color:var(--bad-fg); background:var(--bad-bg); border-color:var(--bad-bd); }
.t-muted{ color:var(--mute-fg); background:var(--mute-bg); border-color:var(--mute-bd); }
.t-info{ color:var(--info-fg); background:var(--info-bg); border-color:var(--info-bd); }

/* running-locally indicator */
.bs-local{ display:inline-flex; align-items:center; gap:10px; padding:7px 12px; border-radius:999px;
  font-size:13.5px; line-height:1.35; border:1px solid var(--ok-bd); background:var(--ok-bg); color:var(--ok-fg); }
.bs-local b{ font-weight:650; }
.bs-local .dot{ width:8px; height:8px; border-radius:50%; background:currentColor; flex:none;
  box-shadow:0 0 0 3px light-dark(rgba(27,107,69,.15), rgba(122,214,162,.18)); }
.bs-local.block{ display:flex; border-radius:var(--r-ctl); }
.bs-local.warn{ border-color:var(--warn-bd); background:var(--warn-bg); color:var(--warn-fg); }

/* ---------- metric cards ---------- */
.bs-cards{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:var(--s3); margin:var(--s2) 0 var(--s5); }
.bs-card{ background:var(--card); border:1px solid var(--border); border-radius:var(--r-card); padding:var(--s4) var(--s5);
  box-shadow:var(--shadow); }
.bs-card .k{ display:flex; align-items:center; gap:8px; font-size:13.5px; color:var(--ink-2); font-weight:600; margin-bottom:6px; }
.bs-card .k .pip{ width:8px; height:8px; border-radius:50%; background:var(--border-strong); flex:none; }
.bs-card.ok .pip{ background:var(--ok-fg); } .bs-card.attn .pip{ background:var(--warn-fg); } .bs-card.info .pip{ background:var(--primary-ink); }
.bs-card .v{ font-size:34px; font-weight:650; color:var(--ink); line-height:1.1; font-variant-numeric:tabular-nums; letter-spacing:-0.01em; }
.bs-card .v small{ font-size:16px; font-weight:600; color:var(--ink-2); margin-left:3px; }
.bs-card .d{ font-size:13.5px; color:var(--muted); margin-top:6px; line-height:1.45; }

/* big readout (visibility score) */
.bs-readout .lbl{ font-size:13.5px; color:var(--muted); margin:0; }
.bs-readout .num{ font-size:52px; font-weight:650; line-height:1.05; font-variant-numeric:tabular-nums; color:var(--ink); letter-spacing:-0.02em; }
.bs-readout .num span{ font-size:17px; color:var(--ink-2); font-weight:600; letter-spacing:0; }
.bs-meter{ position:relative; height:8px; border-radius:4px; background:var(--tint); border:1px solid var(--border); margin:12px 0 14px; }
.bs-meter .fill{ position:absolute; inset:0 auto 0 0; border-radius:4px; }
.bs-meter .mark{ position:absolute; top:-5px; bottom:-5px; width:2px; background:var(--ink); }

/* ---------- similarity bars ---------- */
.bs-sim{ margin:0 0 var(--s4); }
.bs-sim .row{ display:flex; justify-content:space-between; font-size:15px; margin-bottom:6px; gap:8px; color:var(--ink); }
.bs-sim .row b{ font-variant-numeric:tabular-nums; }
.bs-sim .row .vd{ color:var(--muted); font-size:14px; }
.bs-sim .track{ position:relative; height:8px; background:var(--tint); border-radius:4px; border:1px solid var(--border); }
.bs-sim .fill{ position:absolute; left:0; top:0; bottom:0; border-radius:4px; background:var(--primary-ink); }
.bs-sim .tick{ position:absolute; top:-5px; bottom:-5px; width:2px; background:var(--ink); }
.bs-sim-legend{ font-size:13px; color:var(--muted); margin:2px 0 0; }

/* ---------- pipeline stepper ---------- */
.bs-steps{ display:grid; grid-template-columns:repeat(5,1fr); margin:var(--s3) 0 var(--s4) !important; padding:0 !important; list-style:none; }
.bs-steps li{ margin:0 !important; position:relative; display:flex; flex-direction:column; align-items:flex-start; gap:8px;
  padding-right:12px; font-size:14.5px; color:var(--muted); }
.bs-steps li::after{ content:""; position:absolute; top:13px; left:34px; right:6px; height:2px; background:var(--border); border-radius:1px; }
.bs-steps li:last-child::after{ display:none; }
.bs-steps li.done::after{ background:var(--ok-fg); }
.bs-steps .n{ width:28px; height:28px; border-radius:50%; display:inline-flex; align-items:center; justify-content:center;
  font-size:13px; font-weight:700; border:2px solid var(--border-strong); color:var(--ink-2); background:var(--card); flex:none; z-index:1; }
.bs-steps .t{ font-weight:600; color:var(--ink-2); line-height:1.3; }
.bs-steps .s{ display:block; font-size:13px; font-weight:400; color:var(--muted); }
.bs-steps li.active .n{ border-color:var(--primary-ink); color:var(--primary-ink); box-shadow:0 0 0 4px var(--primary-tint); }
.bs-steps li.active .t{ color:var(--ink); }
.bs-steps li.done .n{ background:var(--ok-fg); border-color:var(--ok-fg); color:var(--card); }
@media (max-width:720px){ .bs-steps{ grid-template-columns:1fr; gap:10px; } .bs-steps li::after{ display:none; }
  .bs-steps li{ flex-direction:row; align-items:center; } }

/* ---------- empty state ---------- */
.bs-empty{ padding:var(--s6); border:1px dashed var(--border-strong); border-radius:var(--r-card); background:var(--card); }
.bs-empty h4{ margin:0 0 var(--s2); color:var(--ink); } .bs-empty p{ margin:0 0 var(--s2); color:var(--ink-2); }

/* ---------- facts row ---------- */
.bs-facts{ display:flex; flex-wrap:wrap; gap:0; font-size:14.5px; color:var(--muted); margin:var(--s2) 0 var(--s3); }
.bs-facts > span{ padding:0 14px; border-left:1px solid var(--border); }
.bs-facts > span:first-child{ padding-left:0; border-left:none; }
.bs-facts b{ color:var(--ink); font-weight:600; font-variant-numeric:tabular-nums; }

/* ---------- species gallery ---------- */
.bs-sp-name{ font-family:var(--serif); font-size:22px; font-weight:600; margin:2px 0 6px; color:var(--ink); line-height:1.2; }
.bs-noimg{ aspect-ratio:4/3; background:var(--tint); border-radius:10px; display:flex; align-items:center; justify-content:center;
  color:var(--muted); font-size:14px; border:1px dashed var(--border-strong); }
.bs-meta{ margin:var(--s3) 0 var(--s2) !important; padding:var(--s3) 0 0 !important; display:grid; grid-template-columns:max-content 1fr;
  gap:4px 14px; font-size:14px; border-top:1px solid var(--border); }
.bs-meta dt{ color:var(--muted); } .bs-meta dd{ margin:0; color:var(--ink); overflow-wrap:anywhere; }

/* ---------- review ---------- */
.bs-progress{ display:flex; align-items:center; gap:var(--s3); font-size:14.5px; color:var(--ink-2); }
.bs-progress b{ color:var(--ink); white-space:nowrap; }
.bs-progress .bar{ flex:1; height:8px; border-radius:4px; background:var(--tint); border:1px solid var(--border); overflow:hidden; }
.bs-progress .bar span{ display:block; height:100%; background:var(--ok-fg); }
.bs-item-head{ display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
.bs-item-title{ font-family:var(--serif); font-size:28px; font-weight:600; line-height:1.2; margin:10px 0 0; color:var(--ink); }
.bs-when{ text-align:right; font-size:13.5px; color:var(--muted); margin:0; line-height:1.4; }
.bs-when b{ display:block; font-size:20px; color:var(--ink); font-variant-numeric:tabular-nums; }
.bs-choice{ font-size:13px; font-weight:700; letter-spacing:.06em; text-transform:uppercase; color:var(--muted); margin:0 0 8px; }
.bs-kbd{ display:inline-block; min-width:20px; padding:0 6px; border:1px solid var(--border-strong); border-bottom-width:2px;
  border-radius:5px; font:600 12px/1.6 var(--mono); color:var(--ink); background:var(--card); text-align:center; }
.bs-next-meta{ font-size:13.5px; color:var(--muted); margin:6px 0 0; line-height:1.45; }
.bs-next-meta b{ color:var(--ink); font-size:15px; font-variant-numeric:tabular-nums; }

/* privacy verdict */
.bs-verdict{ display:flex; gap:16px; align-items:center; padding:18px 22px; border-radius:var(--r-card); border:1px solid; margin-bottom:8px; }
.bs-verdict .ico{ font-size:24px; font-weight:800; width:46px; height:46px; border-radius:50%; display:flex; align-items:center;
  justify-content:center; background:currentColor; flex:none; }
.bs-verdict .ico span{ color:var(--card); }
.bs-verdict .big{ font-family:var(--serif); font-size:24px; font-weight:600; display:block; line-height:1.25; }
.bs-verdict .sub{ font-size:14px; color:var(--ink-2); }
ol.bs-how{ margin:0; padding-left:22px; line-height:1.7; color:var(--ink-2); } ol.bs-how li{ margin-bottom:4px; }

table.bs-table{ border-collapse:collapse; width:100%; font-size:14.5px; color:var(--ink); }
table.bs-table th{ text-align:left; color:var(--muted); font-weight:600; font-size:13px; text-transform:uppercase; letter-spacing:.05em;
  border-bottom:1px solid var(--border-strong); padding:8px 10px; }
table.bs-table td{ border-bottom:1px solid var(--border); padding:10px; vertical-align:top; }
table.bs-table code{ font-size:12.5px; word-break:break-all; }
</style>
"""


def inject() -> None:
    """Add the global stylesheet (call once per page run)."""
    st.html(CSS)


def is_dark() -> bool:
    """Best guess of the reader's current theme (for things CSS can't reach: charts and the comparison iframe)."""
    try:
        return st.context.theme.type == "dark"
    except Exception:
        return False


def esc(s: object) -> str:
    return html.escape(str(s))


def header(eyebrow: str, title: str, lede: str | None = None, step: int | None = None) -> None:
    """Page header: eyebrow (with step dots for the 3-step survey flow), serif H1, one-sentence lede."""
    dots = ""
    if step:
        dots = '<span class="dots" aria-hidden="true">' + "".join(
            f'<i class="{"on" if i <= step else ""}"></i>' for i in range(1, 4)) + "</span>"
    st.html(f'<p class="bs-eyebrow">{dots}<span>{esc(eyebrow)}</span></p>')
    st.title(title, anchor=False)
    if lede:
        st.html(f'<p class="bs-lede">{lede}</p>')


def section(title: str, num: str | None = None, hint: str | None = None) -> None:
    """Heading at the top of a card: optional step number, title, short hint."""
    n = f'<span class="num">{esc(num)}</span>' if num else ""
    h = f'<span class="hint">{hint}</span>' if hint else ""
    st.html(f'<div class="bs-sec">{n}<h3>{esc(title)}</h3>{h}</div>')


def badge(status: str, text: str | None = None) -> str:
    """Status badge HTML: icon + text + colour (never colour alone)."""
    label, ico, tone, expl = STATUS.get(status, (status, "•", "info", ""))
    return (f'<span class="bs-badge t-{tone}" title="{esc(expl)}">'
            f'<span class="ico" aria-hidden="true">{ico}</span>{esc(text or label)}</span>')


def plain_badge(text: str, tone: str = "info", icon: str = "") -> str:
    """Neutral pill. tone: info, ok, warn, bad or muted."""
    ico = f'<span class="ico" aria-hidden="true">{icon}</span>' if icon else ""
    return f'<span class="bs-badge t-{tone}">{ico}{esc(text)}</span>'


def visibility_word(v: float, v_min: float) -> tuple[str, str, str]:
    """(word, tone, icon) for a visibility score."""
    if v < v_min:
        return "too murky", "muted", "◐"
    if v < v_min + 0.15:
        return "fair", "warn", "◑"
    return "good", "ok", "●"


def visibility_badge(v: float, v_min: float) -> str:
    """Visibility score with a word label, so it does not rely on colour."""
    word, tone, ico = visibility_word(v, v_min)
    return plain_badge(f"Visibility {v:.2f} · {word}", tone, ico)


def cards(items: Iterable[dict]) -> None:
    """Headline metric cards: dicts with k (label), v (value), optional unit, d (detail), tone (ok/attn/info)."""
    out = []
    for c in items:
        unit = f"<small>{esc(c['unit'])}</small>" if c.get("unit") else ""
        out.append(f'<div class="bs-card {c.get("tone", "")}" role="group" aria-label="{esc(c["k"])}">'
                   f'<div class="k"><span class="pip" aria-hidden="true"></span>{esc(c["k"])}</div>'
                   f'<div class="v">{esc(c["v"])}{unit}</div><div class="d">{c.get("d", "")}</div></div>')
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
            f'<span><b>{s:.2f}</b> <span class="vd">· {verdict}</span></span></div>'
            f'<div class="track" role="img" aria-label="similarity {s:.2f} of 1">'
            f'<div class="fill" style="width:{s * 100:.1f}%"></div>'
            f'<div class="tick" style="left:{t_unknown * 100:.1f}%" title="T_UNKNOWN {t_unknown}"></div>'
            f'<div class="tick" style="left:{t_known * 100:.1f}%" title="T_KNOWN {t_known}"></div></div></div>')
    rows.append(f'<p class="bs-sim-legend">Tick marks: {t_unknown:.2f} partial match · {t_known:.2f} counted automatically.</p>')
    return "".join(rows)


STEPS = [("Enhance", "colour + contrast"), ("Detect", "find moving animals"), ("Track", "one ID per fish"),
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
                  f'<span class="t">{name}<span class="s">{sub}</span></span></li>')
    return '<ol class="bs-steps">' + "".join(li) + "</ol>"


def empty_state(title: str, body: str, hint: str | None = None) -> None:
    """What this is + why it's empty + how to start."""
    h = f'<p class="bs-small">{hint}</p>' if hint else ""
    st.html(f'<div class="bs-empty"><h4>{esc(title)}</h4><p>{body}</p>{h}</div>')


def kbd(k: str) -> str:
    return f'<span class="bs-kbd">{esc(k)}</span>'


def chart_palette() -> dict:
    """Colours for Altair charts, matched to the current light/dark theme."""
    if is_dark():
        return {"count": "#6CB4F0", "vis": "#5BB8D3", "rule": "#FF9385", "sub": "#4A5F6D", "low": "#22313B",
                "grid": "#22313B", "text": "#B4C3CC", "muted": "#93A5B1"}
    return {"count": "#2A78D6", "vis": "#0A6680", "rule": "#B42318", "sub": "#92A4AF", "low": "#DCE3E8",
            "grid": "#E6ECEF", "text": "#3B4D59", "muted": "#586A76"}
