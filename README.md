# BlueSight AI

**See more. Disturb less. Protect better.**

BlueSight turns underwater survey video from Nova Scotia waters into fish counts and flags fish that don't match any known species, with a biologist reviewing anything uncertain. It was built for Coastal Action (RBC HubHacks, Problem Statement 2).

```
Upload video → Enhance frames → Detect and track → Identify species
     ├─ match    → Count known species → Survey report
     └─ no match → Flag unfamiliar fish → Biologist review → Species registry
                                                               └─ feeds back into Identify species
```

**Everything runs offline on this device.** No hosted AI APIs are used. Model weights are downloaded once into `models/hf/`, and after that `HF_HUB_OFFLINE=1` is set automatically by `config.py`.

## Quick start

```bash
# 1. Python 3.11 environment (uv used here because the machine had no Python)
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements.txt -e .

# 2. One-time model download (BioCLIP, OWLv2, DINOv2 -> models/hf/); the only network step
HF_HOME=models/hf .venv/bin/python -c "import open_clip; open_clip.create_model_and_transforms('hf-hub:imageomics/bioclip'); \
from transformers import AutoModel, Owlv2ForObjectDetection, Owlv2Processor; \
Owlv2Processor.from_pretrained('google/owlv2-base-patch16-ensemble'); Owlv2ForObjectDetection.from_pretrained('google/owlv2-base-patch16-ensemble'); \
AutoModel.from_pretrained('facebook/dinov2-small')"

# 3. Build the working data layout from "HubHacks Resources/" (originals are never modified)
.venv/bin/python scripts/prepare_resources.py
.venv/bin/python scripts/extract_ground_truth.py
.venv/bin/python scripts/build_registry.py

# 4. Run the app
.venv/bin/streamlit run app/streamlit_app.py
```

## Command line

| Command | What it does |
|---|---|
| `python scripts/run_video.py "data/videos/T1-STAT2 411.MP4"` | Analyse the protocol window (skip the first minute, analyse 15 min). Writes `outputs/runs/<video>/<start>-<end>s/{report.json, report.csv, species_summary.csv, annotated.mp4}` and evidence packages in `outputs/flags/<flag_id>/` |
| `... --start 1290 --duration 60` | Custom window (seconds) |
| `... --full` | Whole video minus the first and last minute |
| `python scripts/preview_enhance.py <video> --times 420,1320` | Before/after enhancement images with visibility scores → `outputs/enhance_preview/` |
| `python scripts/build_registry.py` | Rebuild species prototypes from `data/reference_images/` and `outputs/registry/` (held-out species excluded) |
| `python scripts/evaluate.py [--tune]` | Measure and write `EVALUATION.md`. `--tune` tunes T_KNOWN, T_UNKNOWN and V_MIN and saves them to `config.yaml` |
| `python -m pytest` | Unit tests (identify, count, registry; synthetic embeddings) |
| `python scripts/make_mock_data.py` | Mock outputs for UI work without models (pick "Mock data" in the sidebar) |
| `python scripts/reset_demo.py` | Clear app approvals/reviews and re-run the demo window (see DEMO.md) |
| `python scripts/rehearse_demo.py` | Automated demo rehearsal (flag → approve → re-run); records results for EVALUATION.md, then resets |

Re-runs are cheap. Detections, tracks, crops and embeddings are cached per video window in `outputs/cache/`, so after a registry change only identification, counting, evidence and the report are redone. Each run's cost is logged in `outputs/logs/runtime.csv`, and all logs go to `outputs/logs/bluesight.log`.

## Adding new videos

Put the video (`.mp4 .mov .avi .mkv .m4v`) anywhere in the project folder (for example `HubHacks Resources/`) and run `scripts/prepare_resources.py`; it symlinks the video into `data/videos/`. Or upload it on the app's **Analyze** page. Site is read from names like `T1-STAT2`. The date is set in `config.yaml → survey`.

## Adding species

* **In the app (normal route):** an unfamiliar fish appears in the **Review queue**. Enter your name in the sidebar, type the species name, and click **New species**. Its crops are saved to `outputs/registry/<species>/` and its prototype is built immediately, with no retraining. **Existing species** adds the crops to that species. **Reject / not a fish** removes the item from future counts.
* **From labelled photos:** put images in `data/reference_images/<species_name>/` and run `scripts/build_registry.py`. Species listed in `config.yaml → held_out_species` are never loaded from there.

## Configuration

`config.yaml` holds every path, threshold, sampling rate and model name. Key settings:
`sampling.fps` (2), `protocol.*` (Coastal Action windows), `detector.name` (`motion` | `owlv2`), `identify.T_KNOWN / T_UNKNOWN / V_MIN / MIN_FRAMES / MIN_AREA`, and `held_out_species`.

## Project layout

```
src/bluesight/   io_video, enhance, detect, track, embed, registry, identify, count, evidence, pipeline, db, config, logs
app/streamlit_app.py
scripts/         prepare_resources, extract_ground_truth, build_registry, run_video, evaluate, preview_enhance, make_mock_data
tests/           pytest (identify, count, registry)
data/            symlinks/derived files (manifest.csv, proposed_labels.csv, ground_truth/)
outputs/         everything generated (bluesight.db, runs/, flags/, registry/, cache/, logs/)
```

Project documents: [RESOURCES.md](RESOURCES.md) · [DECISIONS.md](DECISIONS.md) · [EVALUATION.md](EVALUATION.md) · [DEMO.md](DEMO.md)

## Models and licences

| Component | Model / library | Licence |
|---|---|---|
| Embedder (default) | BioCLIP `imageomics/bioclip` via `open_clip` | MIT (weights and code) |
| Embedder (fallback) | DINOv2-small `facebook/dinov2-small` | Apache-2.0 |
| Detector (optional) | OWLv2 `google/owlv2-base-patch16-ensemble` via `transformers` | Apache-2.0 |
| Detector (default) | BlueSight motion detector (OpenCV + PyTorch median) | project code |
| Tracker | ByteTrack via `supervision` 0.26.1 | MIT |
| Video / maths | OpenCV (Apache-2.0), NumPy/SciPy/pandas (BSD), PyTorch (BSD-3), Streamlit (Apache-2.0) | permissive |
| Video encoding | PyAV (BSD-3) bundling FFmpeg (LGPL). Uses Apple's `h264_videotoolbox` hardware encoder | LGPL |

**GPL note:** PyAV's bundled FFmpeg also contains **libx264 (GPL-2.0)**. BlueSight uses it only as a fallback encoder when the hardware encoder is unavailable. If you redistribute BlueSight binaries, either keep the hardware encoder or ship an FFmpeg build without libx264. No AGPL dependencies are used.

## Energy footprint

Small models only (BioCLIP ViT-B/16, motion detector without a neural network). Frames are sampled at 2 fps, detection runs at 1080p instead of 4K, and results are cached so re-runs cost seconds. The GPU is used when available (CUDA or Apple MPS), otherwise the CPU. Runtime per video is logged (`outputs/logs/runtime.csv`) and shown in the app. Measured numbers are in EVALUATION.md.

## Offline

After the one-time model download, BlueSight makes no network calls. `config.yaml → runtime.offline: true` sets `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` before any model loads. To check, disconnect Wi-Fi and run the app; analysis, review and registry updates all work.
