# Round 2: Advanced Features (research-backed)

Five research tracks studied recent literature and public sources. They covered tipping points, claim verification, spatial statistics, attribution and competitor gaps, and their notes are in [research-round2/](research-round2/). A judging pass then scored 25 candidate features on research backing, novelty, value, challenge fit, trust, effort, data-rule safety and demo impact. This document is the result. **Nothing here is implemented yet.**

## Why these features

None of the tools we checked combines autocorrelation-aware significance testing, change dating, driver tests, a literature check, an integrity check, calibrated uncertainty wording and an exportable provenance record. The tools checked were Giovanni, AppEEARS, Worldview, KNMI Climate Explorer, NOAA Climate at a Glance, Climate Reanalyzer, the Earth Engine trend tutorial and the NCAR Climate Data Guide. The Giovanni manual says its best-fit line "does not draw a scientific trend conclusion". The Earth Engine trend tutorial assumes independent pixels and applies no multiple-testing correction.

## Score summary (top 12 of 25; each criterion 1–5, total out of 40)

| Feature | Total |
|---|---|
| Cluster-permutation field significance | **37** |
| Calibrated IPCC wording (likelihood + confidence) | **36** |
| Resilience check (critical slowing down + λ + gate) | **35** |
| "Hidden by averaging" panel | **35** |
| Per-pixel BEAST change-year map | **35** |
| Paper-reported rate vs our slope | **34** |
| ENSO/IOD/NAO/PDO-adjusted trends (RONI) | 33 (data-rule flag) |
| Causal trend budget + counterfactual test | 33 |
| Time-of-emergence map | 33 |
| Literature forest plot (random effects) | 32 |
| "Is extreme X getting more likely?" | 32 |
| Verdict Watch + backtest | 31 |

---

## Headline features

### H1. "Real everywhere, or hidden by the average?"

**User promise:** see which parts of your region truly changed, and whether the regional average hides opposite trends. This targets the challenge sentence about variables trending opposite ways in different places.

**Method**
1. Run Mann-Kendall and Sen's slope on every pixel.
2. Group significant pixels into connected clusters, separately for rising and falling.
3. Shuffle time in 12–24-month blocks, the same way for every pixel. Repeat this 1000 times.
4. Keep only real clusters that are larger than the 95th percentile of the biggest cluster seen in the shuffles.

If this is too slow, fall back to Benjamini-Hochberg FDR at q = 0.10.

**Panel outputs**
- % of area significantly rising and falling, weighted by cos(latitude)
- The regional-mean slope
- A cancellation index, 1 − |Σw·b| / Σw·|b| (our own metric)
- A representativeness score

**Evidence**
- Cortés et al. 2021, GRL, doi:10.1029/2020GL091496: field significance cut significant global greening from **35.2% to 15.3%** of land.
- Pan et al. 2018, RSE, doi:10.1016/j.rse.2018.05.018: browning hidden inside overall greening.

**Data:** Cloud OPeNDAP GPM_3IMERGM, GLDAS_NOAH025_M and M2TMNXSLV; NDVI from an AppEEARS area task. A 40×40×300 grid is about 2 MB per variable.

**Backend:** `backend/spatial/field_sig.py`, `backend/spatial/hidden.py`, `POST /api/spatial/field-significance`. **Effort:** about 8–10 h.

**Example output:** "Regional mean +0.1%/decade (not significant). 31% of the area is significantly greening and 18% browning. The average hides most of the change."

### H2. Resilience check: "Is this system losing its bounce-back?"

**User promise:** find out whether the system now recovers from shocks more slowly than before. The result is tested against 1000 simulated series made of pure chance.

**Method**
1. Take the STL residual and drop 6 months at each end.
2. Compute rolling lag-1 autocorrelation (AC1) and variance over 60-month windows.
3. Measure the trend in each with Kendall τ.
4. Calibrate τ against 1000 Fourier phase-randomised surrogates.
5. Repeat across a robustness grid of 25–75% window lengths and several detrending bandwidths.

