# ADR-005: Grafana Cloud OTLP gateway for traces, metrics, and logs

**Date:** 2025-05-22  
**Status:** Accepted

## Context

The project needs a unified observability backend (traces, metrics, logs) with
hosted dashboards. On a dev laptop there is no Docker available, ruling out a
local OTel Collector + Jaeger/Prometheus/Loki stack.

Options evaluated:

| Option | Traces | Metrics | Logs | Dashboards | Local dev setup |
|---|---|---|---|---|---|
| Azure Monitor / App Insights | Yes | Yes | Yes | Basic | SDK + connection string |
| Local OTel Collector → Jaeger + Prometheus + Loki | Yes | Yes | Yes | Self-hosted Grafana | Docker required |
| Grafana Cloud free tier (OTLP gateway) | Tempo | Mimir | Loki | Hosted Grafana | None (HTTPS POST) |

Grafana Cloud free tier provides Tempo (traces), Mimir (metrics), and Loki (logs)
under one hosted Grafana instance, with a free allocation sufficient for a POC.
Sending data requires only HTTPS POST to the OTLP gateway — no sidecar, no binary.

## Decision

Send all three OTEL signals directly to the **Grafana Cloud OTLP gateway** via
`opentelemetry-exporter-otlp-proto-http` with HTTP Basic Auth
(`{instance_id}:{api_key}` base64-encoded). The gRPC exporter path to a K8s
OTel Collector is retained as fallback when `GRAFANA_OTLP_ENDPOINT` is unset,
so the K8s deployment is unaffected.

**New dependencies introduced** (requires this ADR per §2):
- `opentelemetry-exporter-otlp-proto-http==1.42.0` — HTTP variant of the OTLP
  exporter; the gRPC variant was already present.
- `opentelemetry-instrumentation-logging==0.63b0` — bridges Python `logging` →
  OTEL `LogRecord`, injecting `trace_id`/`span_id` into every log line. This
  enables Loki → Tempo click-through in Grafana (matching log `trace_id` to the
  Tempo trace).

Config (`app/config.py`):
- `GRAFANA_OTLP_ENDPOINT` — OTLP gateway URL (e.g. `https://otlp-gateway-prod-us-east-0.grafana.net/otlp`)
- `GRAFANA_INSTANCE_ID` — numeric stack instance ID
- `GRAFANA_API_KEY` — API key with MetricsPublisher + LogsPublisher + TracesPublisher scopes (injected from Key Vault in AKS)

## Consequences

- Three Grafana dashboard JSONs ship in `grafana/dashboards/` and are importable
  via Grafana Cloud → Dashboards → Import. No Terraform or Grafana API token is
  needed for the POC.
- The `PIIRedactionLogProcessor` (mirrors `PIIRedactionProcessor` for spans)
  ensures PII is hashed before any log record reaches Loki. Adding a new free-text
  attribute to `REDACT_ATTRS` covers both spans and logs automatically.
- Pinning `opentelemetry-instrumentation-logging==0.63b0` keeps it in sync with
  the other `0.63b0` instrumentation packages. On any OTEL SDK upgrade, all
  instrumentation packages must be bumped together.
- Grafana Cloud free tier limits: 14-day trace retention, 30-day log retention,
  10k series for metrics. Sufficient for a POC; a production deployment should
  evaluate Azure Monitor or a self-hosted Grafana stack.
