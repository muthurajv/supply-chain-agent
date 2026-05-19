"""Unit tests for the Analytics agent — happy path + failure modes (§8.2)."""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_inventory_healthy():
    return {
        "material_id": "M-1001",
        "on_hand_qty": 500.0,
        "safety_stock": 100.0,
    }


@pytest.fixture
def mock_open_pos():
    return [
        {"po_id": "PO-001", "material_id": "M-1001", "qty": 100.0, "status": "open"},
        {"po_id": "PO-002", "material_id": "M-1042", "qty": 200.0, "status": "open"},
    ]


@pytest.mark.asyncio
async def test_analytics_computes_inventory_health_and_po_count(sample_state, mock_open_pos):
    # All 4 tracked materials are above safety stock → health = 100%
    healthy_inv = {"on_hand_qty": 500.0, "safety_stock": 100.0}

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="KPI narrative."))

    with patch("app.agents.analytics.get_inventory") as mock_inv, \
         patch("app.agents.analytics.get_open_pos") as mock_pos, \
         patch("app.agents.analytics.write_kpi") as mock_write, \
         patch("app.agents.analytics.get_llm", return_value=mock_llm):
        mock_inv.ainvoke = AsyncMock(return_value=healthy_inv)
        mock_pos.ainvoke = AsyncMock(return_value=mock_open_pos)
        mock_write.return_value = AsyncMock(return_value={})

        from app.agents.analytics import analytics_agent
        command = await analytics_agent(sample_state)

    kpi = command.update["kpi_results"]
    assert "inventory_health" in kpi
    assert "open_purchase_orders" in kpi
    assert kpi["inventory_health"]["value"] == 100.0
    assert kpi["open_purchase_orders"]["value"] == 2
    assert command.goto == "supervisor"


@pytest.mark.asyncio
async def test_analytics_health_drops_when_material_below_safety_stock(sample_state, mock_open_pos):
    # First material is below safety stock, rest are healthy
    def inv_side_effect(args):
        if args["material_id"] == "M-1001":
            return {"on_hand_qty": 50.0, "safety_stock": 100.0}
        return {"on_hand_qty": 500.0, "safety_stock": 100.0}

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="KPI narrative."))

    with patch("app.agents.analytics.get_inventory") as mock_inv, \
         patch("app.agents.analytics.get_open_pos") as mock_pos, \
         patch("app.agents.analytics.write_kpi") as mock_write, \
         patch("app.agents.analytics.get_llm", return_value=mock_llm):
        mock_inv.ainvoke = AsyncMock(side_effect=inv_side_effect)
        mock_pos.ainvoke = AsyncMock(return_value=mock_open_pos)
        mock_write.return_value = AsyncMock(return_value={})

        from app.agents.analytics import analytics_agent
        command = await analytics_agent(sample_state)

    health = command.update["kpi_results"]["inventory_health"]["value"]
    assert health == 75.0  # 3 of 4 healthy


@pytest.mark.asyncio
async def test_analytics_writes_two_kpis(sample_state, mock_open_pos):
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="Narrative."))

    with patch("app.agents.analytics.get_inventory") as mock_inv, \
         patch("app.agents.analytics.get_open_pos") as mock_pos, \
         patch("app.agents.analytics.write_kpi", new_callable=AsyncMock) as mock_write, \
         patch("app.agents.analytics.get_llm", return_value=mock_llm):
        mock_inv.ainvoke = AsyncMock(return_value={"on_hand_qty": 500.0, "safety_stock": 100.0})
        mock_pos.ainvoke = AsyncMock(return_value=mock_open_pos)

        from app.agents.analytics import analytics_agent
        await analytics_agent(sample_state)

    assert mock_write.call_count == 2
    kpi_names = {call.args[0] for call in mock_write.call_args_list}
    assert "inventory_health" in kpi_names
    assert "open_purchase_orders" in kpi_names


@pytest.mark.asyncio
async def test_analytics_message_includes_kpi_values(sample_state, mock_open_pos):
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="Narrative."))

    with patch("app.agents.analytics.get_inventory") as mock_inv, \
         patch("app.agents.analytics.get_open_pos") as mock_pos, \
         patch("app.agents.analytics.write_kpi", new_callable=AsyncMock), \
         patch("app.agents.analytics.get_llm", return_value=mock_llm):
        mock_inv.ainvoke = AsyncMock(return_value={"on_hand_qty": 500.0, "safety_stock": 100.0})
        mock_pos.ainvoke = AsyncMock(return_value=mock_open_pos)

        from app.agents.analytics import analytics_agent
        command = await analytics_agent(sample_state)

    msg = command.update["messages"][0].content
    assert "100.0%" in msg
    assert "2" in msg
