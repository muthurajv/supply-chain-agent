from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.middleware.tracing import TracingMiddleware
from app.api.routes import chat, dashboards, invoke
from app.api.routes import approvals
from app.config import get_settings
from app.observability.otel import instrument_app, setup_otel


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    setup_otel(s.otel_service_name, s.otel_service_version, s.otlp_endpoint)
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="Supply Chain Agent",
        description="Multi-agent supply chain AI — inventory, forecasting, procurement, and policy",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(TracingMiddleware)

    app.include_router(chat.router)
    app.include_router(invoke.router)
    app.include_router(dashboards.router)
    app.include_router(approvals.router)

    instrument_app(app)

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok", "service": s.otel_service_name, "env": s.app_env}

    # Backward-compat alias.
    @app.get("/health")
    async def health():
        return {"status": "ok", "service": s.otel_service_name, "env": s.app_env}

    return app


app = create_app()
