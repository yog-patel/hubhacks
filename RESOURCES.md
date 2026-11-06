# RESOURCES

Everything the team provided is in **`HubHacks Resources/`**. The originals are read-only: nothing in that folder is modified, renamed or moved. The working copies under `data/` and `docs/` are symlinks or derived files. `data/manifest.csv` maps every original to its role, and `scripts/prepare_resources.py` rebuilds this layout.

## What was provided

| File | Type | Role |
|---|---|---|
| `HubHacks Resources/T1-STAT2 411.MP4` | video, 2.27 GB | the only survey video → `data/videos/` (symlink) |
| `HubHacks Resources/Coastal Action DRAFT FFH Video Analysis Protocol.pdf` | 10-page PDF | counting protocol → `docs/instructions/` (symlink) |
| `HubHacks Resources/Subsample Photos.zip` | 28 PNG screenshots, 38 MB | extracted to `data/raw_photos/` (gitignored); the zip itself is untouched |

## Video

| | |
|---|---|
| File | `T1-STAT2 411.MP4` (transect 1, station 2) |
| Length | 35 min 47 s (2147.3 s, 64,354 frames) |
| Resolution / codec | 3840×2160 (4K), HEVC, 29.97 fps |
| Date | 10 Sept 2025 (from the photo names "T1_STAT 2_Sept 10"; the protocol says Fall 2025) |
| Content | Stationary camera on sandy bottom with a measuring/visibility pole. 0–~1 min: camera being placed (surface visible). ~5–11 min: very hazy (visibility score 0.15–0.19). ~14–35 min: clearer (0.55–0.75). Schools of small, pale, translucent fish (≈80–150 px long at 4K) pass through the water column, and there are camouflaged benthic organisms on the sand (a green crab at 22:00). Sunlight caustics flicker on the sand. |

## Photos (`Subsample Photos.zip` → `Sept 10 & 9th sub-samples/`)

These are **not** species-sorted reference photos. They are 28 annotated screen captures (VLC player, about 1917×1077) of subsample frames from several transects and stations. Biologists marked them up:

| Station / date | Photos | Annotation style |
|---|---|---|
| **T1-STAT2, Sept 10 (this video)** | 4 (14:01, 22:00 ×3) | grid + handwritten count per cell + a black tally dot on each fish; one image has a red circle labelled **"marked green crab"** in its file name |
| T1-STAT3, Sept 9 | 3 | red circles around organisms |
| T2-STAT2, Sept 10 | 10 | red circles; 3 gridded images with red tally dots on schooling fish (13, 14, 21 min) |
| T2-STAT3, Sept 9 | 2 | red circles |
| T3-STAT3, Sept 9 | 9 | red circles |

**Species information:** the only species named anywhere in the resources is the **European green crab** (one file name). Neither the protocol nor the photos contain a species list.

### Crops derived from the annotations (`data/crops/`, 237 total)

| Label | Crops | Where from | Folder |
|---|---|---|---|
| `small_schooling_fish` | 198 | red tally dots on individual schooling fish, T2-STAT2 at 13, 14 and 21 min (18 + 46 + 134) | `data/reference_images/small_schooling_fish/` |
| `european_green_crab` | 1 | the red circle in "T1_STAT 2_Sept 10_count @ 22 _marked green crab.png" (this video, 22:00) | `data/held_out/european_green_crab/` |
| `benthic_organism_unconfirmed` | 38 | red circles around single organisms (T1-STAT3, T2-STAT2/3, T3-STAT3); species not stated | `data/held_out/benthic_organism_unconfirmed/` |

The photos of the survey video itself (14:01 and 22:00) are **ground truth**, not reference images: `data/ground_truth/`.

## Labels and annotations

