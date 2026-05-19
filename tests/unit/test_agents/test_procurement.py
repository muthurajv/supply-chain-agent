"""Unit tests for the Procurement agent — happy path + failure modes (§8.2)."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture
def mock_vendors():
    return [
        {
            "vendor_id": "V-7",
            "name": "Precision Parts Ltd",
            "lead_time_days": 14,
            "preferred": True,
            "payment_terms": "NET30",
        }
    ]


@pytest.mark.asyncio
async def test_procurement_recommends_reorder_when_stock_low(sample_state, mock_vendors):
    # on_hand=220, forecast=380 → gap=160 → reorder needed
    with patch("app.agents.procurement.get_preferred_vendors") as mock_v:
        mock_v.ainvoke = AsyncMock(return_value=mock_vendors)

        from app.agents.procurement import procurement_agent
        command = await procurement_agent(sample_state)

    proposal = command.update["procurement_proposal"]
    assert proposal is not None
    assert proposal.material_id == "M-1042"
    assert proposal.recommended_qty > 0
    assert proposal.vendor_id == "V-7"
    assert proposal.estimated_cost > 0
    assert command.goto == "supervisor"


@pytest.mark.asyncio
async def test_procurement_no_reorder_when_stock_sufficient(sample_state, mock_vendors):
    # on_hand > forecast → no gap
    sample_state["inventory_result"]["on_hand_qty"] = 1000.0
    sample_state["forecast_result"]["forecast_qty"] = 380.0

    with patch("app.agents.procurement.get_preferred_vendors") as mock_v:
        mock_v.ainvoke = AsyncMock(return_value=mock_vendors)

        from app.agents.procurement import procurement_agent
        command = await procurement_agent(sample_state)

    assert command.update.get("procurement_proposal") is None
    assert "No reorder needed" in command.update["messages"][0].content
    assert command.goto == "supervisor"


@pytest.mark.asyncio
async def test_procurement_urgency_is_critical_for_large_gap(sample_state, mock_vendors):
    # Large gap relative to safety stock → critical urgency
    sample_state["inventory_result"]["on_hand_qty"] = 0.0
    sample_state["inventory_result"]["safety_stock"] = 50.0
    sample_state["forecast_result"]["forecast_qty"] = 500.0

    with patch("app.agents.procurement.get_preferred_vendors") as mock_v:
        mock_v.ainvoke = AsyncMock(return_value=mock_vendors)

        from app.agents.procurement import procurement_agent
        command = await procurement_agent(sample_state)

    assert command.update["procurement_proposal"].urgency == "critical"


@pytest.mark.asyncio
async def test_procurement_estimated_cost_matches_qty_times_unit_price(sample_state, mock_vendors):
    with patch("app.agents.procurement.get_preferred_vendors") as mock_v:
        mock_v.ainvoke = AsyncMock(return_value=mock_vendors)

        from app.agents.procurement import procurement_agent
        command = await procurement_agent(sample_state)

    proposal = command.update["procurement_proposal"]
    expected_cost = round(proposal.recommended_qty * 21.0, 2)
    assert proposal.estimated_cost == expected_cost


@pytest.mark.asyncio
async def test_procurement_message_includes_vendor_and_cost(sample_state, mock_vendors):
    with patch("app.agents.procurement.get_preferred_vendors") as mock_v:
        mock_v.ainvoke = AsyncMock(return_value=mock_vendors)

        from app.agents.procurement import procurement_agent
        command = await procurement_agent(sample_state)

    msg = command.update["messages"][0].content
    assert "Precision Parts Ltd" in msg
    assert "V-7" in msg
