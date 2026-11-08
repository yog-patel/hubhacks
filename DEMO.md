# DEMO: BlueSight AI (about 6½ minutes)

**Video:** `T1-STAT2 411.MP4` (T1-STAT2, 10 Sept 2025, 35:47, 4K)
**Demo window:** **21:20 → 22:35** (start **1280 s**, length **75 s**), in the demo half of the video, which was never used for tuning.
**What's in it:** a school of small fish, plus a large **European green crab** (a held-out species, NOT in the registry) walking along the measuring pole from about **21:31 to 21:45**. The biologists' own count at 22:00 is 102 fish + 1 green crab.

Every step below was run end to end through the real app by `scripts/demo_check.py` (results at the bottom). Its screenshots are in `outputs/screenshots/demo/`.

## Before the demo (once, about 2 minutes)

```bash
cd <the project folder>          # e.g. ~/Desktop/hubhacks
.venv/bin/python scripts/reset_demo.py      # clears earlier approvals/reviews, re-runs the demo window (warm cache)
.venv/bin/streamlit run app/streamlit_app.py
```

* Open **http://localhost:8501/?reviewer=Demo+Biologist**. The `reviewer` part fills in "Your name" in the sidebar; or type a name there.
* To prove "offline", turn Wi-Fi off now. Everything below works without a network.
* Expected starting state: **Species registry** = only *Small schooling fish*. **Review queue**, *Show items from* `T1 STAT2 411 · 1280-1355s`: **17 items**, and item 1 is the green crab (**21:32–21:48**, *Possibly a species not in the registry*, item ID `…_1280-1355s_t353`).

## 1. Murky water: enhancement and visibility (Analyze page, ~45 s)

1. Sidebar **Analyze** (the default page). The green badge says **Running locally on Apple GPU (MPS)**.
2. **Check the water clarity** opens at moment **420 s (7:00)**, a very hazy stretch. **Drag the slider across the image** to compare Original and Enhanced.
   The visibility score reads **0.27 / 1**, with a grey **"too murky"** badge: *fish here are counted as "Unable to ID due to visibility" and never flagged as a new species.*
3. Move **Preview moment** to **1297** (21:37): the crab is beside the pole, and visibility is "good".
   *Say:* in murky water the risk is mislabelling haze as a known fish (EVALUATION.md), so murky tracks go to the protocol's own "Unknown/Unable to ID due to visibility" column instead.

## 2. Counts per species with confidence (~1 min)

1. **Run the analysis** → **Custom window** → Start **1280**, Length **75** → **Analyze video**.
   The five steps (Enhance → Detect → Track → Identify → Count) light up and turn into ticks. With a warm cache (after `reset_demo.py`) it finishes in **about 10–40 s**. A first-ever run of this window takes about 3–4 minutes on the M5 and about 8 minutes on an M2, so always run `reset_demo.py` beforehand.
2. The green message: *Finished in … on this computer (Apple M5 …). External network connections during the run: 0.* Three summary cards follow.
3. Click **See full results**. Point at:
   * the four cards: **Fish counted** (MeanCount), **Species found**, **Items to review**, **Footage with low visibility**;
   * **Counts by species**: *Small schooling fish* with MaxN, MeanCount and a **Confidence** bar; *Probably … (unconfirmed)*; *Unfamiliar (flagged for review)*; and the protocol's *Unknown/Unable to ID due to visibility*;
   * **Fish and visibility over time**: two stacked charts on the same time axis, with the 60-second subsample points dotted, the identification threshold dashed, and grey bands where it's too murky;
   * **Original and enhanced** slider, the **annotated video** (green = known, yellow "?" = uncertain, red "NEW?" = unfamiliar), and the **Download** buttons (CSV in the protocol spreadsheet layout, JSON).

## 3. A held-out species is flagged as unfamiliar instead of mislabelled (~1 min)

1. Sidebar **Review queue**. *Show items from* is the 1280-1355s analysis; the counter reads **0 of 17 reviewed**.
2. Item 1: red **! Unfamiliar** badge, **Possibly a species not in the registry**, **21:32–21:48**. Play the **evidence clip**: the crab is boxed in orange. **Best views of this fish** shows the crab.
   **Closest registry matches**: *Small schooling fish* **0.45 · no match**, well left of both threshold marks (0.68 and 0.77).
   *Say:* the only registry species is the schooling fish. The crab was deliberately held out, and BlueSight says "I don't know this" instead of calling it a fish.

## 4. Approve it, and see it in the registry (~45 s)

1. On item 1, type **European green crab** in *Species name*. Click outside the box, then press **N** (or click **New species**).
   A toast confirms it, the counter moves to **1 of 17 reviewed**, and the next item appears. (Shortcuts: `N` new · `E` existing · `X` reject · `J` skip · `K` back.)
2. Sidebar **Species registry**: a **European green crab** card with the green **★ Added in review** badge, **Approved by Demo Biologist**, today's date, and 5 reference images (the crab crops). No retraining: the prototype was rebuilt instantly.

