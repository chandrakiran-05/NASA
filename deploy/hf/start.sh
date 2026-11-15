#!/usr/bin/env bash
# Starts Ollama, the backend and Caddy. If any one stops, the container exits and the Space restarts it.
set -uo pipefail
cd "$(dirname "$0")/../.."

ollama serve &
for i in $(seq 1 60); do ollama list >/dev/null 2>&1 && break; sleep 1; done

python -m uvicorn backend.main:app --host 127.0.0.1 --port 8010 &
caddy run --config deploy/hf/Caddyfile --adapter caddyfile &

wait -n
echo "a service stopped; exiting so the Space restarts" >&2
exit 1
