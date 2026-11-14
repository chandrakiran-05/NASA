# Novelty decision: "Is it real yet?"

> **Superseded by [05-novelty-features.md](05-novelty-features.md)**. That version is grounded in real pain-point evidence.

**How this was decided:**
- Five ideation agents each looked at the project through one lens: science and statistics, UX and education, AI discovery, Earth-system links, and judges and competition. Their raw reports are in [novelty/](novelty/).
- A sixth agent merged their 15 ideas into 11, scored each against the **official Space Apps judging criteria** plus 48-hour feasibility and value to the audience, and picked one coherent product.

## Merged ideas and scores (1–5 each, total /35)

**Columns:** Imp = Impact, Cre = Creativity, Val = Validity, Rel = Relevance, Pres = Presentation (the official criteria). Feas = 48-hour feasibility. Aud = value to the audience.

| # | Idea | From | Imp | Cre | Val | Rel | Pres | Feas | Aud | **Total** |
|---|---|---|---|---|---|---|---|---|---|---|
| M1 | **Evidence Clock**: start/end-year trend triangle, expanding-window slider, years until detectable | A1, A2, A5 | 4 | 5 | 4 | 5 | 5 | 5 | 5 | **33** |
| M4 | **"Could it be chance?"**: lineup of the real series plus block-bootstrap null histogram | A2 | 4 | 4 | 4 | 4 | 5 | 5 | 5 | **31** |
| M2 | **Trend Court**: four statistical tests as jurors, plus cross-examination (seasonal cycle left in, shorter record, change-point) | A5, A1 | 3 | 3 | 5 | 5 | 4 | 5 | 4 | **29** |
| M5 | Predict-then-reveal case file and local story | A2, A5 | 4 | 3 | 4 | 4 | 5 | 4 | 5 | **29** |
| M6b | Per-grid-cell trend map with FDR stippling | A1 | 4 | 5 | 5 | 4 | 5 | 2 | 3 | **28** |
| M6a | Multi-variable Trend Scan with FDR | A3, A5 | 4 | 4 | 4 | 5 | 4 | 2 | 3 | **26** |
| M9 | Evidence Chain (precipitation → soil moisture → NDVI → land surface temperature) | A4 | 4 | 5 | 2 | 4 | 5 | 2 | 4 | **26** |
| M3 | Three Witnesses (satellite vs model vs station) | A4, A5 | 3 | 3 | 4 | 4 | 3 | 4 | 3 | **24** |
| M10 | Heat Island Twin | A4 | 4 | 3 | 3 | 3 | 4 | 3 | 4 | **24** |
| M7 | Ask the Catalog (LLM limited to a closed list of variables) | A3 | 3 | 2 | 3 | 4 | 3 | 4 | 3 | **22** |
| M8 | Region fingerprint from land cover | A3 | 3 | 3 | 4 | 3 | 3 | 2 | 3 | **21** |

## Final product

**Pitch:** *Trend Detective doesn't just tell you whether a NASA-measured trend in your region is significant. It shows you whether it could be chance, whether it survives cross-examination, and how many more years Earth needs before we'll know.*

### Signature feature: Evidence Clock (M1)
- A heatmap of trends for every start/end year, labelled *exploratory*.
- An end-year slider that grows the record and recalculates live.
- A **years-to-detect** countdown based on Weatherhead et al. 1998 (noise plus lag-1 autocorrelation). It is always worded conditionally: *"if the current rate and noise persist, about 7 more years (≈2031)"*.
  - When the slope is near zero, it says "can't tell" instead of giving a number.
- This turns the challenge's own line, *"Sometimes all a trend needs to become significant is a longer period"*, into a feature.

### Supporting feature 1: Trend Court (M2)
- **Jurors:** ordinary least squares (OLS), Hamed-Rao Mann-Kendall, Seasonal Mann-Kendall and Sen's slope. All four are already in division ⑥.
- **Cross-examination:** rerun with the seasonal cycle left in, with a shorter record, and with a Pettitt change-point test (is it a trend, or one jump?).
- The result is a **SIGNIFICANT / NOT PROVEN** stamp. It makes the baseline's statistical rigor visible to judges.

### Supporting feature 2: "Could it be chance?" lineup (M4)
- The real series is hidden among 19 block-bootstrap shuffles (12-month blocks, fixed seed), and the user tries to spot it.
- The real slope is then dropped onto a histogram of 1,000 null slopes.
- The shuffles are labelled *"simulated from your data, not observations"*.

### Framing (from M5)
- Detective case-file flow.
- Two cached local demos: one significant and one "not yet".

