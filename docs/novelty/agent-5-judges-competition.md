# Agent 5: Judges & Competition lens

## Official judging criteria
Source: https://www.spaceappschallenge.org/resources/judging-awards-guide/

Every criterion is scored 1–5 at all levels of judging:
- **Impact:** how big the problem is, how many people it reaches or inspires.
- **Creativity:** a novel idea, or a meaningful improvement on an existing one.
- **Validity:** scientifically grounded, feasible, usable.
- **Relevance:** fully addresses the challenge. NASA data must be a core component, "rather than a superficial addition."
- **Presentation:** both the demo and the full project page count, and the guide asks for equal attention to both.

Global awards that fit this project: **Best Use of Science** and **Best Use of Data**.

## Demo and submission rules
Source: https://www.spaceappschallenge.org/resources/project-submission-guide/
- **Format:** a video of 30 s or less, or at most 7 slides. Going over the limit makes the team ineligible for global judging.
- **Language:** English subtitles if the video is not in English.
- **Access:** links must be public with no login.
- **People:** no minors under 18 on screen.
- **Weighting:** most of the evaluation comes from the project page.
- **AI disclosure:** use of AI must be disclosed, and AI-generated images or video must carry a watermark.

## What 2025 winners had in common
- **SkySense (Twisters):** won "Best Use of Technology". A polished, personalized decision tool built on NASA POWER, Giovanni and GES DISC, with an AI chat.
- **QUEÑARIS:** won "Local Impact". Linked MODIS NDVI/EVI to one concrete local crisis, using real numbers (spring flow fell from 14 L/s to 0).
- **Pattern across winners:**
  - a specific place with human stakes
  - data that drives a decision
  - a live hosted app
  - a strong story
  - a rich project page

## Commodity baseline (most teams will build this)
- A variable dropdown, a map box, a Giovanni or AppEEARS fetch, and a Plotly line with an OLS fit and a p-value.
- Only one test, often with the seasonal cycle left in.
- A generic "AI chatbot explains the chart".
- The same few demos: NO₂ in a city, NDVI in the Amazon, rising temperature.
- No discussion of data gaps, autocorrelation, or robustness.

Our architecture is already ahead of this baseline, but judges won't see that unless we make it visible.

## Differentiators, ranked
1. **Trend Court:** each trend goes on "trial".
   - **Jurors:** OLS, Hamed-Rao MK, Seasonal MK and Sen's slope each give a verdict.
   - **Cross-examination:** rerun with the seasonal cycle left in, with a shorter record, and on a nearby control region.
   - **Witness:** a second source corroborates (GPM vs NCEI stations, MODIS LST vs MERRA-2).
   - **Verdict:** in plain language.
   - Wins **Validity** and **Best Use of Science**. Feasibility: High.
   - Risk: a poor match with the second source.
   - Demo moment: the "SIGNIFICANT" stamp turns to "NOT PROVEN" when the seasonal cycle is left in.
   - Scores: Impact 6 · Novelty 7 · Feasibility 9 · Rigor 10 · Demo 8.
2. **"How long until we know?":** a detectability countdown (Weatherhead 1998), plus a years-to-detection map.
   - Wins **Creativity** and **Impact**. Feasibility: Medium to High.
   - Risk: it must be explained clearly.
   - Demo moment: "Earth will tell us in 2031."
   - Scores: Impact 7 · Novelty 9 · Feasibility 7 · Rigor 9 · Demo 9.
3. **Local Case Files:**
   - A wizard asks for the place type, runs a curated set of variables in parallel, and builds an evidence dashboard with FDR correction.
   - Ships 2–3 real stories in the style of QUEÑARIS for the team's home region.
   - Wins **Impact**, **Presentation**, **Relevance** and the Local Impact award. Feasibility: Medium.
   - Risk: spreading too thin. Cap it at 3 variables.
   - Scores: Impact 9 · Novelty 6 · Feasibility 6 · Rigor 7 · Demo 9.

**Agent recommendation:** build #1 as the core, add #2 as the wow feature (about 6 hours for one person), and use #3's story framing for the demos.

## Video and project page strategy
- **Video:** 28 s or less, subtitled, using real screen capture.
  - 0–3 s: a hook question ("Is [hometown] really getting hotter?").
  - 3–8 s: the challenge and the title.
  - 8–20 s: live app, the stamp flip, and the instruments named on screen.
  - 20–28 s: the detectability countdown and the vision.
- **Hosting:** YouTube, unlisted but public. Test the link in a private window.
- **Project page:**
  - a hosted live app, with demos served from cache
  - a public GitHub repo
  - GIFs
  - a methods section: tests, minimum record length, gap policy
  - datasets and DOIs
  - limitations
  - an AI disclosure
- **Deadline:** freeze features about 6 hours before the deadline, which the agent read as **Nov 15, 11:59 pm local**. Put one person full-time on the demo.

Sources:
- https://www.spaceappschallenge.org/resources/judging-awards-guide/
- https://www.spaceappschallenge.org/resources/project-submission-guide/
- https://www.spaceappschallenge.org/2025/awards/global-winners/
- https://www.spaceappschallenge.org/2025/awards/global-finalists/
