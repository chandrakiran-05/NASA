# Earth System Trend Detective frontend

React, TypeScript, Vite and a persistent Three.js globe. The approved design has two modes: observed Earth (`/`) and the DigiTwin scenario sandbox (`/digitwin`). Local AI setup is at `/airllm`.

## Run

From the repository root:

```powershell
python -m pip install -r requirements.txt
python -m uvicorn backend.main:app --reload --port 8000
```

In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open Vite's printed Local URL. The active review preview for this session is http://127.0.0.1:5180/.

```powershell
npm test
npm run build
```

## Backend selection

Default browser requests go to `/api`; the development proxy forwards them to `http://127.0.0.1:8000`. Set shell variable `BACKEND_URL` before starting Vite to target another API server. Optional build-time `VITE_API_URL` changes the browser API base; it is public and must never contain credentials. Cross-origin connections require backend CORS configuration.

**DigiTwin is already implemented on `backend-active-trends` at `ecf2892`.** This frontend uses its existing `/api/twin` routes. The checked-out main backend lacks them, so it shows an honest unavailable message until connected to a server running that branch. No backend endpoints were created, changed or merged.

Production hosting must route `/api` to the backend and provide SPA fallback for `/digitwin` and `/airllm`. `vite preview` serves the frontend build only.

## Interaction

- Drag Earth, or focus it and use arrow keys. Home and the reset button restore the view. Pause stops continuous rendering.
- Type a recognized country, state or city to focus it through the backend region service; continent centers are navigation aids only. Temperature, rainfall and vegetation words change a labeled illustrative accent, not a measured overlay.
- Submit observed questions through the planning/investigation pipeline. Evidence includes trend tests, caveats, provenance, CSV upload and exports. Comparisons preserve region identity.
- Enter DigiTwin to roll the same Earth upside down and change the interface. The return control restores the observed question and selected location.
- Twin prompts capture the question and open explicit scenario settings. The existing API has no natural-language scenario planner; no numeric assumptions are silently inferred.
- Select/create a twin, upload research CSV or copy an observed series, then run a confirmed scenario. All returned curves and ranges are labeled simulated, with the backend disclaimer.

## Performance

One WebGL context, reduced sphere detail, combined geographic grid, DPR capped at 1.25 and bounded physical pixels. Static, offscreen and hidden states stop drawing. Idle rotation has a 30fps budget; interaction and transitions use animation frames. The prompt's blur is confined to a small surface. Plotly's basic distribution loads only when evidence charts are needed.

See [VERIFICATION.md](VERIFICATION.md) for measured results and test limits. Earth texture credits are in `public/textures/ATTRIBUTION.md`. This independent hackathon project does not imply NASA endorsement.

## Current goal preview
The current preview on port5180 proxies to the already-implemented backend-active-trends snapshot on port8001. The snapshot and its isolated preview data live under ignored frontend/shots/. Main backend files were not modified. See ../docs/design-research/06-goal-completion-audit.md for runtime and full requirement verification.