### Cut, and why
| Cut | Reason |
|---|---|
| M3 Three Witnesses | A single station doesn't match a grid cell, and AIRS is in an outage. An optional NCEI juror can come back only if there is time left. |
| M6a Trend Scan, M6b Trend Map | Giovanni's quota is unknown and fetching about 290 granules from OPeNDAP is too slow for 48 hours. |
| M7 Ask the Catalog | Reads as the generic AI chatbot that judges expect from every team. |
| M8 Region fingerprint | Adds another slow AppEEARS task. |
| M9 Evidence Chain | Risks overclaiming causation, the GLDAS v2.1 dependency is unverified, and AppEEARS adds latency. |
| M10 Heat Island Twin | The rural ring is ambiguous and AppEEARS adds latency. |
| Extras | Classroom mode, sonification, PDF report card. |

## Architecture changes on top of [03-architecture.md](03-architecture.md)

| Division | Change |
|---|---|
| ⑥ Analysis | New `detectability.py`: Weatherhead n*, a triangle of about 300 windows of 10 or more years, and the expanding window.<br>New `robustness.py`: court cross-examination and the Pettitt test.<br>New `permutation.py`: 12-month block bootstrap with a fixed seed. |
| ② API | `POST /api/analyze` adds a `court{}` block.<br>New `GET /api/analyze/{series_id}/detectability` returns `{triangle[], expanding[], years_to_detect, assumptions}`.<br>New `POST /api/analyze/nulls` takes `{series_id, n_panels:19, n_null:1000}`. |
| ① Frontend | New Evidence Clock, Court stamp, and Lineup/null histogram, plus the case-file flow. |
| ⑦ Storage | Cache the null and triangle results for each series. Precompute the demos. |
| ③ Catalog | Demo case metadata only. |
| ④ ⑤ ⑧ | Unchanged. |

## Team (new work, on top of the baseline owners)
| Person | New work |
|---|---|
| A | ⑥ detectability (triangle, expanding window, n* with caps) and its endpoint |
| B | ⑥ court and permutation, their endpoints, and fixture tests |
| C | ① Evidence Clock (heatmap, slider, countdown) |
| D | ① Court stamp, lineup grid, null histogram, and the case-file wizard |
| E | Precache 2 demos via Giovanni/AppEEARS, the project page (methods, DOIs, limitations, AI disclosure), the video, and citation checks |

## If only 24 hours are left
- **Evidence Clock:** years-to-detect plus the expanding slider. Include the triangle only if it is done by T-10h.
- **Court:** the four jurors plus the seasonal-cycle flip only. No Pettitt test and no shorter-record check.
- **Lineup:** replace it with the null histogram only.
- **Demos:** cached only.
- **Feature freeze:** T-6h.

## Demo video (30 s or less, subtitled, real screen capture)
| Time | Beat |
|---|---|
| 0–3 s | "Is [hometown] really getting hotter? Is it real yet?" |
| 3–8 s | The wizard picks a variable and region, the series draws, and the instrument names appear on screen |
| 8–14 s | Lineup: "Spot the real one", then the reveal, with the real slope in the histogram's tail |
| 14–20 s | Court: four SIGNIFICANT jurors; toggle the seasonal cycle and the stamp flips to NOT PROVEN |
| 20–27 s | Clock: drag the end year and the cells turn significant; the rainfall case reads "Not yet: about 2031" |
| 27–30 s | Title card: "Giovanni · AppEEARS · NOAA NCEI" |

## Top risks
| Risk | Mitigation |
|---|---|
| Baseline connectors are late | Build ⑥ and ① against recorded real CSV fixtures, serve demos from cache, freeze at T-6h |
| Overclaiming (Weatherhead assumptions, overlapping triangle cells, a lineup miss read as "no trend") | Conditional wording, "exploratory" labels, an assumptions panel |
| Latency and quota (AppEEARS about 15 min, Giovanni quota unknown, GES DISC outages) | Live mode uses Giovanni monthly point series only; show `/api/sources/status`; pre-run the demos |

## Verify before using in the pitch
- **Cited from memory by the agents:**
  - Weatherhead et al. 1998 (JGR 103(D14):17149): check the constant 3.3, the exponent 2/3 and the definition of σN.
  - Liebmann et al. 2010.
  - Pettitt 1979.
  - Hamed & Rao 1998.
  - Buja et al. 2009.
  - Wickham et al. 2010.
  - Wasserstein & Lazar 2016.
- **On the official Space Apps pages:**
  - The submission rules (video of 30 s or less, AI disclosure).
  - The **deadline, which agent 5 read as Nov 15, 11:59 pm local.**
