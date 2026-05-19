"""Unit tests for PIIRedactionProcessor (§8.2).

Verifies redaction runs on_end, hashes values, preserves non-PII attrs,
and covers every attribute in REDACT_ATTRS. Tracers are obtained directly
from the local TracerProvider (not the global trace API) to avoid the
OTEL SDK's global provider override restriction.
"""
from __future__ import annotations

import hashlib

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.observability.pii import PIIRedactionProcessor, REDACT_ATTRS


@pytest.fixture
def redacting_setup():
    """TracerProvider with PIIRedactionProcessor upstream of InMemorySpanExporter.

    Returns (exporter, tracer) so tests get spans and can create new ones
    without touching the global trace API.
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(PIIRedactionProcessor())
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test")
    yield exporter, tracer
    provider.shutdown()


class TestPIIRedactionProcessor:
    def test_user_email_is_redacted(self, redacting_setup):
        exporter, tracer = redacting_setup
        with tracer.start_as_current_span("test.span") as span:
            span.set_attribute("user.email", "alice@example.com")
        finished = exporter.get_finished_spans()
        value = finished[0].attributes["user.email"]
        assert value.startswith("redacted:")
        assert "alice@example.com" not in value

    def test_redacted_value_matches_sha256_hash(self, redacting_setup):
        exporter, tracer = redacting_setup
        raw = "alice@example.com"
        expected = "redacted:" + hashlib.sha256(raw.encode()).hexdigest()[:12]
        with tracer.start_as_current_span("test.span") as span:
            span.set_attribute("user.email", raw)
        finished = exporter.get_finished_spans()
        assert finished[0].attributes["user.email"] == expected

    def test_non_pii_attribute_passes_through_unchanged(self, redacting_setup):
        exporter, tracer = redacting_setup
        with tracer.start_as_current_span("test.span") as span:
            span.set_attribute("tool.name", "cosmos.read_kpi")
        finished = exporter.get_finished_spans()
        assert finished[0].attributes["tool.name"] == "cosmos.read_kpi"

    def test_rag_query_is_redacted(self, redacting_setup):
        exporter, tracer = redacting_setup
        with tracer.start_as_current_span("test.span") as span:
            span.set_attribute("rag.query", "preferred vendor threshold for V-7")
        finished = exporter.get_finished_spans()
        assert finished[0].attributes["rag.query"].startswith("redacted:")

    def test_authorization_header_is_redacted(self, redacting_setup):
        exporter, tracer = redacting_setup
        with tracer.start_as_current_span("test.span") as span:
            span.set_attribute("http.request.header.authorization", "Bearer secret-token")
        finished = exporter.get_finished_spans()
        assert finished[0].attributes["http.request.header.authorization"].startswith("redacted:")

    def test_user_name_is_redacted(self, redacting_setup):
        exporter, tracer = redacting_setup
        with tracer.start_as_current_span("test.span") as span:
            span.set_attribute("user.name", "Alice Smith")
        finished = exporter.get_finished_spans()
        assert finished[0].attributes["user.name"].startswith("redacted:")

    def test_vendor_contact_is_redacted(self, redacting_setup):
        exporter, tracer = redacting_setup
        with tracer.start_as_current_span("test.span") as span:
            span.set_attribute("vendor.contact", "bob@supplier.com")
        finished = exporter.get_finished_spans()
        assert finished[0].attributes["vendor.contact"].startswith("redacted:")

    def test_enduser_id_is_redacted(self, redacting_setup):
        exporter, tracer = redacting_setup
        with tracer.start_as_current_span("test.span") as span:
            span.set_attribute("enduser.id", "user-12345")
        finished = exporter.get_finished_spans()
        assert finished[0].attributes["enduser.id"].startswith("redacted:")

    def test_absent_pii_attr_does_not_error(self, redacting_setup):
        exporter, tracer = redacting_setup
        with tracer.start_as_current_span("test.span") as span:
            span.set_attribute("agent.name", "inventory")
        finished = exporter.get_finished_spans()
        assert finished[0].attributes["agent.name"] == "inventory"

    @pytest.mark.parametrize("attr", list(REDACT_ATTRS))
    def test_every_redact_attr_is_redacted(self, redacting_setup, attr):
        exporter, tracer = redacting_setup
        with tracer.start_as_current_span("test.span") as span:
            span.set_attribute(attr, f"sensitive-value-for-{attr}")
        finished = exporter.get_finished_spans()
        assert finished[0].attributes[attr].startswith("redacted:"), (
            f"Expected {attr!r} to be redacted"
        )

    def test_redaction_is_deterministic(self, redacting_setup):
        exporter, tracer = redacting_setup
        raw = "test@example.com"
        for _ in range(3):
            with tracer.start_as_current_span("test.span") as span:
                span.set_attribute("user.email", raw)
        finished = exporter.get_finished_spans()
        hashed_values = {s.attributes["user.email"] for s in finished}
        assert len(hashed_values) == 1

    def test_shutdown_does_not_raise(self):
        proc = PIIRedactionProcessor()
        proc.shutdown()

    def test_force_flush_returns_true(self):
        proc = PIIRedactionProcessor()
        assert proc.force_flush(30_000) is True
