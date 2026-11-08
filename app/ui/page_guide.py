"""How it works: a plain-language guide for field staff (no AI or computer background needed)."""
from __future__ import annotations

import streamlit as st

from . import common as C
from . import theme as T


def page() -> None:
    T.header("Start here", "How BlueSight works",
             "BlueSight watches your underwater survey video, finds and counts the fish the same way your protocol does, "
             "and asks you whenever it isn't sure. It runs entirely on this computer: no internet, no cloud.")
    st.html("""
<div class="bs-cards">
  <div class="bs-card info"><div class="k"><span class="pip"></span>Step 1 · Analyze</div><div class="v">Pick a video</div>
    <div class="d">Choose the survey video and press <b>Analyze video</b>. BlueSight skips the first minute (sediment
    settling) and analyses 15 minutes, one sample every 60 seconds, exactly like the protocol.</div></div>
  <div class="bs-card info"><div class="k"><span class="pip"></span>Step 2 · Check</div><div class="v">Fix the count</div>
    <div class="d">On <b>Count check</b>, look at each of the 15 sample frames. The AI has boxed the fish it found:
    remove wrong boxes, add the fish it missed. A few clicks per frame instead of a full manual count.</div></div>
  <div class="bs-card info"><div class="k"><span class="pip"></span>Step 3 · Review</div><div class="v">Name what's new</div>
    <div class="d">On <b>Review queue</b>, decide what the unfamiliar animals are: a known species, a new one, or not a
    fish. Nothing is added to the species list without you.</div></div>
  <div class="bs-card ok"><div class="k"><span class="pip"></span>Step 4 · Report</div><div class="v">Download Excel</div>
    <div class="d">On <b>Results</b>, add the water temperature and pole visibility, then download the Excel report in
    your spreadsheet layout. Watch-list species (like European green crab) raise a red alert.</div></div>
</div>""")
    st.subheader("Words you'll see", anchor=False)
    st.html("""
<dl class="bs-meta" style="grid-template-columns: 200px 1fr; row-gap: 10px">
  <dt>MeanCount</dt><dd>The average number of fish across the 15 sample frames. This is the protocol's main abundance
  number.</dd>
  <dt>MaxN</dt><dd>The most fish seen in any single frame.</dd>
  <dt>Subsample</dt><dd>One of the 15 frames, one every 60 seconds. A fish counts if it's visible within half a second
  of that moment.</dd>
  <dt>Image clarity (0–1)</dt><dd>How easy it is to spot fish in the picture. Below the threshold, fish are counted as
  "Unknown/Unable to ID due to visibility" and are never called a new species. It is not a distance; the pole reading is
  still yours to record.</dd>
  <dt>Unfamiliar</dt><dd>An animal that doesn't look like anything in the species registry. It goes to your review queue.
  </dd>
  <dt>Watch list</dt><dd>Invasive or unexpected species you want to hear about immediately. Edit it under Species
  registry.</dd>
  <dt>Blind count</dt><dd>Quality control from the protocol: you count a frame without seeing the AI's boxes, then
  BlueSight compares. The protocol's target is 95% agreement.</dd>
</dl>""")
    st.subheader("Good to know", anchor=False)
    st.markdown(
        "- **Your video never leaves this computer.** The AI models were downloaded once during setup; after that "
        "BlueSight works with Wi-Fi off. The *Model & privacy* page proves it after every run.\n"
        "- **The AI is an assistant, not the final word.** It finds about half the fish on its own in murky water, "
        "which is why the count check exists. Your corrections make the next version better.\n"
        "- **Re-running is quick.** Detections are saved, so after you approve a species, re-analysing the same video "
        "takes seconds.\n"
        "- **Several videos at once:** on *Analyze*, open *Analyze several videos* and pick them all.")
    c1, c2 = st.columns(2)
    c1.page_link(C.PAGES["analyze"], label="Go to Analyze", icon=":material/play_arrow:")
    c2.page_link(C.PAGES["check"], label="Go to Count check", icon=":material/fact_check:")
