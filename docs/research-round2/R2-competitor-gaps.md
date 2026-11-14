# R2: Competitor gaps, user needs and advanced features

## What existing tools have and lack

| Tool | Has | Lacks |
|---|---|---|
| NASA Giovanni | Maps, area-averaged time series, Hovmöller plots, an optional best-fit line | Its manual says the line "does not draw a scientific trend conclusion". No significance test, change points or literature. |
| AppEEARS | Subsetting, quality layers, summary statistics, charts | Trend tests, change dating, drivers |
| Worldview | More than 1,200 imagery layers, animation | Statistics |
| KNMI Climate Explorer | Correlations, extreme-value analysis, attribution protocol | It's expert-only and its manuals are not regularly updated. No literature check or plain-language output. |
| NOAA Climate at a Glance | Trend per decade over a period the user picks | Significance and change points. Letting users pick the period invites cherry-picking. |
| Climate Reanalyzer | Reanalysis time series and maps | Trends and significance |
| Earth Engine trend tutorial | Mann-Kendall and Sen per pixel | Assumes independent samples, with no correction for autocorrelation or multiple testing. Users must write code. |
| NCAR Climate Data Guide | Explains the pitfalls (serial correlation, discontinuities, start dates) | No compute tool |
| Climate Engine | Trends mentioned in testimonials; has an API | Method and significance testing are undocumented (unverified) |
| Copernicus CDS Toolbox | Discontinued 26 Sep 2024 (Earthkit replaces it) | (from search results, not opened) |

**Gap:** no tool combines autocorrelation-aware significance, change dating, driver tests, a literature check, data integrity, calibrated uncertainty language and a provenance export.

## Evidence of user needs

- **Space Apps 2025 "Will It Rain On My Parade?"** asked whether the likelihood of heavy rain or dangerous heat "have been increasing". It also wanted CSV/JSON downloads with units and links to the input sources. Twisters won Best Use of Technology with this challenge.
- **Judging criteria:** the Validity criterion asks for work "grounded in scientific principles". The Relevance criterion wants NASA data to be "a core component".
- **NASA ESDS AI strategy:** it calls for "reproducibility scaffolding" and says ESDS will not deploy AI "without clear provenance, transparency, and accountability".
- **Data gets revised:** GISTEMP removed faulty records in Feb 2024 and Sep 2025, so a verdict can change after it is published. The CMR `updated_since` and `revision_date` fields can detect reprocessing.

## Proposals

1. **Evidence Dossier (RO-Crate 1.3 and Process Run Crate 0.6).**
   - Each run's crate contains:
     - dataset concept IDs, DOIs and revision dates;
     - the code commit and run parameters;
     - the BEAST and PCMCI+ settings and the calibration table;
     - literature DOIs with the slop-guard verdicts;
     - the LLM prompts and the verification log.
   - The user downloads a .zip with an HTML summary.
   - Effort: about 6–8 h.
2. **Calibrated-language verdicts (IPCC AR6 WGI SPM, footnote 4).**
   - Likelihood terms come from the BEAST sign probability: virtually certain 99–100%, very likely 90–100%, likely 66–100%, about as likely as not 33–66%.
   - Confidence (very low to very high) comes from evidence (checks passed, record length) and agreement (datasets, literature).
   - The verifier enforces the right term.
   - The Mastrandrea 2010 guidance note (doi:10.1007/s10584-011-0178-6) was verified only from a search snippet.
   - Effort: about 4 h.
3. **Verdict Watch and stability backtest.**
   - Query CMR with `updated_since`, rerun the analysis, and diff the likelihood term, change dates and drivers.
   - Backtest by asking "what would we have concluded in 2012, 2016, 2020?"
   - Show a verdict-history timeline and a "verdict changed" banner.
   - Effort: about 4 h for the backtest, about 6 h for the live watch.
4. **"Is extreme X getting more likely here?"**
   - Each year, count the share of days above a threshold in a day-of-year window.
   - Fit a logistic trend, run BEAST, and report the result in calibrated language.
   - Example: "Chance of >35 °C in early July: 12% (1981–2000) → 27% (2005–2024), likely increasing."
   - Effort: about 6 h.
5. **Cross-examination of independent datasets.** Show an agreement matrix and tag change dates as "artifact suspect" when they coincide with sensor transitions.
6. **Multi-region leaderboard with FDR, plus an education mode.**

## Agent's top 2

1. Evidence Dossier with calibrated-language verdicts.
2. Verdict Watch with the stability backtest. The strongest third choice is extreme likelihood (proposal 4).
