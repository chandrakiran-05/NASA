# API reference

Base URL `http://localhost:8000/api`. Interactive docs at `/docs`; the machine-readable schema is
`docs/openapi.json`. All responses are JSON; errors have the shape
`{"error": {"code", "message", "detail"}}` with codes `invalid_request` (422), `not_found` (404),
`insufficient_data` (422), `credentials_missing` (503), `upstream_error` / `upstream_unavailable` (502).

Long operations return **202 + `job_id`**; poll `GET /api/jobs/{job_id}?wait=10` (long-poll up to 30 s).

## Geometry

```json
{"type": "Point",   "coordinates": [lon, lat], "name": "optional label"}
{"type": "BBox",    "bbox": [west, south, east, north]}
{"type": "Polygon", "coordinates": [[[lon, lat], ...closed ring...]]}
```
Dates: `YYYY`, `YYYY-MM` or `YYYY-MM-DD` (end dates are expanded to the end of the year or month).

## Catalog

| Method | Path | Notes |
|---|---|---|
| GET | `/variables?q=&domain=&region_type=&source=&limit=` | search; `region_type` = archetype id (desert, rainforest, estuary, megacity, cropland, arctic, mountain, monsoon, grassland, wetland) |
| GET | `/variables/{id}` | full metadata, CMR link, DOI, unit conversion, active alerts |
| GET | `/regions/archetypes` | region types with recommended variables and reasons |
| GET | `/regions/search?q=Kerala&point=false` | offline gazetteer → ready-to-use geometry |

## Time series

| Method | Path | Body / params | Returns |
|---|---|---|---|
| POST | `/timeseries` | `{variable_id, geometry, start, end, options?, refresh?}`; `options.stations=["USW00094728"]` for NOAA | 202 `{job_id}` → result `{series_id, cached, completeness, source_api, qc, attempts, notes}` |
| GET | `/jobs/{job_id}?wait=0..30` | | `{status: queued, fetching, processing, done or error, progress, message, result, error}` |
| GET | `/timeseries/{series_id}?view=` | `monthly`, `deseasonalized`, `anomaly`, `annual`, `raw` (alias of monthly) | `{time[], value[], units, completeness, provenance}` |
| GET | `/series` | | stored series index |
| POST | `/timeseries/upload` | `{time[], value[], units, label}` | `{series_id}` |
| POST | `/timeseries/upload-csv` | multipart `file`, `label?`, `units?` (first column = time, first numeric column = value) | `{series_id}` |
| GET | `/export/{series_id}?format=csv or json` | | data + provenance + citation |

