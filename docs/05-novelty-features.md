# Trend Detective — Novelty Features

> This document covers only the **novelty layer** that sits on top of the baseline in [03-architecture.md](03-architecture.md). It supersedes the feature pick in [04-novelty-decision.md](04-novelty-decision.md).
> Every feature traces back to real, documented problems: NASA alerts and guides, peer-reviewed papers, Stack Exchange, Reddit, and educator sources. The raw evidence is in [painpoints/](painpoints/).
> Data comes **only** from the official challenge APIs: Giovanni, AppEEARS, NOAA NCEI, CMR and Cloud OPeNDAP.

## One-line pitch
**Trend Detective is the only tool that checks, before it ever says "significant", whether the data is intact, whether the test fits the data, whether the time window was cherry-picked, and whether a second NASA product agrees.**

## Why this matters (the evidence in one paragraph)
- NASA's own Giovanni user guide says its regression line *"does not draw a scientific trend conclusion."*
- NASA found that Cloud Giovanni had inserted **spurious blocks of zeros** into 10 GLDAS, MERRA-2, NLDAS and GRACE collections for data before 2024. The bug was found in Nov 2025 and fixed on 26 Mar 2026, and NASA gave no guidance for data people had already downloaded.
- A change of satellite mission changes how reliable trends are. IMERG rainfall trends agree with rain gauges **86.7%** of the time in the GPM era, but only **75.3%** in the TRMM era (Zhu et al., ERL 2024/25).
- Naive testing inflates claims. The share of global land that is "significantly greening" falls from **35.2% to 15.3%** once the analysis corrects for running thousands of tests at once (Cortés et al., GRL 2021).
- People are asking for help. "How do I test whether two trends differ?" has **235k views** on Stack Exchange. "Which trend test should I use?" has **20k**.

---

## Feature overview

| Role | Feature | User promise | Score /40 |
|---|---|---|---|
| ★ Signature | **F1 Seam & Integrity Audit** | "Before we call it a trend, we check it isn't a broken record or a satellite swap." | 35 |
| Centrepiece visual | **F2 Evidence Clock** | "Is it real yet? If not, when will we know? And was this window cherry-picked?" | 37 |
| Supporting | **F3 Method Verdict** | "We pick the right test, show where tests disagree, and explain why." | 34 |
| Supporting | **F4 Second Opinion** | "Does another NASA product, or the nearest station, agree on the trend?" | 30 |

**How the scores work:**
- Each feature is scored 1–5 on eight things: evidence strength, user value, the five official judging criteria (Impact, Creativity, Validity, Relevance, Presentation), and 48-hour feasibility. The maximum is 40.
- F1 is the signature even though F2 scores higher. F1 has the hardest evidence (an official NASA alert plus 4 papers), and it is the feature other teams are least likely to build.

---

## F1 — Seam & Integrity Audit ★ signature

**Problem it solves**

| Evidence | Source | Strength |
|---|---|---|
| Cloud Giovanni bug: spurious zero blocks in 10 collections (fixed 2026-03-26) | earthdata.nasa.gov/data/alerts-outages/reprocessed-hydrology-products-available-from-cloud-giovanni | Official NASA, opened |
| IMERG trend–gauge agreement is 86.7% (GPM era) vs 75.3% (TRMM era) | Zhu et al., ERL 20:014064, doi:10.1088/1748-9326/ad984e | Peer-reviewed, metadata |
| MERRA: SSM/I (1987) and AMSU (1998) introduced unphysical precipitation trends | Gelaro et al. 2017, J. Climate, doi:10.1175/JCLI-D-16-0758.1 | Peer-reviewed, confirmed |
| MODIS Terra orbital drift after 2020 biases products | ntrs.nasa.gov/citations/20240001409; doi:10.1016/j.srs.2023.100116 | NASA NTRS / metadata |
| "Data is all fill values"; mm/month units bias by month length | Giovanni user guide | Official NASA, opened |
| How do I find where an abrupt change happens? (10.4k views) | stats.stackexchange.com/questions/116363 | Opened |

