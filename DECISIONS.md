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

## D19. Which video frame the 14:01 tally points belong to
The biologists' 14:01 screenshot pins the annotated instant only to the second. Fish move more than their own length in half a second, so scoring detections against the 36 points on the wrong frame gives meaningless F1 (scores on neighbouring frames 840.5–842.0 s ranged from 0.25 to 0.63).
* **Detector-independent alignment:** the screenshot's high-pass detail was correlated with every video frame from 840.0 to 842.2 s. The peak is at **frame 25214 (841.31 s)**, with the neighbouring frames 841.24–841.37 s next.
* v1's motion detector, scored frame by frame, also peaks at 841.33 s. The two agree, though the correlation margin is small (0.498 vs a median of 0.487).
* **Phase-2 detection F1** is therefore the mean over the 5 exact frames 25212–25216 (±67 ms), each with an exact ±k-second background. The averaging reduces per-frame noise. v1's single-frame score at 841.00 s (F1 0.38) is kept as the BASELINE number for continuity.
* The **count at 14:01** keeps the protocol rule (best sampled frame within ±0.5 s of 841 s, persistent tracks only), so it measures exactly what a survey run reports.

## D20. Motion-detector background size alternates (known v1 inconsistency, left as is)
Frame times are rounded frame indices, so "8 s later" is either 7.975 or 8.008 s. With v1's 1e-6 tolerance the +8 s frame is dropped for about half of the frames. The background stack then alternates between 16 and 17 frames, and `torch.median` takes the lower middle value for even sizes. `detector.motion.ctx_tol_s` (new; 0.26 keeps the stack size constant) was measured (EVALUATION E2): identical frame-level F1, and the count at 14:01 moved from 18 to 16 (further from the manual 36). That isn't a measurable improvement, so the default stays at v1 behaviour (option off), as the "keep only what helps" rule requires.

## D21. Phase-2 outcome: what was kept
Rule applied: keep a change only if it measurably helps on tuning data (tuning half + held-out photos), never judged on the demo half. All numbers are in EVALUATION.md → Phase 2 experiment log.
* **Kept: CLAHE clip 2 / grid 4** (was 3 / 8) for the detector's luminance input and the displayed enhanced frame. It gave the best detection F1 at the annotated 14:01 instant. The visibility score is computed on the original frame, so it is unchanged.
* **Kept: tracker `min_assoc_size` 200 and `box_expand` 2.5** (were 120 and 3.0). Fewer split tracks and fewer merged tracks.
* **Reverted** everything else, including two changes that looked good on the screenshot photos only (enhanced crops for BioCLIP; k-means sub-prototypes). On real video tracks the first fell to chance and the second doubled "possibly new species" flags. The k-means code stays as an option (`identify.prototypes_per_species`, default 1) with the measurements recorded.
* **Sampling stays at 2 fps:** 1 fps undercounts at 14:01 even with the same persistence time, and 0.5 fps counts nothing.
* **No distillation:** OWLv2 base (60 settings) and large (30 settings) found 0 of the 36 annotated fish, so there are no pseudo-labels to distil from.
* **ByteTrack `lost_track_buffer` is a no-op at 2 fps** (supervision scales it by frame_rate/30; values < 15 → 0 frames). It's left at 4 (= 0 frames), because buffers that actually take effect (30, 45) increased merged tracks. The config comment says so.
* Changing the CLAHE and tracker settings changes the cache key, so every video window is re-detected once with the FINAL settings (EVALUATION.md has the fresh runtimes).

## D22. Local verification design
* **Offline env in `bluesight/__init__.py`**, not only in `load_config()`, because `huggingface_hub` reads `HF_HUB_OFFLINE` at import time. `BLUESIGHT_ALLOW_DOWNLOADS=1` is the explicit, documented way to do the one-time download.
* **Network guard (`bluesight/netguard.py`)**: patches `socket.connect`, `connect_ex` and `getaddrinfo` for the duration of each run. Loopback and Unix sockets are allowed; anything else is recorded and, in `block` mode (default), refused. It's in-process: it covers every library BlueSight uses, but not other programs (the Wi-Fi-off test covers those). The count is stored in each `report.json` and drives the Model & privacy indicator.
* **The offline test patches sockets itself**, so the guard isn't the only thing checking the guard.
* **Energy:** CodeCarbon `OfflineEmissionsTracker` (MIT), Nova Scotia grid. On Apple Silicon without root it can only estimate CPU power from load plus a RAM model, and it can't see the Apple GPU, so the numbers are labelled estimates and lower bounds everywhere.
* **Streamlit:** `gatherUsageStats=false`, `server.address=localhost`, `toolbarMode=minimal` (hides "Deploy"), system fonts only.

