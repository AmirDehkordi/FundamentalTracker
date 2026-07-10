# syntax=docker/dockerfile:1

# ---- stage 1: build the frontend ------------------------------------------------------------
FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- stage 2: backend + built frontend -------------------------------------------------------
FROM python:3.12-slim
RUN pip install --no-cache-dir uv
WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY backend/src backend/src
RUN uv sync --frozen --no-dev

COPY --from=frontend-build /app/frontend/dist frontend/dist

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "tracker.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
