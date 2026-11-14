# Agent 2: UX, Education & Storytelling lens

The agent cited these sources from memory without verifying them; check them before quoting.

## 1. "Could It Be Chance?" Lineup + Shuffle Machine
- **Pitch:** The student tries to spot the real series hidden among 19 shuffled versions of itself. If they can, the trend is unlikely to be chance (about 1 in 20).
- **New:** Students experience what significance means, rather than reading a p-value.
  - An animated histogram of about 1,000 shuffled slopes, with the real slope dropped onto it.
  - The resulting "permutation p" is shown next to the MK p.
- **Evidence:**
  - Lineup method: Buja et al. 2009 (Phil Trans A), Wickham et al. 2010 (IEEE TVCG), Majumder et al. 2013 (JASA).
  - Simulation-based teaching of inference: Tintle et al. 2011/2012 (J Stat Educ).
- **Data:** Any baseline deseasonalized series. No new calls.
- **Implementation:**
  - ⑥ `permutation.py` uses a block bootstrap (12-month blocks), which keeps lag-1 autocorrelation so significance is not overstated.
  - ② `POST /api/analyze/nulls`.
  - ① Lineup grid and animated histogram.
- **Feasibility:** High. Risk: choosing the block length (fixed at 12 months and documented).
- **Wow moment:** A judge picks the wrong panel, the real series is revealed, and its slope lands far in the tail of the histogram.
- **Scores:** Impact 9 · Novelty 9 · Feasibility 8 · Rigor 9 · Demo 10.

## 2. Predict-then-Reveal Case File
- **Pitch:** A case file with Suspect, Scene, Hunch, Evidence and Verdict. The student draws the trend they expect before the real series is drawn over their sketch.
- **New:** A prediction-error learning loop. The baseline goes straight to the results.
- **Evidence:**
  - Crouch et al. 2004 (Am J Phys): predicting before a demonstration improves learning.
  - NYT "You Draw It" (2015–17).
  - Hullman et al. 2015 (PLoS ONE): hypothetical outcome plots.
- **Data:** The baseline series. Definitions come from CMR metadata.
- **Implementation:** Mostly ① Frontend: a draw layer, the case-file layout, and a score for how far the sketch was from the real series. ③ Catalog: "suspect cards" built from CMR. Keyboard fallback with up / flat / down buttons.
- **Feasibility:** High. Risk: touch input and accessibility.
- **Wow moment:** A student expects "my city's rainfall is obviously rising", and the result is "not significant". That is a teachable non-result.

## 3. Evidence Time Machine + Shareable Trend Report Card
- **Pitch:** A slider grows the record from 3 years to the full record. The CI narrows and p falls live. The result exports as a one-page report card.
- **New:**
  - Misconception guards: correlation is not causation, one point is not a region, short record.
  - A cross-check against an NCEI station.
  - Classroom mode with an anonymous histogram of the class's predictions.
  - Sonification for accessibility.
- **Evidence:**
  - ASA p-value statement (Wasserstein & Lazar 2016).
  - Peer instruction (Crouch & Mazur 2001).
- **Implementation:** ⑥ expanding-window OLS/MK. ② `GET /api/analyze/{id}/expanding`. ① Slider and PNG/PDF card. ⑦ Class vote counts.
- **Feasibility:** Medium. Risk: scope creep. Build the slider and card first.
- **Wow moment:** The verdict flips from "can't tell yet" to "significant" at year 14.
- **Scores:** Impact 8 · Novelty 7 · Feasibility 7 · Rigor 8 · Demo 9.

**Agent recommendation:** Build #1 and #2 as one flow: predict → lineup → reveal → verdict. Add the #3 slider if time allows. Most of the work is frontend, plus about 150 lines of analysis code.
