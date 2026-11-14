# Agent 1 — Scientific & Statistical lens

Note from agent: the docs had no conflicts. No web search was used, so citations are standard references from memory; verify page numbers before quoting.

## 1. "When does it count?": Trend triangle + years-to-detection
- **Pitch:** A matrix of trends for every start/end year, plus a forecast of how many more years until the trend becomes significant.
- **New:** Other teams report one p-value for one window. This answers the challenge's line that "all a trend needs to become significant is a longer period", and shows sensitivity to start/end years.
- **Basis:** Weatherhead et al. 1998 (JGR 103(D14):17149): n* ≈ [3.3·σN/|ω| · √((1+φ)/(1−φ))]^(2/3). Liebmann et al. 2010 (BAMS 91:1485) on start/end-date sensitivity.
- **Data:** Any baseline series. No new fetches.
- **Implementation:**
  - ⑥: `detectability.py` reuses the STL residuals and lag-1 φ, then runs Sen + Hamed-Rao MK over every window of 10+ years (~300 windows, under 1 s).
  - ②: `/analyze` returns `triangle[]` and `years_to_detect`.
  - ①: Plotly heatmap.
- **Feasibility:** High. Risk: overlapping windows are not independent tests, so label the matrix "exploratory".
- **Wow moment:** Drag the end-year slider from 2010 to 2024 and watch cells turn significant. "Not yet significant; at this noise level you need ~7 more years (~2031)."
- **Scores:** Impact 8 · Novelty 8 · Feasibility 9 · Rigor 9 · Demo 9.

## 2. "Same cause, opposite sign": Per-grid-cell trend map with field significance
- **Pitch:** A map of Sen slope and MK result for every grid cell, stippled where it passes an FDR correction, with opposite-sign sub-regions highlighted automatically.
- **New:** Regional averages hide trends that cancel each other out. This shows the challenge's "one way here, opposite there" with proper multiple-testing control.
- **Basis:** Wilks 2016 (BAMS 97:2263): Benjamini-Hochberg with α_FDR = 2α. Benjamini & Hochberg 1995. Held & Soden 2006 ("wet gets wetter, dry gets drier").
- **Data:** Cloud OPeNDAP monthly bbox subsets of GPM_3IMERGM, GLDAS_NOAH025_M and M2TMNXSLV (~290 requests for 2001–2024). Harmony gridded output without averaging is not verified.
- **Implementation:**
  - ④: bbox-cube fetcher.
  - ⑤: xarray cube of anomalies.
  - ⑥: vectorized per-cell MK/Sen + `multipletests('fdr_bh')`.
  - ①: Leaflet raster with stippling; click a cell to see its series.
- **Feasibility:** Medium. Risk: OPeNDAP fetch time. Pre-cache 2 demo regions and cap at ~40×40 cells.
- **Wow moment:** The regional average shows "no significant trend". Toggle the map and two significant patches of opposite sign appear that cancel each other out.
- **Scores:** Impact 9 · Novelty 9 · Feasibility 6 · Rigor 9 · Demo 10.

## 3. "Trend or jump?": Change-point detective
- **Pitch:** Test for a step change (regime shift, sensor or version change, event) before calling something a linear trend.
- **New:** Guards against false trends. A single step makes OLS and MK report a "significant trend".
- **Basis:** Pettitt 1979. Killick et al. 2012 (PELT, `ruptures`). Reeves et al. 2007.
- **Data:** The same series, overlaid with CMR/provenance version dates.
- **Implementation:**
  - ⑥: Pettitt + PELT on the deseasonalized series, then MK per segment. The verdict reads "steady trend", "step change" or "both".
  - ①: shaded regimes on the chart.
- **Feasibility:** High. Risk: spurious breaks in autocorrelated noise. Use a BIC penalty, segments of at least 3 years, and Pettitt p < 0.05.
- **Wow moment:** "Significant warming" gets relabeled "mostly one jump in 2012".
- **Scores:** Impact 7 · Novelty 7 · Feasibility 8 · Rigor 8 · Demo 8.

**Agent recommendation:** Build #1 first, add #2 as the headline visual using pre-cached regions, and add #3 if time allows.
