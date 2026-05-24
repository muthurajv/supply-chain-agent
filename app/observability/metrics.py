from __future__ import annotations

from opentelemetry.metrics import CallbackOptions, Observation

from .otel import get_meter

# ── lazy singletons (bound after setup_otel() runs) ───────────────────────────

_workflow_requests_total = None
_workflows_in_progress = None
_agent_execution_histogram = None
_workflow_duration_histogram = None
_llm_tokens_total = None
_llm_cost_total = None
_compliance_checks_total = None
_compliance_flags_total = None
_audit_records_total = None
_queue_gauge_registered = False
_human_review_queue_depth_value: int = 0

# New instruments — HTTP, approval cycle, domain KPIs
_http_request_histogram = None
_approval_cycle_histogram = None
_supervisor_routing_total = None
_inventory_below_safety_stock_total = None
_procurement_recommendations_total = None
_forecast_confidence_histogram = None
_rag_retrieval_score_histogram = None

# ── observable gauge callback ─────────────────────────────────────────────────

def _observe_queue_depth(_: CallbackOptions) -> list[Observation]:
    return [Observation(_human_review_queue_depth_value)]


def set_human_review_queue_depth(depth: int) -> None:
    """Update the human-review queue depth observable gauge."""
    global _human_review_queue_depth_value
    _human_review_queue_depth_value = depth
    _ensure_queue_gauge()


def _ensure_queue_gauge() -> None:
    global _queue_gauge_registered
    if not _queue_gauge_registered:
        get_meter().create_observable_gauge(
            "human_review_queue_depth",
            callbacks=[_observe_queue_depth],
            description="Number of pending human-review approvals in the queue",
        )
        _queue_gauge_registered = True


# ── getter functions (lazy init) ──────────────────────────────────────────────

def workflow_requests_counter():
    global _workflow_requests_total
    if _workflow_requests_total is None:
        _workflow_requests_total = get_meter().create_counter(
            "workflow_requests_total",
            description="Total workflow executions labelled by terminal status (completed|failed|interrupted)",
        )
    return _workflow_requests_total


def workflows_in_progress_counter():
    global _workflows_in_progress
    if _workflows_in_progress is None:
        _workflows_in_progress = get_meter().create_up_down_counter(
            "workflows_in_progress",
            description="Workflows currently executing in LangGraph",
        )
    return _workflows_in_progress


def agent_execution_histogram():
    global _agent_execution_histogram
    if _agent_execution_histogram is None:
        _agent_execution_histogram = get_meter().create_histogram(
            "agent_execution_duration_seconds",
            unit="s",
            description="Wall-clock time each agent node takes to execute",
        )
    return _agent_execution_histogram


def workflow_duration_histogram():
    global _workflow_duration_histogram
    if _workflow_duration_histogram is None:
        _workflow_duration_histogram = get_meter().create_histogram(
            "workflow_total_duration_seconds",
            unit="s",
            description="End-to-end duration for a full workflow run (graph.ainvoke)",
        )
    return _workflow_duration_histogram


def llm_tokens_counter():
    global _llm_tokens_total
    if _llm_tokens_total is None:
        _llm_tokens_total = get_meter().create_counter(
            "llm_tokens_consumed_total",
            description="LLM tokens consumed per agent and type (prompt|completion)",
        )
    return _llm_tokens_total


def llm_cost_counter():
    global _llm_cost_total
    if _llm_cost_total is None:
        _llm_cost_total = get_meter().create_counter(
            "llm_estimated_cost_usd_USD",
            unit="USD",
            description="Estimated LLM cost based on GPT-4o pricing ($2.50/1M prompt, $10/1M completion)",
        )
    return _llm_cost_total


def compliance_checks_counter():
    global _compliance_checks_total
    if _compliance_checks_total is None:
        _compliance_checks_total = get_meter().create_counter(
            "compliance_checks_total",
            description="Policy evaluations by outcome (auto_approved|needs_human|denied)",
        )
    return _compliance_checks_total


def compliance_flags_counter():
    global _compliance_flags_total
    if _compliance_flags_total is None:
        _compliance_flags_total = get_meter().create_counter(
            "compliance_flags_requiring_review_total",
            description="Policy checks that required human review, labelled by rule_id",
        )
    return _compliance_flags_total


def audit_records_counter():
    global _audit_records_total
    if _audit_records_total is None:
        _audit_records_total = get_meter().create_counter(
            "audit_records_written_total",
            description="Approval queue records written to Cosmos DB",
        )
    return _audit_records_total


def http_request_histogram():
    global _http_request_histogram
    if _http_request_histogram is None:
        _http_request_histogram = get_meter().create_histogram(
            "http_request_duration_seconds",
            unit="s",
            description="HTTP request duration by method, route, and status code",
        )
    return _http_request_histogram


def approval_cycle_histogram():
    global _approval_cycle_histogram
    if _approval_cycle_histogram is None:
        _approval_cycle_histogram = get_meter().create_histogram(
            "approval_cycle_duration_seconds",
            unit="s",
            description="Time from proposal creation to human approval decision",
        )
    return _approval_cycle_histogram


def supervisor_routing_counter():
    global _supervisor_routing_total
    if _supervisor_routing_total is None:
        _supervisor_routing_total = get_meter().create_counter(
            "supervisor_routing_total",
            description="Supervisor routing decisions by destination agent",
        )
    return _supervisor_routing_total


def inventory_below_safety_stock_counter():
    global _inventory_below_safety_stock_total
    if _inventory_below_safety_stock_total is None:
        _inventory_below_safety_stock_total = get_meter().create_counter(
            "inventory_below_safety_stock_total",
            description="Number of inventory checks where on_hand < safety_stock, by material_id",
        )
    return _inventory_below_safety_stock_total


def procurement_recommendations_counter():
    global _procurement_recommendations_total
    if _procurement_recommendations_total is None:
        _procurement_recommendations_total = get_meter().create_counter(
            "procurement_recommendations_total",
            description="Procurement recommendations generated, by urgency and vendor_id",
        )
    return _procurement_recommendations_total


def forecast_confidence_histogram():
    global _forecast_confidence_histogram
    if _forecast_confidence_histogram is None:
        _forecast_confidence_histogram = get_meter().create_histogram(
            "forecast_confidence_range_units",
            description="Forecast confidence band width (confidence_high - confidence_low) by material",
        )
    return _forecast_confidence_histogram


def rag_retrieval_score_histogram():
    global _rag_retrieval_score_histogram
    if _rag_retrieval_score_histogram is None:
        _rag_retrieval_score_histogram = get_meter().create_histogram(
            "rag_retrieval_score",
            description="Azure AI Search relevance scores for retrieved documents, by index",
        )
    return _rag_retrieval_score_histogram