## D23. Accessibility: what is and isn't covered
An automated pass with Playwright on every page found no images without alt text, no unlabelled inputs and no unnamed buttons. All BlueSight buttons are ≥ 44 px tall, and no text below 4.5:1 after the fixes. Two things are left:
* Streamlit's built-in icon buttons (help "?", table toolbar, fullscreen) are 16–24 px. That meets WCAG 2.2's 24 px minimum for most of them, with spacing for the help icons, and can't be resized without patching Streamlit.
* Data tables are drawn on a canvas by Streamlit's grid component. It has its own keyboard navigation, but screen-reader support is limited. The CSV download and the "Show this chart as a table" views are the accessible fallback.
* Not tested: real screen readers (VoiceOver/NVDA) and 200% zoom. Both are recommended before production use.

## D24. Light and dark mode, visual refresh
- `.streamlit/config.toml` defines `[theme.light]` and `[theme.dark]`. The app follows the computer's setting, and the reader can override it in ⋮ → Settings (so `toolbarMode` is now `viewer`; `minimal` hides that menu).
- Every custom colour in `app/ui/theme.py` is a CSS `light-dark()` token. Streamlit sets `color-scheme` on the app root, so the custom components switch along with Streamlit's own widgets, with no JavaScript. The only places CSS can't reach (Altair charts, the before/after iframe and the logo) read `st.context.theme.type`.
- Dark palette: deep-water background `#0B141A`. All text is at least 4.5:1 (ink 14.2, muted 6.7, status colours 7.5–9.2). Primary buttons use `#1F7C96` (4.8:1 with white text); text accents use the lighter `#5BB8D3`.
- Page titles and species names use a system book serif (Iowan Old Style / New York / Georgia) for a field-guide feel; nothing is downloaded. Hardcoded hex colours in the pages were replaced with tone classes (`t-ok`, `t-warn`, `t-bad`, `t-muted`, `t-info`).

# v3 decisions (branch `v3-hackathon`, 2026-11-08)

Goal: make BlueSight usable by non-technical staff, match Coastal Action's protocol outputs, and add the climate/invasive
angle from the problem statement, without breaking any hard constraint (local only, permissive licences, scientists in
charge). Coastal Action could not be contacted during the hackathon, so the assumptions below are recorded instead.

## D25. Image clarity is not a visibility distance
The protocol records horizontal visibility in four categories read off the 2 m pole (<0.5, 0.5–1.0, 1.0–1.5, >1.5 m).
We tried to map BlueSight's 0–1 score onto those categories, but in T1-STAT2 the black tape bands are visible to the far
end of the pole even at score 0.27 (7:00, the haziest stretch) and 0.35 (11:00). The score measures how hard fish are
to spot (contrast, haze), not distance. So: staff enter the pole category in **Survey details**; the score is reported as
"image clarity" (too murky to identify / fair / good) and never as metres. Automatic pole reading is future work.

## D26. AI-assisted counting replaces a 6-hour detector training run
With ~140 hand-marked fish and one video, a trained detector was unlikely to beat the motion detector within the
hackathon (OWLv2 found 0 of 36 fish; EVALUATION.md). The **Count check** page instead shows the AI's numbered marks on
each 60-second subsample frame; a person removes wrong marks (one by one or a whole category, e.g. "too murky") and adds
missed fish. Checked counts replace the AI's in the "MeanCount with checks", the Excel file says which rows were
checked, and corrections export to `outputs/training_labels/<run>/labels.json` (kept boxes = positives, removed = hard
negatives, missed fish = count) so a Nova Scotia detector can be trained later on real corrections.

## D27. Blind-count QC follows the protocol's numbers
Blind mode hides the AI's marks. Per frame we report the percent difference |a−b| / mean(a, b) (protocol: < 6 %); overall
agreement = Σmin / Σmax over the blind frames (protocol: ≥ 95 %). Assisted checks win over blind ones when both exist
for a subsample, because they are the corrected count.

## D28. Watch list, expected species list and temperature
* **Watch list** (config `watch_list`, then edited in the app; stored in SQLite): seeded with European green crab
  (invasive in Nova Scotia), black sea bass and blue crab (warm-water species expanding north, "verify and report").
  The two warm-water entries are examples of the alert, chosen by us, not by Coastal Action.
* **Temperature ranges are left empty** on purpose: we would rather show no range alert than an invented range. Staff
  enter ranges they trust; a survey temperature outside a range raises an alert.
* **Water temperature is typed in** from field sheets (Survey details). Nothing is fetched online (CIOOS etc. would
  need a live connection; a one-time import is future work).
