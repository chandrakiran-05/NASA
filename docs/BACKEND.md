# Backend design notes

This implements `03-architecture.md` division by division. Where the build added to the
design, it is marked **(new)**.

| # | Division | Code | Notes |
|---|---|---|---|
| ① | Frontend | — | next step; see below |
| ② | Backend API | `backend/api/` | stateless endpoints; long work runs as jobs (`backend/jobs/`) persisted in SQLite; interrupted jobs are marked on restart |
| ③ | Catalog | `backend/catalog/` | seed catalog (verified IDs from `02-platforms-and-apis.md`) + `build_catalog.py` output from official listings; BM25 search; region archetypes; source router |
| ④ | Connectors | `backend/connectors/` | common `fetch(variable, region, start, end) → RawSeries`, full provenance |
| ⑤ | Time-series engine | `backend/timeseries/` | parse → QC (source metadata) → monthly (completeness rule) → Parquet |
| ⑥ | Analysis | `backend/analysis/` + `backend/insights/` **(new)** | deterministic, versioned (`methods_version`) |
| ⑦ | Storage / cache | `backend/storage/`, `core/http.py` | raw response cache keyed by request hash; Parquet series; result cache for analyses and insights |
| ⑧ | Auth / ops | `backend/core/` | tokens from `.env` only; 429 + Retry-After back-off; CDO 5 req/s token bucket; GES DISC alerts drive routing |
| ⑨ | Offline AI **(new)** | `backend/ai/` | guardrail, planner, grounded Q&A, fact-checked explanations; deterministic fallbacks |

## Routing (architecture §3)

| Variable family | Point | Area | Fallback |
|---|---|---|---|
| MERRA-2, GLDAS, IMERG, AIRS, OMI | Giovanni `/timeseries` | Harmony `average=area` | Cloud OPeNDAP monthly collection (subset + local area mean) |
| MODIS, SMAP | AppEEARS point task | AppEEARS area task (netCDF → cos-lat mean, QC layer) | — |
| Station temperature / precipitation | NCEI ADS (nearest station via CDO `/stations`, or given ids) | multi-station climate-anomaly average | CDO v2 `/data` |

Variables listed in the GES DISC outage alert (`catalog/data/alerts.json`) skip Giovanni and go
straight to the fallback. If no fallback exists (OMI and AIRS daily) the error says so clearly.

## Verified vs. assumed

| Item | Status |
|---|---|
| Endpoints, auth, IDs, concept IDs in `02-platforms-and-apis.md` | verified by the team on 2026-11-14 |
| Giovanni `/timeseries` request + 13-line CSV header, `/quota` format | **checked against NASA's tutorial** (nasa/gesdisc-tutorials) |
| Harmony `variables=[Giovanni ID]`, `average="area"`, CSV header ending in `,`, `time,mean_<ID>` | **checked against NASA's tutorial** |
| AppEEARS task JSON, status values, bundle names, CSV columns `<PRODUCT>_<VER>_<LAYER>` | **checked against NASA's tutorial** (nasa/AppEEARS-Data-Resources) |
| AppEEARS CSV pre-scaled? | UNVERIFIED in the doc → auto-detected from the valid range; reported in the QC block |
| Cloud OPeNDAP DAP4 hyperslab requests | standard DAP4 syntax; dimension order is read from each collection's DMR |
| Seed units and coverage dates | `*_source: "seed"` until `build_catalog.py` replaces them with official metadata |
| `verified: false` catalog entries (extra GLDAS/MERRA-2/OMI variables, EVI, SMAP) | checked by `build_catalog.py` |

## For the frontend team

- Wizard: `POST /ai/plan` turns the student's sentence into `{variables, regions[].geometry, period}`
  to prefill the What/Where/When steps; `GET /variables?region_type=…` powers the suggestions.
- Map: send Point, BBox or Polygon GeoJSON; `GET /regions/search` gives boxes for place names.
- Chart: `POST /analyze` returns `chart.{time, raw, deseasonalized, stl_trend, ols_line, sen_line}`.
- Result card: `verdict.{arrow, rate_per_decade, rate_units, significant, strength, plain_language, caveats}`
  plus `insights.trend_evidence_index`.
- Extra panels: `insights.triangle` (heat-map matrix), `insights.breaks.segments`,
  `insights.forecast.forecast.{mean, lo80, hi80, lo95, hi95}`, `trendmap` grids for a Leaflet raster.
- Progress: poll `/jobs/{id}?wait=10`; show `message` and `progress`; AppEEARS jobs take about 15 min.
- Demos: `GET /demos`, then `POST /demos/{id}/run` (instant once `build_demos.py` has cached them).