* No bounding boxes and no CSV/Excel of counts were provided. The protocol mentions an Excel sheet, but it was not included.
* **Manual counts for this video** were recovered from the gridded screenshots (`data/ground_truth/manual_counts.csv`, produced by `scripts/extract_ground_truth.py`):
  * **14:01 → 36 fish** (cells 13+9+5+5+3+1). The 36 tally dots were also extracted as point labels (`points_841s.json`), and their per-cell counts match the handwritten numbers exactly.
  * **22:00 → 102 fish** (cells 13+25+12+7+14+10+3+8+8+2) **+ 1 green crab**.
* Point-style annotations: black tally dots (T1-STAT2) and red tally dots (T2-STAT2) mark individual fish; red circles mark single organisms.

## BioCLIP zero-shot label proposals: please check

As instructed, every crop got a BioCLIP zero-shot proposal over the 14 candidate species in `config.yaml` (`data/proposed_labels.csv`, with confidences). **The proposals are not reliable on these murky crops.** Plain sand patches get "mummichog" at 0.93–0.99. The 198 crops of one school split between "mummichog" (127) and "threespine stickleback" (56). The one labelled green crab is proposed as "mummichog 0.36", and green crab isn't in its top 3. High confidence was therefore **not** used to admit crops into the registry. Labels come from how the biologists annotated the photos (see DECISIONS.md D4).

**Please check:** (1) what species the small schooling fish are, then rename `small_schooling_fish` in the app or folder; (2) what each circled organism is. The circled crops and BioCLIP's (unreliable) top 3:

