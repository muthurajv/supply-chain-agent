"""Unit tests for the Procurement Agent."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_procurement_recommends_reorder(sample_state):
    mock_vendors = [
        {"vendor_id": "V-7", "name": "Precision Parts Ltd", "lead_time_days": 14, "preferred": True, "payment_terms": "NET30"}
    ]

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
async def test_procurement_no_reorder_when_sufficient(sample_state):
    sample_state["inventory_result"]["on_hand_qty"] = 1000.0
    sample_state["forecast_result"]["forecast_qty"] = 200.0

    mock_vendors = [{"vendor_id": "V-7", "name": "Precision Parts Ltd", "lead_time_days": 14, "preferred": True, "payment_terms": "NET30"}]

    with patch("app.agents.procurement.get_preferred_vendors") as mock_v:
        mock_v.ainvoke = AsyncMock(return_value=mock_vendors)
        from app.agents.procurement import procurement_agent
        command = await procurement_agent(sample_state)

    assert command.update.get("procurement_proposal") is None
    assert "No reorder needed" in command.update["messages"][0].content


@pytest.mark.asyncio
async def test_procurement_urgency_critical(sample_state):
    sample_state["inventory_result"]["on_hand_qty"] = 10.0
    sample_state["forecast_result"]["forecast_qty"] = 500.0
    sample_state["inventory_result"]["safety_stock"] = 50.0

    mock_vendors = [{"vendor_id": "V-7", "name": "Precision Parts Ltd", "lead_time_days": 14, "preferred": True, "payment_terms": "NET30"}]

    with patch("app.agents.procurement.get_preferred_vendors") as mock_v:
        mock_v.ainvoke = AsyncMock(return_value=mock_vendors)
        from app.agents.procurement import procurement_agent
        command = await procurement_agent(sample_state)

    assert command.update["procurement_proposal"].urgency in ("high", "critical")
