# One container: builds the PWA, serves it + the API from FastAPI (one URL to share).
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt backend/
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY data/ data/
COPY --from=web /web/dist frontend/dist
ENV PYTHONUNBUFFERED=1 FINN_DIST=/app/frontend/dist
WORKDIR /app/backend
# If no real DB was shipped, fall back to the synthetic demo so the link never 404s.
CMD sh -c '[ -f /app/data/finn.sqlite ] || python -m finn demo; uvicorn finn.api:app --host 0.0.0.0 --port ${PORT:-8000}'
