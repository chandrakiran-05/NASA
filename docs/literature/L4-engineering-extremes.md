# L4: Engineering, extremes, emergence and heat (agent report)

All DOIs below were checked against Crossref or OpenAlex. **[snippet]** means only a search-engine snippet was seen.

## 1. "Design storm drift": nonstationary GEV return levels
- **What it does:** fits a GEV distribution to annual-maximum daily rain, letting the location parameter drift with time (μ = μ0 + μ1·t). A likelihood-ratio test compares this against a stationary fit.
- **Papers:**
  - Cheng & AghaKouchak 2014, *Sci. Rep.*, 10.1038/srep07093 (NEVA)
  - Ragno et al. 2018, *WRR*, 10.1002/2017WR021975
  - **Wright, Bosma & Lopez-Cantu 2019, *GRL*, 10.1029/2019GL083235.** Trends in rare storms can't be detected at single points because the signal-to-noise ratio is too low. Pooling across a region shows that 100-year storms have become more frequent across much of the US.
  - Vinod & Mahesha 2024, *Urban Climate*, 10.1016/j.uclim.2024.102065
  - On the limits of the method: Serinaldi & Kilsby 2015, *Adv. Water Resour.*, 10.1016/j.advwatres.2014.12.013
- **Libraries:**
  - `scipy.stats.genextreme` plus a custom MLE (BSD)
  - `climextremes` 0.3.1 (BSD; needs the R package extRemes)
  - `pyextremes` 2.6.1 (MIT; stationary fits only)
- **Output:** "1-in-50-yr daily rain went from X to Y mm between 2001 and 2025 (90% bootstrap CI); the nonstationary model is preferred, p = …"
- **Data:** GPM_3IMERGDF V07 `precipitation`, or NOAA GHCN-D `PRCP`.
- **Caveats:**
  - IMERG gives about 25 annual maxima, which is the bare minimum. Pool across the region.
  - Show the wide CIs.
- **Feasibility:** High.

## 2. Satellite IDF table
- **What it does:** builds intensity-duration-frequency (IDF) curves from IMERG for durations of 1–24 h and return periods of 2–100 yr.
- **Papers:**
  - Ombadi et al. 2018, *WRR*, 10.1029/2018WR022929
  - Li et al. 2022, *J. Hydrol.*, 10.1016/j.jhydrol.2021.127357 [snippet]. The IMERG Final run captures extremes best.
- **Data:** GPM_3IMERGHH (half-hourly). The volume is large, so use a single point or a small box.
- **Caveat:** label every output "screening only, not a design value".
- **Feasibility:** Medium.

## 3. Time-of-emergence gauge (familiar / unusual / unfamiliar)
- **What it does:** regresses the local series on global mean temperature. S/N is the fitted signal divided by the residual standard deviation. The labels are S/N > 1 "unusual", > 2 "unfamiliar" and > 3 "unknown".
- **Papers:**
  - Hawkins et al. 2020, *GRL*, 10.1029/2019GL086259
  - Murphy et al. 2023, *Weather Clim. Extremes*, 10.1016/j.wace.2023.100608 (station level, 16 indices)
- **Data:**
  - MERRA-2 M2T1NXSLV T2M, aggregated to daily (record starts 1980).
  - NASA GISTEMP global mean temperature, as suggested by the agent. **GISTEMP is not in the challenge resources.** Use the MERRA-2 global-mean T2M instead, or just use time as the covariate.
- **Feasibility:** High.

## 4. ETCCDI extremes scorecard
- **What it does:** computes the standard extremes indices Rx1day, Rx5day, CDD, CWD, R20mm, SDII, TX90p, SU25 and TR20, then tests each one with MK and Sen's slope.
- **Papers:**
  - Alexander et al. 2020, *ERL*, 10.1088/1748-9326/ab79e2. Products disagree most on frequency indices such as R20mm, and reanalyses disagree most of all.
  - Dunn et al. 2020, *JGR-Atmos* (HadEX3), 10.1029/2019JD032263
- **Libraries:**
  - `xclim` 1.0.0 (Apache-2.0; Bourgault et al. 2023, *JOSS*, 10.21105/joss.05415)
  - `pymannkendall`
- **Data:** IMERG daily, plus MERRA-2 daily Tmax/Tmin.
- **Feasibility:** High.

## 5. Drought: SPI/SPEI and soil-moisture percentile trend
- **What it does:** builds the SPI and SPEI drought indices and tracks the trend in drought frequency.
- **Paper:** Vicente-Serrano et al. 2010, *J. Climate*, 10.1175/2009JCLI2909.1
- **Libraries:** `climate-indices` 3.2.0, or xclim.
- **Data:** GPM_3IMERGM precipitation; GLDAS 2.1 `PotEvap_tavg` and `SoilMoi0_10cm_inst`.
- **Caveat:** around 30 yrs of data is preferable, so IMERG is marginal.
- **Feasibility:** High.

## 6. Humid-heat days (wet-bulb / WBGT)
- **What it does:** counts days above wet-bulb thresholds of 26, 28 and 31 °C and tracks the trend in that count.
- **Papers:**
  - Raymond, Matthews & Horton 2020, *Sci. Adv.*, 10.1126/sciadv.aaw1838. Extreme humid heat has more than doubled since 1979, but reanalyses underestimate it.
  - Vecellio et al. 2022, *J. Appl. Physiol.*, 10.1152/japplphysiol.00738.2021 [snippet for the finding]
  - Kong & Huber 2022, *Earth's Future*, 10.1029/2021EF002334 [snippet]
- **Library:** `thermofeel` (Apache-2.0; Brimicombe et al. 2022, *SoftwareX*, 10.1016/j.softx.2022.101005).
- **Data:**
  - MERRA-2 T2M, QV2M and PS.
  - M2T1NXRAD for WBGT.
  - Avoid `T2MWET`, which is reported on a forum to be roughly equal to dew point.
- **Caveat:** frame the output as a trend, not an absolute level.
- **Feasibility:** Medium-High.

## 7. Fit-for-extremes trust badge
- **What it does:** compares each grid cell with the nearest GHCN-D station on three things: bias in annual maxima, hit rate for days above the 95th percentile, and whether the trend has the same sign.
- **Papers:** Li 2022; Alexander 2020.
- **Feasibility:** High.

## Agent's top 2
1. **Design storm drift** (regionally pooled) plus the trust badge.
2. **Time-of-emergence gauge** plus the xclim ETCCDI scorecard.