**EWS gate.** The label is EWS-VERIFIED only if all of these hold:
- AC1 and variance agree
- The restoring rate λ (statsmodels GLSAR) agrees and the noise colour ρ is not trending
- Gaps are under 5%
- BEAST finds no sensor step
- The record is at least 15 years
- EVI or soil moisture is used instead of NDVI in dense forest

The tool **never gives a tipping date**.

**Evidence**
- Scheffer 2009, doi:10.1038/nature08227
- Dakos 2012, doi:10.1371/journal.pone.0041010
- Boulton, Lenton & Boers 2022, *Nature Climate Change*, doi:10.1038/s41558-022-01287-8 (Amazon resilience loss)
- Smith, Traxl & Boers 2022, doi:10.1038/s41558-022-01352-2
- Boettner & Boers 2022, doi:10.1103/PhysRevResearch.4.013230 (red-noise false alarms)
- Ben-Yami 2024, doi:10.1126/sciadv.adl4841 (why tipping dates should not be extrapolated)

**Library:** ewstools v2.1.3 (MIT). The surrogate test is about 15 lines of numpy.

**Data:** MODIS NDVI/EVI, GLDAS soil moisture, NSIDC sea ice, ERDDAP SST, USGS streamflow.

**Backend:** `backend/insights/resilience.py`, `GET /api/analyze/{series_id}/resilience`. **Effort:** about 8 h.

**Example output:** "Vegetation resilience has declined since about 2012: AC1 τ = 0.62, p = 0.004 against 1000 surrogates. The result is robust in 87% of settings and the noise colour is stable."

### H3. "What do papers say, and do their numbers agree with ours?"

**User promise:** each paper's own sentence and its reported rate, checked against our slope.

**Stance by sentence-level NLI**
1. Test each abstract sentence against "X increased in R" and "X decreased in R".
2. Model: `MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli` (MIT, about 184M parameters, runs on CPU).
3. Calibrate the scores with temperature scaling on about 100 labelled pairs, then set a threshold of about 0.5 for roughly 90% precision.
4. Scope gate: the chosen sentence or the title must name both the variable and the region.

**Rate check**
1. Extract the paper's rate and period with `quantulum3` and regex. Use Qwen only for hard cases, and keep its result only if the text span appears verbatim in the abstract.
2. Skip the comparison when the two periods overlap by less than 0.5 (intersection over union).
3. Compute z = Δb / √(se_p² + se_o²). Call the paper consistent if |z| < 2.

**Evidence**
- SciFact, arXiv:2004.14974
- SummaC, arXiv:2111.09525 (sentence pairs work better than whole documents)
- SciFact-Open, arXiv:2210.13777
- MiniCheck, arXiv:2404.10774
- Dagdelen 2024, doi:10.1038/s41467-024-45563-x (scientific information extraction)

**Backend:** `backend/research/nli.py`, `backend/research/rates.py`, plus new fields in `POST /api/research/evidence`. **Effort:** about 10–12 h.

**Example output:** "Paper: +0.30 °C/decade (1980–2020). Ours: +0.27 ± 0.05 (1981–2020). Consistent, z = 0.5."

---

## Quick wins

| Feature | Promise | Trust step | Hours |
|---|---|---|---|
| **Calibrated wording (IPCC AR6)** | "Very likely" means 90–100% | The term comes from the BEAST sign probability, binned the IPCC AR6 way. Confidence comes from checks passed, record length and agreement. The verifier rejects any other term. `backend/ai/likelihood.py` | 4 |
| **Retraction flags** | Retracted papers never count | OpenAlex `is_retracted` or Crossref `update-to` retraction sets trust to 0, shown struck through. An expression of concern multiplies trust by 0.3. | 3 |
| **Per-pixel BEAST change-year map** | When each place changed | `rb.beast123` on the cube (about 62 s for 40×40×300). Synthetic test: a true 2012.5 break was recovered at 2011.9–2012.8. Pixels are masked where cpPr < 0.5 and confirmed only above 0.8. `POST /api/spatial/change-map` | 3–4 |

## Stretch (priority order)

