# Challenge: Be An Earth System Trend Detective! (NASA Space Apps 2026)

Source: https://www.spaceappschallenge.org/2026/challenges/earth-system-trend-detective/
Scraped: 2026-11-14 (Details + Resources tabs). Difficulty: Advanced. Subjects: Earth Science, Software.

## The task (summary)
Build a tool that:
1. **Selects** variables measured by Earth science missions or produced by models.
2. **Acquires** that variable for a particular **region** (most trends are regional).
3. **Generates and visualizes a time series** long enough for statistical analysis.
4. **Analyzes** it: rate of change over time + **significance** (t-test, Mann-Kendall, or confidence intervals).

A response that does both visualization and analysis meets the full scope.

Named instruments/models: MODIS, OMI, AIRS, GPM (instruments); MERRA-2, GLDAS (models).

## Potential considerations (from the page)
- Audience: high-school/college students and the science-literate public → simple variable definitions.
- Approach: short question series (what / where) → search related variables; include 1–2 watchable demo examples. Optional "SI" (likely AI) to suggest variables for region types (desert, rainforest, estuary, city atmosphere).
- Daily and monthly data are easiest. A non-significant trend is still interesting; longer records may make it significant.
- Remove the seasonal cycle before trend testing; linear trends are enough for scope.
- Optional: CUAHSI hydrology plotting tools.

## Resources tab (verbatim list)
### NASA Data & Resources
| Resource | URL |
|---|---|
| Giovanni | https://giovanni.gsfc.nasa.gov/ |
| Hydrology Time Series | https://disc.gsfc.nasa.gov/information/tools?title=Hydrology%20Time%20Series |
| AppEEARS | https://appeears.earthdatacloud.nasa.gov/ |
| Climate Data Online (CDO) | https://www.ncei.noaa.gov/cdo-web/ |
| SeaWiFS Chlorophyll time-series paper | https://ntrs.nasa.gov/api/citations/20090042747/downloads/20090042747.pdf |

### Space Agency Partner Resources
| Resource | URL |
|---|---|
| KNMI Climate Explorer | https://climexp.knmi.nl/ |
| Statistical test methods to detect trends | https://medium.com/@snp.kriss/statistical-test-methods-to-detect-trends-in-time-series-data-b361a0ec530b |
| Comprehensive Guide to Statistical Significance | https://www.statsig.com/perspectives/a-comprehensive-guide-to-statistical-significance |
| CSA – RADARSAT Constellation Mission data | https://donnees-data.asc-csa.gc.ca/en/dataset/rcm |
| Geo.ca | http://geo.ca/ |
| CSA – SWOT mission info | https://www.asc-csa.gc.ca/eng/satellites/swot/ |
| CSA – Monitoring ecosystems from space | https://www.asc-csa.gc.ca/eng/satellites/everyday-lives/monitoring-and-protecting-our-ecosystems-from-space.asp |
| CSA – SAR Python tutorial | https://github.com/asc-csa/Synthetic_Aperture_Radar_Tutorial |
