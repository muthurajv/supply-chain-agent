"""Integration tests — full LangGraph run with all external services mocked (§8.1)."""
from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Shared fixture data
# ---------------------------------------------------------------------------

_SAMPLE_INVENTORY = {
    "material_id": "M-1042",
    "description": "Precision Ball Screw 16mm",
    "plant": "P001",
    "on_hand_qty": 220.0,
    "safety_stock": 150.0,
    "unit": "EA",
    "last_updated": "2024-01-15T00:00:00",
}

_SAMPLE_LOCATIONS = [
    {"plant": "P001", "storage_loc": "SL-01", "qty": 150.0},
    {"plant": "P001", "storage_loc": "SL-03", "qty": 70.0},
]

_SAMPLE_HISTORY = [
    {"shipment_date": "2024-01-10", "qty": 300.0, "plant": "P001", "customer": "CUST-101"},
    {"shipment_date": "2024-02-10", "qty": 320.0, "plant": "P001", "customer": "CUST-102"},
    {"shipment_date": "2024-03-10", "qty": 310.0, "plant": "P001", "customer": "CUST-101"},
]

_FORECAST_JSON = json.dumps({
    "forecast_qty": 380.0,
    "confidence_low": 320.0,
    "confidence_high": 440.0,
    "trend_pct": 12.0,
    "seasonal_note": "Q4 uplift expected",
    "rationale": "Trending up 12% YoY.",
})

