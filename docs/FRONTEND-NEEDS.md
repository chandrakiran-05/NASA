# Frontend integration boundaries

- All browser API calls use the typed client and reach only the application backend.
- The actual DigiTwin engine and registered `/api/twin` routes are on `origin/backend-active-trends` at `ecf2892`. The current `main` runtime does not expose them. Configure the backend target to that existing service; this frontend task did not implement or merge backend endpoints.
- Twin data is isolated from verified observations. `/import` makes a one-way copy. UI scenario settings are explicit; natural-language questions do not silently set numeric knobs.
- Current-weather APIs are absent. Topic color is illustrative; historical observations retain date and units.
- Stop waiting aborts browser requests/polling, not backend computation.
- AirLLM deep review exists on the newer backend branch. Live answers continue to use the configured Ollama/OpenAI-compatible service or deterministic fallback.
- Production needs API reverse-proxy routing and SPA fallback for `/digitwin` and `/airllm`.
