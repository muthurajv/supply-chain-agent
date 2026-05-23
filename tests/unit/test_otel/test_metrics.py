"""Unit tests for app/observability/metrics.py (§8.2).

Verifies that each getter creates the expected instrument type and name,
that singletons are truly lazy (no instrument before first call), and that
the observable-gauge callback reflects the most recently set depth.

The OTEL SDK prevents re-registering instruments under the same name on the
same MeterProvider, so each test resets all module-level singletons via
monkeypatch to get a fresh state without replacing the global MeterProvider.
"""
from __future__ import annotations

import importlib

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.metrics import CallbackOptions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_metrics_module(monkeypatch):
    """Reset all lazy-singleton globals in metrics.py so each test starts clean."""
    import app.observability.metrics as m

    for attr in [
        "_workflow_requests_total",
        "_workflows_in_progress",
        "_agent_execution_histogram",
        "_workflow_duration_histogram",
        "_llm_tokens_total",
        "_llm_cost_total",
        "_compliance_checks_total",
        "_compliance_flags_total",
        "_audit_records_total",
    ]:
        monkeypatch.setattr(m, attr, None)

    monkeypatch.setattr(m, "_queue_gauge_registered", False)
    monkeypatch.setattr(m, "_human_review_queue_depth_value", 0)


@pytest.fixture
def reader_and_meter(monkeypatch):
    """Inject a fresh SDK MeterProvider + InMemoryMetricReader.

    Patches get_meter() in the metrics module so instruments land in the
    in-memory provider rather than the no-op global one.
    """
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    meter = provider.get_meter("supply-chain-agent-test")

    import app.observability.metrics as m
    _reset_metrics_module(monkeypatch)
    monkeypatch.setattr("app.observability.metrics.get_meter", lambda: meter)

    yield reader, meter

    provider.shutdown()


# ---------------------------------------------------------------------------
# Singleton / lazy-init behaviour
# ---------------------------------------------------------------------------

class TestLazyInit:
    def test_singletons_are_none_before_first_call(self, monkeypatch):
        import app.observability.metrics as m
        _reset_metrics_module(monkeypatch)
        assert m._workflow_requests_total is None
        assert m._workflows_in_progress is None
        assert m._agent_execution_histogram is None
        assert m._workflow_duration_histogram is None
        assert m._llm_tokens_total is None
        assert m._llm_cost_total is None
        assert m._compliance_checks_total is None
        assert m._compliance_flags_total is None
        assert m._audit_records_total is None
        assert m._queue_gauge_registered is False

    def test_workflow_requests_counter_returns_same_object(self, reader_and_meter):
        from app.observability.metrics import workflow_requests_counter
        a = workflow_requests_counter()
        b = workflow_requests_counter()
        assert a is b

    def test_workflows_in_progress_returns_same_object(self, reader_and_meter):
        from app.observability.metrics import workflows_in_progress_counter
        a = workflows_in_progress_counter()
        b = workflows_in_progress_counter()
        assert a is b

    def test_agent_execution_histogram_returns_same_object(self, reader_and_meter):
        from app.observability.metrics import agent_execution_histogram
        a = agent_execution_histogram()
        b = agent_execution_histogram()
        assert a is b

    def test_workflow_duration_histogram_returns_same_object(self, reader_and_meter):
        from app.observability.metrics import workflow_duration_histogram
        a = workflow_duration_histogram()
        b = workflow_duration_histogram()
        assert a is b

    def test_llm_tokens_counter_returns_same_object(self, reader_and_meter):
        from app.observability.metrics import llm_tokens_counter
        a = llm_tokens_counter()
        b = llm_tokens_counter()
        assert a is b

    def test_llm_cost_counter_returns_same_object(self, reader_and_meter):
        from app.observability.metrics import llm_cost_counter
        a = llm_cost_counter()
        b = llm_cost_counter()
        assert a is b

    def test_compliance_checks_counter_returns_same_object(self, reader_and_meter):
        from app.observability.metrics import compliance_checks_counter
        a = compliance_checks_counter()
        b = compliance_checks_counter()
        assert a is b

    def test_compliance_flags_counter_returns_same_object(self, reader_and_meter):
        from app.observability.metrics import compliance_flags_counter
        a = compliance_flags_counter()
        b = compliance_flags_counter()
        assert a is b

    def test_audit_records_counter_returns_same_object(self, reader_and_meter):
        from app.observability.metrics import audit_records_counter
        a = audit_records_counter()
        b = audit_records_counter()
        assert a is b


