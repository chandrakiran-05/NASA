# 07 — Novelty research: multi-variable trend analysis

**Status:** research notes plus a working first version (`POST /api/scan`). This builds on
`05-novelty-features.md` and `06-feature-spec.md`; it does not replace them. F1–F5 are the core
pitch; the ideas here are candidates for F12 (Trend Scan) and F14 (Evidence Chain), redesigned so
they avoid the reasons those were cut (slowness and overclaiming causation).

## The gap

The challenge says there are too many variables to know which ones are changing, and that the
same process can push a variable one way in one region and the opposite way in another.

Existing tools test **one variable at a time**:
- Giovanni draws one series and a regression line with no significance test.
- AppEEARS extracts layers but does not test them.
- KNMI Climate Explorer correlates two series but does not scan a region.

No student-facing tool answers: *"In this box, which of the NASA variables are really changing,
after correcting for testing many of them, and do their trends tell a physically consistent story?"*

The statistical pieces all exist in the literature: FDR across many tests, multivariate and
seasonal Mann-Kendall, sign-consistency checks. Their combination into one guided "case" for a
region is the novel part.

## Implemented now (v1): Trend Scan + Earth-System Coherence

`POST /api/scan {geometry, start, end, variable_ids? | region_type?}` → job. Code: `backend/novelty/scan.py`.

1. Builds and analyses each variable for the same region and period (default: the region-type
   recommendations from `catalog/data/archetypes.json`).
2. **FDR across variables** (Benjamini-Hochberg), using the conservative p of the two calibrated
   tests. This is the "35% → 15% greening" lesson (Cortés et al. 2021) applied to variables
   instead of pixels.
3. **Ranks by effect size**: change per decade in standard deviations of the deseasonalized
   series, so variables with different units can be compared.
4. **Coherence check**: for each physically linked pair in `catalog/data/links.json` (rain → soil
   moisture → NDVI, NDVI ↔ surface temperature, air temperature → snow…), it checks whether the
   trend signs match the expected relationship, giving *consistent / inconsistent / not testable*.

An **inconsistent** link is the interesting finding. For example, rainfall falling while NDVI
rises points to irrigation, CO₂ fertilisation, a data seam (→ F1), or a local driver. It turns
the tool into a detective rather than a calculator, and it never claims causation.

## Candidate next steps (ranked by value ÷ effort)

| # | Idea | What the user sees | Method | Effort | Risk |
|---|---|---|---|---|---|
| R1 | **Detection race** | "Of the variables changing here, which one will we be sure about first?" A countdown per variable | Weatherhead n* (already in F2) per variable from the scan | S: reuse `evidence_clock` per scan row | low |
| R2 | **Season of change** | "The trend is all in the monsoon months" — a 12-bar chart | per-calendar-month Sen slopes + MK (`seasonal_mk.per_season` already computes S per month) | S | low |
| R3 | **Joint (multivariate) trend test** | "Each signal alone is weak, but together the drying story is significant" | Correlated multivariate Mann-Kendall (Lettenmaier 1988; Hirsch & Slack covariance) across a linked chain | M | medium: explain clearly |
| R4 | **Lead-lag cascade** | Arrows rain → soil (1 mo) → NDVI (2 mo) with lags | detrended lagged correlation with Bretherton n_eff (already in `insights/drivers.py`) along `links.json` chains | M | association, not causation |
| R5 | **Trend budget** | "About 60% of the NDVI decline is consistent with the rainfall decline" (waterfall chart) | interannual sensitivity × driver trend (drivers module), several drivers at once | M | needs careful wording |
| R6 | **Means vs extremes** | "Average rainfall is flat, but the wettest days are getting wetter" | monthly maxima / 95th percentile from daily IMERG, same tests | M | more data per request |
| R7 | **Opposite-trend map** | Inside one box, which pixels rise and which fall (the challenge's "one way here, the opposite way there") | already in `/api/trendmap` (`area_fraction_rising/falling`); add a scan over several variables | L (quota) | Giovanni quota |

**Recommendation:** ship v1 (done) + **R1 and R2** for the pitch, since both are cheap and reuse
validated code. R3 is the strongest scientific novelty if there is time; present it as "a joint
test for a story told by several variables."

## How it plugs into the pitch

*"Trend Detective checks four things before it calls a trend significant (F1–F4) and then asks
the question nobody asks: which of the other NASA variables in your box agree, and do they tell a
physically consistent story?"*

- Demo idea: **Punjab cropland**. Rainfall is flat or falling, yet NDVI and ET are rising. The
  coherence check flags the link as inconsistent, and the explanation is irrigation (groundwater).
  This is a well-documented real phenomenon worth verifying on the real data before claiming it.
- Second demo: **Tamil Nadu**. Air temperature, land-surface temperature and humidity all rise
  consistently, while rainfall is "not yet" detectable (F2 countdown).

## Honest limits

- `links.json` encodes simple expected signs; in energy-limited regions (cold, wet) some links
  reverse (e.g. greenness can rise with temperature). The scan reports `not_testable` when
  neither trend is significant, and the wording is always "consistent with".
- Testing ~5–8 variables means 5–8 data requests; AppEEARS ones take ~15 min. Pre-cache demos.
- Effect sizes in SD/decade depend on the noise level of each product; compare directions and
  significance first, magnitudes second.

## References to verify before the pitch

Cortés et al. 2021 (GRL, doi:10.1029/2020GL091496); Lettenmaier 1988 (multivariate MK);
Hirsch & Slack 1984 (WRR); Bretherton et al. 1999 (J. Climate); Weatherhead et al. 1998 (JGR).
