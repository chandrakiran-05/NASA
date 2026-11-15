# Deploy on Hugging Face Spaces (free, no credit card)

One Docker container runs everything on HF's free CPU hardware (2 cores, 16 GB RAM):

```
Browser ──HTTPS (HF)──► Caddy :7860 ── website (frontend/dist)
                                  └─ /api/* ──► backend 127.0.0.1:8010 ──► Ollama 127.0.0.1:11434 (qwen3.5:2b)
```

Files in `deploy/hf/`: `Dockerfile`, `start.sh` (starts the three services), `Caddyfile`,
`publish_space.py` (uploads to the Space). `deploy_hf.cmd` in the repo root runs it from any folder.

## Steps

1. Create a free account at huggingface.co (email only).
2. Settings → Access Tokens → **New token**, type **Write**. Copy it.
3. Commit your work, then in PowerShell:

```powershell
$env:HF_TOKEN="hf_..."
& "C:\New folder (2)\NASA\deploy_hf.cmd" <hf-username>/trend-detective
```

- Creates the Space (Docker), stores `EARTHDATA_TOKEN` from `.env` as an encrypted Space secret,
  uploads the last commit. HF then builds it: 10–20 min the first time, watch the **Logs** tab.
- Site: `https://<hf-username>-trend-detective.hf.space`. Run the same command to update.
- `--dry-run` only builds and lists the upload folder.

## Limits

- AI answers are slow on 2 CPU cores (the 2b model is used for that reason).
- The Space sleeps after ~48 h without visitors; the first visit wakes it in 1–2 min.
- Downloaded NASA data is not kept across restarts, so the first queries after a restart are slower.
