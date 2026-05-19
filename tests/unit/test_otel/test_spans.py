"""Unit tests for observability span context managers (§8.2).

Uses InMemorySpanExporter + SimpleSpanProcessor to capture spans without
any real OTLP endpoint (§8.3). The module-level _tracer in spans.py is
patched via monkeypatch to avoid touching the global TracerProvider, which
the OTEL SDK prevents overriding after the first set.
"""
from __future__ import annotations

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from app.observability.attributes import Attr
from app.observability.spans import (
    agent_span,
    policy_evaluation_span,
    rag_span,
    tool_span,
)


@pytest.fixture(autouse=True)
def otel_setup(monkeypatch):
    """Patch the module-level _tracer in spans.py with an in-memory tracer.

    monkeypatch automatically restores the original after each test, giving
    every test a fresh exporter with no leaked spans.
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    test_tracer = provider.get_tracer("supply-chain-agent")
    monkeypatch.setattr("app.observability.spans._tracer", test_tracer)
    yield exporter
    provider.shutdown()


class TestAgentSpan:
    def test_span_name_is_prefixed(self, otel_setup):
        with agent_span("inventory", turn=1):
            pass
        spans = otel_setup.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "agent.inventory"

    def test_agent_name_attribute(self, otel_setup):
        with agent_span("forecast", turn=2):
            pass
        span = otel_setup.get_finished_spans()[0]
        assert span.attributes[Attr.AGENT_NAME] == "forecast"

    def test_agent_turn_attribute(self, otel_setup):
        with agent_span("procurement", turn=3):
            pass
        span = otel_setup.get_finished_spans()[0]
        assert span.attributes[Attr.AGENT_TURN] == 3

    def test_turn_defaults_to_zero(self, otel_setup):
        with agent_span("knowledge"):
            pass
        span = otel_setup.get_finished_spans()[0]
        assert span.attributes[Attr.AGENT_TURN] == 0

    def test_status_ok_on_success(self, otel_setup):
        with agent_span("policy", turn=0):
            pass
        span = otel_setup.get_finished_spans()[0]
        assert span.status.status_code == StatusCode.OK

    def test_status_error_on_exception(self, otel_setup):
        with pytest.raises(ValueError):
            with agent_span("analytics", turn=0):
                raise ValueError("simulated failure")
        span = otel_setup.get_finished_spans()[0]
        assert span.status.status_code == StatusCode.ERROR

    def test_exception_is_recorded_as_event(self, otel_setup):
        with pytest.raises(RuntimeError):
            with agent_span("supervisor", turn=1):
                raise RuntimeError("crash")
        span = otel_setup.get_finished_spans()[0]
        assert any(e.name == "exception" for e in span.events)

    def test_extra_attribute_settable_inside_span(self, otel_setup):
        with agent_span("inventory", turn=0) as span:
            span.set_attribute(Attr.AGENT_DECISION, "reorder=yes")
        finished = otel_setup.get_finished_spans()[0]
        assert finished.attributes[Attr.AGENT_DECISION] == "reorder=yes"


class TestToolSpan:
    def test_span_name_is_prefixed(self, otel_setup):
        with tool_span("cosmos.read_kpi"):
            pass
        spans = otel_setup.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "tool.cosmos.read_kpi"

    def test_tool_name_attribute(self, otel_setup):
        with tool_span("sap_mock.get_inventory"):
            pass
        span = otel_setup.get_finished_spans()[0]
        assert span.attributes[Attr.TOOL_NAME] == "sap_mock.get_inventory"

    def test_duration_ms_set_on_success(self, otel_setup):
        with tool_span("cosmos.write_kpi"):
            pass
        span = otel_setup.get_finished_spans()[0]
        assert Attr.TOOL_DURATION_MS in span.attributes
        assert span.attributes[Attr.TOOL_DURATION_MS] >= 0

    def test_extra_kwargs_land_on_span(self, otel_setup):
        with tool_span("sap_mock.get_inventory", **{Attr.SAP_MOCK: True}):
            pass
        span = otel_setup.get_finished_spans()[0]
        assert span.attributes[Attr.SAP_MOCK] is True

    def test_result_size_settable_inside_span(self, otel_setup):
        with tool_span("cosmos.list_kpis") as span:
            span.set_attribute(Attr.TOOL_RESULT_SIZE, 5)
        finished = otel_setup.get_finished_spans()[0]
        assert finished.attributes[Attr.TOOL_RESULT_SIZE] == 5

    def test_status_ok_on_success(self, otel_setup):
        with tool_span("cosmos.read_kpi"):
            pass
        span = otel_setup.get_finished_spans()[0]
        assert span.status.status_code == StatusCode.OK

    def test_status_error_on_exception(self, otel_setup):
        with pytest.raises(RuntimeError):
            with tool_span("cosmos.read_kpi"):
                raise RuntimeError("cosmos timeout")
        span = otel_setup.get_finished_spans()[0]
        assert span.status.status_code == StatusCode.ERROR

    def test_exception_is_recorded_as_event(self, otel_setup):
        with pytest.raises(ConnectionError):
            with tool_span("sap_mock.get_vendor"):
                raise ConnectionError("unreachable")
        span = otel_setup.get_finished_spans()[0]
        assert any(e.name == "exception" for e in span.events)

    def test_duration_ms_absent_on_exception(self, otel_setup):
        # TOOL_DURATION_MS is set in the success branch only (after yield)
        with pytest.raises(RuntimeError):
            with tool_span("cosmos.write_kpi"):
                raise RuntimeError("write failed")
        span = otel_setup.get_finished_spans()[0]
        assert span.status.status_code == StatusCode.ERROR
        assert Attr.TOOL_DURATION_MS not in span.attributes


class TestPolicyEvaluationSpan:
    def test_span_name(self, otel_setup):
        with policy_evaluation_span(amount_usd=3000.0, threshold_usd=5000.0):
            pass
        spans = otel_setup.get_finished_spans()
        assert spans[0].name == "policy.evaluation"

    def test_amount_usd_attribute(self, otel_setup):
        with policy_evaluation_span(amount_usd=3000.0, threshold_usd=5000.0):
            pass
        span = otel_setup.get_finished_spans()[0]
        assert span.attributes[Attr.POLICY_AMOUNT_USD] == 3000.0

    def test_threshold_usd_attribute(self, otel_setup):
        with policy_evaluation_span(amount_usd=3000.0, threshold_usd=5000.0):
            pass
        span = otel_setup.get_finished_spans()[0]
        assert span.attributes[Attr.POLICY_THRESHOLD_USD] == 5000.0

    def test_policy_span_alias_is_same_object(self):
        from app.observability.spans import policy_span
        assert policy_span is policy_evaluation_span

    def test_policy_evaluation_span_exported_from_package(self):
        from app.observability import policy_evaluation_span as pev
        assert pev is not None

    def test_status_ok_on_success(self, otel_setup):
        with policy_evaluation_span(amount_usd=100.0, threshold_usd=500.0):
            pass
        span = otel_setup.get_finished_spans()[0]
        assert span.status.status_code == StatusCode.OK

    def test_status_error_on_exception(self, otel_setup):
        with pytest.raises(ValueError):
            with policy_evaluation_span(amount_usd=100.0, threshold_usd=500.0):
                raise ValueError("eval failed")
        span = otel_setup.get_finished_spans()[0]
        assert span.status.status_code == StatusCode.ERROR

    def test_policy_attributes_settable_inside_span(self, otel_setup):
        with policy_evaluation_span(amount_usd=500.0, threshold_usd=1000.0) as span:
            span.set_attribute(Attr.POLICY_OUTCOME, "auto_approved")
            span.set_attribute(Attr.POLICY_RULE_ID, "P-PROC-01")
        finished = otel_setup.get_finished_spans()[0]
        assert finished.attributes[Attr.POLICY_OUTCOME] == "auto_approved"
        assert finished.attributes[Attr.POLICY_RULE_ID] == "P-PROC-01"


class TestRagSpan:
    def test_span_name(self, otel_setup):
        with rag_span(query="vendor approval threshold", top_k=5):
            pass
        spans = otel_setup.get_finished_spans()
        assert spans[0].name == "rag.retrieval"

    def test_query_attribute_truncated_to_200(self, otel_setup):
        long_query = "x" * 300
        with rag_span(query=long_query, top_k=5):
            pass
        span = otel_setup.get_finished_spans()[0]
        assert len(span.attributes[Attr.RAG_QUERY]) == 200

    def test_query_attribute_short_query_unchanged(self, otel_setup):
        with rag_span(query="short", top_k=5):
            pass
        span = otel_setup.get_finished_spans()[0]
        assert span.attributes[Attr.RAG_QUERY] == "short"

    def test_top_k_attribute(self, otel_setup):
        with rag_span(query="test", top_k=3):
            pass
        span = otel_setup.get_finished_spans()[0]
        assert span.attributes[Attr.RAG_TOP_K] == 3

    def test_doc_types_joined_with_comma(self, otel_setup):
        with rag_span(query="test", top_k=5, doc_types=["policy", "sop"]):
            pass
        span = otel_setup.get_finished_spans()[0]
        assert span.attributes[Attr.RAG_DOC_TYPES] == "policy,sop"

    def test_doc_types_none_does_not_set_attribute(self, otel_setup):
        with rag_span(query="test", top_k=5, doc_types=None):
            pass
        span = otel_setup.get_finished_spans()[0]
        assert Attr.RAG_DOC_TYPES not in span.attributes

    def test_result_count_settable_inside_span(self, otel_setup):
        with rag_span(query="test", top_k=5) as span:
            span.set_attribute(Attr.RAG_RESULT_COUNT, 3)
        finished = otel_setup.get_finished_spans()[0]
        assert finished.attributes[Attr.RAG_RESULT_COUNT] == 3

    def test_status_ok_on_success(self, otel_setup):
        with rag_span(query="test", top_k=5):
            pass
        span = otel_setup.get_finished_spans()[0]
        assert span.status.status_code == StatusCode.OK

    def test_status_error_on_exception(self, otel_setup):
        with pytest.raises(ConnectionError):
            with rag_span(query="test", top_k=5):
                raise ConnectionError("search timeout")
        span = otel_setup.get_finished_spans()[0]
        assert span.status.status_code == StatusCode.ERROR
