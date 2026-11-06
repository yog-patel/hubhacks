# DEMO: BlueSight AI (about 6 minutes)

**Video:** `T1-STAT2 411.MP4` (T1-STAT2, 10 Sept 2025, 35:47, 4K)
**Demo window:** **21:20 → 22:35** (start **1280 s**, duration **75 s**), in the demo half of the video, which was never used for tuning.
**What's in it:** a school of small fish, plus a large **European green crab** (a held-out species, NOT in the registry) walking along the measuring pole from about **21:31 to 21:45**. The biologists' own count at 22:00 is 102 fish + 1 green crab.

## Before the demo (once, about 1 minute)

```bash
cd ~/Documents/hubhacks
.venv/bin/python scripts/reset_demo.py     # clears earlier approvals/reviews, re-runs the demo window (warm cache)
.venv/bin/streamlit run app/streamlit_app.py
```

* Open http://localhost:8501. Type a name in **Reviewer name** in the sidebar, e.g. "Demo Biologist".
* To prove "offline": turn Wi-Fi off now. Everything below works without a network.
* Expected starting state: Species registry = only *small schooling fish*. Review queue item #1 = the green crab (`…_1280-1355s_t630`).

## 1. Murky clip: enhancement and visibility (Analyze page)

1. Sidebar **Page → Analyze**. Video: `T1-STAT2 411.MP4`.
2. Set **Preview time** to **420** (7:00), a very hazy stretch. The original and enhanced images appear side by side. **Visibility ≈ 0.27, below V_MIN = 0.40.** The message says fish here are *not* identified and *never* flagged as new.
3. Move the slider to **1297** (21:37): the crab is next to the pole. Visibility ≈ 0.57, OK to identify.
   *Say:* in murky water the risk is mislabelling haze as a known fish (EVALUATION.md §4), so murky tracks go to the protocol's "Unknown/Unable to ID due to visibility" column.

## 2. Counts per species with confidence

1. Still on Analyze: **Analysis window → Custom**, Start **1280**, Duration **75** → **▶ Analyze**. It finishes in seconds because the cache is warm. A first-ever run of this window takes about 2–3 min on the M5.
2. The result shows **"Ran on this device: Apple M5 … device=mps. Offline: yes."**
3. Point at the **Counts per species** table: *small_schooling_fish* (confidence ≈ 0.87), "Unconfirmed: probably …?", "Unfamiliar (flagged for review)", and the protocol's "Unknown/Unable to ID due to visibility" column. Columns: **MaxN**, **MeanCount** (protocol 60-s subsamples), MeanCount over all sampled frames, and tracks.
4. Point at **Footage too murky** (≈ 0 % in this window) and the visibility chart, then the **annotated video** (green = known, yellow = uncertain, red = unfamiliar) and the **⬇ report.csv** button (protocol spreadsheet format).

## 3. A held-out species is flagged as unfamiliar instead of mislabelled

1. **Page → Review queue** ("Show items from" = the 1280-1355 s analysis).
2. Item #1: **🔴 Unfamiliar: possibly a species not in the registry**, `…_t630`, 21:32–21:41. Play the **clip**: the crab is boxed in orange. The crops show the crab. **Top-3:** small schooling fish **0.47**, far below T_UNKNOWN = 0.68.
   *Say:* the only registry species is the schooling fish. The crab was deliberately held out, and BlueSight says "I don't know this" instead of calling it a fish.

## 4. Approve it, and see it in the registry

1. On item #1, type **European green crab** in "New species name" → click **➕ New species**.
2. **Page → Species registry**: **European green crab**, source *approved*, **approved by Demo Biologist**, today's date, 5 reference images (the crab crops). No retraining: the prototype was rebuilt instantly.

## 5. Re-run: the new species is recognised

1. **Page → Analyze** → same Custom window (1280 / 75) → **▶ Analyze** (about 30 s).
2. The Counts table now has a **european_green_crab** row. In the protocol subsamples it appears in the **invertebrate_count** column, not in total fish.
3. The **second crab track** (21:43–21:48), which nobody reviewed, is now recognised automatically as European green crab (similarity 0.83). It was "unfamiliar" before.
   *Be upfront:* after approval from a single track, the crab prototype also matches some sand patches (EVALUATION.md §5b: 2 of 10 matches are the crab). The fix is the review loop: confirm more crab examples with **Existing species** and **Reject** sand items. Rejected items become negative examples, and similar items are auto-rejected on the next run.

## 6. Runtime and offline

* Results page → **Run details**: `ran_on`, `runtime_s`, `timings_s`, models (motion detector + BioCLIP), thresholds.
* Full cost of first-time processing: about **62–69 s of compute per minute of 4K video** on the Apple M5 (EVALUATION.md §1). Cached re-runs take seconds.
* Sidebar: **Offline models: ✅ yes**, *No cloud or hosted AI APIs are used.* Wi-Fi has been off the whole time.

## Optional: rejecting junk

In the Review queue, pick an item that shows only the pole or sand → **✖ Reject / not a fish** → re-run. That item is excluded from counts, and similar flagged items are auto-rejected (`auto_rejected_tracks` in Run details).

## After the demo

`.venv/bin/python scripts/reset_demo.py` restores the starting state (removes approved species and review decisions).

## If something goes wrong

* The queue doesn't start with the crab → set "Show items from" to `T1_STAT2_411__1280-1355s`, or run `scripts/reset_demo.py` again.
* The app looks stale → refresh the browser. Logs are in `outputs/logs/bluesight.log`.
* No video plays → the clips are H.264 (hardware-encoded) and play in Chrome/Safari.
