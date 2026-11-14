# CLAUDE.md — Earth System Trend Detective (NASA Space Apps 2026)

Read this first. It tells you what already exists and the rules for building on it. Default
task for a new session: **build the frontend in `frontend/` against the existing backend API.**

## 1. What this project is

A web tool for high-school and college students to become "data detectives". They pick an Earth
variable, a region and a period, and the tool fetches official NASA/NOAA data, builds a monthly
time series and tests whether it is trending, and whether that conclusion can be trusted.

Source of truth for scope, in this order:
1. `docs/06-feature-spec.md` — the feature list (F1–F16) and build order. **Build only what is there.**
2. `docs/05-novelty-features.md` — why each feature exists (evidence). Do not invent new features.
3. `docs/03-architecture.md` — divisions ①–⑧ and the original design.
4. `docs/API.md` and `docs/openapi.json` — the backend contract (backend is done; see §3).
5. `docs/01-challenge.md` — the official challenge text.

## 2. Hard rules (do not deviate)

| Rule | Why |
|---|---|
| The frontend calls **only our backend** (`/api/...`). Never call Giovanni, AppEEARS, NCEI, CMR or OPeNDAP from the browser. | Tokens stay server-side; caching, QC and provenance live in the backend. |
| **Never compute statistics in the frontend.** Every number shown (slopes, p-values, CIs, years-to-detect, badges) comes from an API response. | Division ⑥ is the single source of numbers; results are validated against reference libraries. |
| Never invent, interpolate or smooth data. Missing months are `null` in the API; draw them as gaps. | Data rule in every design doc. |
| Do **not** change files in `backend/`, `tests/` or `scripts/` unless the user explicitly asks. If the UI needs something the API lacks, write it down in `docs/FRONTEND-NEEDS.md` and tell the user. | Backend has 92 passing tests and a fixed contract. |
| Use the exact honest wording below. | Judges score validity; overclaiming is the main risk. |
| Data sources shown on screen: Giovanni, AppEEARS, NOAA NCEI (plus CMR / Cloud OPeNDAP behind them). Show the `provenance` block (dataset, version, DOI, retrieved_at) for every series. | Challenge resources only; reproducibility. |

### Required wording

| Situation | Say | Never say |
|---|---|---|
| Seam step detected (F1) | "possible instrument effect" | "artifact", "error in the data" |
| Trend triangle / heatmap (F2) | label it "exploratory" | imply each cell is an independent test |
| Years-to-detect (F2) | "If the current rate and noise persist, about N more years (≈YYYY)" — use `years_to_detect.plain_language` | "it will become significant in YYYY" |
| Lineup / null histogram (F5) | "Simulated from your data, not observations" | show shuffles as real data |
| Projection (`insights.forecast`) | "statistical extrapolation, not a climate projection" (`disclaimer` field) | "prediction", "forecast of climate" |
| Driver hints / scan coherence | "consistent with", "associated with" | "caused by", "because of" |
| Stamp (F3) | `SIGNIFICANT` / `NOT PROVEN` | "proven", "no trend exists" |

Whenever the API returns `plain_language`, `limit`, `limits`, `caveats` or `disclaimer`, show it.

## 3. Backend (done — how to run and call it)

```bash
pip install -r requirements-dev.txt
cp .env.example .env            # credentials are optional for UI work, see below
uvicorn backend.main:app --reload --port 8000     # API docs: http://localhost:8000/docs
pytest -q                       # 92 tests, ~20 s
```

**Working without NASA credentials:** upload any monthly CSV with `POST /api/timeseries/upload-csv`
(or JSON to `/api/timeseries/upload`). Every analysis, novelty and AI endpoint works on uploaded
series, so the whole UI can be built and demoed offline.

**Long operations are jobs.** `POST` returns `202 {job_id}`; poll `GET /api/jobs/{job_id}?wait=10`
until `status` is `done` or `error`; show `progress` (0–1) and `message`. AppEEARS jobs can take ~15 min.

**Errors** always look like `{"error": {"code", "message", "detail"}}`. Show `message` to users.

CORS allows `http://localhost:5173` and `:3000` (change `CORS_ORIGINS` in `.env`).

## 4. Screen → endpoint map