* **Expected species list** = `species_candidates` + `expected_extra` (the photo labels). A species confirmed in review
  that is on neither list raises a "possible new arrival" alert.
* The review queue's species name is now a picker over the expected list + watch list + registry, and still accepts any
  typed name.

## D29. Excel export
`openpyxl` (MIT). Sheet *Subsamples* uses the protocol's column names (Total Fish Count, Invertebrate count, Total species
observed, a column per species, "Unknown/Unable to ID due to visibility", Notes) plus image clarity and who counted it.
*Summary* has MeanCount (AI and with checks), MaxN, richness, clarity, pole visibility, temperature, juveniles, QC
agreement, alerts, models and the network-call count. We did not have Coastal Action's actual template (D3), so column
order may need adjusting to their sheet.

## D30. Launchers and setup
`Start BlueSight (Windows).bat` / `Start BlueSight (Mac).command`: first start installs uv, Python 3.11 and the packages
(`uv pip --torch-backend=auto` picks the CUDA build of PyTorch when an NVIDIA GPU is present), downloads the models once
(`scripts/setup_models.py`) and builds the data layout; later starts just launch the app and open the browser. The
Windows launcher was written for Coastal Action's planned 12 GB-GPU PC but **has not been run on Windows** during the
hackathon (no Windows machine available). Video encoding falls back from Apple's hardware encoder to libx264/h264/mp4v,
so Windows needs no extra install. Copying `models/` from another computer skips the download.

## D31. Schooling fish label stays unconfirmed
`small_schooling_fish` comes from the biologists' tally dots on T2-STAT2 screenshots; no species was named. Visually the
fish (small, slender, silvery, mid-water schools over sand in September) fit Atlantic silverside, juvenile herring or
sand lance. We did not rename it: identification is the biologists' call, and the review queue lets them rename or
confirm it.

# v4 decisions (branch `v4-accuracy`, 2026-11-08)

## D32. A density counter, not a box detector
The labels are dots, not boxes, and only five frames have them. Density counting (predict fish per patch, sum) learns
directly from dots and from the biologists' own counting rule; a box detector would need invented box sizes. DINOv2-small
is frozen (already on disk, Apache-2.0, 22 M parameters) so only a 0.5 M-parameter head is trained: seconds per run and no
risk of wrecking the backbone with five images.

## D33. Choosing the configuration
Leave-one-frame-out on all five annotated frames; kept the lowest average error, tie broken by the survey-video folds
(EVALUATION v4). 3× resolution and CLAHE input were measured and rejected. No threshold or combination rule was tuned on the
two survey-video frames.

## D34. Second opinion, not replacement
The counter is better than the motion detector at 14:01 and worse at 22:00, so it does not replace the motion-based count
(which also carries species and tracks). It is reported next to it, flags disagreements for human checking first, and draws
a heatmap in Count check. Both counts appear in the Excel file. Config: `density.*`; `density.enabled: false` turns it off.

## D35. Web reference photos are a field guide, not training data for identification
Downloaded once with the user's approval (iNaturalist, CC0/CC-BY/CC-BY-SA only, attribution committed, images not).
Measured (EVALUATION v5): no extra harm on held-out survey crops, but the real video crab's closest web species is blue
crab (0.85 > T_KNOWN) and the web green-crab photos rank 12th, so registry prototypes from web photos would create false
watch-list alarms. Kept out of the registry; shown to reviewers only. Green crab photos are stored separately
(data/reference_web_heldout/) so the held-out demo stays honest; they are shown in the field guide but were never in the
registry. NC-licensed photos were excluded to keep everything permissive.

## D36. Visual identity (UI pass with Anthropic's frontend-design guidance)
* **Subject first:** a field tool for Coastal Action staff working with murky Nova Scotia survey video.
* **Signature element:** the banded 2 m visibility pole seen in every survey video (white pipe, black tape every 0.5 m)
  is the progress bar for the four steps and the 15 check points. It is the one bold element; everything else is quiet.
* **Palette from nautical charts:** chart paper `#F1F4F0`, deep-water ink `#11293A`, sounding blue `#2A5D7C`, shallow
  tint `#DDE9EC`, kelp olive `#4F5E26` for "done", survey-flag orange `#A93A0B` only for "check first" and alerts. Dark
  mode mirrors it. Text contrast ≥ 4.5:1.
* **Type:** Atkinson Hyperlegible Next (Braille Institute; SIL Open Font License), one family, chosen for legibility by
  non-technical staff. Bundled in `static/fonts/` and served by Streamlit's static serving, so the app stays offline.
* **Removed generic tells:** ALL-CAPS labels, monospace number badges, step eyebrows, identical shadowed cards, long
  intros. Labels are sentence case; panels are flat with small radii.
