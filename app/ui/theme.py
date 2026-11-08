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
    "known": ("Identified", "✓", "ok", "Matches a species in the library; counted automatically."),
    "uncertain": ("Not sure", "?", "warn", "Looks like a known species, but not closely enough to count without you."),
    "unfamiliar": ("New to BlueSight", "!", "bad", "Doesn't look like anything in the species library."),
    "unidentified_low_visibility": ("Too murky", "◐", "muted",
                                    "Too murky, small or brief to name. Never treated as a new species."),
    "rejected": ("Not an animal", "✕", "muted", "A reviewer marked this as not a fish."),
}

CSS = """
<style>
/* BlueSight visual identity (DECISIONS.md D36)
   Subject: field survey of murky Nova Scotia water. Palette from nautical charts; one legibility-first typeface
   (Atkinson Hyperlegible Next, bundled). Signature: the banded 2 m visibility pole seen in every survey video, used as
   the progress bar for the four steps and the 15 check points. Everything else stays quiet. */
:root{
  --ink:        light-dark(#11293A, #E2EBEE);
  --ink-2:      light-dark(#34495A, #B7C7CE);
  --muted:      light-dark(#566B78, #91A6B2);
  --primary:    light-dark(#2A5D7C, #3B7BA0);
  --primary-ink:light-dark(#2A5D7C, #8CC3DC);
  --primary-tint:light-dark(#DDE9EC, #16313F);
  --bg:         light-dark(#F1F4F0, #0E1C26);
  --card:       light-dark(#F9FBF8, #132430);
  --tint:       light-dark(#E4ECEB, #182B37);
  --border:     light-dark(#C9D5D4, #2A3F4C);
  --border-strong: light-dark(#8FA3A8, #4D6573);
  --pole:       light-dark(#FDFEFD, #DCE5E8);   /* white PVC */
  --tape:       light-dark(#14202A, #0A1218);   /* black electrical tape */

  --ok-fg:   light-dark(#4F5E26, #B5C77A);  --ok-bg:   light-dark(#E9EEDB, #222B16);  --ok-bd:   light-dark(#BCC995, #46542A);
  --warn-fg: light-dark(#A93A0B, #FF9F72);  --warn-bg: light-dark(#FBE8DD, #33200F);  --warn-bd: light-dark(#EBB394, #6A3418);
  --bad-fg:  light-dark(#A11D1D, #FF9090);  --bad-bg:  light-dark(#FBE7E7, #331818);  --bad-bd:  light-dark(#E7A9A9, #642A2A);
  --mute-fg: light-dark(#4D5E68, #B1BEC6);  --mute-bg: light-dark(#E8ECEC, #1B2A33);  --mute-bd: light-dark(#C3CDCF, #34474F);
  --info-fg: light-dark(#2A5D7C, #8CC3DC);  --info-bg: light-dark(#DDE9EC, #16313F);  --info-bd: light-dark(#A5C2CF, #2B5468);

  --s1:4px; --s2:8px; --s3:12px; --s4:16px; --s5:24px; --s6:32px; --s7:48px;
  --r:4px; --r-lg:8px;
  --sans: "Atkinson Hyperlegible Next", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
  --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
html, body, [data-testid="stApp"]{ font-family:var(--sans); }
[data-testid="stMainBlockContainer"]{ max-width:1180px; padding-top:var(--s6); padding-bottom:var(--s7); }
[data-testid="stHeader"]{ background:transparent; }

/* ---------- type: one family, a modular scale 14 / 16 / 19 / 24 / 32 / 44 ---------- */
h1{ font-family:var(--sans) !important; font-size:44px !important; line-height:1.05 !important; font-weight:750 !important;
    letter-spacing:-0.025em; padding:0 !important; }
h2{ font-family:var(--sans) !important; font-size:32px !important; line-height:1.15 !important; font-weight:700 !important;
    letter-spacing:-0.015em; }
h3{ font-size:24px !important; line-height:1.25 !important; font-weight:700 !important; letter-spacing:-0.01em; }
h4{ font-size:19px !important; line-height:1.3 !important; font-weight:700 !important; }
p, li, label, [data-testid="stMarkdownContainer"]{ font-size:16px; line-height:1.55; }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p, .bs-small{
  font-size:14px !important; color:var(--muted) !important; opacity:1 !important; line-height:1.5; }
[data-testid="stWidgetLabel"] p{ font-size:15px !important; font-weight:700; color:var(--ink-2) !important; }
code{ font-family:var(--mono); font-size:.9em; }

/* ---------- surfaces: one quiet panel style, no shadows ---------- */
[data-testid="stVerticalBlockBorderWrapper"]{ border-radius:var(--r-lg) !important; background:var(--card); box-shadow:none; }
[data-testid="stExpander"] details{ border-radius:var(--r) !important; background:transparent; }
hr{ border-color:var(--border) !important; }
.bs-sec{ display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; margin:0 0 var(--s3); }
.bs-sec .num{ font-weight:750; font-size:24px; line-height:1; color:var(--primary-ink); }
.bs-sec h3{ margin:0 !important; padding:0 !important; }
.bs-sec .hint{ font-size:14px; color:var(--muted); }

/* ---------- images ---------- */
.st-key-crops [data-testid="stImage"] img{ height:118px; width:100%; object-fit:contain; background:var(--tint);
  border-radius:var(--r); }
[class*="st-key-upnext"] [data-testid="stImage"] img{ height:120px; width:100%; object-fit:cover; border-radius:var(--r); }
[class*="st-key-spcard"] [data-testid="stImage"]:first-of-type img,
[class*="st-key-fg_"] [data-testid="stImage"] img{ border-radius:var(--r); aspect-ratio:4/3; object-fit:cover; }

/* ---------- focus + targets ---------- */
button:focus-visible, a:focus-visible, input:focus-visible, [role="radio"]:focus-visible, [tabindex]:focus-visible{
  outline:3px solid var(--primary-ink) !important; outline-offset:2px !important; }
.stButton button, .stDownloadButton button, [data-testid="stFormSubmitButton"] button{
  min-height:44px; font-weight:700; border-radius:var(--r); }
.st-key-decide .stButton button{ min-height:52px; font-size:16px; }
.st-key-run_btn button{ min-height:56px; padding:0 32px; font-size:17px; }
button kbd[aria-label^="Shortcut"]{ opacity:.8 !important; font-weight:700; border:1px solid currentColor; border-radius:3px;
  padding:0 5px; margin-left:8px; font-size:12px; line-height:1.5; background:transparent; }
@media (prefers-reduced-motion: reduce){ *{ transition:none !important; animation:none !important; } }

/* ---------- sidebar ---------- */
[data-testid="stSidebarNav"] a span{ font-size:16px; opacity:1 !important; color:var(--ink) !important; }
[data-testid="stSidebarNav"] a, [data-testid="stSidebarNavSeparator"], [data-testid="stNavSectionHeader"]{ opacity:1 !important; }
[data-testid="stNavSectionHeader"], [data-testid="stNavSectionHeader"] *{ color:var(--muted) !important; opacity:1 !important;
  font-size:14px !important; font-weight:700 !important; }

/* ---------- the pole: signature progress element ----------
   White pipe with black tape bands at each boundary, like the 2 m visibility pole in the footage. */
.bs-pole{ display:grid; grid-template-columns:repeat(var(--n),1fr); height:14px; border-radius:7px; overflow:hidden;
  background:var(--pole); box-shadow:inset 0 0 0 1px var(--border-strong); margin:0 0 6px; }
.bs-pole i{ display:block; border-right:4px solid var(--tape); }
.bs-pole i:last-child{ border-right:none; }
.bs-pole i.done{ background:var(--primary); }
.bs-pole i.cur{ background:repeating-linear-gradient(90deg, var(--primary) 0 6px, var(--primary-tint) 6px 12px); }
.bs-pole-labels{ display:grid; grid-template-columns:repeat(var(--n),1fr); font-size:14px; color:var(--muted); margin:0 0 var(--s5); }
.bs-pole-labels span.cur{ color:var(--ink); font-weight:700; }
.bs-lede{ font-size:19px; line-height:1.45; color:var(--ink-2); margin:var(--s2) 0 var(--s5); max-width:56ch; }

/* check-point pole: 15 one-minute segments, numbered */
.bs-strip{ display:grid; grid-template-columns:repeat(var(--n),1fr); height:34px; border-radius:17px; overflow:hidden;
  background:var(--pole); box-shadow:inset 0 0 0 1px var(--border-strong); margin:var(--s2) 0 6px; }
.bs-strip i{ display:flex; align-items:center; justify-content:center; font:700 13px/1 var(--sans); font-style:normal;
  color:var(--muted); border-right:3px solid var(--tape); position:relative; }
.bs-strip i:last-child{ border-right:none; }
.bs-strip i.done{ background:var(--ok-fg); color:var(--pole); }
.bs-strip i.flag::after{ content:""; position:absolute; left:0; right:0; bottom:0; height:5px; background:var(--warn-fg); }
.bs-strip i.cur{ background:var(--primary); color:var(--pole); }
.bs-strip-key{ font-size:14px; color:var(--muted); margin:0 0 var(--s4); }
.bs-strip-key b{ font-weight:700; } .bs-strip-key .o{ color:var(--warn-fg); } .bs-strip-key .g{ color:var(--ok-fg); }

/* ---------- badges ---------- */
.bs-badge{ display:inline-flex; align-items:center; gap:6px; padding:2px 10px; border-radius:var(--r); font-size:14px;
  font-weight:700; line-height:1.5; border:1px solid; white-space:nowrap; vertical-align:middle; }
.bs-badge .ico{ font-weight:800; }
.t-ok{ color:var(--ok-fg); background:var(--ok-bg); border-color:var(--ok-bd); }
.t-warn{ color:var(--warn-fg); background:var(--warn-bg); border-color:var(--warn-bd); }
.t-bad{ color:var(--bad-fg); background:var(--bad-bg); border-color:var(--bad-bd); }
.t-muted{ color:var(--mute-fg); background:var(--mute-bg); border-color:var(--mute-bd); }
.t-info{ color:var(--info-fg); background:var(--info-bg); border-color:var(--info-bd); }
.bs-local{ display:inline-flex; align-items:center; gap:10px; padding:8px 12px; border-radius:var(--r);
  font-size:14px; line-height:1.35; color:var(--ok-fg); background:var(--ok-bg); border:1px solid var(--ok-bd); }
.bs-local b{ font-weight:700; }
.bs-local .dot{ width:8px; height:8px; border-radius:50%; background:currentColor; flex:none; }
.bs-local.block{ display:flex; }
.bs-local.warn{ border-color:var(--warn-bd); background:var(--warn-bg); color:var(--warn-fg); }

/* ---------- numbers ---------- */
.bs-stats{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:var(--s5); margin:var(--s3) 0 var(--s6); }
.bs-stat .n{ font-size:52px; font-weight:750; line-height:.95; color:var(--ink); font-variant-numeric:tabular-nums lining-nums;
  letter-spacing:-0.03em; }
.bs-stat .n small{ font-size:22px; color:var(--ink-2); font-weight:700; margin-left:2px; letter-spacing:0; }
.bs-stat .l{ font-size:15px; color:var(--ink-2); margin-top:8px; max-width:22ch; line-height:1.35; }
.bs-stat.attn .n{ color:var(--warn-fg); } .bs-stat.ok .n{ color:var(--ok-fg); }
.bs-cards{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:var(--s4); margin:var(--s2) 0 var(--s5); }
.bs-card{ padding:var(--s2) 0; }
.bs-card .k{ font-size:15px; color:var(--ink-2); font-weight:700; margin-bottom:4px; } .bs-card .k .pip{ display:none; }
.bs-card .v{ font-size:40px; font-weight:750; color:var(--ink); line-height:1; font-variant-numeric:tabular-nums; letter-spacing:-0.02em; }
.bs-card .v small{ font-size:18px; font-weight:700; color:var(--ink-2); margin-left:3px; }
.bs-card .d{ font-size:14px; color:var(--muted); margin-top:6px; line-height:1.45; }
.bs-readout .lbl{ font-size:15px; color:var(--muted); margin:0; }
.bs-readout .num{ font-size:44px; font-weight:750; line-height:1.05; font-variant-numeric:tabular-nums; color:var(--ink); letter-spacing:-0.025em; }
.bs-readout .num span{ font-size:19px; color:var(--ink-2); font-weight:700; letter-spacing:0; }
.bs-meter{ position:relative; height:10px; border-radius:5px; background:var(--pole); box-shadow:inset 0 0 0 1px var(--border-strong); margin:12px 0 14px; }
.bs-meter .fill{ position:absolute; inset:0 auto 0 0; border-radius:5px; }
.bs-meter .mark{ position:absolute; top:-4px; bottom:-4px; width:4px; background:var(--tape); }

/* ---------- similarity ---------- */
.bs-sim{ margin:0 0 var(--s4); }
.bs-sim .row{ display:flex; justify-content:space-between; font-size:16px; margin-bottom:6px; gap:8px; color:var(--ink); }
.bs-sim .row .vd{ color:var(--muted); font-size:14px; }
.bs-sim .track{ position:relative; height:10px; background:var(--pole); border-radius:5px; box-shadow:inset 0 0 0 1px var(--border-strong); }
.bs-sim .fill{ position:absolute; left:0; top:0; bottom:0; border-radius:5px; background:var(--primary); }
.bs-sim .tick{ position:absolute; top:-4px; bottom:-4px; width:3px; background:var(--tape); }
.bs-sim-legend{ font-size:14px; color:var(--muted); margin:2px 0 0; }

/* ---------- pipeline stepper (while analysing) ---------- */
.bs-steps{ display:grid; grid-template-columns:repeat(5,1fr); margin:var(--s3) 0 var(--s4) !important; padding:0 !important; list-style:none; }
.bs-steps li{ margin:0 !important; display:flex; flex-direction:column; gap:8px; font-size:15px; color:var(--muted); padding-right:8px; }
.bs-steps li::before{ content:""; height:10px; border-radius:5px; background:var(--pole); box-shadow:inset 0 0 0 1px var(--border-strong); }
.bs-steps li.active::before{ background:repeating-linear-gradient(90deg, var(--primary) 0 6px, var(--primary-tint) 6px 12px); }
.bs-steps li.done::before{ background:var(--primary); box-shadow:none; }
.bs-steps .n{ display:none; }
.bs-steps .t{ font-weight:700; color:var(--ink-2); }
.bs-steps li.active .t{ color:var(--ink); }
@media (max-width:720px){ .bs-steps{ grid-template-columns:1fr 1fr; gap:10px; } }

/* ---------- empty state ---------- */
.bs-empty{ padding:var(--s6) 0; }
.bs-empty h4{ margin:0 0 var(--s2); color:var(--ink); font-size:24px !important; } .bs-empty p{ margin:0 0 var(--s2); color:var(--ink-2); }

/* ---------- facts row ---------- */
.bs-facts{ display:flex; flex-wrap:wrap; gap:var(--s5); font-size:15px; color:var(--muted); margin:var(--s2) 0 var(--s3); }
.bs-facts b{ color:var(--ink); font-weight:700; font-variant-numeric:tabular-nums; margin-left:4px; }

/* ---------- species ---------- */
.bs-sp-name{ font-size:21px; font-weight:750; margin:4px 0 6px; color:var(--ink); line-height:1.2; letter-spacing:-0.01em; }
.bs-noimg{ aspect-ratio:4/3; background:var(--tint); border-radius:var(--r); display:flex; align-items:center; justify-content:center;
  color:var(--muted); font-size:14px; }
.bs-meta{ margin:var(--s3) 0 var(--s2) !important; padding:0 !important; display:grid; grid-template-columns:max-content 1fr;
  gap:4px 16px; font-size:15px; }
.bs-meta dt{ color:var(--muted); } .bs-meta dd{ margin:0; color:var(--ink); overflow-wrap:anywhere; }

/* ---------- review ---------- */
.bs-progress{ display:flex; align-items:center; gap:var(--s3); font-size:15px; color:var(--ink-2); }
.bs-progress b{ color:var(--ink); white-space:nowrap; }
.bs-progress .bar{ flex:1; height:10px; border-radius:5px; background:var(--pole); box-shadow:inset 0 0 0 1px var(--border-strong); overflow:hidden; }
.bs-progress .bar span{ display:block; height:100%; background:var(--ok-fg); }
.bs-item-head{ display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
.bs-item-title{ font-size:32px; font-weight:750; line-height:1.15; margin:10px 0 0; color:var(--ink); letter-spacing:-0.02em; }
.bs-when{ text-align:right; font-size:14px; color:var(--muted); margin:0; line-height:1.4; }
.bs-when b{ display:block; font-size:24px; color:var(--ink); font-variant-numeric:tabular-nums; font-weight:750; }
.bs-choice{ font-size:15px; font-weight:700; color:var(--ink-2); margin:0 0 8px; }
.bs-kbd{ display:inline-block; min-width:20px; padding:0 6px; border:1px solid var(--border-strong); border-radius:3px;
  font:700 12px/1.6 var(--sans); color:var(--ink); background:var(--card); text-align:center; }
.bs-next-meta{ font-size:14px; color:var(--muted); margin:6px 0 0; line-height:1.45; }
.bs-next-meta b{ color:var(--ink); font-size:16px; font-variant-numeric:tabular-nums; }

/* ---------- report sentence (numbers inside the sentence they prove) ---------- */
.bs-summary{ font-size:24px; line-height:1.4; color:var(--ink-2); max-width:44ch; margin:var(--s2) 0 var(--s5); letter-spacing:-0.005em; }
.bs-summary b{ color:var(--ink); font-weight:750; font-variant-numeric:tabular-nums; }
.bs-summary b.w{ color:var(--warn-fg); }
/* legend shown above a visual, never as a caption under it */
.bs-key{ display:flex; flex-wrap:wrap; align-items:center; gap:6px 16px; font-size:14px; color:var(--ink-2); margin:0 0 8px; }
.bs-key .sw{ display:inline-block; width:12px; height:12px; border-radius:2px; margin-right:-10px; }
.bs-key .sw.box{ background:transparent; border:2px solid; }
.bs-key .dm{ color:var(--warn-fg); margin-right:-10px; } .bs-key .fl{ color:var(--warn-fg); margin-right:-10px; }
.bs-key .x{ color:var(--muted); font-weight:800; margin-right:-10px; }

/* ---------- micro-interactions: buttons step and press, linked tiles lift, photos zoom inside their frame ---------- */
.stButton button, .stDownloadButton button, [data-testid="stFormSubmitButton"] button, [data-testid="stPageLink"] a{
  transition:transform .14s ease, box-shadow .14s ease, background-color .14s ease; }
.stButton button:hover, .stDownloadButton button:hover, [data-testid="stFormSubmitButton"] button:hover{ transform:translateY(-1px); }
.stButton button:active, .stDownloadButton button:active, [data-testid="stFormSubmitButton"] button:active{ transform:translateY(0) scale(.98); }
[data-testid="stPageLink"] a span{ background:linear-gradient(currentColor,currentColor) 0 100%/0 1.5px no-repeat;
  transition:background-size .2s ease; }
[data-testid="stPageLink"] a:hover span{ background-size:100% 1.5px; }
[class*="st-key-upnext"]{ transition:transform .16s ease; }
[class*="st-key-upnext"]:hover{ transform:translateY(-2px); }
[class*="st-key-upnext"] [data-testid="stImage"], .st-key-crops [data-testid="stImage"],
[class*="st-key-fg_"] [data-testid="stImage"], [class*="st-key-spcard"] [data-testid="stImage"]{ overflow:hidden; border-radius:var(--r); }
[class*="st-key-upnext"] [data-testid="stImage"] img, .st-key-crops [data-testid="stImage"] img,
[class*="st-key-fg_"] [data-testid="stImage"] img, [class*="st-key-spcard"] [data-testid="stImage"] img{ transition:transform .3s ease; }
[class*="st-key-upnext"]:hover [data-testid="stImage"] img, .st-key-crops [data-testid="stImage"]:hover img,
[class*="st-key-fg_"]:hover [data-testid="stImage"] img, [class*="st-key-spcard"]:hover [data-testid="stImage"] img{ transform:scale(1.03); }
/* one entrance on load: the main panel of the first screen */
@keyframes bs-enter{ from{ opacity:0; transform:translateY(8px); } to{ opacity:1; transform:none; } }
.st-key-hero, .st-key-check_card, .st-key-review_card{ animation:bs-enter .45s ease-out both; }
@media (prefers-reduced-motion: reduce){ .st-key-hero, .st-key-check_card, .st-key-review_card{ animation:none; }
  .stButton button:hover, [class*="st-key-upnext"]:hover{ transform:none; } }

/* ---------- privacy checklist ---------- */
.bs-checks{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:var(--s5) var(--s6); margin:var(--s4) 0 var(--s6); }
.bs-check{ display:flex; gap:14px; align-items:flex-start; }
.bs-check .ico{ width:30px; height:30px; border-radius:50%; background:var(--ok-fg); color:var(--pole);
  display:flex; align-items:center; justify-content:center; font-weight:800; flex:none; margin-top:2px; }
.bs-check b{ display:block; font-size:19px; color:var(--ink); font-weight:750; line-height:1.25; }
.bs-check span{ font-size:15px; color:var(--muted); }

/* ---------- help: the four steps on one pole ---------- */
.bs-flow{ display:grid; grid-template-columns:repeat(4,1fr); gap:var(--s4); margin:var(--s3) 0 var(--s6); }
.bs-flow > div::before{ content:""; display:block; height:14px; border-radius:7px; background:var(--primary);
  margin-bottom:var(--s3); box-shadow:inset -4px 0 0 var(--tape); }
.bs-flow .n{ font-weight:750; font-size:15px; color:var(--primary-ink); }
.bs-flow b{ display:block; font-size:24px; margin:2px 0 6px; color:var(--ink); font-weight:750; letter-spacing:-0.01em; }
.bs-flow span{ font-size:16px; color:var(--ink-2); line-height:1.45; }
@media (max-width:720px){ .bs-flow{ grid-template-columns:1fr 1fr; } }

.bs-verdict{ display:flex; gap:16px; align-items:center; padding:18px 0; margin-bottom:8px; }
ol.bs-how{ margin:0; padding-left:22px; line-height:1.7; color:var(--ink-2); } ol.bs-how li{ margin-bottom:4px; }
table.bs-table{ border-collapse:collapse; width:100%; font-size:15px; color:var(--ink); }
table.bs-table th{ text-align:left; color:var(--muted); font-weight:700; font-size:14px; border-bottom:1px solid var(--border-strong); padding:8px 10px; }
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
    """Page header: a small step marker (survey pages only), the title and at most one short line."""
    if step:
        names = ["Analyze", "Check counts", "New animals", "Report"]
        seg = "".join(f'<i class="{"done" if i < step else ("cur" if i == step else "")}"></i>' for i in range(1, 5))
        lab = "".join(f'<span class="{"cur" if i == step else ""}">{n}</span>' for i, n in enumerate(names, start=1))
        st.html(f'<div role="img" aria-label="Step {step} of 4: {names[step - 1]}"><div class="bs-pole" style="--n:4">{seg}</div>'
                f'<div class="bs-pole-labels" style="--n:4">{lab}</div></div>')
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
    """(word, tone, icon) for a water-clarity score."""
    if v < v_min:
        return "Too murky", "muted", "◐"
    if v < v_min + 0.15:
        return "Hazy", "warn", "◑"
    return "Clear", "ok", "●"


def visibility_badge(v: float, v_min: float) -> str:
    """Water clarity as a word (the 0-1 score is in the tooltip), so it does not rely on colour."""
    word, tone, ico = visibility_word(v, v_min)
    return (f'<span class="bs-badge t-{tone}" title="Water clarity {v:.2f} of 1">'
            f'<span class="ico" aria-hidden="true">{ico}</span>{esc(word)} water</span>')


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
        return '<p class="bs-small">The species library is empty.</p>'
    rows = []
    for m in top3:
        s = max(0.0, min(1.0, float(m["similarity"])))
        verdict = "strong match" if s >= t_known else ("weak match" if s >= t_unknown else "no match")
        rows.append(
            f'<div class="bs-sim"><div class="row"><span>{esc(m["species"].replace("_", " ").capitalize())}</span>'
            f'<span class="vd">{verdict}</span></div>'
            f'<div class="track" role="img" aria-label="similarity {s:.2f} of 1">'
            f'<div class="fill" style="width:{s * 100:.1f}%"></div>'
            f'<div class="tick" style="left:{t_unknown * 100:.1f}%" title="T_UNKNOWN {t_unknown}"></div>'
            f'<div class="tick" style="left:{t_known * 100:.1f}%" title="T_KNOWN {t_known}"></div></div></div>')
    rows.append('<p class="bs-sim-legend">Right of the second tick = counted automatically.</p>')
    return "".join(rows)


STEPS = [("Clean image", ""), ("Find fish", ""), ("Follow each fish", ""), ("Name species", ""), ("Count", "")]


def stepper(active: Iterable[int] = (), done: Iterable[int] = ()) -> str:
    """Pipeline progress steps. Enhance/Detect/Track run together frame by frame, so they light up together."""
    active, done = set(active), set(done)
    li = []
    for i, (name, sub) in enumerate(STEPS):
        cls = "done" if i in done else ("active" if i in active else "")
        state = "finished" if i in done else ("in progress" if i in active else "waiting")
        n = "✓" if i in done else str(i + 1)
        li.append(f'<li class="{cls}" aria-label="{name}: {state}"><span class="n" aria-hidden="true">{n}</span>'
                  f'<span class="t">{name}</span></li>')
    return '<ol class="bs-steps">' + "".join(li) + "</ol>"


def empty_state(title: str, body: str, hint: str | None = None) -> None:
    """What this is + why it's empty + how to start."""
    h = f'<p class="bs-small">{hint}</p>' if hint else ""
    st.html(f'<div class="bs-empty"><h4>{esc(title)}</h4><p>{body}</p>{h}</div>')


