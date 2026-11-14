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

## Active trends (live, verified) — `backend/active/`

"What is changing **now**?" For each variable: the last W = clip(N/3, 10, 15) years are tested against
the years before (AR(1)-corrected Mann-Kendall + AR(1)-adjusted OLS). Candidates then go through
independent checks that run concurrently and stream as they finish, and finally a calibrated BEAST gate.

| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | `/criteria` | | the 28 criteria: `id`, `n`, `name`, `definition`, `status` (live / proxy / short_record / not_trendable), `variables[]`, `note`, `where_to_look[]`, `missing_variables[]` |
| POST | `/active-trends` | `{geometry, start, end, criteria?[], variable_ids?[], per_criterion=1, options{}, alpha, ai_review=true}` **or** `{series_ids[]}` | 202 `{job_id, variables[], skipped[], events_url, stream_url, status_url, reused}`. Identical requests return the same job (`reused:true`), so the UI may start a scan while the student is still typing. |
| GET | `/active-trends/{job_id}/events` | `after=0`, `wait=0..30` | `{events[], next, done}` (long-poll) |
| GET | `/active-trends/{job_id}/stream` | `after=0` | Server-Sent Events, one event per step; ends after `done` / `error` |
| GET | `/jobs/{job_id}` | | final result (below) |
| POST | `/active-trends/{job_id}/deep-review?top=3` | | 202 job: optional AirLLM reviewer on the top trends (advisory, slow); also emits `deep_review` events |
| GET | `/ai/hardware` | | GPU/RAM/disk profile and the live/deep model that fits it |

**Event types** (each has `seq`, `type`, `t`, usually `variable_id`): `started`, `fetching`, `fetched`,
`candidate` / `not_active` (`state`, `plain_language`, `rate_per_decade`, `units`), `check`
(`check`, `status` pass/warn/fail/skipped, `plain_language`, `detail`), `beast_started`, `beast`
(`status` agrees/disagrees/uncertain/skipped, `active_since`), `verdict` (`provisional` true after BEAST,
false once the cross-variable checks are in), `failed`, `done`, `error`.

**States:** `active` (trend continues), `accelerating`, `emerging` (not detectable before the window),
`reversed`, `stalled` (full-record trend not detectable recently), `none`, `too_short` (< 15 years).

**Checks:** `integrity` (F1; seams/jumps near the window start), `court` (F3 on the recent window),
`chance` (F5 block bootstrap), `stability` (nearby windows give the same answer), `physics` (sign
coherence with linked active variables), `second_opinion` (other product of the same quantity in the scan),
`fdr` (Benjamini-Hochberg across scanned variables), `ai_review` (local LLM, advisory, never changes the label).

**Labels:** `VERIFIED` (no failed check, ≥ 3 passed, BEAST agrees, regime start not at a seam),
`PROBABLE`, `NOT VERIFIED`. Show `verdict.limit`: VERIFIED is not a cause and not a forecast.

Result: `{trends:[{variable_id, name, series_id, criteria[], detect, checks[], beast, verdict, ai_review?}],
not_active[], failed{}, skipped[], summary, plain_language, method, limits[]}`.

## Digital twin (separate mode) — `backend/twin/`

A sandbox for engineers. Research data (e.g. from the chatbot team) is stored as-is: it does **not** go
through integrity, Trend Court, active-trend checks or BEAST. Each variable gets a fitted baseline
(monthly climatology + linear trend + AR(1) noise); simulations continue it forward under what-if knobs.

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/twin` | `{name, description?}` | `{id, name, variables: []}` |
| GET | `/twin` | | all twins |
| GET | `/twin/{id}` | | twin + `variables[].baseline.{slope_per_decade, slope_se_per_decade, noise_sd, lag1_autocorr, last_observed}` |
| POST | `/twin/{id}/data` | `{source?, variables:[{name, units?, time[], value[]}]}` | twin (same name re-uploaded = replaced; upload order matters for drivers) |
| POST | `/twin/{id}/import` | `{series_id, name?}` | one-way copy of a main-mode series into the twin (original untouched) |
| POST | `/twin/{id}/data-csv` | multipart `file` (date column, then one numeric column per variable), `source?` | twin |
| POST | `/twin/{id}/simulate` | `{horizon_years=30, n_runs=500, seed, scenario:{<name>:{trend_multiplier, trend_add_per_decade, shocks:[{year,size}], drivers:[{from, coefficient}], threshold:{value, direction:"above"|"below"}}}}` | `variables.<name>.{time[], p05[], p50[], p95[], baseline, threshold.{probability_by_end, median_first_crossing, earliest_10pct, plain_language}}`, `disclaimer` |
| POST | `/twin/{id}/compound` | `{conditions:[{variable, value, direction}] (1–5), scenario?, horizon_years, n_runs, seed}` | `probability_same_year[{year, p}]` (share of runs where all conditions are met in the same calendar year), `probability_by_end`, `conditions[].probability_by_end` (equals `/simulate` for that threshold), `plain_language`, `label:"simulated"`, `disclaimer` |
| POST | `/twin/{id}/scenarios` | `{scenarios:{<label>:{<variable>: knobs}} (1–6), horizon_years, n_runs, seed}` | `scenarios.<label>.<variable>.{time[], p50[], threshold}`; one shared seed, so differences come only from the knobs |
| POST | `/twin/{id}/sensitivity` | `{target, scenario (target needs a threshold), horizon_years, n_runs=300, seed}` | `probability_with_all_knobs`, `ranking[{variable, knob, item, setting, probability_without, change}]` (one knob removed at a time, same seed, ranked by abs(change)), `note` (knobs interact). Max 10 knobs; each shock/driver counts as one |
| DELETE | `/twin/{id}` | | `{deleted}` |
| DELETE | `/twin/{id}/variables/{name}` | | `{deleted, variables[]}` (drivers that pointed at it then fail with 422) |

Twin data lives only in the twin's own file; it never enters the verified series store. Yearly data is detected (`baseline.frequency = "annual"`) and simulated on a yearly grid. `compare_to_baseline: true` adds `reference` (same noise, no knobs) and `delta_p50`; thresholds also return `probability_by_year[{year, p}]` (share of simulated runs crossed by each year).

`drivers` couple a variable to one uploaded **earlier**: y += coefficient × (driver − driver's baseline).
Always show `disclaimer` and label every curve "simulated".

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
