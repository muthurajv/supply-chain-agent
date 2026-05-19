"""Unit tests for the Forecast Agent."""
from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage


@pytest.mark.asyncio
async def test_forecast_returns_structured_result(sample_state):
    mock_history = [
        {"shipment_date": "2024-01-10", "qty": 300.0, "plant": "P001", "customer": "CUST-101"},
        {"shipment_date": "2024-02-10", "qty": 320.0, "plant": "P001", "customer": "CUST-102"},
    ]
    mock_forecast_json = json.dumps({
        "forecast_qty": 380.0,
        "confidence_low": 320.0,
        "confidence_high": 440.0,
        "trend_pct": 12.0,
        "seasonal_note": "Q4 uplift expected",
        "rationale": "Trending up 12% YoY.",
    })

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content=mock_forecast_json))

    with patch("app.agents.forecast.get_shipment_history") as mock_hist, \
         patch("app.agents.forecast.get_llm", return_value=mock_llm):
        mock_hist.ainvoke = AsyncMock(return_value=mock_history)
        from app.agents.forecast import forecast_agent
        command = await forecast_agent(sample_state)

    assert command.update["forecast_result"]["forecast_qty"] == 380.0
    assert command.update["forecast_result"]["trend_pct"] == 12.0
    assert command.goto == "supervisor"
    assert "380.0" in command.update["messages"][0].content