| UI piece | Feature | Endpoint(s) | Key response fields |
|---|---|---|---|
| Question box ("Is rainfall changing in Chennai since 2001?") prefills the wizard | wizard | `POST /api/ai/plan` | `variables[]`, `regions[].geometry`, `period`, `wishes`, `on_topic`, `message` |
| Wizard step 1 "Suspect" (variable) | F6 | `GET /api/variables?q=&region_type=`, `GET /api/variables/{id}` | `name`, `definition`, `units`, `coverage_start`, `alerts[]` |
| Region-type chips (desert, rainforest, estuary, megacity…) | — | `GET /api/regions/archetypes` | `variables[].why` |
| Wizard step 2 "Scene" (map) | — | `GET /api/regions/search?q=` ; send GeoJSON Point / Polygon or `{type:"BBox", bbox:[w,s,e,n]}` | `geometry`, `approximate` (say "approximate box, adjust on map") |
| Fetch series | — | `POST /api/timeseries` → job → `result.series_id` | `completeness`, `source_api`, `qc`, `attempts` |
| Step 3 "Hunch" (draw or ↑/→/↓) | F6 | client-side only (store the hunch; never treated as data) | — |
| Main chart | baseline | `POST /api/analyze` (`include_series:true`) | `chart.{time, raw, deseasonalized, seasonal, stl_trend, ols_line, sen_line}` |
| Result card | baseline | same | `verdict.{arrow, direction, rate_per_decade, rate_units, significant, strength, plain_language, caveats}` |
| **F1 Fit-for-trends badge, coverage strip, seam lines** ★ | F1 | `GET /api/timeseries/{id}/integrity` | `badge`, `badge_icon`, `reasons[]`, `coverage.fraction_valid[]`, `flags[]`, `seams[].{date, step, step_p, trend_before_per_decade, trend_after_per_decade, citation, url}`, `trend_or_jump` |
| **F3 Trend Court** (jurors table, stamp, toggles) | F3 | `court` block inside `POST /api/analyze` (or `GET /api/analyze/{id}/court`) | `stamp`, `chosen_test`, `reason`, `jurors[]`, `flips`, `consistency[]`, `cross_examination[].{question, significant, flips_verdict}` |
| **F2 Evidence Clock** (heatmap, end-year slider, countdown, cherry-pick rank) | F2 | `GET /api/analyze/{id}/detectability?start=&end=` | `triangle.{start_years, end_years, slope_per_decade[][], p_value[][]}`, `expanding[]`, `years_to_detect`, `window_rank` |
| **F4 Second Opinion** | F4 | `GET /api/variables/{id}/second-opinions`, then fetch that series, then `POST /api/compare {series_ids:[a,b], mode:"product_agreement"}` | `badge` (ROBUST / DISPUTED / INCONCLUSIVE), `a`, `b`, `difference` |
| Two regions, same variable | F4 | `POST /api/compare {series_ids, mode:"regions"}` | `regions[]` (FDR), `pairs[]`, `divergent` |
| **F5 Could It Be Chance?** (lineup grid + null histogram) | F5 | `POST /api/analyze/nulls {series_id, n_null:1000, n_panels:19}` | `lineup.{time, panels[20][], real_index}`, `null_slopes_per_decade[]`, `real_slope_per_decade`, `perm_p`, `label` |
| F7 FDR trend map | F7 | `POST /api/trendmap` → job | `lat[]`, `lon[]`, `slope_per_decade[][]`, `significant[][]`, `area_fraction_rising/falling` |
| Extra insight cards | — | `POST /api/insights` | `breaks`, `emergence`, `records`, `forecast`, `trend_evidence_index` |
| Trend Scan ("what's changing here?") | F12 | `POST /api/scan` → job | `ranking[]`, `coherence[]`, `plain_language` |
| Explain / ask | F13 | `POST /api/ai/explain {series_id}`, `POST /api/ai/ask {question}` | `explanation`, `answer`, `source` (show "AI-written, number-checked" when `local_llm`) |
| Demo cases | F6 | `GET /api/demos`, `POST /api/demos/{id}/run` → job | full report |
| Data-source status banner | ⑧ | `GET /api/sources/status` | `alerts.alerts[]`, `llm.available` |
| Export | F9 | `GET /api/export/{id}?format=csv|json` | file with provenance + citation |

## 5. Frontend stack and layout

- React + Vite + TypeScript, Plotly.js for charts, Leaflet (react-leaflet + leaflet-draw) for the map.
- `VITE_API_URL` (default `http://localhost:8000`). One typed API client in `frontend/src/api/` generated
  from or matching `docs/openapi.json`; no `fetch` calls scattered in components.
- Folders (from architecture §7): `frontend/src/{api,wizard,map,charts,results,court,clock,lineup,integrity,demos,glossary}/`.
- Flow (F6 case file): **Suspect → Scene → Hunch → Evidence → Verdict** (Verdict = F1 badge + F3 stamp + F2 clock).
- Build order (docs/06): Baseline UI → F1 → F3 → F2 → F5 → F4 → F6 → extended (F7, F9) → optional.
- Accessibility: every chart has a text summary (use `plain_language`); colour is never the only signal
  (badges carry icons and words); keyboard alternative for the hunch drawing.
- Audience is students: short sentences, show `definition` next to every variable name, units on every axis.

## 6. Definition of done for any frontend feature

1. All numbers come from the API response, rendered with units.
2. The honest wording in §2 is used and `limit`/`caveats` are visible.
3. Works on an uploaded CSV series (no credentials) and shows job progress for live fetches.
4. Errors show `error.message`, never a blank screen.
5. Provenance (dataset, version, DOI, retrieved date) is reachable from the chart.
