# R2: Advanced attribution features

All citations below were checked against Crossref. The tigramite v5.2.10.1 source was read. The NOAA index files were downloaded and checked on 2026-11-14.

> **Data-rule note.** The NOAA CPC/PSL/NCEI climate-index files are official NOAA products. They are not on the challenge's resource list, which names NOAA CDO. The team must decide whether to allow them.

> **Licence note.** tigramite is GPL-3.0, so the backend must be released under the GPL.

## 1. Trends adjusted for ENSO, IOD, NAO and PDO

**Model.** Fit, on STL anomalies:

`Y = a + b·t + Σ_k Σ_L c_kL·I_k,t−L + e`

- Lags 0–6, chosen by AIC from a list fixed in advance.
- HAC (Newey–West) standard errors, plus a moving-block bootstrap.
- Run Mann–Kendall on the adjusted series.
- Always show the raw trend next to the adjusted one.

**Indices (all verified live):**

| Index | Source | Notes |
|---|---|---|
| **RONI** | cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt | CPC's official ENSO index since 1 Feb 2026 (NWS pns26-05). It removes tropical-mean warming, so regressing on it does not strip out the forced trend. **Use RONI, not ONI.** |
| ONI | cpc.ncep.noaa.gov/data/indices/oni.ascii.txt | Legacy; for comparison only (ASO 2026: ONI 2.46, RONI 1.97) |
| Niño3.4 | cpc.ncep.noaa.gov/data/indices/sstoi.indices | Monthly, 1982 to Oct 2026 |
| NAO | cpc.ncep.noaa.gov/products/precip/CWlink/pna/norm.nao.monthly.b5001.current.ascii | |
| IOD/DMI | psl.noaa.gov/gcos_wgsp/Timeseries/Data/dmi.had.long.data | Missing value −9999; ends May 2026 |
| PDO | ncei.noaa.gov/pub/data/cmb/ersst/v5/index/ersst.v5.pdo.dat | Missing value 99.99 |
| MEI v2 | psl.noaa.gov/enso/mei/data/meiv2.data | Missing value −999 |
| PSL AMO | amon.us.data | **Avoid**: stops in 2023 |

**Citations**
- Compo & Sardeshmukh 2010, doi:10.1175/2009JCLI2735.1
- Foster & Rahmstorf 2011, doi:10.1088/1748-9326/6/4/044022
- Deser, Terray & Phillips 2016, doi:10.1175/JCLI-D-15-0304.1
- Smoliak 2015, doi:10.1175/JCLI-D-14-00111.1
- Guo 2019, doi:10.1029/2018GL081316
- Sippel 2019, doi:10.1175/JCLI-D-18-0882.1

**Example output.** "After linear ENSO+IOD adjustment, the rainfall trend is +3.1 mm/decade (90% CI 0.8–5.4; raw +4.6)."

**Wording.** Say "index-regression adjustment", never "dynamical adjustment".

**Pitfalls**
- ONI and RONI are 3-month seasons; map each to its centre month.
- Missing-value codes differ between files.
- Indices that contain a trend absorb part of the forced trend.
- Too many lags overfit short records.

**Effort.** About 8 h. Demo: toggle between raw and adjusted across the 2026 El Niño.

## 2. Causal-effect trend budget

**API**
- `tigramite.models.LinearMediation(dataframe, data_transform=None)` keeps physical units.
- `.fit_model(all_parents, tau_max)`, then `get_ce` / `get_mce` / `get_coeff`.
- For confidence intervals: `fit_model_bootstrap(boot_blocklength='from_autocorrelation', boot_samples=500)` and `get_bootstrap_of`.

**Algorithm**
1. Long-run effect: LR = Σ_τ get_ce(X,−τ,Y). The mediated part uses get_mce.
2. Explained trend = LR × trend(X). Share = LR·trend(X) / trend(Y).
3. Joint moving-block bootstrap, with the graph fixed.

**Citations**
- Runge et al. 2015, Nat. Commun. 6:8502, doi:10.1038/ncomms9502
- Kretschmer et al. 2021, BAMS 102:E2247, doi:10.1175/BAMS-D-20-0117.1
- Runge et al. 2023, doi:10.1038/s43017-023-00431-y
- Krich 2020, doi:10.5194/bg-17-1033-2020

**Example output.** "40% (90% CI 15–62%) of the NDVI trend is consistent with the soil-moisture trend propagated through the estimated causal effect; 25% of that is mediated via ET."

**Pitfalls**
- Unoriented `o-o` links: report "not identifiable".
- Hidden confounders.
- Assuming month-to-month effects also hold over decades.
- Shares can exceed 100%.

**Effort.** About 10 h.

## 3. Counterfactual "without driver X's trend" plus a detection test

**Algorithm**
1. Keep the residuals.
2. Set X_cf = X − trend_X.
3. Propagate X_cf forward through the fitted graph.
4. Report trend(Y_cf) with a block-bootstrap confidence interval.

**Detection test.** From Higgins et al. 2023, Nat. Geosci. 16:147, doi:10.1038/s41561-022-01114-x (PDF read).
- Regress observed on modelled values, with zero intercept.
- Attribution holds only if the slope with full drivers is above the slope with detrended drivers, and their confidence intervals do not overlap.
- Driver importance is how much the slope drops when that driver is detrended.

**Alternative.** `CausalEffects(graph,'stationary_dag',X,Y)` with `.fit_total_effect(adjustment_set='optimal')`, `.predict_total_effect`, `fit_wright_effect(mediation=...)`, and bootstrap functions.

**Example output.** "Without the temperature trend, the NDVI trend would be +0.4 (CI −0.2 to 1.0) ×10⁻³/yr instead of +1.9; attribution test passed."

**Effort.** About 6 h if it reuses the model from method 2.

## 4. Shapley / LMG split among correlated drivers

**Algorithm**
1. For every subset S of up to 6 drivers, compute v(S) = the trend of the fitted values from OLS on S.
2. Take Shapley averages, then bootstrap.

**Citations**
- Grömping 2007, doi:10.1198/000313007X188252
- Huettner & Sunder 2012, doi:10.1214/12-EJS710

**Wording.** Call it "shared statistical credit, not causal".

**Effort.** About 4 h, about 30 lines of numpy.

## 5. Detection and attribution "lite" (low priority)

There are no model fingerprints available from our APIs. Regressing on log CO2 (gml.noaa.gov co2_mm_mlo.txt, to Sep 2026) is almost the same as regressing on time. Show it only as a consistency check.

## Rules for all methods

- Results are conditional on the pre-registered graph and suspect list.
- Every share has a confidence interval.
- Suppress shares when the target's trend CI includes 0.
- Report n_eff; if it is below 30, label the result "too short".
- Always show raw and adjusted together.

## Agent's top 2

1. Mode-adjusted trends using RONI (method 1).
2. Causal trend budget plus the Higgins counterfactual test (methods 2 + 3).
