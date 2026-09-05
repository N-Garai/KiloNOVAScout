# Multi-stage Dockerfile for KilonovaScout
# Optimized for Render Free Tier (512MB RAM)

# ---- Build Stage (Python deps + backend) ----
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies for astropy/numpy
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libopenblas-dev \
    gfortran \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY src/backend/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src/ ./src/
COPY config/ ./config/

# ---- Frontend Build Stage (Node) ----
FROM node:20-slim AS frontend-builder

WORKDIR /app

# Copy frontend source
COPY src/frontend/package.json ./
COPY src/frontend/package-lock.json* ./

# Install dependencies
RUN npm install

# Copy remaining frontend source and build
COPY src/frontend/ ./
RUN npm run build

# ---- Runtime Stage ----
FROM python:3.11-slim AS runtime

WORKDIR /app

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash appuser

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY --from=builder /app/src ./src
COPY --from=builder /app/config ./config

# Copy compiled frontend into backend static folder
COPY --from=frontend-builder /app/dist ./src/frontend/dist

# Set ownership
RUN chown -R appuser:appuser /app

USER appuser

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PORT=8000

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application as a package so relative imports work
CMD ["python", "-u", "-m", "backend.main"]