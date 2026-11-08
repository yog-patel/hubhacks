# BlueSight AI: quick-start for field staff (one page)

**What it does:** counts fish in your underwater survey videos the way the Coastal Action protocol does, flags animals
it doesn't recognise, and alerts you to watch-list species such as European green crab. **Everything runs on this
computer. Your video never leaves it, and it works with the internet off.**

## Start it
- **Windows:** double-click **`Start BlueSight (Windows).bat`**. **Mac:** double-click **`Start BlueSight (Mac).command`**.
- The **first time** it sets itself up (needs internet once, 10–20 minutes). After that it opens in under a minute.
- Your web browser opens at **http://localhost:8501**. Keep the black window open while you work; close it to stop.
- Type your name under **Reviewer** (left side). It's saved with every decision.

## Four steps per video

| Step | Page | What you do | Time |
|---|---|---|---|
| 1 | **Analyze** | Pick the video → **Protocol window** → **Analyze video**. Several videos? Open *Analyze several videos*. | 15–20 min per video (computer works, you don't) |
| 2 | **Count check** | For each of the 15 sample frames: remove boxes that aren't fish (or a whole category at once), add fish the AI missed → **Save and next**. | a few minutes |
| 3 | **Review queue** | For each unfamiliar animal: pick its name from the Nova Scotia list (**New species** / **Existing species**) or **Reject: not a fish**. Keys: N, E, X. | ~10 s per item |
| 4 | **Results** | Open **Survey details**: add water temperature, pole visibility, juveniles. Then **Download Excel report**. | 2 min |

## Reading the results
- **MeanCount**: average fish per sample frame (the protocol's main number). **MaxN**: the most fish in one frame.
- **Unknown/Unable to ID due to visibility**: fish seen but too murky to name. Never reported as zero fish.
- **Red alert**: a watch-list species was counted or confirmed. **Orange alert**: outside its usual temperature range,
  or a species that isn't on the expected Nova Scotia list (a possible new arrival).
- **Image clarity** is how easy fish are to spot. It is *not* a distance: record the pole reading yourself.

## Quality control (protocol QC)
On **Count check**, choose **Blind count** for a random 10% of frames (2 frames per 15-frame video). You count without
seeing the AI's boxes and BlueSight compares. The protocol's target is **95% agreement** and **under 6% difference**.

## Good to know
- The AI finds roughly half the fish on its own in murky water. **The count check is what makes the numbers
  trustworthy**, and your corrections are saved (Count check → *Save corrections as training data*) to train a better
  model on Nova Scotia footage.
- Edit the **watch list** (and usual temperature ranges) under **Species registry → Watch list**.
- **How it works** (left menu) explains every word on screen. Problems? `outputs/logs/bluesight.log` has the details.
