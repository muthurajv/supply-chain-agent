# ── Stage 1: dependency installer ─────────────────────────────────────────────
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS deps

WORKDIR /app

# Install production deps only into /app/.venv using the lockfile.
# Bind-mounts keep pyproject.toml / uv.lock out of the layer cache key so a
# lockfile bump is the only thing that invalidates this layer.
RUN --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# ── Stage 2: runtime ───────────────────────────────────────────────────────────
FROM python:3.11-slim-bookworm AS runtime

# Security: run as non-root
RUN groupadd --system appgroup && useradd --system --gid appgroup --no-create-home appuser

WORKDIR /app

# Copy the pre-built virtualenv from the deps stage
COPY --from=deps --chown=appuser:appgroup /app/.venv /app/.venv

# Copy application source
COPY --chown=appuser:appgroup app/       app/

# Put the venv on PATH so `python` and `uvicorn` resolve without activation
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/healthz')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", \
     "--workers", "2", "--log-level", "warning"]