## Analysis

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/analyze` | `{series_id, alpha=0.05, deseasonalize=true or stl or climatology or none, mk_variant=auto, include_series=true}` | result contract below |
| POST | `/insights` | `{series_id, which=[detectability, emergence, records, breaks, triangle, forecast], forecast_horizon=60, triangle_min_years=10, min_segment_years=4}` | one block per insight + `trend_evidence_index` + `timings_ms` |
| POST | `/compare` | `{series_ids[2..20], alpha}` | per-region FDR-corrected results, pairwise differences, `divergent` flag |
| POST | `/drivers` | `{target_series_id, driver_series_ids[], max_lag=6}` | best lag, r, p (FDR), sensitivity, trend share |
| POST | `/trendmap` | `{variable_id, geometry (bbox or polygon), start, end}` | 202 job → slope/p grids, significance mask, area fractions rising/falling |
| POST | `/trendmap/upload` | multipart `file` (netCDF), `variable` | same as above, synchronous |

### `/analyze` result (abridged)

```json
{
  "series_id": "s_…", "label": "…", "units": "°C",
  "period": {"start": "2001-01", "end": "2024-12", "n_months": 288, "n_valid": 285, "missing_pct": 1.0, "years": 24.0},
  "deseasonalize_method": "stl", "seasonal_amplitude": 6.1, "climatology": [12 values],
  "ols": {"slope_per_decade": 0.24, "ci95_adj_per_decade": [0.12, 0.36], "p": 1e-9, "p_adj": 2e-4,
          "lag1_autocorr": 0.41, "n_eff": 120.3, "r2": 0.08, "durbin_watson": 1.2},
  "mann_kendall": {"variant": "ess_ar1", "s": 4123, "z": 3.9, "p": 1e-4, "tau": 0.1, "trend": "increasing"},
  "seasonal_mk": {"p": 2e-6, "trend": "increasing", "sen_slope_per_decade": 0.25, "per_season": […]},
  "sen": {"slope_per_decade": 0.25, "ci95_per_decade": [0.15, 0.35]},
  "diagnostics": {"lag1_autocorr": 0.41, "durbin_watson": 1.2, "n_eff": 120.3},
  "verdict": {"direction": "rising", "arrow": "↑", "significant": true, "strength": "strong",
              "tests_agree": true, "rate_per_decade": 0.25, "rate_units": "°C/decade",
              "total_change": 0.6, "headline_p": 2e-4, "plain_language": "…", "caveats": […], "notes": […]},
  "chart": {"time": […], "raw": […], "deseasonalized": […], "seasonal": […], "stl_trend": […],
            "ols_line": […], "sen_line": […]},
  "provenance": {"source_api": "giovanni.timeseries", "dataset_short_name": "M2T1NXSLV", "version": "5.12.4",
                 "concept_id": "C1276812863-GES_DISC", "request_url": "…", "retrieved_at": "…", "doi": "…", "notes": […]}
}
```

## Novelty (team spec F1–F5, plus scan)

| Method | Path | Body / params | Returns |
|---|---|---|---|
| GET | `/timeseries/{id}/integrity` | | F1: `badge` (OK/CAUTION/NOT_FIT), `badge_icon`, `reasons[]`, `coverage`, `flags[]`, `seams[]` (cited, with step test and before/after trends), `trend_or_jump`, `limits` |
| GET | `/analyze/{id}/court` | `alpha` | F3: `stamp`, `chosen_test`, `reason`, `diagnostics`, `jurors[]`, `flips`, `consistency[]`, `cross_examination[]` (also returned as `court` inside `POST /analyze`) |
| GET | `/analyze/{id}/detectability` | `start`, `end` (years, optional), `min_years=10` | F2: `triangle`, `expanding[]`, `years_to_detect`, `window_rank`, `assumptions` |
| POST | `/analyze/nulls` | `{series_id, n_null=1000, n_panels=19, block=12, seed}` | F5: `null_slopes_per_decade[]`, `real_slope_per_decade`, `perm_p`, `lineup.{time, panels, real_index}`, `label` |
| GET | `/variables/{id}/second-opinions` | | F4: other products/stations for the same quantity |
| POST | `/compare` | `{series_ids:[a,b], mode:"product_agreement"}` | F4: `badge` ROBUST/DISPUTED/INCONCLUSIVE, `a`, `b`, `difference`, `slope_difference` |
| POST | `/scan` | `{geometry, start, end, variable_ids? , region_type?}` | 202 job → `ranking[]` (FDR across variables, effect size), `coherence[]`, `failed{}` |

## Investigation and demos

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/investigate` | `{question}` **or** `{variable_id, geometry, start, end}`; `insights[]`, `explain`, `max_regions` | 202 job → `{plan, results:[{series, analysis, insights}], comparison?, explanation}`; off-topic questions get 200 `{on_topic:false}` immediately |
| GET | `/demos` | | demo list with `cached` flag |
| POST | `/demos/{id}/run` | | 202 job → full report |

## Offline AI

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/ai/status` | | provider, model, availability, install hint |
| POST | `/ai/guard` | `{question}` | `{on_topic, score, reasons}` |
| POST | `/ai/plan` | `{question}` | variables, regions (geometry), period, wishes (forecast/compare/drivers), planner used |
| POST | `/ai/ask` | `{question}` | grounded answer, `source` = local_llm or deterministic, `fact_check` |
| POST | `/ai/explain` | `{series_id, include_insights}` | explanation, `source`, `fact_check`, facts used |

## Meta

| Method | Path | Returns |
|---|---|---|
| GET | `/health` | status, version, catalog size |
| GET | `/sources/status?check_quota=false` | which credentials are configured (booleans only), GES DISC alerts, HTTP stats, LLM status, Giovanni quota |
