# Agent 4: Earth-System Connections lens

The agent cited these sources from memory without verifying them; check them before quoting. All datasets come from the verified tables in 02-platforms-and-apis.md.

## 1. Evidence Chain Explorer
- **Pitch:** Pick a region and a process story, for example drought. The tool shows a linked chain: precipitation ↓ → soil moisture ↓ → NDVI ↓ → LST ↑.
  - Each link gets its own trend verdict.
  - Each arrow shows the lagged association between its two ends.
- **New:** Turns separate variables into a mechanism. The challenge asks teams to relate trends to processes.
- **Basis:** Seneviratne et al. 2010 (Earth-Sci Rev); Vicente-Serrano et al. 2013 (PNAS); Bretherton et al. 1999 (effective degrees of freedom).
- **Data:**
  - GPM_3IMERGM (Giovanni).
  - Soil moisture: GLDAS_NOAH025_M SoilMoi0_10cm via the OPeNDAP fallback (Giovanni v2.1 is UNVERIFIED and GLDAS 3H is in an outage), or SPL3SMP_E for 2015 onward.
  - MOD13A3 NDVI and MOD11A2 LST (AppEEARS).
- **Implementation:**
  - ③ `chains.json`: curated links with the expected sign and a physical rationale.
  - ⑥ `POST /api/relate`: detrended STL anomalies, lag 0–6 cross-correlation, effective-degrees-of-freedom p.
  - ① Chain diagram.
  - Always say "consistent with", never "caused by".
- **Feasibility:** Medium to high. Risk: the soil-moisture source, and AppEEARS taking about 15 minutes, so precompute the demos.
- **Wow moment:** California Central Valley 2012–16. The chain lights up link by link, and NDVI lags soil moisture by 1–2 months.
- **Scores:** Impact 9 · Novelty 9 · Feasibility 7 · Rigor 8 · Demo 9.

## 2. Three Witnesses: multi-source trend confidence
- **Pitch:** Satellite, reanalysis model and NOAA ground station act as independent witnesses for the same quantity. Agreement between them raises confidence.
  - Temperature: MERRA-2 T2M, AIRS SurfAirTemp, NOAA GSOM TAVG, DAYMET.
  - Precipitation: IMERG, NOAA PRCP, DAYMET.
- **New:**
  - A confidence badge in the IPCC AR6 calibrated-language style (agreement × evidence; Mastrandrea et al. 2010).
  - A trend test on the difference series catches station problems.
  - Independence tags record sources that share inputs.
- **Basis:** Weatherhead et al. 1998; Santer et al. 2000 (comparing trends using effective sample size).
- **Implementation:**
  - ③ Quantity groups with independence tags.
  - ⑤ Unit harmonization and a common overlap period.
  - ⑥ Cross-source `/api/compare`: per-source Sen slope + CI, a trend-difference test, and an agreement score.
  - ① Witness panel.
- **Feasibility:** High. Risk: a single station may not represent a whole grid cell.
- **Wow moment:** Three sources agree at about +0.3 °C per decade with overlapping CIs, earning a "High confidence" badge. A station with a step in its difference series gets flagged.
- **Scores:** Impact 8 · Novelty 7 · Feasibility 9 · Rigor 9 · Demo 8.

## 3. Heat Island Twin
- **Pitch:** Draw a city and the tool generates a rural ring around it. It then shows the trend in urban minus rural LST, day and night, alongside the NDVI difference.
- **New:** Differencing removes the shared regional signal, so a land-use trend shows up sooner.
- **Basis:** Peng et al. 2012 (ES&T, 419 cities); Imhoff et al. 2010 (RSE).
- **Data:** MOD11A2 LST day and night and MOD13A3 NDVI (AppEEARS area tasks). Optionally NCEI station pairs.
- **Feasibility:** High. Risk: there is no land-cover product in the verified tables, so the ring may include water or other towns.
- **Wow moment:** "Phoenix nights warmed X °C per decade faster than its countryside (p < 0.05)."
- **Scores:** Impact 8 · Novelty 6 · Feasibility 9 · Rigor 8 · Demo 9.

**Agent recommendation:** Build #2 into the core first. Make #1 the headline feature. Use #3 as a guided demo.
