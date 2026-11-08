# AUDIT (v1, before the v2 work)

Audit of AquaLens v1 (commit `d31133e`) done on 2026-11-07, before any v2 change. Screenshots of every v1 page are in
`outputs/screenshots/before/`. Baseline numbers come from `scripts/evaluate.py` re-run on this machine (Apple M5, MPS);
they reproduce v1's EVALUATION.md exactly (see EVALUATION.md → BASELINE).

Setup note: this folder was a fresh clone without the resources, venv, models or caches. The original working copy is in
`~/Documents/hubhacks` (same commit). That copy was left untouched. `HubHacks Resources` here is a symlink to its
read-only originals, and models and detection caches were copied (DECISIONS.md D17).

## 1. Tests and app

* `pytest`: **19 passed** (identify, count, registry).
* The app starts and all four pages render with real data. No crashes.

## 2. UI problems

| # | Page | Problem | Severity |
|---|---|---|---|
| U1 | all | Streamlit's default **red** primary colour. "Analyze" (a normal action) looks like a destructive or error button. No palette, type scale or spacing system. | major |
| U2 | all | Navigation is a "Page" radio, so pages have no URLs. Mixed into the sidebar with "Data" and the reviewer name, with no grouping. | minor |
| U3 | all | Status is shown with 🔴 / 🟡 emoji only. Colour is the only difference between unfamiliar and uncertain (WCAG 1.4.1). | major |
| U4 | Analyze | **Upload limit is Streamlit's default 200 MB.** The real survey video is 2.3 GB, so drag-and-drop upload of real footage fails. | **critical for real use** |
| U5 | Analyze | No pipeline steps: one progress bar with internal messages ("detect+track t=1300s (95 detections)"). | major |
| U6 | Analyze | Original/enhanced are two small images; the difference is hard to see. Visibility is a bare progress bar. | minor |
| U7 | Analyze | Results are dumped below the Run button, duplicating the Results page. | minor |
| U8 | Results | No headline cards for the four questions a biologist asks: how many fish, which species, what needs review, how much footage was too murky. "Runtime" takes a card slot instead. | major |
| U9 | Results | Species table shows raw keys (`small_schooling_fish`, `Unconfirmed: probably small_schooling_fish?`), `None` confidence, and columns that run off the right edge. | major |
| U10 | Results | Visibility chart: x-axis in raw seconds, no axis titles, V_MIN drawn as a second "series" in the legend. Fish detections over time are not shown at all. | major |
| U11 | Results | Box colours in the annotated video are explained by colour words only. | minor |
| U12 | Review | **All 28 items render at once** as one long wall (the screenshot is ~9000 px tall), each with its own video. It is slow and there is no sense of progress ("how many are left?"). | **critical for the demo** |
| U13 | Review | With no reviewer name every button is disabled, and the only explanation is a banner at the top, out of view. | major |
| U14 | Review | Small buttons (default height), no keyboard shortcuts, top-3 as generic progress bars without thresholds. | major |
| U15 | Review | Crops are tiled at mixed sizes and overflow their column. | minor |
| U16 | Registry | A raw database table is shown above the cards. No gallery layout, and no badge for species added through review. | major |
| U17 | all | Streamlit "Deploy" button visible (it links to Streamlit Community Cloud, which is off-message for an offline tool). | minor |
| U18 | all | Empty states are one-liners without a next step ("Nothing awaiting review."). | minor |

## 3. Model weaknesses (measured baseline)

| # | Area | Finding |
|---|---|---|
| M1 | Detection | Motion detector at 14:01: **P 0.44, R 0.33, F1 0.38** against 36 tally points. Count accuracy: 19 vs 36 (61.8 % diff) and 61 vs 102 (50.3 % diff). It under-detects dense, slow schools. |
| M2 | Detection | OWLv2 base finds **0** fish at 14:01 and 13 at 22:00 (of 102), at ~9 s per frame. Open-vocabulary detection doesn't work on these faint fish as configured. |
| M3 | False positives | Sunlight caustics and the swaying pole produce ~18–22 transient detections per frame (not counted, but they cost work) and some persistent "uncertain" review items. |
| M4 | Identification | Image level: known correct 76.1 %, **false alarms 23.9 %**, held-out mislabelled as known **10.3 %**. Only one fish class exists, built from screenshot crops of another station. |
| M5 | Identification | Murky haze resembles the pale reference crops; only the visibility gate prevents mislabelling (V_MIN 0.40). |
| M6 | Registry | A species approved from one track gets a loose single prototype. After approving the crab, 8 of 10 matches are sand patches (EVALUATION §5b). One mean prototype per species can't represent a varied species. |
| M7 | Cost | First-time processing: 62–69 s of compute per minute of 4K video. Decoding 4K HEVC and computing the per-pixel median dominate. Sampling rate (2 fps) has never been tested for a cheaper setting. |
| M8 | Tracking | ByteTrack parameters (buffer 4, matching 0.9, ×3 box expansion) were never tuned; fragmentation was never measured. |

