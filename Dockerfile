# Multi-stage Dockerfile for KilonovaScout
# Optimized for Render Free Tier (512MB RAM)

# ---- Build Stage ----
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies
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
COPY src/backend/ ./src/backend/
COPY config/ ./config/

# ---- Runtime Stage ----
FROM python:3.11-slim AS runtime

WORKDIR /app

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash appuser

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY --from=builder /app/src/backend ./src/backend
COPY --from=builder /app/config ./config

# Set ownership
RUN chown -R appuser:appuser /app

USER appuser

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src/backend \
    PORT=8000

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["python", "-u", "src/backend/main.py"]