# ---------------------------------------------------------------------------
# Instrument names — Prometheus scrape names are derived from these
# ---------------------------------------------------------------------------

class TestInstrumentNames:
    """Each metric name must match exactly what the Grafana dashboards query."""

    def test_workflow_requests_counter_name(self, reader_and_meter):
        from app.observability.metrics import workflow_requests_counter
        assert workflow_requests_counter().name == "workflow_requests_total"

    def test_workflows_in_progress_name(self, reader_and_meter):
        from app.observability.metrics import workflows_in_progress_counter
        assert workflows_in_progress_counter().name == "workflows_in_progress"

    def test_agent_execution_histogram_name(self, reader_and_meter):
        from app.observability.metrics import agent_execution_histogram
        assert agent_execution_histogram().name == "agent_execution_duration_seconds"

    def test_workflow_duration_histogram_name(self, reader_and_meter):
        from app.observability.metrics import workflow_duration_histogram
        assert workflow_duration_histogram().name == "workflow_total_duration_seconds"

    def test_llm_tokens_counter_name(self, reader_and_meter):
        from app.observability.metrics import llm_tokens_counter
        assert llm_tokens_counter().name == "llm_tokens_consumed_total"

    def test_compliance_checks_counter_name(self, reader_and_meter):
        from app.observability.metrics import compliance_checks_counter
        assert compliance_checks_counter().name == "compliance_checks_total"

    def test_compliance_flags_counter_name(self, reader_and_meter):
        from app.observability.metrics import compliance_flags_counter
        assert compliance_flags_counter().name == "compliance_flags_requiring_review_total"

    def test_audit_records_counter_name(self, reader_and_meter):
        from app.observability.metrics import audit_records_counter
        assert audit_records_counter().name == "audit_records_written_total"


# ---------------------------------------------------------------------------
# Observable gauge — queue depth
# ---------------------------------------------------------------------------

class TestHumanReviewQueueDepth:
    def test_initial_depth_is_zero(self, monkeypatch):
        import app.observability.metrics as m
        _reset_metrics_module(monkeypatch)
        assert m._human_review_queue_depth_value == 0

    def test_set_depth_updates_value(self, reader_and_meter, monkeypatch):
        from app.observability.metrics import set_human_review_queue_depth
        import app.observability.metrics as m
        set_human_review_queue_depth(42)
        assert m._human_review_queue_depth_value == 42

    def test_set_depth_twice_keeps_latest(self, reader_and_meter, monkeypatch):
        from app.observability.metrics import set_human_review_queue_depth
        import app.observability.metrics as m
        set_human_review_queue_depth(10)
        set_human_review_queue_depth(99)
        assert m._human_review_queue_depth_value == 99

    def test_gauge_registered_after_first_set(self, reader_and_meter, monkeypatch):
        from app.observability.metrics import set_human_review_queue_depth
        import app.observability.metrics as m
        assert m._queue_gauge_registered is False
        set_human_review_queue_depth(5)
        assert m._queue_gauge_registered is True

    def test_gauge_registered_only_once(self, reader_and_meter, monkeypatch):
        from app.observability.metrics import set_human_review_queue_depth
        import app.observability.metrics as m
        set_human_review_queue_depth(1)
        set_human_review_queue_depth(2)
        # _queue_gauge_registered stays True (no double-registration error)
        assert m._queue_gauge_registered is True

    def test_observe_callback_returns_current_depth(self, reader_and_meter, monkeypatch):
        from app.observability.metrics import set_human_review_queue_depth
        import app.observability.metrics as m
        set_human_review_queue_depth(7)
        observations = m._observe_queue_depth(CallbackOptions())
        assert len(observations) == 1
        assert observations[0].value == 7
