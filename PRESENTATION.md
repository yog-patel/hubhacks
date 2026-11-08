# Presentation prep: speaker script, demo cues and judge Q&A

Deck: "BlueSight AI Pitch Deck" (15 slides; share it from the deck's Share menu, export PDF/PPTX there).
Demo: [DEMO.md](DEMO.md). Every number below is measured; sources are in [EVALUATION.md](EVALUATION.md).

## Before you present (checklist)
- [ ] Deck placeholders filled: team name (cover), team names (last slide), and the time-saved slide (`[~40]` / `[~10]` min) replaced with a stopwatch test or clearly said "estimate".
- [ ] PR #1 merged into `main`; repo made public by its owner (Settings → General → Change visibility).
- [ ] Demo laptop: `cd hubhacks && .venv/bin/python scripts/reset_demo.py`, then `.venv/bin/streamlit run app/streamlit_app.py`, open `http://localhost:8501/?reviewer=Demo+Biologist`. Turn Wi-Fi off.
- [ ] Backup: screen-record one full demo run (QuickTime → New Screen Recording) in case the live demo fails.
- [ ] Submitted at rbchubhacks.com/submit (deck + public repo link) well before 11:59 PM AT.

## Speaker script (about 7 minutes; demo inside)

| # | Slide | Time | Say (short version) |
|---|---|---|---|
| 1 | Cover | 0:20 | "We're [team]. BlueSight turns Coastal Action's underwater survey video into protocol-ready fish counts, on one computer, with no internet." |
| 2 | The problem | 0:30 | Murky water (70% of our test window was too murky to name species), fatigue at 0.25× speed, new species arriving, and **no hosted AI allowed**. |
| 3 | Their protocol | 0:30 | "We started from their protocol, not from a model": 15-min window, 15 frames every 60 s, two cues, 95% QC agreement. Output keeps their "Unable to ID" column. |
| 4 | Our solution | 0:15 | "The AI does the tedious watching. Biologists make every decision." |
| 5 | Four steps | 0:30 | Analyze → Check counts → Review → Excel. Under the hood: small open models, measured on their footage (the big open detector found 0 of 36 fish, so we didn't use it). |
| 6 | Check counts | 0:40 | **Live demo 1**: Check counts page, remove the "too murky" marks in one click (82 → 63), toggle the heatmap, point at ⚑ "check first". Say: the AI misses faint fish, so a person confirms 15 frames instead of watching 15 minutes; corrections become training data. |
| 7 | Unfamiliar species | 0:50 | **Live demo 2**: New animals item #1 is the green crab we hid from the system; best match 0.45, so "I don't know this". Pick *European green crab* → red watch-list banner. |
| 8 | Watch list | 0:25 | Invasive/unexpected species alerts, temperature-range check (staff enter the temperature, nothing fetched), "not on the expected list" = possible new arrival. |
| 9 | Results | 0:45 | Honest numbers: marks are 76% precise but recall 51%; AI-only counts undercount (80 vs 102). **Our counter trained on their own tally dots: 37.8 vs 36 on a frame it never saw** (motion detector: 14). Faintest frame still hard, so it's a second opinion that tells staff where to check. |
| 10 | Privacy | 0:30 | **Live demo 3** (optional): Privacy page, "0 external network calls". Open models only (MIT/Apache), no LLM, 1.2 GB of models vs a 12 GB GPU. |
| 11 | Built for staff | 0:20 | Double-click start, plain language, their spreadsheet, field guide. |
| 12 | Time saved | 0:20 | Say clearly whether the numbers are measured or estimated. |
| 13 | Scalable | 0:20 | Batch folders, new species without retraining, corrections become training data. |
| 14 | Roadmap | 0:20 | Pilot on their PC → retrain the counter on a season of corrections → trends dashboard. |
| 15 | Close | 0:15 | "Less time watching video, more time protecting the coast." Ask for the pilot. |

If time is short, skip demo 3 and slides 12–13; never skip slide 9 (judges reward honesty about accuracy).

## Judge Q&A (answers backed by measurements)

**How accurate is it?**
It depends on the job. Species flagging is strong: 90% of species we hid from the system were flagged instead of mislabelled, and the green crab came first in the queue. Counting is the weak spot for the AI alone: it finds about half the fish in murky water (precision 0.76, recall 0.51 at 14:01), and AI-only counts undercount (80 vs the biologists' 102). Our counter trained on the biologists' own dots matched 37.8 vs 36 on a frame it never saw, but undercounts the faintest frame. That's why counts are confirmed by a person in Check counts, which takes minutes instead of watching the whole window.

**Why is the AI worse on some frames?**
The fish are small, pale and translucent; at 22:00 they're nearly invisible in a still frame. We only had two hand-counted frames from the survey video to learn from. Every count a person checks in the app is saved as training data, so the counter improves with use (`scripts/train_density.py --final`).

**How did you test it without cheating?**
Leave-one-frame-out: for each of the five annotated frames, we trained without it and measured on it. Everything we tried and rejected is listed in EVALUATION.md (3× resolution, contrast enhancement, neighbouring frames, web photos).

**Does it really run offline?**
Yes. Models download once at setup; after that, a network guard blocks and counts every outbound connection during each analysis (0 in every run), an automated test runs the whole pipeline with the internet blocked, and the app only listens on the computer itself. No telemetry.

**Why not YOLO / ChatGPT / a big model?**
Ultralytics YOLO is AGPL, which clashes with an open, permissive build; hosted models like ChatGPT are ruled out by Coastal Action. We tried a large open detector (OWLv2): it found 0 of 36 fish and was 35× slower. Small, measured models fit their energy concerns: 3.1 Wh per 15-minute window (CPU+RAM estimate).

**Will it run on their hardware?**
Their planned PC has a 12 GB GPU; our models total 1.2 GB. A 15-minute 4K window takes 9.8 minutes on a laptop (Apple M4). The Windows launcher picks the NVIDIA build automatically. Honest note: we couldn't test on Windows during the hackathon.

**What about species identification?**
Coastal Action's material names only one species (the green crab), and the schooling fish were never identified. So the system knows "small schooling fish" and flags everything else for a biologist, who names it once; it's then recognised on the next run, no retraining. We tested 430 openly licensed web photos for automatic identification and rejected it: the real green crab looked most like a *blue crab* photo, which would have raised a false invasive-species alarm. The photos are now a field guide for reviewers only.

**What does visibility mean in your app?**
"Image clarity" (0–1) is how hard fish are to spot. It's not a distance: the whole 2 m pole is visible even at a score of 0.27, so staff still record the pole reading, as the protocol says.

**What does it cost Coastal Action?**
Free and open source, on hardware they're already buying. The main cost is staff time, and that's what it saves: a person checks 15 pre-marked frames and reviews flagged animals instead of watching every minute at quarter speed.

**What would you do with more time?**
Pilot it on a season of their videos, retrain the counter on staff corrections, read the visibility pole automatically, and build a trends dashboard (counts vs water temperature over years).
