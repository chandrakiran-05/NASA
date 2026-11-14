# Statistical methods

All methods come from the challenge resources (SeaWiFS paper, the Medium article on trend tests,
the Statsig significance guide) or from the peer-reviewed literature cited below.

## Pipeline

1. **Monthly series.** Native data (hourly, 3-hourly, daily, 8/16-day, monthly) are QC-masked
   using the source's own metadata, then averaged into months. A month is kept only if ≥70% of
   its days are valid (configurable). Gaps stay missing; nothing is interpolated.
2. **Remove the seasonal cycle.** STL (`period=12, robust=True`). STL cannot accept gaps, so they
   are filled *only to fit the decomposition*; every output and test sees them as missing again.
   An alternative is anomalies against the monthly climatology.
3. **Trend tests** on the deseasonalized series (Seasonal MK uses the raw monthly series).
4. **Verdict.** A trend is reported as significant only if the AR(1)-adjusted regression test
   and the Mann-Kendall test both reject at α and agree in sign with Sen's slope. The headline
   rate is Sen's slope (robust to outliers).

## Tests

| Test | Implementation | Validated against |
|---|---|---|
| OLS slope, t-test, 95% CI | closed form | `scipy.stats.linregress` (identical) |
| AR(1)-adjusted OLS | n_eff = n(1−r₁)/(1+r₁), t with n_eff−2 dof (Santer et al. 2000) | calibration study below |
| Mann-Kendall S | O(n log n) Fenwick tree over dense ranks, tie-corrected variance | brute force O(n²), pymannkendall (identical) |
| MK Hamed-Rao, Yue-Wang, TFPW | as in pymannkendall | pymannkendall (identical; TFPW within 1e-3) |
| **MK ess_ar1 (default)** | variance × [1 + 2Σ(1−k/n)r₁ᵏ], r₁ of the Sen-detrended series, small-sample bias corrected | calibration study below |
| Seasonal Mann-Kendall + seasonal Sen | Hirsch, Slack & Smith (1982) | pymannkendall (identical) |
| Sen's slope + CI | Sen (1968) eq. 2.6, compiled pairwise slopes | `scipy.stats.theilslopes` (identical) |

## Why the default Mann-Kendall variant is `ess_ar1`

Monthly Earth-science anomalies are persistent: one month resembles the next. Persistence makes
a series look trendier than it is, so tests that ignore it report too many false trends. We
simulated 400 trend-free AR(1) series of 240 months for each persistence level φ and counted how
often each test wrongly reported a significant trend at α = 0.05. A well-calibrated test stays
near 0.05. Reproduce with `python scripts/calibration_study.py`.

| φ | OLS naive | **OLS AR(1)-adj** | MK original | MK Hamed-Rao* | MK Yue-Wang* | MK TFPW* | **MK ess_ar1** |
|---|---|---|---|---|---|---|---|
| 0.0 | 0.040 | **0.035** | 0.028 | 0.072 | 0.490 | 0.030 | **0.025** |
| 0.3 | 0.155 | **0.058** | 0.133 | 0.107 | 0.475 | 0.165 | **0.055** |
| 0.5 | 0.233 | **0.060** | 0.235 | 0.160 | 0.480 | 0.318 | **0.048** |
| 0.7 | 0.350 | **0.048** | 0.365 | 0.160 | 0.482 | 0.495 | **0.040** |
| 0.85 | 0.613 | **0.050** | 0.600 | 0.245 | 0.540 | 0.777 | **0.045** |

\* pymannkendall defaults. Yue-Wang with all lags is broken even for white noise: the biased
autocorrelations of a mean-removed series always sum to about −½, which removes most of the
variance. The other variants remain available through `mk_variant` for comparison; the tests in
`tests/test_statistics.py` pin both their exact equality with pymannkendall and the calibration
of the defaults.

The price of honesty is power. With strong persistence (φ = 0.7), a trend of 0.5 standard
deviations per decade over 20 years is detected about 45% of the time by the calibrated tests.
The liberal tests look more powerful only because they also fire when there is no trend. This
is exactly the situation the **detectability horizon** explains to the user.

## Insight models

| Model | Method | Reference |
|---|---|---|
| Detectability horizon | n* = [3.3σ/|ω| · √((1+φ)/(1−φ))]^(2/3) years; 95% bounds n*·e^(±B) | Weatherhead et al. 1998, JGR 103(D14) |
| Time of emergence | first year when the fitted change ≥ k × σ(annual noise), k = 1, 2; plus observed 5-yr running mean | concept: Hawkins & Sutton 2012, GRL |
| Record-breaking | record highs/lows vs H_n = Σ1/i expected without a trend | Benestad 2003 |
| Trend breaks | PELT, piecewise-linear RSS cost in O(1) via prefix sums; penalty 3σ²ln(n)·(1+φ)/(1−φ); BIC check | Killick et al. 2012, JASA |
| Trend triangle | OLS + AR(1)-adjusted p for every start/end window ≥10 yr, O(1) per window | Liebmann et al. 2010, BAMS |
| Projection | seasonal naive, harmonic + AR(1), damped Holt-Winters, Theta; inverse-MASE² weights from rolling-origin CV; split-conformal bands plus trend-uncertainty cone | Assimakopoulos & Nikolopoulos 2000; Vovk et al. 2005 |
| Regional contrast | Benjamini-Hochberg FDR across regions; slope-difference z-tests | Statsig guide; Benjamini & Hochberg 1995 |
| Driver hints | detrended anomalies, lagged r with n_eff (Bretherton et al. 1999), FDR, sensitivity × driver trend | Bretherton et al. 1999, J. Climate |
| Trend maps | per-pixel OLS-adj + MK, BH-FDR at 2α (field significance) | Wilks 2016, BAMS |

Measured behaviour (tests in `tests/test_insights.py`): PELT gave 0 false breaks in 30 trend-only
AR(1) series and found a planted trend reversal in 30/30 (date within ±4 years in ≥17/20);
the forecast's empirical 80/95% coverage in back-tests is reported with every projection.

## Trend Evidence Index (TEI)

A 0–100 summary for students; every component is returned so the score is never a black box.

| Component | Weight | 1.0 when… |
|---|---|---|
| Significance | 0.35 | both calibrated tests p < 0.01 (0.75 if < 0.05; 0.4 if only one) |
| Robustness | 0.25 | all ≥10-yr windows are significant with the same sign |
| Detectability | 0.15 | record length ≥ years needed |
| Emergence | 0.15 | current signal ≥ 2 × annual noise |
| Records | 0.10 | excess of record years is significant (p < 0.05) |

Labels: ≥75 Confirmed trend · ≥50 Likely trend · ≥25 Emerging or uncertain · otherwise No trend detected.