1. **ENSO/IOD/NAO/PDO-adjusted trends.**
   - Uses RONI, CPC's official ENSO index since 1 Feb 2026.
   - HAC standard errors plus a block bootstrap. The raw trend is always shown next to the adjusted one, labelled "index-regression adjustment".
   - ⚠️ The NOAA CPC/PSL index files are not in the challenge resource list, so the team needs to decide.
2. **Time-of-emergence map** (Hawkins 2020, doi:10.1029/2019GL086259). 3 h.
3. **Causal trend budget and counterfactual detection test.** Uses tigramite LinearMediation and Higgins 2023, doi:10.1038/s41561-022-01114-x. About 16 h.
4. **Verdict backtest:** "What would we have concluded in 2012, 2016 or 2020?" 4 h.
5. **"Is extreme X getting more likely?"** Logistic trend plus BEAST. Answers the 2025 Space Apps challenge text. 6 h.
6. **Literature forest plot** using random effects (statsmodels `combine_effects`), only when 3 or more papers report a rate.
7. **Recovery validation of the resilience indicator** (Smith 2022 method).
8. **Evidence Dossier export** (RO-Crate 1.3).
9. **Local Moran + EOF dipole check** feeding PC1 into PCMCI+.

## Cut

| Feature | Reason |
|---|---|
| Detection-and-attribution lite (log CO2) | Indistinguishable from a time trend |
| Recency consensus index | Weak backing |
| Separate Qwen-judge module | Folded into H3 |
| Emerging hot-spot analysis | Vendor-only backing; dominated by seasonality |
| Area-wide resilience | AppEEARS latency |
| Shapley credit split | Confusing; not causal |
| Leaderboard | Low novelty |

## One flow

```
Question → official data → STL → AR(1)-corrected MK/OLS/Sen
 → calibrated BEAST ──► change-year map
 → field significance + hidden-by-averaging (gridded regions)
 → PCMCI+ suspects → resilience check (EWS gate)
 → active verification (VERIFIED / PROBABLE / NOT VERIFIED) → calibrated likelihood + confidence wording
 → research: retraction filter → NLI stance → rate z-test → agreement
 → best trend → AI text verifier (also enforces the calibrated term) → user
```

## 30-second demo

| Time | Shown |
|---|---|
| 0–8 s | The Sahel NDVI regional mean is "not significant". The map then reveals significant greening and browning patches: "the average hides most of the change". |
| 8–14 s | Scattered false pixels vanish after the permutation test. The change-year map shows when each place changed. |
| 14–22 s | Resilience card: AC1 τ, p against 1000 surrogates, robustness %, and an EWS-VERIFIED or INCONCLUSIVE label. No tipping date. |
| 22–30 s | Research card: a paper's verbatim sentence, "+a vs +b: consistent, z = 0.5", a retracted paper struck through, and the final verdict "very likely increasing, medium confidence". |

## Pitch

Giovanni's best-fit line "does not draw a scientific trend conclusion". Trend Detective does draw one, and every claim must beat a null:

- **Maps:** clusters must be larger than block-permuted chance. With this kind of correction, Cortés et al. 2021 cut significant global greening from 35.2% to 15.3% of land.
- **Resilience loss:** reported only when critical slowing down beats 1000 surrogates and red-noise-robust checks. It never includes a tipping date.
- **Papers:** read sentence by sentence with calibrated NLI, and their reported rates are z-tested against our own slope.
- **Wording:** "very likely" means what IPCC AR6 says it means.

## Open decisions and caveats

- **NOAA climate indices:** may the CPC/PSL files (RONI, IOD, NAO, PDO) be used, given they are outside the listed challenge resources?
- **OpenAlex:** now applies a daily budget without an API key. Register a free key.
- **tigramite:** GPL-3.0, so the repository stays GPL.
- **esda:** used by the Moran/EOF option, needs Python ≥ 3.12.
- **Secondary-only sources:** the Mastrandrea/IPCC guidance note and the Wilks "q = 0.10" rule were verified only through secondary sources or search snippets.
