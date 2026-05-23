from __future__ import annotations

from fastapi import FastAPI

# ── Bootstrap observability FIRST, before any route module is imported.
# chat.py and approvals.py create OTel instruments at module level; if
# setup_otel() runs after those imports the instruments bind to the no-op
# provider and never export to Grafana Cloud.
from app.config import get_settings
from app.observability.otel import instrument_app, setup_otel

_s = get_settings()
setup_otel(
    _s.otel_service_name,
    _s.otel_service_version,
    _s.otlp_endpoint,
    log_level=_s.log_level,
    grafana_otlp_endpoint=_s.grafana_otlp_endpoint,
    grafana_instance_id=_s.grafana_instance_id,
    grafana_api_key=_s.grafana_api_key,
)

# Now import routes — meters/instruments created here use the real provider.
from app.api.middleware.tracing import TracingMiddleware
from app.api.routes import approvals, chat, dashboards, invoke


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="Supply Chain Agent",
        description="Multi-agent supply chain AI — inventory, forecasting, procurement, and policy",
        version="1.0.0",
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

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": s.otel_service_name, "env": s.app_env}

    return app


app = create_app()
