# Earth System Trend Detective — Backend

NASA Space Apps 2026 · *Be An Earth System Trend Detective!*

A FastAPI backend that lets students **select** an Earth-science variable, **acquire** it for a
region from the official NASA/NOAA services, **build** a monthly time series, and **test** whether
it is trending, with statistically honest significance tests, new insight models and an
**offline** AI assistant that only talks about Earth-system data.

Status: backend complete; 92 automated tests pass in about 20 s. The frontend is next: **frontend
Claude sessions must read [`CLAUDE.md`](CLAUDE.md) first.** Feature scope: `docs/06-feature-spec.md`.

---

## What it does

| Challenge objective | How the backend does it |
|---|---|
| 1. Identify variables | Catalog of 22 curated variables with plain-language definitions (MERRA-2, GLDAS, GPM IMERG, AIRS, OMI, MODIS, SMAP, NOAA stations), expandable to all ~867 Giovanni variables with `scripts/build_catalog.py`. BM25 search, region-type recommendations (desert, rainforest, estuary, megacity…). |
| 2. Acquire data for a region | One connector per official API: Giovanni `/timeseries` (point), Giovanni-Harmony `average=area`, Cloud OPeNDAP fallback, AppEEARS async tasks, NCEI Access Data Service, CDO v2. Automatic routing around the current GES DISC outages, 429 back-off, request-level caching. |
| 3. Time series + visualisation data | Source-metadata QC (fill / scale / valid range / quality flags), day-weighted monthly aggregation with a completeness rule, gaps never interpolated. Chart-ready JSON: raw, deseasonalized, STL trend, OLS and Sen lines. |
| 4. Rate of change + significance | OLS with t-test and AR(1)-corrected p-values and CIs, Mann-Kendall (calibrated effective-sample-size variant, plus the classic variants), Seasonal Mann-Kendall, Sen's slope with CI, plain-language verdict and caveats. |

### Team novelty features (docs/06-feature-spec.md) — implemented in `backend/novelty/`

| Feature | Endpoint |
|---|---|
| ★ **F1 Seam & Integrity Audit**: fit-for-trends badge, zero/constant-run flags, NASA pipeline-fix check, cited seam events (IMERG TRMM→GPM, MERRA-2 SSM/I & AMSU, Terra drift), step tests, Pettitt, trend-or-jump | `GET /api/timeseries/{id}/integrity` |
| **F2 Evidence Clock**: triangle, end-year slider, years-to-detect countdown, cherry-pick rank | `GET /api/analyze/{id}/detectability` |
| **F3 Trend Court**: diagnostics choose the test, 8 jurors, flips flag, cross-examination, SIGNIFICANT / NOT PROVEN | `court` in `POST /api/analyze` |
| **F4 Second Opinion**: difference-series test, ROBUST / DISPUTED | `POST /api/compare` `mode=product_agreement` |
| **F5 Could It Be Chance?**: block-bootstrap null histogram + 20-panel lineup | `POST /api/analyze/nulls` |
| **Trend Scan + coherence** (research, docs/07) | `POST /api/scan` |

### Additional insight models

