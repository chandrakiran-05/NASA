# Pain points from Stack Exchange and Stack Overflow

**How the evidence was gathered**
- The question bodies were read through the public Stack Exchange API (api.stackexchange.com/2.3). The scores and view counts are real.
- The answers were not read.
- Quora produced no relevant threads, so it is not cited.

| # | Pain point | Evidence (votes / views) | Feature idea |
|---|---|---|---|
| 1 | Which trend test should I use: Mann-Kendall (MK), OLS or chi-square? | stats.stackexchange.com/questions/512049 (5 / 20.3k, deforestation analyst, 19 yrs); /147819 (5 / 2.7k) | A method recommender that checks normality, n and autocorrelation, then explains its choice and gives a citation |
| 2 | Autocorrelation correction (prewhitening, block length) is confusing | stats.../160776 (21 / 3.0k); /221072 (10 / 19.4k); gis.stackexchange.com/questions/291945 (2 / 2.4k) | Raw MK, TFPW-prewhitened MK and modified MK side by side, with an ACF badge and a flag when the conclusion flips |
| 3 | Contradictory output: MK says significant but the Sen slope is 0 | stats.../557979 (4 / 3.4k, asked on several forums) | A consistency checker that explains ties and rounding |
| 4 | When to use the Seasonal Kendall test; results change with aggregation | stats.../138138 (5 / 995, 0 answers); /478340 (pymannkendall daily vs monthly, 0 answers) | An automatic seasonality test (Kruskal-Wallis by month) that picks the test, with results shown at daily, monthly and annual resolution |
| 5 | Start/end-date sensitivity (cherry-picking) | stats.../12988 (2 / 278, global-warming "lapse"); /419351 (3 / 714) | A robustness triangle: a heatmap over every start × end window |
| 6 | Comparing trends between regions or products | stats.../19103 (**80 / 235k**, top hit); /489219 (4 / 230); earthscience.stackexchange.com/questions/884 (9 / 646, conflicting sea-ice trends) | Region A vs B, or product vs product, with a slope-difference test and CIs |
| 7 | Abrupt change vs gradual trend | stats.../116363 (23 / 10.4k); /670302 (2025, BFAST around COVID); /659446 (2025) | A Pettitt/PELT change-point overlay showing the trend before and after the break |
| 8 | Summarizing per-pixel trend maps; no awareness of FDR | gis.../475383 (2024, 0 answers) | An FDR significance mask and "% of area significantly up or down" |
| 9 | Per-pixel trends are slow and break on NoData or irregular dates | stackoverflow.com/questions/46856314 (2 / 9.1k); gis.../220338 (5 / 1.7k); /210705 (6 / 3.2k) | Vectorized MK/Sen with a minimum-valid-observations threshold |
| 10 | Fill values and QC flags contaminate the series | gis.../407354 (MOD11A1 QC); /277110 (NDVI fill); earthscience.../18453 (MERRA-2 missing over land) | A provenance panel showing the % masked per time step, with a warning for missing months |
| 11 | Minimum coverage for a valid monthly mean | earthscience.../7411 (6 / 282, MODIS/AIRS/OMI) | A user-set coverage threshold that greys out low-coverage months |
| 12 | Area averages over custom polygons; time zones | gis.../435930 (Giovanni lacks shapefile upload for IMERG); /351102 (IMERG UTC vs local); stackoverflow.../76184467; /79951814 (2026, Earthdata S3 403) | GeoJSON upload with cos-latitude weighting and explicit UTC labels |

**Sensor discontinuities:** this pain point has no strong forum evidence. Its support comes from the literature only.

## Top 3 picked by the agent
1. A robustness triangle with a change-point overlay (#5 and #7).
2. An autocorrelation-aware "method verdict" that runs several tests side by side and explains where they disagree (#1–#4). Two of these questions have 235k and 20k views.
3. A data-quality and coverage panel that excludes low-coverage months (#10 and #11).
