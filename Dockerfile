# Railway-compatible image. Database migration/bootstrap are manual, never part of container start.
FROM oven/bun:1 AS frontend
WORKDIR /src/web/frontend
COPY web/frontend/package.json web/frontend/bun.lock ./
RUN bun install --frozen-lockfile
COPY web/frontend/ ./
RUN bun run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY stometric/ ./stometric/
COPY scripts/ ./scripts/
COPY tools/ ./tools/
COPY web/ ./web/
COPY --from=frontend /src/web/frontend/dist ./web/frontend/dist
RUN mkdir -p /app/data
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn stometric.web:app --host 0.0.0.0 --port ${PORT:-8080}"]
