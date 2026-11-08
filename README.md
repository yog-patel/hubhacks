# BlueSight AI

**See more. Disturb less. Protect better.**

BlueSight turns underwater survey video from Nova Scotia waters into fish counts and flags fish that don't match any known species, with a biologist reviewing anything uncertain. It was built for Coastal Action (RBC HubHacks, Problem Statement 2).

```
Upload video → Enhance frames → Detect and track → Identify species
     ├─ match    → Count known species → Survey report
     └─ no match → Flag unfamiliar fish → Biologist review → Species registry
                                                               └─ feeds back into Identify species
```

**Everything runs on this computer.** No hosted AI APIs, no telemetry. Model weights are downloaded once into `models/hf/`; after that, importing `bluesight` switches every model library to offline mode, and a network guard counts and blocks outbound connections during each analysis. The evidence (offline test, code scan, model hashes, energy) is in **[LOCAL_VERIFICATION.md](LOCAL_VERIFICATION.md)** and on the app's **Model & privacy** page.

## Quick start (field staff)

**Double-click `Start BlueSight (Windows).bat` or `Start BlueSight (Mac).command`.** The first start installs everything
(internet needed once, 10–20 min; NVIDIA GPUs are picked up automatically). After that the app opens in your browser
in under a minute and works offline. The one-page guide for staff is **[QUICKSTART.md](QUICKSTART.md)**.

## Quick start (developers)

```bash
# 1. Python 3.11 environment (uv was used because the machine had no Python)
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements.txt -e .

# 2. One-time model download (BioCLIP, OWLv2, DINOv2 -> models/hf/). The ONLY network step.
BLUESIGHT_ALLOW_DOWNLOADS=1 HF_HOME=models/hf .venv/bin/python -c "import open_clip; open_clip.create_model_and_transforms('hf-hub:imageomics/bioclip'); \
from transformers import AutoModel, Owlv2ForObjectDetection, Owlv2Processor; \
Owlv2Processor.from_pretrained('google/owlv2-base-patch16-ensemble'); Owlv2ForObjectDetection.from_pretrained('google/owlv2-base-patch16-ensemble'); \
AutoModel.from_pretrained('facebook/dinov2-small')"

# 3. Build the working data layout from "HubHacks Resources/" (originals are never modified)
.venv/bin/python scripts/prepare_resources.py
.venv/bin/python scripts/extract_ground_truth.py
.venv/bin/python scripts/build_registry.py

# 4. Run the app (opens http://localhost:8501; reachable from this computer only)
.venv/bin/streamlit run app/streamlit_app.py
```

## The app

| Page | What it's for |
|---|---|
| **How it works** | Plain-language guide: the four steps and every term on screen (MeanCount, MaxN, image clarity, watch list, blind count). |
| **Count check** | Subsamples where the motion detector and the **trained fish counter** disagree are listed first (⚑), with an optional heatmap of where the counter sees fish. The 15 protocol subsample frames with the AI's numbered marks. Remove wrong marks (one by one or a whole category such as "too murky") and add missed fish; or **blind count** for the protocol's QC (agreement vs the 95 % target, < 6 % difference per frame). Checked counts replace the AI's in the report; corrections export as training data (`outputs/training_labels/`). |
| **Analyze** | Drag and drop or pick a video, check water clarity with a before/after slider and the visibility score, choose the window (protocol 15 min, custom, whole video), and run. The five steps (Enhance → Detect → Track → Identify → Count) light up as they run. Shows "Running locally on <device>". |
| **Results** | **Survey details** (water temperature, pole visibility, juveniles, observer; typed in, never fetched), **watch-list / temperature-range / new-arrival alerts**, **Excel report in the protocol layout**, headline cards (fish counted, species found, items to review, footage with low visibility), counts by species (MaxN, MeanCount, confidence), fish-and-visibility timeline, original vs enhanced frame, annotated video, CSV/JSON downloads. |
| **Review queue** | One item at a time, most unfamiliar first: evidence clip, best crops, top-3 matches as bars with the thresholds marked, visibility badge. Species names are picked from the Nova Scotia list (or typed). **New species** (`N`), **Existing species** (`E`), **Reject: not a fish** (`X`), skip (`J`), back (`K`). Progress counter. |
| **Species registry** | Gallery of species cards, plus the editable **watch list** (invasive/unexpected species, optional usual temperature range) and the **expected Nova Scotia species list**. |
| **Model & privacy** | Each model's name, version, licence and local path; device; offline mode; telemetry off; last run's runtime and energy estimate; "0 external network calls during last run" from the pipeline's network guard. |

