# AquaLens AI — project guide for Claude Code

See more. Disturb less. Protect better.

AquaLens turns underwater survey video from Nova Scotia waters into fish counts, species IDs and flags for unfamiliar species, with a biologist reviewing anything uncertain. Built for Coastal Action (RBC HubHacks, Problem Statement 2).

Work autonomously. Only stop to ask if something is truly blocking; otherwise make a sensible assumption, record it in `DECISIONS.md`, and keep going.

## Hard constraints (never break these)

- **All AI runs locally.** No hosted AI APIs of any kind (OpenAI, Anthropic, Google, Hugging Face Inference API, Roboflow cloud, etc.). Open-source weights may be downloaded once; after that everything must work offline.
- **Open-source models only**, preferring permissive licences (MIT, Apache-2.0, BSD). Flag any AGPL/GPL dependency in the README.
- **Low energy footprint.** Coastal Action restricts AI for environmental reasons. Use small models, sample frames (default 2 fps, configurable), cache results, use GPU (CUDA or Apple MPS) when available and CPU otherwise, and log runtime per video.
- **Scientists stay in charge.** The system never adds a species without human approval in the app.
- **The provided resources are read-only.** The videos, images and instructions the team added to this project folder are originals: never modify, rename, move or delete them. Everything generated goes to `outputs/`.

## Resources

The team has placed the videos, photos and instructions **inside this project folder**, either loose in the root or in a subfolder (for example `HubHacks Resources/`). Find them by file type:

- videos: `.mp4 .mov .avi .mkv .m4v`
- images: `.jpg .jpeg .png .webp .tif .tiff .heic`
- instructions: `.pdf .docx .doc .txt .md .pptx .xlsx .csv`

Leave the originals exactly where they are. Build the working layout below with **symlinks** pointing to the originals (copy only if symlinks fail), so the code always reads from `data/` and `docs/`:

```
data/
  videos/                  # survey footage
  reference_images/
    <species_name>/        # images per known species; folder name = species label
  held_out/
    <species_name>/        # species deliberately kept OUT of the registry, for testing the unfamiliar-fish flag
  ground_truth/            # manual counts, if provided
  unsorted/                # images whose species can't be inferred
docs/
  instructions/            # Coastal Action docs, methodology, species list
```

### Phase 0: understand the resources before building anything

1. Recursively list this project folder (ignore `.git/`, `.venv/`, `outputs/`, `data/`, `src/`, `app/`, `scripts/`, `tests/`) to find every video, image and instruction file. Read every instruction or document file.
2. Write `RESOURCES.md`: where each resource was found, videos (count, length, resolution), images (organisation, species covered, count per species), any labels or annotations (e.g. bounding boxes, CSVs of counts), and the key requirements from the instructions. Also write `data/manifest.csv` mapping each original file path to its role (video / reference image + species / held-out / instruction / unsorted).
3. If the instructions define counting methodology, the species list or survey protocol, **they override the defaults in this file**. Record each override in `DECISIONS.md`.
4. Sort images by species using folder or file names. If that's impossible, put them in `data/unsorted/` and note it.
5. Choose the 2 species with the most images as **held-out species** and record them in `DECISIONS.md`.

## Tech stack

- Python 3.11, virtualenv, `requirements.txt`, git
- OpenCV + NumPy: video I/O and frame enhancement
- **Detector** (behind a `Detector` interface):
  - Default: a local open-vocabulary detector (OWLv2 or Grounding DINO via Hugging Face `transformers`) prompted with "fish". No training needed.
  - If the resources include bounding-box labels, also fine-tune a small open detector and keep whichever performs better in evaluation.
- **Tracker:** ByteTrack via `supervision`
- **Embedder** (behind an `Embedder` interface): BioCLIP via `open_clip`; fall back to DINOv2 if it fails
- **Storage:** SQLite at `outputs/bluesight.db` (detections, tracks, flags, registry)
- **App:** Streamlit
- **Config:** `config.yaml` holds all paths, thresholds, fps and model names. Nothing hardcoded.

## Pipeline (must match this flow)

```
Upload video → Enhance frames → Detect and track → Identify species
     ├─ match    → Count known species → Survey report
     └─ no match → Flag unfamiliar fish → Biologist review → Species registry
                                                               └─ feeds back into Identify species
```

### Module layout

```
src/bluesight/
  io_video.py     # read video, sample frames at config fps, write clips
  enhance.py      # enhance_frame(); visibility_score() -> 0..1
  detect.py       # Detector interface + implementations
  track.py        # ByteTrack wrapper
  embed.py        # Embedder interface + BioCLIP / DINOv2
  registry.py     # prototypes, add/approve species, persist
  identify.py     # classify_track() -> status, top-3 matches
  count.py        # maxn(), meancount()
  evidence.py     # evidence package per flag
  pipeline.py     # run_video(path) -> report
  db.py           # SQLite access
app/streamlit_app.py
scripts/build_registry.py, scripts/run_video.py, scripts/evaluate.py, scripts/preview_enhance.py
tests/
outputs/
```

### Step details

