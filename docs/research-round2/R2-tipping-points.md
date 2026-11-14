# R2: Early warning signals and resilience loss

All DOIs were checked through Crossref. The methods sections were read for Boulton 2022, Smith 2022, Morr & Boers 2024 and Dakos 2012.

**Core papers**
- Scheffer 2009, *Nature*, 10.1038/nature08227
- Dakos 2012, *PLoS ONE*, 10.1371/journal.pone.0041010
- Boers 2021 (AMOC), *NCC*, 10.1038/s41558-021-01097-4
- Boulton, Lenton & Boers 2022, *NCC*, 10.1038/s41558-022-01287-8 (Amazon)
- Smith, Traxl & Boers 2022, *NCC*, 10.1038/s41558-022-01352-2
- Smith & Boers 2023, *Nat. Ecol. Evol.*, 10.1038/s41559-023-02194-7
- Forzieri 2022, *Nature*, 10.1038/s41586-022-04959-9
- Boettner & Boers 2022, *PRR*, 10.1103/PhysRevResearch.4.013230
- Morr & Boers 2024, *PRX*, 10.1103/PhysRevX.14.021037; code on Zenodo, 10.5281/zenodo.11198606 (CC-BY)
- Ben-Yami 2024, *Sci. Adv.*, 10.1126/sciadv.adl4841
- Dakos 2024, *ESD*, 10.5194/esd-15-1117-2024

**Library**
- ewstools v2.1.3, MIT licence, JOSS 10.21105/joss.05038.
- It provides detrending, rolling AC1 and variance, and Kendall τ.
- It does not do surrogate significance testing, so we write that ourselves (about 15 lines of numpy).

## 1. Critical slowing down with a calibrated surrogate test

**Steps**
1. Run STL on the series and keep the residual (trend window about 2 years). Drop 6 months at each edge.
2. Compute rolling AC1 and variance with a 60-month window.
3. Measure the trend in each indicator with Kendall τ against time.
4. Calibrate against surrogates: build 1000 Fourier phase-randomised surrogates of the residual and recompute τ for each. Then p = (#τ_s ≥ τ_obs + 1) / (N + 1).
   - Alternative: an ARMA surrogate selected by AIC (Dakos 2012).
5. Robustness grid: repeat with windows of 25–75% of the series length and several detrending bandwidths. Report the fraction of settings with p < 0.05.

**Data needs**
- At least about 15 years of record.
- Window of at least 48 months.

**Datasets**
- MODIS NDVI/EVI
- GLDAS soil moisture
- NSIDC sea ice
- ERDDAP SST
- USGS streamflow (daily anomalies)

**Example output:** "Vegetation resilience in X has declined since ~2012: AC1 τ = 0.62, p = 0.004 vs 1000 surrogates; robust in 87% of settings."

## 2. Restoring rate λ that works with red noise

**Why:** AC1 and variance give false alarms when the noise itself reddens (Boettner & Boers 2022).

**Steps**
1. In each window, regress Δx on x using `statsmodels GLSAR(rho=1)`. This gives φ̂ and λ ≈ −ln φ̂.
2. If the fitted ρ trends over time, flag the result: the noise colour is changing.

**Option:** λ_PSD (Morr & Boers 2024) outperforms AC1, variance and φ̂ in their ROC/AUC simulations.

**Example output:** "Recovery rate fell from 0.9 to 0.5 per month (p = 0.01); noise colour stable."

## 3. Checking the indicator against observed recoveries (Smith 2022)

**Steps**
1. Find disturbances: 9-month mean difference, Savitzky–Golay smoothing, above the 99th percentile. BEAST change dates can supply candidates.
2. Keep only events where the 5 years before and after look alike (Kolmogorov–Smirnov test).
3. Fit an exponential to the recovery to get the rate r.
4. Compare r with κ = ln(AC1)/Δt.

**Example output:** "The indicator matches the observed post-2015-drought recovery (r = −0.31 vs κ = −0.28 per month)."

## 4. False-positive gate (EWS-VERIFIED / PROBABLE / INCONCLUSIVE)

A result is only verified if all of these hold:
- AC1 and variance agree.
- λ-GLSAR agrees and the noise ρ is not trending.
- Robust across the settings grid.
- Gaps make up less than 5% of the record.
- No sensor step (checked with BEAST).
- Biomass mask: optical NDVI is unreliable in dense forest, so prefer EVI or soil moisture there.

Never extrapolate a tipping date (Ben-Yami 2024).

## 5. Area-wide test with FDR

Compute a surrogate p-value for each pixel, then apply BH-FDR at 0.10.

**Example output:** "38% of forest pixels show a significant AC1 rise."

**Feasibility:** low to medium (AppEEARS latency); cap at about 200 pixels.

## Pitfalls

- The choice of detrending bandwidth matters.
- Leftover seasonality inflates AC1.
- Monthly aggregation lowers AC1 for fast systems: NDVI's characteristic timescale is about 0.8 months.
- Fourier surrogates assume stationarity.

## Agent's top 2

1. Method 1 plus GLSAR λ, behind the method 4 gate.
2. Method 3, checking the indicator against observed recoveries.