Type your name in the sidebar before reviewing; it's saved with every decision (or open the app with `?reviewer=Your+Name`).

## Command line

| Command | What it does |
|---|---|
| `python scripts/run_video.py "data/videos/T1-STAT2 411.MP4"` | Analyse the protocol window (skip the first minute, analyse 15 min). Writes `outputs/runs/<video>/<start>-<end>s/{report.json, report.csv, species_summary.csv, annotated.mp4}` and evidence packages in `outputs/flags/<flag_id>/` |
| `... --start 1290 --duration 60` / `--full` | Custom window (seconds) / whole video minus the first and last minute |
| `python scripts/preview_enhance.py <video> --times 420,1320` | Before/after enhancement images with visibility scores → `outputs/enhance_preview/` |
| `python scripts/fetch_reference_photos.py` | One-time, optional: openly licensed field-guide photos (iNaturalist CC0/CC-BY/CC-BY-SA; credits in `data/reference_web/attribution.csv`). Display only, never used for labels (EVALUATION.md v5) |
| `python scripts/setup_models.py` | One-time model download (skips models already in `models/hf/`; copy that folder to skip it entirely) |
| `python scripts/density_data.py` · `train_density.py --variant raw --scale 2.0 --motion --final` | Rebuild the dot-labelled training set and retrain/evaluate the fish counter (leave-one-frame-out; results in EVALUATION.md v4) |
| `python scripts/build_registry.py` | Rebuild species prototypes from `data/reference_images/` and `outputs/registry/` (held-out species excluded) |
| `python scripts/evaluate.py [--tune]` | Measure and write `EVALUATION.md`; `--tune` re-tunes T_KNOWN, T_UNKNOWN, V_MIN and saves them to `config.yaml` |
| `python scripts/experiments.py <name>` | Phase-2 model experiments (enhance, detector, owl, tracker, crops, prototypes, video_id, fps) → `outputs/eval/experiments.json` |
| `python -m pytest` | Unit tests + the offline test (`tests/test_offline.py` runs the full pipeline with the internet blocked) |
| `python scripts/model_inventory.py` · `scan_network.py` · `local_verification.py` | Model hashes · code scan for network use · regenerate LOCAL_VERIFICATION.md |
| `python scripts/screenshot_app.py --out outputs/screenshots/after` | Full-page screenshots of every app page (dev tool; needs `pip install -r requirements-dev.txt && playwright install chromium`) |
| `python scripts/make_mock_data.py` | Mock outputs for UI work without models (pick "Mock data" in the sidebar) |
| `python scripts/reset_demo.py` / `rehearse_demo.py` | Reset approvals and reviews and re-run the demo window / automated demo rehearsal (see DEMO.md) |

Re-runs are cheap. Detections, tracks, crops and embeddings are cached per video window in `outputs/cache/`, so after a registry change only identification, counting, evidence and the report are redone. Each run's runtime goes to `outputs/logs/runtime.csv`, its energy estimate and network-guard count to `outputs/logs/energy.csv`, and all logs to `outputs/logs/bluesight.log`.

## Adding new videos

Put the video (`.mp4 .mov .avi .mkv .m4v`) anywhere in the project folder (for example `HubHacks Resources/`) and run `scripts/prepare_resources.py`; it symlinks the video into `data/videos/`. Or drop it on the app's **Analyze** page (up to 8 GB; it's copied to `outputs/uploads/` on this computer). Site is read from names like `T1-STAT2`; the date is set in `config.yaml → survey`.

## Adding species

* **In the app (normal route):** an unfamiliar fish appears in the **Review queue**. Type the species name and click **New species**. Its crops are saved to `outputs/registry/<species>/` and its prototype(s) are rebuilt immediately, with no retraining. **Existing species** adds the crops to that species. **Reject** removes the item from counts, and similar items are auto-rejected on later runs.
* **From labelled photos:** put images in `data/reference_images/<species_name>/` and run `scripts/build_registry.py`. Species in `config.yaml → held_out_species` are never loaded from there.

## Configuration

`config.yaml` holds every path, threshold, sampling rate and model name. Key settings:
`sampling.fps`, `protocol.*` (Coastal Action windows), `detector.name` (`motion` | `owlv2`) and `detector.motion.*`, `tracker.*`, `identify.T_KNOWN / T_UNKNOWN / V_MIN / MIN_FRAMES / MIN_AREA / prototypes_per_species`, `runtime.network_guard` (`block` | `count`), `energy.*`, and `held_out_species`. App look and privacy settings are in `.streamlit/config.toml`.

