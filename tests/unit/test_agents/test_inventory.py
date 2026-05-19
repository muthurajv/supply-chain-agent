"""Unit tests for the Inventory Agent — happy path + failure mode (§8.2)."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import HumanMessage


@pytest.mark.asyncio
async def test_inventory_above_safety_stock(sample_state):
    mock_inv = {
        "material_id": "M-1042",
        "description": "Precision Ball Screw 16mm",
        "plant": "P001",
        "on_hand_qty": 220.0,
        "safety_stock": 150.0,
        "unit": "EA",
        "last_updated": "2024-01-15T00:00:00",
    }
    mock_locations = [{"plant": "P001", "storage_loc": "SL-01", "qty": 150.0}]

    with patch("app.agents.inventory.get_inventory") as mock_get_inv, \
         patch("app.agents.inventory.get_stock_locations") as mock_get_loc:
        mock_get_inv.ainvoke = AsyncMock(return_value=mock_inv)
        mock_get_loc.ainvoke = AsyncMock(return_value=mock_locations)

        from app.agents.inventory import inventory_agent
        command = await inventory_agent(sample_state)

    update = command.update
    assert update["inventory_result"]["on_hand_qty"] == 220.0
    assert update["inventory_result"]["below_safety_stock"] is False
    assert update["material_id"] == "M-1042"
    assert "Above safety stock" in update["messages"][0].content
    assert command.goto == "supervisor"


@pytest.mark.asyncio
async def test_inventory_below_safety_stock(sample_state):
    mock_inv = {
        "material_id": "M-1042",
        "description": "Precision Ball Screw 16mm",
        "plant": "P001",
        "on_hand_qty": 100.0,
        "safety_stock": 150.0,
        "unit": "EA",
        "last_updated": "2024-01-15T00:00:00",
    }
    mock_locations = []

    with patch("app.agents.inventory.get_inventory") as mock_get_inv, \
         patch("app.agents.inventory.get_stock_locations") as mock_get_loc:
        mock_get_inv.ainvoke = AsyncMock(return_value=mock_inv)
        mock_get_loc.ainvoke = AsyncMock(return_value=mock_locations)

        from app.agents.inventory import inventory_agent
        command = await inventory_agent(sample_state)

    assert command.update["inventory_result"]["below_safety_stock"] is True
    assert "BELOW safety stock" in command.update["messages"][0].content
