# Multi-stage Dockerfile for KiloNOVAScout
# Stage 1: Build frontend
FROM node:20-alpine AS frontend-builder

WORKDIR /app/src/frontend
COPY src/frontend/package*.json ./
RUN npm ci
COPY src/frontend/ ./
RUN npm run build

# Stage 2: Python backend with built frontend
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY src/backend/requirements.txt ./src/backend/
RUN pip install --no-cache-dir -r src/backend/requirements.txt

# Copy backend code
COPY src/backend/ ./src/backend/

# Copy built frontend from stage 1
COPY --from=frontend-builder /app/src/frontend/dist ./src/frontend/dist

# Expose ports
EXPOSE 8000

# Start backend (serves frontend as static files)
CMD ["uvicorn", "src.backend.main:app", "--host", "0.0.0.0", "--port", "8000"]

</ARG>