**What the user sees**
- A **"Fit for trends?"** badge: ✅ OK, ⚠️ Caution, or ❌ Not fit, with the reasons listed.
- **Coverage per month:** a strip under the chart showing the % of valid pixels, with low-coverage months greyed out.
- **Integrity flags:** runs of zeros or constant values highlighted on the chart. Data retrieved before the 2026-03-26 fix is also flagged.
- **Seam markers:** vertical lines at known instrument and version changes. These come from a cited `events.json`, for example IMERG TRMM→GPM in 2014-06, Terra drift from 2020-02, Terra exit in 2022-10, MERRA-2 1987/1998, and GLDAS 2.0→2.1.
- **Step test at each seam:** shows the trend before vs after, plus a Pettitt test for unknown breaks.

**How it works (architecture)**

| Division | Change |
|---|---|
| ⑤ Time-series | New `integrity.py`: zero/constant-run detector, coverage % per step, days-in-month normalisation |
| ⑥ Analysis | New `seams.py`: step-dummy OLS at known dates, Pettitt test for unknown breaks, segment trends |
| ③ Catalog | New `events.json`: each event carries its citation (the only hand-curated file; every entry is sourced) |
| ⑧ Ops | Compare `retrieved_at` against NASA alert dates |
| ② API | `GET /api/timeseries/{id}/integrity` |
| ① Frontend | Seam markers, coverage strip, badge |

**Judge wow:** The IMERG rainfall chart splits at June 2014, and the trend is shown separately on each side. Then a recorded series with a block of zeros inserted (labelled "simulated") gets caught: *"NASA's own pipeline shipped this bug — we detect it."*

**Honest limits**
- A step can be a real climate shift, so we always say "possible instrument effect", never "artifact".
- The event list is incomplete.
- Short segments have low statistical power.

---

## F2 — Evidence Clock (+ cherry-pick rank)

**Problem it solves**

| Evidence | Source |
|---|---|
| Hunting for "pause" or "acceleration" windows is hidden multiple testing | Rahmstorf, Foster & Cahill 2017, ERL, doi:10.1088/1748-9326/aa6825 |
| Short cherry-picked windows mislead the public ("the escalator") | skepticalscience.com/escalator_2022.html |
| Picking a window by its slope invalidates the test; no significant pause found | PIK release (naturefund.de article) |
| "What's it called when you test over many start/end values?" | stats.stackexchange.com/questions/12988, /419351 |
| Users need to know how long a record is needed | Weatherhead et al. 1998 (**verify constants**) |
| The challenge itself: "Sometimes all a trend needs to become significant is a longer period" | Challenge page |

**What the user sees**
- **Trend triangle:** a heatmap of slope and significance for every start × end year. It is labelled *exploratory*.
- **End-year slider:** grow the record and watch the confidence interval narrow.
- **Years-to-detect countdown:** *"If the current rate and noise persist, about 7 more years (≈2031)."* If the slope is near zero, it shows "can't tell" instead.
- **Cherry-pick rank:** *"Your 10-year window ranks 3rd of 34 same-length windows. It's unusually flat."*

**Architecture:** ⑥ `detectability.py` (Weatherhead n*, about 300 windows, window rank) · ② `GET /api/analyze/{id}/detectability` · ① Plotly heatmap, slider and countdown.

**Judge wow:** Drag the end year and the cells turn significant. On the rainfall case, the countdown reads "Not yet — ≈2031."

**Honest limits**
- The detectability formula assumes AR(1) noise and that the current trend continues.
- Triangle cells overlap, so they are not independent tests.

---

## F3 — Method Verdict (assumption-aware tests)

**Problem it solves**

| Evidence | Source |
|---|---|
| The choice of prewhitening changes Mann-Kendall p-values and Sen slopes; plain MK gives false positives | Collaud Coen et al. 2020, AMT, doi:10.5194/amt-13-6945-2020 |
| "Which trend test should I use?" (20.3k views) | stats.stackexchange.com/questions/512049 |
| "Why is prewhitening important?" (19.4k views); block-length confusion | stats.stackexchange.com/questions/221072, /160776 |
| MK says significant but Sen slope = 0 | stats.stackexchange.com/questions/557979 |
| When to use Seasonal Kendall (0 answers) | stats.stackexchange.com/questions/138138 |
| Giovanni draws a line but gives no significance test | Giovanni user guide |

**What the user sees**
- **Diagnostics first:** a lag-1 autocorrelation badge and a seasonality test (Kruskal-Wallis by month). Together these **choose the test automatically, and the app says why it chose it**.
- **Tests side by side:** raw MK, TFPW-prewhitened MK, Hamed-Rao MK, Seasonal MK, Sen's slope and OLS.
- **"Conclusion flips" flag:** raised when the tests disagree. A consistency checker also explains ties and zero slopes.
- **Null histogram:** the real slope plotted against a block-bootstrap null distribution, labelled "simulated from your data". This is the part kept from the earlier "chance" idea.
- **Plain-language verdict:** a SIGNIFICANT or NOT PROVEN stamp.

