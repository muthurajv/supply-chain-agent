from __future__ import annotations

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from .pii import PIIRedactionProcessor


def setup_otel(service_name: str, service_version: str, otlp_endpoint: str) -> None:
    """Bootstrap OpenTelemetry — call once at application startup."""
    resource = Resource.create({
        SERVICE_NAME: service_name,
        SERVICE_VERSION: service_version,
    })

    span_exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(PIIRedactionProcessor())
    tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    trace.set_tracer_provider(tracer_provider)

    metric_exporter = OTLPMetricExporter(endpoint=otlp_endpoint, insecure=True)
    metric_reader = PeriodicExportingMetricReader(metric_exporter, export_interval_millis=30_000)
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

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