| Crop (`data/crops/`) | Station | Current label | BioCLIP zero-shot top 3 |
|---|---|---|---|
| `T1_STAT_2_Sept_10_count__22__marked_green_crab_c0.jpg` | T1-STAT2 | european_green_crab | mummichog=0.36; threespine_stickleback=0.31; cunner=0.26 |
| `T1-STAT_3_Sept_9__count__17min_c0.jpg` | T1-STAT3 | benthic_organism_unconfirmed | mummichog=0.93; threespine_stickleback=0.03; fourspine_stickleback=0.02 |
| `T1-STAT_3_Sept_9__count__17min_c1.jpg` | T1-STAT3 | benthic_organism_unconfirmed | mummichog=0.99; threespine_stickleback=0.01; cunner=0.01 |
| `T1-STAT_3_Sept_9__count__19min_c0.jpg` | T1-STAT3 | benthic_organism_unconfirmed | mummichog=0.67; winter_flounder=0.15; threespine_stickleback=0.10 |
| `T1-STAT_3_Sept_9__count__20min_c0.jpg` | T1-STAT3 | benthic_organism_unconfirmed | mummichog=0.96; threespine_stickleback=0.01; cunner=0.01 |
| `T1-STAT_3_Sept_9__count__20min_c1.jpg` | T1-STAT3 | benthic_organism_unconfirmed | mummichog=0.92; winter_flounder=0.03; sand_shrimp=0.02 |
| `T1-STAT_3_Sept_9__count__20min_c2.jpg` | T1-STAT3 | benthic_organism_unconfirmed | mummichog=0.99; winter_flounder=0.00; atlantic_silverside=0.00 |
| `T2_STAT_2_Sept_10_count_10min_c0.jpg` | T2-STAT2 | benthic_organism_unconfirmed | threespine_stickleback=0.73; mummichog=0.27; fourspine_stickleback=0.00 |
| `T2_STAT_2_Sept_10_count_10min_c1.jpg` | T2-STAT2 | benthic_organism_unconfirmed | mummichog=0.78; threespine_stickleback=0.22; atlantic_silverside=0.00 |
| `T2_STAT_2_Sept_10_count_11min_c0.jpg` | T2-STAT2 | benthic_organism_unconfirmed | mummichog=0.71; threespine_stickleback=0.29; fourspine_stickleback=0.00 |
| `T2_STAT_2_Sept_10_count_12min_c0.jpg` | T2-STAT2 | benthic_organism_unconfirmed | mummichog=0.60; threespine_stickleback=0.28; european_green_crab=0.06 |
| `T2_STAT_2_Sept_10_count_12min_c1.jpg` | T2-STAT2 | benthic_organism_unconfirmed | mummichog=0.90; sand_shrimp=0.05; threespine_stickleback=0.02 |
| `T2_STAT_2_Sept_10_count_14min_c0.jpg` | T2-STAT2 | benthic_organism_unconfirmed | threespine_stickleback=0.82; cunner=0.10; fourspine_stickleback=0.04 |
| `T2_STAT_2_Sept_10_count_14min_c1.jpg` | T2-STAT2 | benthic_organism_unconfirmed | mummichog=0.44; background:sandy seabed with rocks=0.43; cunner=0.03 |
| `T2_STAT_2_Sept_10_count_14min_c2.jpg` | T2-STAT2 | benthic_organism_unconfirmed | mummichog=0.70; european_green_crab=0.19; cunner=0.06 |
| `T2_STAT_2_Sept_10_count_15min_c0.jpg` | T2-STAT2 | benthic_organism_unconfirmed | mummichog=0.97; threespine_stickleback=0.02; cunner=0.01 |
| `T2_STAT_2_Sept_10_count_15min_c1.jpg` | T2-STAT2 | benthic_organism_unconfirmed | mummichog=0.84; threespine_stickleback=0.15; atlantic_silverside=0.02 |
| `T2_STAT_2_Sept_10_count_15min_c2.jpg` | T2-STAT2 | benthic_organism_unconfirmed | mummichog=0.96; sand_shrimp=0.02; threespine_stickleback=0.01 |
| `T2_STAT_2_Sept_10_count_21min_c0.jpg` | T2-STAT2 | benthic_organism_unconfirmed | mummichog=0.85; cunner=0.07; sand_shrimp=0.05 |
| `T2_STAT_2_Sept_10_count_21min_c1.jpg` | T2-STAT2 | benthic_organism_unconfirmed | mummichog=0.87; threespine_stickleback=0.06; winter_flounder=0.02 |
| `T2_STAT_2_Sept_10_count_7min_c0.jpg` | T2-STAT2 | benthic_organism_unconfirmed | mummichog=0.30; atlantic_silverside=0.24; american_sand_lance=0.13 |
| `T2_STAT_2_Sept_10_count_7min_c1.jpg` | T2-STAT2 | benthic_organism_unconfirmed | mummichog=0.98; winter_flounder=0.01; threespine_stickleback=0.00 |
| `T2_STAT_2_Sept_10_count_8min_c0.jpg` | T2-STAT2 | benthic_organism_unconfirmed | threespine_stickleback=0.88; fourspine_stickleback=0.05; mummichog=0.04 |
| `T2_STAT_2_Sept_10_count_9min_c0.jpg` | T2-STAT2 | benthic_organism_unconfirmed | threespine_stickleback=0.87; mummichog=0.11; fourspine_stickleback=0.01 |
| `T2_STAT_2_Sept_10_count_9min_c1.jpg` | T2-STAT2 | benthic_organism_unconfirmed | threespine_stickleback=0.80; mummichog=0.11; fourspine_stickleback=0.06 |
| `T2_STAT_2_Sept_10_count_9min_c2.jpg` | T2-STAT2 | benthic_organism_unconfirmed | mummichog=0.98; threespine_stickleback=0.01; cunner=0.01 |
| `T2_STAT_2_Sept_10_count_9min_c3.jpg` | T2-STAT2 | benthic_organism_unconfirmed | mummichog=0.97; winter_flounder=0.01; cunner=0.01 |
| `T2_STAT_3_Sept_9_count_25min30sec_c0.jpg` | T2-STAT3 | benthic_organism_unconfirmed | mummichog=0.98; rock_gunnel=0.01; atlantic_rock_crab=0.01 |
| `T2_STAT_3_Sept_9_count_28min_c0.jpg` | T2-STAT3 | benthic_organism_unconfirmed | mummichog=0.72; winter_flounder=0.11; threespine_stickleback=0.11 |
| `T3-STAT_3_Sept_9__count__26min_c0.jpg` | T3-STAT3 | benthic_organism_unconfirmed | european_green_crab=0.29; winter_flounder=0.26; sand_shrimp=0.12 |
| `T3-STAT_3_Sept_9__count__27min12sec_c0.jpg` | T3-STAT3 | benthic_organism_unconfirmed | threespine_stickleback=0.88; mummichog=0.11; cunner=0.00 |
| `T3-STAT_3_Sept_9__count__27min50sec_c0.jpg` | T3-STAT3 | benthic_organism_unconfirmed | mummichog=0.97; atlantic_silverside=0.01; threespine_stickleback=0.01 |
| `T3-STAT_3_Sept_9__count__30min_c0.jpg` | T3-STAT3 | benthic_organism_unconfirmed | mummichog=0.98; cunner=0.01; threespine_stickleback=0.01 |
| `T3-STAT_3_Sept_9__count__31min_c0.jpg` | T3-STAT3 | benthic_organism_unconfirmed | mummichog=0.97; threespine_stickleback=0.02; rock_gunnel=0.01 |
| `T3-STAT_3_Sept_9__count__32min_c0.jpg` | T3-STAT3 | benthic_organism_unconfirmed | mummichog=0.98; threespine_stickleback=0.01; grubby_sculpin=0.00 |
| `T3-STAT_3_Sept_9__count__32min_c1.jpg` | T3-STAT3 | benthic_organism_unconfirmed | threespine_stickleback=0.58; mummichog=0.33; atlantic_silverside=0.08 |
| `T3-STAT_3_Sept_9__count__33min_c0.jpg` | T3-STAT3 | benthic_organism_unconfirmed | winter_flounder=0.93; mummichog=0.03; european_green_crab=0.01 |
| `T3-STAT_3_Sept_9__count__34min_c0.jpg` | T3-STAT3 | benthic_organism_unconfirmed | mummichog=0.61; threespine_stickleback=0.37; atlantic_silverside=0.02 |
| `T3-STAT_3_Sept_9__count__35min_c0.jpg` | T3-STAT3 | benthic_organism_unconfirmed | threespine_stickleback=0.85; mummichog=0.14; cunner=0.01 |

