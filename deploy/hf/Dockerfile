# Hugging Face Docker Space: website + FastAPI backend + Ollama (Qwen) in one container, served on :7860.
# Published by deploy/hf/publish_space.py, which places this file at the Space root.

# 1. Build the website
FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# 2. Ollama binaries (same version as the laptop)
FROM ollama/ollama:0.40.16 AS ollama

# 3. Runtime
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends caddy build-essential ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ollama /usr/bin/ollama /usr/bin/ollama
COPY --from=ollama /usr/lib/ollama /usr/lib/ollama

# Spaces run the container as user 1000
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    OLLAMA_HOST=127.0.0.1:11434 \
    OLLAMA_MODELS=/home/user/.ollama/models \
    OLLAMA_KEEP_ALIVE=-1 \
    LLM_PROVIDER=ollama \
    LLM_BASE_URL=http://127.0.0.1:11434 \
    LLM_MODEL=qwen3.5:2b
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Bake the model into the image so a restart does not download it again (2 CPU cores: the 2b model)
RUN ollama serve >/tmp/ollama.log 2>&1 & \
    for i in $(seq 1 60); do ollama list >/dev/null 2>&1 && break; sleep 1; done; \
    ollama pull "$LLM_MODEL"

COPY --chown=user . .
COPY --chown=user --from=web /web/dist frontend/dist

EXPOSE 7860
CMD ["bash", "deploy/hf/start.sh"]
