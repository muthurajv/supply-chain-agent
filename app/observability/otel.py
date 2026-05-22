from __future__ import annotations

import base64
import logging

from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from .log_processor import PIIRedactionLogProcessor
from .pii import PIIRedactionProcessor


def _build_auth_headers(instance_id: str, api_key: str) -> dict[str, str]:
    token = base64.b64encode(f"{instance_id}:{api_key}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def setup_otel(
    service_name: str,
    service_version: str,
    otlp_endpoint: str,
    log_level: str = "INFO",
    grafana_otlp_endpoint: str = "",
    grafana_instance_id: str = "",
    grafana_api_key: str = "",
) -> None:
    """Bootstrap OpenTelemetry — call once at application startup.

    When grafana_otlp_endpoint + credentials are provided, all three signals
    (traces, metrics, logs) are exported via OTLP/HTTPS to Grafana Cloud.
    Otherwise falls back to OTLP/gRPC for the local/K8s collector path.
    """
    resource = Resource.create({
        SERVICE_NAME: service_name,
        SERVICE_VERSION: service_version,
    })

    use_grafana_cloud = bool(grafana_otlp_endpoint and grafana_instance_id and grafana_api_key)

    if use_grafana_cloud:
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter as HTTPLogExporter
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter as HTTPMetricExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as HTTPSpanExporter

        headers = _build_auth_headers(grafana_instance_id, grafana_api_key)
        span_exporter = HTTPSpanExporter(endpoint=f"{grafana_otlp_endpoint}/v1/traces", headers=headers)
        metric_exporter = HTTPMetricExporter(endpoint=f"{grafana_otlp_endpoint}/v1/metrics", headers=headers)
        log_exporter: object = HTTPLogExporter(endpoint=f"{grafana_otlp_endpoint}/v1/logs", headers=headers)
    else:
        from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter as GRPCLogExporter

        span_exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
        metric_exporter = OTLPMetricExporter(endpoint=otlp_endpoint, insecure=True)
        log_exporter = GRPCLogExporter(endpoint=otlp_endpoint, insecure=True)

    # Traces
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(PIIRedactionProcessor())
    tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    trace.set_tracer_provider(tracer_provider)

    # Metrics
    metric_reader = PeriodicExportingMetricReader(metric_exporter, export_interval_millis=30_000)
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

    # Logs — bridges Python logging module to OTEL; injects trace_id/span_id into every record
    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(PIIRedactionLogProcessor())
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
    set_logger_provider(logger_provider)

    LoggingInstrumentor().instrument(set_logging_format=True)
    logging.basicConfig(level=getattr(logging, log_level.upper(), logging.INFO))

    # Auto-instrument outbound HTTP (covers sap-mock calls and Azure SDK calls).
    HTTPXClientInstrumentor().instrument()
    RequestsInstrumentor().instrument()


# Alias used by CLAUDE.md bootstrap name.
init_telemetry = setup_otel


def instrument_app(app) -> None:
    FastAPIInstrumentor.instrument_app(app)


def get_tracer(name: str = "supply-chain-agent"):
    return trace.get_tracer(name)


def get_meter(name: str = "supply-chain-agent"):
    return metrics.get_meter(name)