| Insight | Question it answers |
|---|---|
| **Detectability horizon** (Weatherhead et al. 1998) | "My trend isn't significant — how many more years until it would be?" |
| **Time of emergence** | "When did the change rise above natural year-to-year noise?" |
| **Trend breaks** (PELT, piecewise-linear) | "Did the trend speed up, slow down or reverse — and when?" |
| **Trend-stability triangle** | "Would I get the same answer with different start/end years?" |
| **Record-breaking test** | "Are there more record years than chance would give?" |
| **Projection ensemble** (CV-weighted, conformal bands) | "Where is it heading if nothing changes?" (clearly labelled as statistical extrapolation) |
| **Regional contrast** (FDR-corrected) | "Is it rising here but falling there?" (the challenge's opposite-trends case) |
| **Driver hints** (detrended lagged correlation) | "Which other variable moves with it, and how much of the trend could it explain?" |
| **Per-pixel trend maps** (field-significance corrected) | "Where inside my region is it changing?" |
| **Trend Evidence Index** (0–100) | One transparent score combining all of the above. |

### Accuracy and speed

- Every test is validated against independent reference libraries (pymannkendall, scipy) to
  machine precision. See `tests/test_statistics.py`.
- A simulation study (`scripts/calibration_study.py`) showed that some popular Mann-Kendall
  variants report **25–78% false trends** in persistent data. The backend's default tests stay
  at **~5%**; details in `docs/STATISTICS.md`.
- Compiled kernels (numba): Mann-Kendall S in O(n log n) with a Fenwick tree is 20–2,900× faster
  than pymannkendall; a full analysis of a 24-year monthly series takes ~17 ms; all insights
  ~0.5 s; a 4,800-pixel trend map ~0.3 s (`scripts/benchmark.py`).

### Offline AI

- Runs a **local** model through Ollama (default `qwen3.5:4b`; `gemma4:e4b` or any
  OpenAI-compatible local server such as llama.cpp or LM Studio also work). Nothing goes to the internet.
- **Earth-topic guardrail** (deterministic, <1 ms) refuses off-topic requests and prompt injection.
- **Planner**: "Is rainfall changing in Chennai since 2001?" → variable, region (offline
  gazetteer of 34k cities plus countries and approximate regional boxes), and period.
- **Grounded explanations with a numeric fact-check**: every number the model writes must
  appear in the computed results, or the text is rejected and the deterministic explanation is used.
- Works fully **without** a model: every AI endpoint has a deterministic fallback.

---

## Quick start

```bash
# 1. Python 3.11+ (tested on 3.13)
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. Credentials (server-side only)
cp .env.example .env        # then fill in EARTHDATA_TOKEN etc. (see comments in the file)

# 3. Run
uvicorn backend.main:app --reload --port 8000
# open http://localhost:8000/docs  (interactive API)

# 4. Optional: offline AI
#    install Ollama from ollama.com, then:
ollama pull qwen3.5:4b
```

### Before the demo (on a machine with internet and credentials)

```bash
python scripts/live_smoke_test.py          # checks every real API format assumption, saves real responses
python scripts/live_smoke_test.py --full   # also Harmony + AppEEARS (~15 min)
python scripts/build_catalog.py            # verify seed IDs, add all official Giovanni variables
python scripts/build_demos.py              # cache real data for the guided demos
```

### Tests and benchmarks

```bash
pip install -r requirements-dev.txt
pytest -q                                   # 92 tests, ~20 s, fully offline
python scripts/benchmark.py
python scripts/calibration_study.py
```

---

## Try it

```bash
# one-shot investigation from a question (returns a job id)
curl -X POST localhost:8000/api/investigate -H 'content-type: application/json' \
     -d '{"question": "Is rainfall changing in Tamil Nadu since 2001?"}'
curl 'localhost:8000/api/jobs/<job_id>?wait=30'

# or step by step
curl -X POST localhost:8000/api/timeseries -H 'content-type: application/json' -d '{
  "variable_id": "merra2_t2m",
  "geometry": {"type": "Point", "coordinates": [80.27, 13.08], "name": "Chennai"},
  "start": "1981-01", "end": "2024-12"}'
curl -X POST localhost:8000/api/analyze  -d '{"series_id": "<id>"}' -H 'content-type: application/json'
curl -X POST localhost:8000/api/insights -d '{"series_id": "<id>"}' -H 'content-type: application/json'
```

No credentials yet? Upload any monthly CSV (`/api/timeseries/upload-csv`, e.g. exported from
the Giovanni web UI or KNMI Climate Explorer) and the analysis, insights and AI endpoints all work.

---

## Repository layout

```
backend/
  main.py              app factory, lifespan (JIT warm-up), error handling
  api/                 routes, request schemas, pipeline (investigate / demos / result cache)
  core/                settings, auth, resilient HTTP (retry, 429, rate limit, raw cache), geometry
  catalog/             catalog service, source router, data/ (seed catalog, archetypes, alerts,
                       glossary, region presets, demos)
  connectors/          giovanni, harmony_area, opendap, appeears, ncei (+CDO), cmr
  timeseries/          model, parsers, QC, monthly resampling, gridded helpers, service
  analysis/            numba kernels, trend tests, STL, verdict, engine
  insights/            detectability, emergence, changepoint, triangle, forecast,
                       compare, drivers, cube, engine (Trend Evidence Index)
  novelty/             F1 integrity+seams, F2 evidence clock, F3 court, F4 agreement, F5 nulls, scan
  ai/                  guardrail, BM25, gazetteer, local LLM client, fact-check, assistant
  jobs/  storage/      async job runner; SQLite + Parquet
scripts/               live_smoke_test, build_catalog, build_demos, benchmark, calibration_study
tests/                 92 tests (incl. real recorded NASA/NOAA responses) + fake upstream services
docs/                  API.md, STATISTICS.md, BACKEND.md, openapi.json, original design docs
```

## Honest limits

- Connector formats were checked against **NASA's own tutorial code**
  ([nasa/gesdisc-tutorials](https://github.com/nasa/gesdisc-tutorials): Giovanni time series and
  averaging service; [nasa/AppEEARS-Data-Resources](https://github.com/nasa/AppEEARS-Data-Resources):
  point/area tasks), but the build environment could not call the live APIs. Run
  `scripts/live_smoke_test.py` first; anything it flags is a small parser fix.
- Seed units and coverage dates marked `*_source: "seed"` are from general knowledge until
  `build_catalog.py` replaces them with official metadata. Entries with `verified: false` are
  checked by the same script.
- Projections are statistical extrapolations, not climate-model projections, and the API says so.
- Driver hints show association, not causation, and the API says so.