## Project layout

```
src/bluesight/   io_video, enhance, detect, track, embed, registry, identify, count, evidence, pipeline, db, config, logs,
                 netguard (outbound-connection guard), energy (offline CO2 estimate),
                 countcheck (assisted + blind counts, QC agreement, training-label export),
                 survey (survey details, watch list, alerts, image clarity), export (Excel workbook)
app/streamlit_app.py, app/ui/   theme (design tokens + components), page_* (one module per page)
scripts/         prepare_resources, extract_ground_truth, build_registry, run_video, evaluate, experiments, preview_enhance,
                 model_inventory, scan_network, local_verification, screenshot_app, make_mock_data, reset_demo, rehearse_demo
tests/           pytest (identify, count, registry, v2 units, offline)
outputs/         everything generated (bluesight.db, runs/, flags/, registry/, cache/, logs/, eval/, screenshots/)
```

Project documents: [QUICKSTART.md](QUICKSTART.md) · [RESOURCES.md](RESOURCES.md) · [DECISIONS.md](DECISIONS.md) · [EVALUATION.md](EVALUATION.md) · [DEMO.md](DEMO.md) · [AUDIT.md](AUDIT.md) · [LOCAL_VERIFICATION.md](LOCAL_VERIFICATION.md)

## Models and licences

| Component | Model / library | Licence |
|---|---|---|
| Embedder (default) | BioCLIP `imageomics/bioclip` via `open_clip` | MIT (weights and code) |
| Embedder (fallback) and fish-counter backbone | DINOv2-small `facebook/dinov2-small` | Apache-2.0 |
| Field-guide photos | iNaturalist observers (credited per photo in `data/reference_web/attribution.csv`) | CC0 / CC-BY / CC-BY-SA |
| Fish counter head | trained here on the biologists' tally dots (`models/density/head.pt`, 2 MB; `scripts/train_density.py`) | project code |
| Detector (optional) | OWLv2 `google/owlv2-base-patch16-ensemble` (and `-large-patch14`, experiments only) via `transformers` | Apache-2.0 |
| Detector (default) | BlueSight motion detector (OpenCV + PyTorch median) | project code |
| Tracker | ByteTrack via `supervision` 0.26.1 | MIT |
| Energy estimate | CodeCarbon `OfflineEmissionsTracker` | MIT |
| Excel export | openpyxl | MIT |
| App | Streamlit (Apache-2.0), Altair/Vega-Lite (BSD-3) | permissive |
| Video / maths | OpenCV (Apache-2.0), NumPy/SciPy/pandas (BSD), PyTorch (BSD-3) | permissive |
| Video encoding | PyAV (BSD-3) bundling FFmpeg (LGPL). Uses Apple's `h264_videotoolbox` hardware encoder | LGPL |
| Screenshots (dev only) | Playwright (Apache-2.0) | permissive |

**GPL note:** PyAV's bundled FFmpeg also contains **libx264 (GPL-2.0)**. BlueSight uses it only as a fallback encoder when the hardware encoder is unavailable. If you redistribute BlueSight binaries, either keep the hardware encoder or ship an FFmpeg build without libx264. No AGPL dependencies are used.

## Energy footprint

Small models only (BioCLIP ViT-B/16; a motion detector without a neural network). Frames are sampled at 2 fps, detection runs at 1080p instead of 4K, and results are cached so re-runs cost seconds. The GPU is used when available (CUDA or Apple MPS), otherwise the CPU. Every run logs its runtime, and an energy/CO2 estimate from CodeCarbon's offline tracker (Nova Scotia grid). On Apple Silicon that estimate covers CPU and RAM but not the GPU, so it is a lower bound. Measured numbers are in EVALUATION.md and LOCAL_VERIFICATION.md.

## Offline

After the one-time model download, BlueSight makes no network calls. `bluesight/__init__.py` sets `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` and `HF_HUB_DISABLE_TELEMETRY=1` before any model library loads (set `BLUESIGHT_ALLOW_DOWNLOADS=1` only for the download). The app binds to `localhost` and sends no usage statistics. To check it yourself, turn Wi-Fi off and run the app, or run `python -m pytest tests/test_offline.py -s`. Details: [LOCAL_VERIFICATION.md](LOCAL_VERIFICATION.md).