## 5. Re-run: the new species is recognised (~1 min)

1. **Analyze** → same Custom window (1280 / 75) → **Analyze video** (cached detections, but the crops are re-identified against the new registry: about 40 s on the M5, **about 1½ minutes on an M2**. Talk through the registry card while it runs).
2. **See full results**: **Species found** now includes **European green crab**, and the species table has a *European green crab* row. In the protocol subsamples it is counted as an **invertebrate**, not in total fish.
3. Two more crab tracks that nobody reviewed (**21:29–21:42** and **21:35–21:48**) are now recognised automatically (EVALUATION.md §5b).
   *Be upfront:* a species approved from a single track has a loose prototype and also matches some sand patches. In the rehearsal 2 of the 5 tracks recognised as crab were outside the crab's walk (v1: 8 of 10). The fix is the review loop: confirm more crab examples with **Existing species** and **Reject** sand items. Rejected items become negative examples, and similar items are auto-rejected on the next run.

## 6. How we know it's local (30 seconds, Model & privacy page)

Sidebar **Model & privacy**. Read it top to bottom:
1. **Green banner: "0 external network calls during the last run."** This is not a slogan. During every analysis BlueSight's network guard watches every outgoing connection; anything that isn't to this computer would be blocked and counted. This number comes from the run you just did.
2. **Cards:** *Compute device: Apple GPU*, **Offline mode: On** (the model libraries are switched to offline before they load), **App telemetry: Off** (and the app is only reachable from this computer), and the last run's runtime with its **energy estimate** in Wh and grams of CO2.
3. **AI models on this computer:** BioCLIP (MIT), OWLv2 (Apache-2.0, optional), DINOv2 (Apache-2.0, fallback): version, licence, and the **folder on this disk** each one is loaded from, with its SHA-256 fingerprint.
4. *Say:* "Wi-Fi has been off the whole time. There's also an automated test that runs the whole analysis with the internet blocked, and the full evidence is in LOCAL_VERIFICATION.md."

## Optional: rejecting junk

In the Review queue, open an item that shows only the pole or sand → **Reject: not a fish** (or press `X`) → re-run. It's excluded from counts, and similar flagged items are auto-rejected (`auto_rejected_tracks` in *Run details*).

## After the demo

`.venv/bin/python scripts/reset_demo.py` restores the starting state (removes approved species and review decisions, re-runs the demo window).

## If something goes wrong

* The queue doesn't start with the crab → in **Show items from** pick `T1 STAT2 411 · 1280-1355s`, or run `scripts/reset_demo.py` again.
* Review buttons are greyed out → type your name in the sidebar ("Your name (recorded with each review)").
* The app looks stale → refresh the browser. Logs are in `outputs/logs/bluesight.log`.
* No video plays → the clips are H.264 (hardware-encoded) and play in Chrome and Safari.
* A keyboard shortcut doesn't fire → click on an empty part of the page first (shortcuts are ignored while typing in a box).

## Rehearsal record (`scripts/demo_check.py`, 2026-11-07, Apple M5, after `reset_demo.py`)

13/13 checks passed through the real app (screenshots in `outputs/screenshots/demo/`):

| Step | Check | Result |
|---|---|---|
| 1 | murky frame (7:00) labelled "too murky" | PASS |
| 2 | demo window analysed in the app; 0 external network connections | PASS (12 s, cached) |
| 3 | results page shows counts by species | PASS |
| 4 | review item #1 is unfamiliar and inside the crab's walk | PASS (21:32–21:48) |
| 4 | approved with the `N` shortcut as "European green crab" | PASS |
| 6 | registry shows it with the "New · added in review" badge, approved by Demo Biologist | PASS |
| 7 | re-run in the app; 0 external network connections | PASS (43 s) |
| 8 | results list European green crab | PASS |
| 9 | Model & privacy: "0 external network calls during the last run", offline mode on | PASS |

## Rehearsal record: second laptop (Apple M2, 2026-11-08, fresh clone)

Set up from scratch (README quick start), then `scripts/demo_check.py`: **13/13 checks passed**. Measured on the M2:

| Step | Time on M2 |
|---|---|
| First-ever analysis of the demo window (`reset_demo.py` on a cold cache) | 465 s (~8 min) |
| `reset_demo.py` with a warm cache | ~100 s |
| Step 2, Analyze in the app (warm cache) | 9 s |
| Step 5, re-run after approving the crab | 83 s (161 s the first time) |

`scripts/rehearse_demo.py` on the M2 reproduced the EVALUATION.md §5b numbers exactly: item 1 = crab, unfamiliar, 0.45, 21:32–21:48; after approval 5 tracks recognised as crab (3 inside the walk, incl. the unreviewed 21:29–21:42 and 21:35–21:48), 11 'probably crab?', review items 17 → 16.
