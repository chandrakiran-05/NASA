# Backend API endpoints

49 endpoints, generated from the app's OpenAPI schema (`/openapi.json`).

| # | Group | Method | Path | What it does |
|---|---|---|---|---|
| 1 | meta | GET | `/api/health` | Health |
| 2 | meta | GET | `/api/sources/status` | Sources Status |
| 3 | catalog | GET | `/api/regions/archetypes` | Archetypes |
| 4 | catalog | GET | `/api/regions/search` | Region Search |
| 5 | catalog | GET | `/api/variables` | List Variables |
| 6 | catalog | GET | `/api/variables/{variable_id}` | Get Variable |
| 7 | timeseries | GET | `/api/export/{series_id}` | Export Series |
| 8 | timeseries | GET | `/api/jobs/{job_id}` | Get Job |
| 9 | timeseries | GET | `/api/series` | List Series |
| 10 | timeseries | POST | `/api/timeseries` | Create Timeseries |
| 11 | timeseries | POST | `/api/timeseries/upload` | Bring your own series (e.g. a CSV exported from Giovanni or KNMI Climate Explorer). |
| 12 | timeseries | POST | `/api/timeseries/upload-csv` | Upload Csv |
| 13 | timeseries | GET | `/api/timeseries/{series_id}` | Get Timeseries |
| 14 | analysis | POST | `/api/analyze` | Analyze |
| 15 | analysis | POST | `/api/compare` | Compare |
| 16 | analysis | POST | `/api/drivers` | Drivers |
| 17 | analysis | POST | `/api/insights` | Insights |
| 18 | analysis | POST | `/api/trendmap` | Trendmap |
| 19 | analysis | POST | `/api/trendmap/upload` | Per-pixel trends for a monthly netCDF you already have (e.g. downloaded from Giovanni). |
| 20 | novelty | POST | `/api/analyze/nulls` | F5 Could It Be Chance? block-bootstrap null histogram + lineup. |
| 21 | novelty | GET | `/api/analyze/{series_id}/court` | F3 Method Verdict / Trend Court. |
| 22 | novelty | GET | `/api/analyze/{series_id}/detectability` | F2 Evidence Clock: triangle, expanding window, years-to-detect, cherry-pick rank of [start, end]. |
| 23 | novelty | POST | `/api/scan` | Trend Scan: many variables, one region; FDR across variables; physical-coherence check. |
| 24 | novelty | GET | `/api/timeseries/{series_id}/integrity` | F1 Seam & Integrity Audit: fit-for-trends badge, coverage strip, flags, seams, trend-or-jump. |
| 25 | novelty | GET | `/api/variables/{variable_id}/second-opinions` | F4: which other products/stations measure the same quantity. |
| 26 | forensics | POST | `/api/ai/suspects` | Trend Forensics WHY, step 1: pre-registered driver hypotheses (no data seen). |
| 27 | forensics | GET | `/api/analyze/{series_id}/onset` | Trend Forensics WHEN: calibrated BEAST change dating (events, probability, 90% interval, seams). |
| 28 | active | POST | `/api/active-trends` | Which variables are changing NOW? Detect -> independent checks (concurrent) -> BEAST -> verdict. |
| 29 | active | POST | `/api/active-trends/{job_id}/deep-review` | Optional AirLLM deep reviewer on the top finished trends. Slow (minutes per trend on a 4 GB GPU), |
| 30 | active | GET | `/api/active-trends/{job_id}/events` | Events after sequence number `after`; waits up to `wait` seconds for new ones. |
| 31 | active | GET | `/api/active-trends/{job_id}/stream` | Server-Sent Events: one `data:` line per event; the stream ends after `done` or `error`. |
| 32 | active | GET | `/api/criteria` | The 28 investigation criteria, their catalog variables and whether they can be trend-tested. |
| 33 | research | POST | `/api/research/evidence` | Search recent literature (arXiv, OpenAlex, Springer Nature) for a variable/region/direction and report |
| 34 | investigate | GET | `/api/demos` | Demos |
| 35 | investigate | POST | `/api/demos/{demo_id}/run` | Run Demo |
| 36 | investigate | POST | `/api/investigate` | Investigate |
| 37 | ai | POST | `/api/ai/ask` | Ai Ask |
| 38 | ai | POST | `/api/ai/explain` | Ai Explain |
| 39 | ai | POST | `/api/ai/guard` | Ai Guard |
| 40 | ai | GET | `/api/ai/hardware` | This machine's GPU/RAM/disk, and which live (Ollama) and deep (AirLLM) models fit it. |
| 41 | ai | POST | `/api/ai/plan` | Ai Plan |
| 42 | ai | GET | `/api/ai/status` | Ai Status |
| 43 | digital twin | GET | `/api/twin` | List Twins |
| 44 | digital twin | POST | `/api/twin` | Create Twin |
| 45 | digital twin | GET | `/api/twin/{twin_id}` | Get Twin |
| 46 | digital twin | POST | `/api/twin/{twin_id}/data` | Research data in, as-is (JSON; for other teams' tools). Variables are kept in upload order. |
| 47 | digital twin | POST | `/api/twin/{twin_id}/data-csv` | CSV with a date column first, then one numeric column per variable. |
| 48 | digital twin | POST | `/api/twin/{twin_id}/import` | Copy a series from the main mode into the twin (one-way snapshot; the original is untouched). |
| 49 | digital twin | POST | `/api/twin/{twin_id}/simulate` | Run Simulation |