## Key requirements from the protocol (Coastal Action DRAFT FFH Video Analysis Protocol)

1. **Stationary unbaited remote underwater video (RUV)**: species richness and relative abundance via **MeanCount**.
2. **Analysis window:** analyse a **15-minute segment**. Discard the first and last minute (sediment settling). Up to 4 min may be removed if disturbance persists; reviewer comments allow up to 10–15 min for videos longer than 25–30 min. Record the start and end times used.
3. **Systematic subsampling:** one frame every **60 s** → **15 frames**. "One second = one analysed frame." A fish visible within about 0.5 s (no more than 1 s) either side of the subsample point may be counted. Watch about 5 s before and after for context.
4. **MeanCount** = mean number of fish across the subsample frames. MaxN appears only in a reviewer comment ("there will only be 1 MaxN per video").
5. **Count only what is certain.** An organism must show at least two of: fish shape, anatomical features, colouration/flash of scales, swimming behaviour. Uncertain movement (algae, sediment, bubbles) is not counted, even if that underestimates.
6. Record per subsample: total fish count, invertebrate count, number of species, individuals per species, and an **"Unknown/Unable to ID due to visibility"** column. Identify species to the lowest practicable taxonomic level.
7. **Visibility:** 2–3 observers assign a category (<0.5 m, 0.5–1.0 m, 1.0–1.5 m, >1.5 m) using the visibility pole, and note changes ≥0.5 m at each subsample.
8. Optional: juvenile presence (1/0) per video.
9. **QC:** blind double counts on a random 10% of frames (6–12 per video). Agreement must be ≥95%, with less than 6% difference between counters.
10. An older draft section (left in the PDF) describes 12-min windows with 60 points; the current procedure (15 min, 15 frames) is used.
