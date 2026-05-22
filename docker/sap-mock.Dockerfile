# ── Stage 1: dependency installer ─────────────────────────────────────────────
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS deps

WORKDIR /app

RUN --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# ── Stage 2: runtime ───────────────────────────────────────────────────────────
FROM python:3.11-slim-bookworm AS runtime

RUN groupadd --system appgroup && useradd --system --gid appgroup --no-create-home appuser

WORKDIR /app

COPY --from=deps --chown=appuser:appgroup /app/.venv /app/.venv

# Copy the sap_mock package only — no agent code needed
COPY --chown=appuser:appgroup sap_mock/ sap_mock/

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # SQLite DB written to /data so it can be backed by a PersistentVolumeClaim.
    # For the POC a plain emptyDir is fine — the DB is re-seeded on each start.
    SAP_MOCK_DATABASE_URL="sqlite+aiosqlite:////data/sap_mock.db"

# /data is the mount point for the SQLite file
RUN mkdir /data && chown appuser:appgroup /data

USER appuser

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')"

CMD ["uvicorn", "sap_mock.main:app", "--host", "0.0.0.0", "--port", "8001", \
     "--workers", "1", "--log-level", "warning"]
