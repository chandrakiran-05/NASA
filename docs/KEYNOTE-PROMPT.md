# Prompt for Claude on a Mac: build the Keynote deck

Copy everything below the line into Claude Code (or Claude with computer use) on a Mac that has Keynote installed.

---

Build a Keynote presentation (a real `.key` file) for our NASA Space Apps 2026 project **"Earth System Trend Detective"** (challenge: *Be an Earth System Trend Detective*). Save it as `~/Desktop/Earth-System-Trend-Detective.key`.

## How to build it
- Drive Keynote directly with AppleScript / JXA through `osascript`. Create the document, every slide, the text boxes and shapes, and the transitions in code. When you finish, open the file and step through it to check every slide.
- Use 16:9 (1920×1080) and one blank master for all slides, so you control the layout.
- **Connected motion is the main design idea.** Use the **Magic Move** transition (`transition effect: magic move`, about 0.8–1.0 s, ease in-out) between every pair of slides. A shared element must have the same shape or text and the same fill on both slides, so Keynote morphs it. Duplicate the previous slide, then move or resize the elements, rather than building each slide from scratch. That is how elements "travel" from one slide to the next.
- Inside a slide, keep builds clean and few: *Appear*, *Dissolve* or *Move In*, 0.3–0.5 s, one idea per click. No spinning, bouncing or flying effects.
- No screenshots of the app and no live-demo slides.

## Visual style
- Background: warm paper `#F4F2ED`. Ink: `#1F2723`. Accent blue: `#086BDC`. Warning red: `#B5452F`.
- Headings in a serif (New York or Georgia, regular weight, large: 80–110 pt). Body in SF Pro or Helvetica Neue, 26–32 pt. Small capitals for labels.
- Lots of empty space. At most about 25 words per slide; put the details in the presenter notes.
- One thin circle (the "Earth ring", 2 pt stroke, accent blue) is the recurring element. It appears on the title slide and turns into the feature hub.

## Slides (add presenter notes to each)
1. **Title.** "Earth System Trend Detective". Subtitle: "Is it really changing? Ask Earth in plain words." The Earth ring sits large on the right. Footer: "NASA Space Apps 2026".
2. **The problem.** "Earth data is huge, noisy and seasonal." Three short lines appear one by one: *Seasons hide trends.* · *Gaps and instrument changes fake jumps.* · *Pick the right years and anything looks like a trend.* The Earth ring shrinks to the top-right corner (Magic Move).
3. **Who it hurts.** "Students can download data, but can't tell a real trend from chance." Show a simple zig-zag line, a thin line drawn as shapes (not a screenshot), with a "?" over it.
4. **Our solution.** "Type a question. Get a full evidence report." A command-box shape (rounded pill) moves to the centre and contains "Is Chennai getting hotter?". An arrow builds to a stack of report cards labelled *Answer · Data · Chart · How much · Is it real? · When · Seasons · Map · Research · Limits*.
5. **The feature hub (key slide).** The Earth ring grows to the centre. Six numbered circles sit around it like a clock face and build in order 1→6:
   1. Plain words in
   2. Real NASA + NOAA data
   3. Trend tests & checks
   4. BEAST + PELT change dating
   5. Grounded local AI
   6. DigiTwin & Discovery