_PREFERRED_VENDORS = [
    {
        "vendor_id": "V-7",
        "name": "Precision Parts Ltd",
        "lead_time_days": 14,
        "preferred": True,
        "payment_terms": "NET30",
    }
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sup_llm(*next_agents: str) -> MagicMock:
    """Mock supervisor LLM that routes through agents in the given order."""
    mock = MagicMock()
    mock.ainvoke = AsyncMock(side_effect=[
        AIMessage(content=json.dumps({"next": a})) for a in next_agents
    ])
    return mock


def _initial_state(message: str = "Do I need to reorder M-1042?") -> dict:
    return {
        "messages": [HumanMessage(content=message)],
        "next_agent": "",
        "turn": 0,
        "material_id": None,
        "inventory_result": None,
        "forecast_result": None,
        "procurement_proposal": None,
        "policy_decision": None,
        "kpi_results": None,
        "approval_required": False,
        "approval_queue_id": None,
        "trace_id": "integration-test",
        "user_id": "test-user",
        "scheduled_task": None,
    }


def _hop_names(state: dict) -> list[str]:
    return [m.name for m in state["messages"] if getattr(m, "name", None)]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_reorder_flow_auto_approved():
    """Supervisor routes inventory→forecast→procurement→policy→END; proposal auto-approved.

    on_hand=220, forecast=380 → gap=160 → reorder_qty=176 → cost=$3,696 (V-7, <$5k)
    → FALLBACK-R1 fires → auto_approved.
    """
    from app.agents.graph import build_graph

    forecast_llm = MagicMock()
    forecast_llm.ainvoke = AsyncMock(return_value=AIMessage(content=_FORECAST_JSON))

    with patch("app.agents.supervisor.get_llm", return_value=_sup_llm(
        "inventory_agent", "forecast_agent", "procurement_agent", "policy_agent", "END",
    )), \
         patch("app.agents.inventory.get_inventory") as mock_inv, \
         patch("app.agents.inventory.get_stock_locations") as mock_locs, \
         patch("app.agents.forecast.get_shipment_history") as mock_hist, \
         patch("app.agents.forecast.get_llm", return_value=forecast_llm), \
         patch("app.agents.procurement.get_preferred_vendors") as mock_vendors, \
         patch("app.agents.policy.retrieve_policy_docs") as mock_docs:

        mock_inv.ainvoke = AsyncMock(return_value=_SAMPLE_INVENTORY)
        mock_locs.ainvoke = AsyncMock(return_value=_SAMPLE_LOCATIONS)
        mock_hist.ainvoke = AsyncMock(return_value=_SAMPLE_HISTORY)
        mock_vendors.ainvoke = AsyncMock(return_value=_PREFERRED_VENDORS)
        # Empty docs → policy_node falls back to _FALLBACK_RULES (no LLM extraction needed)
        mock_docs.ainvoke = AsyncMock(return_value=[])

        graph = build_graph(checkpointer=MemorySaver())
        state = await graph.ainvoke(
            _initial_state(), {"configurable": {"thread_id": "e2e-001"}}
        )

    decision = state["policy_decision"]
    assert decision is not None, "policy_decision must be set"
    assert decision.outcome == "auto_approved"

    proposal = state["procurement_proposal"]
    assert proposal is not None, "procurement_proposal must be set"
    assert proposal.material_id == "M-1042"
    assert proposal.vendor_id == "V-7"
    assert proposal.estimated_cost < 5_000.0

    assert _hop_names(state) == [
        "inventory_agent", "forecast_agent", "procurement_agent", "policy_agent"
    ]


@pytest.mark.asyncio
async def test_no_reorder_when_stock_sufficient():
    """When on_hand > forecast, procurement emits no proposal and policy is not called."""
    from app.agents.graph import build_graph

    high_inventory = {**_SAMPLE_INVENTORY, "on_hand_qty": 1_000.0}

    forecast_llm = MagicMock()
    forecast_llm.ainvoke = AsyncMock(return_value=AIMessage(content=_FORECAST_JSON))

    with patch("app.agents.supervisor.get_llm", return_value=_sup_llm(
        "inventory_agent", "forecast_agent", "procurement_agent", "END",
    )), \
         patch("app.agents.inventory.get_inventory") as mock_inv, \
         patch("app.agents.inventory.get_stock_locations") as mock_locs, \
         patch("app.agents.forecast.get_shipment_history") as mock_hist, \
         patch("app.agents.forecast.get_llm", return_value=forecast_llm):

        mock_inv.ainvoke = AsyncMock(return_value=high_inventory)
        mock_locs.ainvoke = AsyncMock(return_value=_SAMPLE_LOCATIONS)
        mock_hist.ainvoke = AsyncMock(return_value=_SAMPLE_HISTORY)

        graph = build_graph(checkpointer=MemorySaver())
        state = await graph.ainvoke(
            _initial_state(), {"configurable": {"thread_id": "e2e-002"}}
        )

    assert state.get("procurement_proposal") is None
    assert state.get("policy_decision") is None

    hops = _hop_names(state)
    assert "inventory_agent" in hops
    assert "forecast_agent" in hops
    assert "procurement_agent" in hops
    assert "policy_agent" not in hops


@pytest.mark.asyncio
async def test_analytics_scheduled_task():
    """Scheduled task triggers supervisor→analytics_agent→END; KPIs are written."""
    from app.agents.graph import build_graph

    analytics_llm = MagicMock()
    analytics_llm.ainvoke = AsyncMock(return_value=AIMessage(content="Inventory is healthy."))

    open_pos = [
        {"po_id": "PO-001", "material_id": "M-1001", "qty": 100.0, "status": "open"},
        {"po_id": "PO-002", "material_id": "M-1042", "qty": 200.0, "status": "open"},
    ]

    scheduled = {
        **_initial_state("Refresh executive KPIs."),
        "scheduled_task": "refresh_executive_kpis",
    }

    with patch("app.agents.supervisor.get_llm", return_value=_sup_llm(
        "analytics_agent", "END",
    )), \
         patch("app.agents.analytics.get_inventory") as mock_inv, \
         patch("app.agents.analytics.get_open_pos") as mock_pos, \
         patch("app.agents.analytics.write_kpi", new_callable=AsyncMock), \
         patch("app.agents.analytics.get_llm", return_value=analytics_llm):

        mock_inv.ainvoke = AsyncMock(return_value={"on_hand_qty": 500.0, "safety_stock": 100.0})
        mock_pos.ainvoke = AsyncMock(return_value=open_pos)

        graph = build_graph(checkpointer=MemorySaver())
        state = await graph.ainvoke(
            scheduled, {"configurable": {"thread_id": "e2e-003"}}
        )

    kpis = state["kpi_results"]
    assert kpis is not None
    assert kpis["inventory_health"]["value"] == 100.0
    assert kpis["open_purchase_orders"]["value"] == 2

    assert "analytics_agent" in _hop_names(state)