1. **Enhance frames:** CLAHE + simple underwater colour correction. Compute a per-frame visibility score (0–1) from contrast, sharpness and haze. `scripts/preview_enhance.py` saves before/after images.
2. **Detect and track:** detect fish on sampled frames; ByteTrack assigns IDs so a fish is never double counted.
3. **Registry:** one prototype per known species, the mean embedding of its reference images. Held-out species are excluded.
4. **Identify species (per TRACK, not per frame):**
   1. Take the 3–5 best crops (sharpest, largest, least occluded), embed and average them.
   2. Compute cosine similarity to every prototype and keep the top 3.
   3. Decide:

   ```python
   if visibility < V_MIN or track_len < MIN_FRAMES or box_area < MIN_AREA:
       status = "unidentified_low_visibility"   # couldn't see it; NOT a new-species flag
   elif best >= T_KNOWN:
       status = "known"                          # counted automatically
   elif best >= T_UNKNOWN:
       status = "uncertain"                      # review queue, shown as "probably X?"
   else:
       status = "unfamiliar"                     # flagged as possibly new
   ```

   The visibility gate is essential: murky blobs must never be flagged as new species.

   4. Merge flagged tracks in one video whose embeddings are very similar into a single review item.
5. **Count known species:**
   - **MaxN:** the most individuals of a species visible in any single sampled frame.
   - **MeanCount:** the mean per-frame count of a species across sampled frames.
   - Always report the fraction of footage below the visibility threshold, so poor visibility is never reported as zero fish.
   - Follow Coastal Action's definitions in `docs/instructions/` if they differ.
6. **Evidence package:** for each unfamiliar or uncertain item, save to `outputs/flags/<flag_id>/`:
   - `clip.mp4`: the track ±2 s, fish boxed
   - `crop_1.jpg … crop_5.jpg`
   - `flag.json`:

   ```json
   {
     "flag_id": "...",
     "video_file": "...", "site": "...", "date": "...",
     "start_time_s": 0.0, "end_time_s": 0.0,
     "status": "unfamiliar",
     "top3": [{"species": "...", "similarity": 0.0}],
     "visibility": 0.0, "track_frames": 0,
     "model_versions": {"detector": "...", "embedder": "..."},
     "thresholds": {"T_KNOWN": 0.0, "T_UNKNOWN": 0.0, "V_MIN": 0.0},
     "review": {"decision": null, "species": null, "reviewer": null, "timestamp": null}
   }
   ```
7. **Survey report:** `scripts/run_video.py <video>` outputs an annotated video, `report.json`, `report.csv` and the flags to `outputs/runs/<video_name>/`. Cache detections and embeddings per video so re-runs are fast and cheap.

## Streamlit app

1. **Analyze:** pick or upload a video; show progress, runtime and "ran on this device."
2. **Results:** species table (MaxN, MeanCount, confidence), visibility summary, annotated video, CSV download.
3. **Review queue:** for each item, the clip, crops, top-3 matches and visibility. Buttons: *New species* (enter name), *Existing species* (choose one), *Reject / not a fish*. Most clearly unfamiliar items first.
4. **Species registry:** species list, example images, date added, approved by.

Approving a new species saves its crops as reference images under `outputs/registry/<species>/` and rebuilds that prototype immediately. No retraining.

Run with: `streamlit run app/streamlit_app.py`

## Build order

0. Understand the resources (Phase 0 above)
1. Project setup: venv, requirements, config, README, git init
2. Enhancement + visibility score
3. Streamlit app on **mock data**, so UI work isn't blocked by the models
4. Detection + tracking on one short video, saving an annotated output
5. Registry, embeddings, identification
6. Counting + survey report
7. Evidence packages + review queue wired to real flags; approval updates the registry
8. Tests + evaluation + threshold tuning
9. Full run on every video + demo rehearsal

Get each step working end to end on one short video before scaling up. Commit to git after each step.

## Tests and evaluation

- pytest unit tests for `identify`, `count` and `registry` using synthetic embeddings. They must pass.
- `scripts/evaluate.py` writes `EVALUATION.md` with **measured numbers only**:
  - processing time per minute of video, and the hardware used
  - count accuracy against any manual counts provided
  - unfamiliar-fish flag: % of held-out species flagged vs mislabelled as known; false-alarm rate on known species
  - estimated reviewer time (review items × 10 s) vs video length
- Tune `T_KNOWN`, `T_UNKNOWN` and `V_MIN` on the held-out species, save them to `config.yaml`, and record the before and after values in `EVALUATION.md`.

## Demo (must work flawlessly)

1. Analyse a murky clip and show the enhancement and visibility score.
2. Show counts per species with confidence.
3. A held-out species is **flagged as unfamiliar instead of mislabelled**.
4. Approve it in the review queue and show it in the registry.
5. Re-run the clip and show the new species is recognised.
6. Show the runtime and that everything ran offline.

Write `DEMO.md` with the exact commands and clicks, and which video and timestamp to use.

## Project documents to maintain

- `RESOURCES.md`: what resources were provided and where they are
- `DECISIONS.md`: assumptions, overrides from the instructions, held-out species
- `EVALUATION.md`: measured results and threshold tuning
- `DEMO.md`: demo script
- `README.md`: setup, adding videos and species, running the app, model licences, offline note

## Coding rules

- Type hints and docstrings on public functions; small, testable modules.
- No silent failures; log to `outputs/logs/`.
- Never invent results. If something works poorly, say so honestly in `EVALUATION.md`.
- When finished, summarise what works, the measured numbers, known weaknesses, and the command to start the app.