def stats(items: Iterable[dict]) -> None:
    """A row of big numbers with short labels (k = label, v = value, optional unit and tone ok/attn)."""
    out = []
    for c in items:
        unit = f"<small>{esc(c['unit'])}</small>" if c.get("unit") else ""
        tip = f' title="{esc(c["tip"])}"' if c.get("tip") else ""
        out.append(f'<div class="bs-stat {c.get("tone", "")}"{tip}><div class="n">{esc(c["v"])}{unit}</div>'
                   f'<div class="l">{esc(c["k"])}</div></div>')
    st.html('<div class="bs-stats">' + "".join(out) + "</div>")


def kbd(k: str) -> str:
    return f'<span class="bs-kbd">{esc(k)}</span>'


def chart_palette() -> dict:
    """Colours for Altair charts, matched to the current light/dark theme."""
    if is_dark():
        return {"count": "#8CC3DC", "vis": "#B5C77A", "rule": "#FF9F72", "sub": "#4D6573", "low": "#1B2A33",
                "grid": "#22343F", "text": "#B7C7CE", "muted": "#91A6B2"}
    return {"count": "#2A5D7C", "vis": "#5C6B33", "rule": "#C2410C", "sub": "#A9BDC2", "low": "#E1E8E6",
            "grid": "#DFE6E4", "text": "#34495A", "muted": "#566B78"}
