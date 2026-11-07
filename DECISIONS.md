# DECISIONS

Assumptions, overrides from Coastal Action's protocol, and judgment calls made while building BlueSight. Each entry says what was decided and why.

## D1. Tooling on this machine
* This Mac has **no Python and no Xcode command-line tools**, so `/usr/bin/git` and `/usr/bin/python3` are only install stubs. Python 3.11.18 was installed with **uv** (standalone, no sudo) into `.venv/`.
* **git:** commits are made with **dulwich**, a pure-Python git implementation, because system git is unavailable. The repository is standard and works with normal git once the developer tools are installed (`xcode-select --install`).
* `supervision` is pinned to **0.26.1**. Versions from 0.27 on removed the built-in `ByteTrack`, which the spec requires.

## D2. Protocol overrides (Coastal Action DRAFT FFH Video Analysis Protocol → overrides CLAUDE.md defaults)
| Topic | CLAUDE.md default | Protocol (used) |
|---|---|---|
| Primary abundance metric | MaxN and MeanCount | **MeanCount** from systematic subsampling. MaxN is still reported, but the protocol mentions it only in a reviewer comment. |
| Analysis window | whole video | **discard the first and last minute; analyse a 15-min segment** (`protocol.*` in config). The pipeline defaults to 60–960 s. Other windows can be set but are labelled. |
| Subsampling | MeanCount over all sampled frames | **one subsample every 60 s (15 per 15 min)**. The count at a point is the sampled frame within **±0.5 s** with the most fish ("one second = one analysed frame"; fish visible within ~0.5 s may be counted). MeanCount over all 2-fps frames is also reported, labelled separately. |
| What is counted | every detection | only organisms recognisable by **≥2 cues (shape + swimming behaviour)**. Detections that never move consistently for `MIN_FRAMES` samples are **transient and not counted**. Their number per frame is reported. |
| Columns | species | species columns, **"Unknown/Unable to ID due to visibility"** (the protocol's own column), total fish count, **invertebrate count** (crabs/shrimp via `invertebrate_species`), visibility per subsample |
| Visibility | 0–1 score | The protocol uses metre categories from 2–3 human observers and a visibility pole. BlueSight cannot measure metres, so it reports its **0–1 visibility score per subsample** and the share of footage below V_MIN. It does not claim metre categories. |

The protocol has an older draft section (12-min windows, 60 points). The current procedure (15 min, 15 frames) is used.

## D3. Species list
The PDF contains **no species list**. For zero-shot label proposals only, `config.yaml → species_candidates` holds 14 common nearshore Nova Scotia taxa (Atlantic silverside, sticklebacks, mummichog, tomcod, winter flounder, cunner, rock gunnel, Atlantic herring, sand lance, grubby sculpin, European green crab, Atlantic rock crab, sand shrimp). **This list is an assumption. Please replace it with Coastal Action's list.**

## D4. How reference images were labelled (deviation from the requested zero-shot rule)
* The photos are annotated screenshots, not species folders. The only species name in any file name is "green crab".
* As requested, BioCLIP zero-shot proposed a label for every crop (`data/proposed_labels.csv`, with confidences). **The proposals turned out to be unreliable:** plain sand patches got "mummichog" at 0.93–0.99, one school split between mummichog and threespine stickleback, and the green-crab crop got "mummichog 0.36" with green crab not in its top 3. Using "high-confidence proposals" for the registry would have made the registry wrong. `labels.trust_zero_shot` is therefore `false`.
* Labels come from **how the biologists marked the photos**:
  * red tally dots on schooling fish → `small_schooling_fish` (198 crops, T2-STAT2). **The species is unconfirmed; please identify it.** It can be renamed in the registry folder or added under a new name in the app.
  * file name "marked green crab" → `european_green_crab` (1 crop)
  * other red circles → `benthic_organism_unconfirmed` (38 crops, species not stated)
* All circle crops and their zero-shot top 3 are listed in RESOURCES.md for checking.

## D5. Held-out species
* **Held out: `european_green_crab` and `benthic_organism_unconfirmed`.**
* The request was to prefer 2 species that appear in `T1-STAT2 411.MP4`. After detection and identification on the video, the European green crab clearly appears: a large crab walks past the pole at about 21:33–21:40 and is circled at 22:00. The schooling fish also appear.
* The schooling fish were **not** held out. They are the only other labelled class, so holding them out would leave the registry empty. Then nothing could be "known", and the false-alarm test and the counts-per-species demo step would be meaningless.
* The second held-out group is the circled benthic organisms. They are kept out of the registry and used as extra "not in registry" test images. They may contain several taxa, possibly including more green crabs.
* The "2 species with the most images" fallback was not needed and would not work here: there are only three classes, and one of them is the only fish reference.

## D6. Detector: motion-based by default, OWLv2 kept as an option
* The spec's default is OWLv2/Grounding DINO prompted with "fish". Measured on the 22:00 frame (102 fish), OWLv2 base found 0–11 fish, depending on tiling and threshold, at about 0.7 s per tile.
* The camera is stationary, so a **temporal-novelty detector** works much better. A pixel is foreground when it differs from the per-pixel median of ±8 s of frames by more than 2.5 robust z-scores of its own variability (MAD). That variability normalisation suppresses flickering caustics. Elongated blobs only. Parameters came from a sweep on the **14:01 frame (tuning half)**, scored against the 36 tally-dot points.
* Both detectors sit behind `Detector`. `detector.name` switches between them. The measured comparison is in EVALUATION.md.
* No bounding-box labels were provided, so no detector was fine-tuned.
* **`max_area` correction (disclosed):** `max_area` was not part of the sweep and was first set to 8,000 px² for small fish. Inspecting the demo half showed a large European green crab (~400×150 px at 1080p, 21:31–21:45) being filtered out as "too big", leaving only leg fragments. `max_area` was raised to 80,000. On the tuning frame (14:01) this changes nothing (F1 0.38 before and after, no large blobs), so the fish detection results stand. This is the one setting changed after looking at demo-half footage.

## D7. Tracking at 2 fps
At 2 fps a 50 px fish moves more than its own length between samples, so boxes are inflated (×3, at least 120 px) **for association only**. ByteTrack reports a new track only from its second frame, so its first detection is backfilled by IoU with the previous frame's untracked detections.

## D8. Visibility score calibration
The cue ranges (contrast 0.04–0.10, sharpness log-Laplacian 0.4–1.8, dark-channel haze 0.35–0.56) were calibrated on this camera's footage across the whole video. With these ranges the very hazy 5–10 min stretch scores about 0.15–0.20 and the clear 18–35 min stretch about 0.65–0.75. New cameras may need recalibration.

## D9. Ground truth
* The handwritten grid counts in the two T1-STAT2 screenshots were **transcribed by reading the images**: 14:01 → 36 and 22:00 → 102 (+1 green crab). The VLC timebar ("/35:47") proves they come from this video.
* At 14:01 the 36 black tally dots were extracted automatically, and their per-cell counts reproduce the handwritten numbers exactly. They serve as point labels. At 22:00 dot extraction also picks up sand texture, so only the total is used there.
* Photos of this video are evaluation data and never reference images. The exception is the single green-crab crop, which belongs to the held-out set and therefore never enters the registry.

## D10. Tuning half / demo half
The video is split at its midpoint (1073.6 s): **tuning half 60–1073.6 s** (contains the 14:01 count) and **demo half 1073.6–2087.3 s** (contains 22:00 and the green crab). Detector parameters and V_MIN are tuned on the tuning half only. T_KNOWN and T_UNKNOWN are tuned on image-level held-out vs known crops. The demo uses the demo half.

## D11. Site and date
Site comes from the file name (`T1-STAT2`). The date (2025-09-10) comes from the photo names "T1_STAT 2_Sept 10" and the protocol's "Fall 2025". Both are in `config.yaml → survey`.

## D12. Video encoding
Clips and annotated videos are H.264 via PyAV, using **Apple's hardware encoder `h264_videotoolbox`** (low energy, no GPL code), with libx264 as fallback. PyAV and OpenCV each bundle FFmpeg, and macOS prints a harmless duplicate-class warning (`AVFFrameReceiver`). It doesn't affect file decoding or encoding. PyAV is imported only when writing clips.

## D13. Review decisions feed back into counts
* **Approve as new or existing species:** the crops are copied to `outputs/registry/<species>/`, and that prototype is rebuilt immediately. On re-run, the reviewed tracks count as that species (human-verified), and similar tracks match the updated prototype.
* **Reject / not a fish:** on re-run those tracks are excluded from counts.
* Nothing ever adds a species without a named reviewer.

## D14. Build order
The Streamlit UI was built after the first real pipeline outputs existed, because model setup took minutes rather than blocking UI work. To keep UI work independent of models anyway, `scripts/make_mock_data.py` + the "Mock data" switch in the sidebar provide a model-free mock mode.

## D15. Learning from "Reject / not a fish"
The motion detector picks up the swaying measuring pole and sand caustics. Their frequency is too low (≤ 10% of frames per cell) for a static mask. Instead, every item a reviewer rejects becomes a **negative example**. On later runs, a *flagged* track more similar to a rejected item (cosine ≥ `identify.reject_similarity`, 0.90) than to any species is auto-rejected and not counted (`auto_reject()` in identify.py). Known species are never affected and nothing is ever auto-accepted, so the "no species without human approval" rule holds.

---

# v2 decisions (branch `v2-ui-model`, 2026-11-07)

## D16. UI: skills used, design system, accessibility
**Skills loaded and followed** (no `frontend-design` skill was available in this environment):

| Skill | How it was used |
|---|---|
| `design:design-system` | Defined tokens before any page: one palette, a type scale (12/14/16/18/22/28/34 px), a 4-8-12-16-24-32-48 px spacing scale, 8 px control / 12 px card radii, and reusable components (status badge, visibility badge, metric card, similarity bars, stepper, empty state). They live in one file, `app/ui/theme.py`, mirrored in `.streamlit/config.toml`. |
| `design:accessibility-review` | WCAG 2.1 AA checks: contrast computed for every text/background pair (lowest pair: muted text on the tinted background, 4.73:1; body text 16.3:1; white on primary 7.4:1). Status always carries an icon and a word as well as a colour (1.4.1). Visible 3 px focus ring (2.4.7). Buttons ≥ 44 px tall, decision buttons 56 px (2.5.5). Every input has a visible label (3.3.2). Charts have a text `alt` and a "show as table" view. |
| `design:ux-copy` | Plain verbs on buttons ("Analyze video", "New species", "Reject: not a fish", "Skip for now"). Empty states say what the page is for, why it's empty and what to do next. Errors say what happened and how to fix it. Biologist vocabulary is used: MeanCount, MaxN, subsample, "Unable to ID due to visibility". |
| `design:design-critique` | Each screenshot round (`outputs/screenshots/after/round0…`) was critiqued for hierarchy, consistency and usability, then fixed (see D18). |
| `dataviz` | Never a dual y-axis: fish count and visibility are two stacked charts on the same time domain. One series per chart, so no legend box; titles name them. Thresholds are drawn as labelled rules. Recessive grid, hover tooltips, a table view, and status colours kept out of the series palette. |

**Palette** (ocean, calm, trustworthy): primary deep-sea teal `#0B5C7A`, ink `#0F2230`, sea-mist background `#F4F7F9`. Status colours are reserved: known green `#1B6B45`, uncertain amber `#8A5300`, unfamiliar red `#B42318`, low visibility slate `#4F5B66`.
**Fonts:** the system font stack. Web fonts were rejected because loading them means the browser contacts a font CDN, which conflicts with "everything runs locally".
**Light theme only.** The custom CSS and the status colours are validated against the light surfaces. A dark theme would need its own validated steps, and there was no time to do that properly.

## D17. Working copy setup
This Desktop folder was a fresh clone (no resources, venv, models, outputs). The original working copy at `~/Documents/hubhacks` (same commit `d31133e`) was **not modified**.
* `HubHacks Resources` here is a **symlink** to the read-only originals in the Documents copy (gitignored). `scripts/prepare_resources.py` uses `rglob`, which doesn't follow a symlinked directory, so the already-built `data/` layout (relative symlinks plus derived crops) was copied from the Documents copy instead of being rebuilt.
* `models/` and `outputs/cache` were copied, so no model was re-downloaded and no detection was recomputed for the baseline.
* A new `.venv` was created with uv, pinned to the exact package versions of the original venv. Added: `codecarbon` (energy estimate, runtime), `playwright` (screenshots, dev only).

## D18. Stay in Streamlit
Streamlit was kept. A FastAPI + web frontend would mean re-implementing upload, video playback, tables, charts and state for no gain the users would notice. Streamlit 1.67 provides what was needed:
* `st.navigation`, so pages have URLs (`/results`, `/review`, …).
* `st.button(shortcut=…)` for keyboard shortcuts.
* Keyed containers for scoped CSS.
* `st.iframe` for a self-contained before/after slider (inline JS, nothing fetched).
The pipeline (`src/bluesight/`) is untouched by the UI work; the UI lives in `app/ui/`.

Review-queue interaction: **one focused card at a time** (plus a compact "Up next" grid) instead of v1's wall of 28+ cards with 28 videos. This gives a progress counter ("3 of 30 reviewed") and a fast keyboard flow: `N` new species, `E` existing, `X` reject, `J` skip, `K` back. `R` would be the natural key for Reject, but Streamlit reserves `R` (rerun) and `C`; `X` matches the ✕ icon. Shortcuts are ignored while typing in the species-name box (tested with Playwright).
