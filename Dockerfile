FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend backend
COPY scripts scripts
ENV DATA_DIR=/app/data
EXPOSE 8000
# the local LLM runs outside the container: set LLM_BASE_URL=http://host.docker.internal:11434
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