## 4. Things that could break during the demo

| # | Risk | Mitigation in v2 |
|---|---|---|
| D1 | DEMO.md says `cd ~/Documents/hubhacks`, but the project is now on the Desktop. | DEMO.md rewritten with relative commands. |
| D2 | The review queue's item #1 must be the crab. That depends on DB state; earlier approvals or rejections reorder it. | `scripts/reset_demo.py` (unchanged) + a check in the rehearsal. |
| D3 | A demo window that isn't cached takes 2–3 min; any change to detector, tracker, sampling or enhance settings invalidates every cache. | Run `reset_demo.py` after the final config; warm cache before the demo. |
| D4 | Review page renders 28 videos at once (U12): slow on a laptop under demo pressure. | One-item-at-a-time review card. |
| D5 | Reviewer name empty → every button greyed out with an off-screen explanation (U13). | Name field prefilled from `?reviewer=`; inline warning. |
| D6 | macOS prints `Class AVFFrameReceiver is implemented in both … cv2 … av` (two bundled FFmpegs). Harmless so far, but noisy in the terminal. | Documented; PyAV is only imported for writing clips. |
| D7 | Upload of real footage fails (U4). | `server.maxUploadSize = 8192`. |

## 5. Places the code could reach the internet

Scanned: `src/`, `app/`, `scripts/`, `tests/`, `config.yaml`, `requirements.txt`, `pyproject.toml` for
`requests|httpx|urllib|urlopen|socket|http://|https://|openai|anthropic|api_key|hf_hub_download|from_pretrained|create_model_and_transforms|telemetry|gatherUsageStats|inference`.

| # | Where | What | Risk | v2 action |
|---|---|---|---|---|
| N1 | `embed.py` (`open_clip.create_model_and_transforms("hf-hub:…")`, `AutoModel.from_pretrained`), `detect.py` (`Owlv2*.from_pretrained`) | Hugging Face Hub downloads / update checks | Offline env vars are set only inside `load_config()`. `huggingface_hub` reads `HF_HUB_OFFLINE` **at import time**, so any code path that imports it before `load_config()` would be online. | Set `HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE`, `HF_HUB_DISABLE_TELEMETRY` in `bluesight/__init__.py` (before anything else loads), plus a runtime network guard. |
| N2 | Streamlit | `browser.gatherUsageStats` defaults to **true**: the browser sends usage stats to Streamlit. | Telemetry leaves the machine. | `.streamlit/config.toml`: `gatherUsageStats = false`. |
| N3 | Streamlit | `server.address` unset → listens on **all interfaces** (reachable from the local network). | Survey data visible to anyone on the same Wi-Fi. | `server.address = "localhost"`. |
| N4 | Streamlit | "Deploy" toolbar button links to Streamlit Cloud. | Only if clicked. | `client.toolbarMode = "minimal"` hides it. |
| N8 | Streamlit error box | Shows "Ask Google" / "Ask ChatGPT" buttons on any exception (default `showErrorLinks = "auto"` = on localhost). Clicking sends the error text to a hosted service. Found during v2 testing. | Only if clicked, but off-message | `client.showErrorLinks = false`. |
| N5 | none found | No `requests`/`httpx`/`urllib`, no API keys, no OpenAI/Anthropic/hosted-inference clients in project code. | — | — |
| N6 | `scripts/prepare_resources.py` | BioCLIP zero-shot label proposals | Same as N1 (already calls `load_config()` first). | Covered by N1. |
| N7 | Dev tools (new in v2) | Playwright (screenshots) and codecarbon | Playwright drives a local browser at localhost only. codecarbon's `OfflineEmissionsTracker` makes no calls; its online `EmissionsTracker` would (never used). | Listed in LOCAL_VERIFICATION.md. |
