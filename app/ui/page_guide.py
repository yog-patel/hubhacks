"""Help: the four steps and the few words on screen, for field staff."""
from __future__ import annotations

import streamlit as st

from . import common as C
from . import theme as T


def page() -> None:
    T.header("", "How BlueSight works", "Four steps per video. Everything stays on this computer.")
    st.html("""
<div class="bs-flow">
  <div><span class="n">1</span><b>Analyze</b><span>Pick the video, press Analyze. The computer does the watching.</span></div>
  <div><span class="n">2</span><b>Check counts</b><span>One frame per minute. Remove wrong boxes, add missed fish.</span></div>
  <div><span class="n">3</span><b>New animals</b><span>Name anything BlueSight doesn't know. It learns straight away.</span></div>
  <div><span class="n">4</span><b>Report</b><span>Add the water temperature and download the Excel file.</span></div>
</div>""")
    c1, c2 = st.columns(2)
    c1.page_link(C.PAGES["analyze"], label="Start: Analyze a video", icon=":material/play_arrow:")
    st.subheader("Words on screen", anchor=False)
    st.html("""
<dl class="bs-meta" style="grid-template-columns: 220px 1fr; row-gap: 10px; border-top:none; padding-top:0 !important">
  <dt>Check point</dt><dd>One frame each minute: 15 per video, as in the protocol.</dd>
  <dt>Fish per check point</dt><dd>The average over the 15 check points (the protocol's MeanCount).</dd>
  <dt>Most at once</dt><dd>The most fish in a single frame (MaxN).</dd>
  <dt>Water clarity</dt><dd>How easy fish are to see. Not a distance: record the pole reading yourself.</dd>
  <dt>Too murky to name</dt><dd>Seen, but too unclear to name. Never called a new species.</dd>
  <dt>Second AI count</dt><dd>A second, independent count. Where the two disagree, check first (⚑).</dd>
  <dt>Watch list</dt><dd>Invasive or unexpected species that trigger a red alert.</dd>
  <dt>Count without hints</dt><dd>The protocol's quality check: you count without seeing the AI's boxes.</dd>
</dl>""")
    st.caption("More help: QUICKSTART.md in the BlueSight folder.")
