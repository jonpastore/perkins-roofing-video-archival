# Serving image (Cloud Run). Ingestion runs as a separate Cloud Run Job using the same image
# with a different entrypoint (python -m app.ingest ...).
FROM python:3.12-slim
WORKDIR /srv
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
ENV PORT=8080
CMD ["sh", "-c", "uvicorn app.api:app --host 0.0.0.0 --port ${PORT}"]