6–11. **One slide per feature.** Each one Magic-Moves from the hub: the chosen circle grows and slides to the left as a big numbered badge, the other circles fade or shrink to a small row at the bottom (with the current one highlighted), and the content builds on the right. The next slide moves the badge back into the row and grows the next number, so the sequence *continues* from circle to circle.
   - **1 · Plain words in.** Casual questions ("india rains", "is it getting hotter", "rajasthan dry these days") become a precise research question: variable, place, period and test. Everyday words map to scientific variables. If you ask for years before any record exists (e.g. 1600–1700), it explains why and shows the earliest real record.
   - **2 · Real NASA + NOAA data.** Fetched live from official APIs with our NASA Earthdata login: Giovanni (MERRA-2, GPM IMERG, GLDAS, MODIS, OMI, AIRS…), Cloud OPeNDAP + CMR, AppEEARS, NOAA NCEI / Climate Data Online, NOAA ERDDAP, NSIDC sea ice, NOAA tide gauges, USGS rivers (CUAHSI WaterML), PO.DAAC SWOT. Every number carries dataset, version, DOI and retrieval date. Gaps stay gaps; nothing is filled in.
   - **3 · Trend tests & checks.** Seasonal cycle removed; Sen's slope with Mann-Kendall; regression corrected for month-to-month persistence; a "could it be chance?" shuffle test; a second data product as a second opinion; checks for instrument seams. Stamps: SIGNIFICANT / NOT PROVEN.
   - **4 · BEAST + PELT.** A Bayesian ensemble (BEAST) dates *when* a trend changed, cross-checked by PELT change-point detection, and calibrated against persistent climate noise. Labels: VERIFIED / PROBABLE / NOT VERIFIED, each with its limit.
   - **5 · Grounded local AI.** Qwen runs on our own laptop GPU (no cloud). It only writes the explanation. Every number it writes is checked against the computed results, and it falls back to template text if anything doesn't match. It remembers the conversation for follow-ups ("what about Kerala?").
   - **6 · DigiTwin & Discovery.** DigiTwin simulates "what if" futures from a fitted baseline (always labelled *simulated, not a prediction*). Discovery mode is an autonomous AI scientist. Show its five steps as a mini chain of small circles that build left to right: *Scan the planet → Keep what's real → Check what's known → Flag the gaps → Write it up* (a brief with figures, DOIs, preprints and news, and a reproducible notebook).
12. **Built on the challenge resources.** Title: "Every resource on the challenge page, put to work." A grid of resource tiles builds in. Mark each tile **In use** or **Next**:
   - In use: **Giovanni** (time series for hundreds of NASA variables).
   - In use: **Hydrology Time Series**. Explain on the slide in one line: *NASA's hydrology time series give water-cycle records (soil moisture, runoff, evaporation, snow water, groundwater) from the GLDAS/NLDAS land models and GRACE. The old "Data Rods" service was retired in 2025, so we read the same hydrology variables through cloud Giovanni.*
   - In use: **AppEEARS** (MODIS vegetation and land products).
   - In use: **Climate Data Online / NCEI** (weather-station records).
   - In use: **The SeaWiFS time-series paper**. Explain in one line: *NASA's study of SeaWiFS chlorophyll near river mouths shows how to build a monthly satellite time series, remove the seasons and test whether the slope is significant. Our trend engine follows that recipe, and every report cites it.*
   - In use: **Trend-test and statistical-significance guides** (Mann-Kendall, Sen's slope, p-values and what they do *not* mean).
   - In use: **SWOT** (river and lake water heights via PO.DAAC Hydrocron).
   - Next: **KNMI Climate Explorer** (cross-checking results), **RADARSAT Constellation Mission + SAR Python tutorial** (radar for floods, ice and coasts), **Geo.ca** (Canadian open geodata).
13. **Honest by design.** Four short rules build one by one: *"possible instrument effect", never "error"* · *"consistent with", never "caused by"* · *"simulated", never "prediction"* · *every report ends with what it cannot tell you.*
14. **Impact & next steps.** "From one student's question to an AI scientist scanning the planet." Next: more radar and ocean sources, classroom mode, and sharing reports with CUAHSI HydroShare. The Earth ring returns to its title-slide size and position (Magic Move), closing the loop.

## Presenter notes
For each slide, write 2–4 sentences the speaker can read. Use plain English, no jargon without a short explanation, and keep the honest wording above (never claim causes or predictions).

## Final check
- Step through the whole deck in play mode and confirm three things: every transition is Magic Move with matching objects (shapes that should morph really morph and don't cross-fade), no text overflows its box, and the build order on slide 5 goes 1→6.
- Save and report the file path.
