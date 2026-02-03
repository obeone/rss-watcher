# syntax=docker/dockerfile:1
# RSS Watcher Docker Image
# Optimized multi-stage build with BuildKit features

FROM python:3.12-slim AS builder

WORKDIR /app

# Install uv for fast dependency installation
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install dependencies first (better layer caching)
# Using bind mounts to avoid copying files into intermediate layer
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=README.md,target=README.md \
    uv venv /app/.venv && \
    uv pip install --no-cache --python /app/.venv/bin/python .

# Final stage
FROM python:3.12-slim

WORKDIR /app

# Create non-root user with explicit UID/GID for consistency
RUN groupadd -r -g 10001 appuser && \
    useradd -r -u 10001 -g appuser appuser

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY rss_watcher/ rss_watcher/

# Create data directory and set ownership
RUN mkdir -p /app/data && chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Environment configuration
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CONFIG_PATH="/app/config.yaml"

# Health check - verify the module can be imported
HEALTHCHECK --interval=60s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "from rss_watcher import main; print('ok')" || exit 1

# Run the application
ENTRYPOINT ["python", "-m", "rss_watcher.main"]
CMD ["-c", "/app/config.yaml"]