**Architecture:** ⑥ `robustness.py` (pymannkendall variants, Kruskal-Wallis, ties check, block bootstrap) · ② `verdict.explain[]` added to `/api/analyze` · ① test table and stamp.

**Judge wow:** Switch off the autocorrelation correction and watch the stamp flip from NOT PROVEN to SIGNIFICANT. The lesson: *"this is how papers overclaim."*

**Honest limit:** when several tests agree, that is not proof of a trend.

---

## F4 — Second Opinion (cross-product / cross-region agreement)

**Problem it solves**

| Evidence | Source |
|---|---|
| "How to test whether two series' trends are the same" (**235k views**) | stats.stackexchange.com/questions/19103 |
| Conflicting sea-ice trends from different sources | earthscience.stackexchange.com/questions/884 |
| 22 precipitation products disagree; reanalyses split into wet and dry camps | Alexander, Contractor et al. 2020, ERL, doi:10.1088/1748-9326/ab79e2 |
| Reanalysis and station data can differ by more than 25% | r/meteorology/comments/es9r40 (snippet) |

**What the user sees**
- **Same region, second product:** IMERG vs MERRA-2 precipitation, or MERRA-2 T2M vs the nearest NCEI station.
  - The slopes from each source, side by side.
  - A trend test on the difference between the two series.
  - A **Robust / Disputed** badge.
- **Two regions, same variable:** a slope-difference test, adjusted for autocorrelation.

**Architecture:** ⑥ `compare.py` (difference-series trend, z-test on slopes using the effective sample size) · ② `/api/compare?mode=slope_diff` · ① agreement panel.

**Judge wow:** Satellite, model and ground station all show rising temperature, so the badge reads ROBUST. A rainfall case shows DISPUTED, because the products disagree on the sign.

**Honest limits**
- A single station may not represent a whole grid cell.
- When the variables differ (e.g. land surface temperature vs air temperature), only the sign of the trend is compared.

---

## Stretch (only if core is done)
| Feature | Evidence | Why it's a stretch |
|---|---|---|
| FDR trend map (corrects for testing many grid cells) | Cortés 2021 (35%→15%); Wilks 2016; gis.SE/475383 | Gridded fetch is limited by quota and latency |
| Terra vs Aqua split (MOD vs MYD) | Twedt 2023; Jeong 2024 (snippet) | Needs a second AppEEARS task |
| Reproducibility pack (`.py` + provenance JSON + integrity log) | Kedron & Frazier 2022, doi:10.3390/rs14215471 | Cheap; do it if any time is left |
| "Be the Skeptic" class mode + lesson card | NSTA poll; NPR/Ipsos 2019; LPM 2019; My NASA Data poster | Mostly framing and UX |
| CMR sibling-collection pre-check (e.g. GRACE vs GRACE-FO) | github.com/earthaccess-dev/earthaccess/issues/1434 | Small, but not core |

## Cut (and why)
| Cut | Reason |
|---|---|
| 19-panel lineup | Thin evidence (one teaching blog); only its null histogram moves into F3 |
| Ask-the-Catalog LLM | Judges expect the generic chatbot; it solves no evidenced problem |
| Evidence Chain (precipitation → soil → NDVI) | Risks claiming causation; slow AppEEARS |
| Heat Island Twin, Region fingerprint | Slow AppEEARS; weak evidence |
| Axis-honesty / "spot the trick" labs | Media literacy, not trend detection |
| Sonification, PDF report card | Low value per hour |

## Already in the baseline (not novelty, so not pitched as such)
- Polygon area averages, no file formats to handle, CSV output (Reddit's #1 pain).
- QC masking and the completeness rule.
- The "My place" wizard with an NCEI station series.
- Status and caching for AppEEARS jobs that sit in pending.

## Must verify before the pitch
- Weatherhead et al. 1998: the 3.3 constant, the 2/3 exponent and the definition of σN.
- Zhu et al. 2024/25 and Jeong et al. 2024: only the abstract snippet and metadata were seen.
- All Reddit and Earthdata Forum citations: search snippets only.
- Submission deadline on the official page (an agent read it as Nov 15, 11:59 pm local).
