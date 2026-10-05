# ---- Frontend build ----
FROM node:20-alpine AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# Same-origin: the API is served by the same container, so no VITE_API_URL needed.
RUN npm run build

# ---- Backend ----
FROM python:3.12-slim
WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY --from=frontend /fe/dist ./frontend/dist

ENV FRONTEND_DIST=/app/frontend/dist \
    DATA_DIR=/app/data \
    PORT=8000

EXPOSE 8000

# SECRET_KEY must be provided at runtime (Railway variables). Never bake it in.
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
