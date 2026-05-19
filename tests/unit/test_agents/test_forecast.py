"""Unit tests for the Forecast agent — happy path + failure modes (§8.2)."""
from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_history():
    return [
        {"shipment_date": "2024-01-10", "qty": 300.0, "plant": "P001", "customer": "CUST-101"},
        {"shipment_date": "2024-02-10", "qty": 320.0, "plant": "P001", "customer": "CUST-102"},
        {"shipment_date": "2024-03-10", "qty": 310.0, "plant": "P001", "customer": "CUST-101"},
    ]


@pytest.mark.asyncio
async def test_forecast_returns_structured_result(sample_state, mock_history):
    forecast_json = json.dumps({
        "forecast_qty": 380.0,
        "confidence_low": 320.0,
        "confidence_high": 440.0,
        "trend_pct": 12.0,
        "seasonal_note": "Q4 uplift expected",
        "rationale": "Trending up 12% YoY.",
    })

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content=forecast_json))

    with patch("app.agents.forecast.get_shipment_history") as mock_hist, \
         patch("app.agents.forecast.get_llm", return_value=mock_llm):
        mock_hist.ainvoke = AsyncMock(return_value=mock_history)

        from app.agents.forecast import forecast_agent
        command = await forecast_agent(sample_state)

    result = command.update["forecast_result"]
    assert result["forecast_qty"] == 380.0
    assert result["trend_pct"] == 12.0
    assert result["confidence_low"] == 320.0
    assert result["confidence_high"] == 440.0
    assert command.goto == "supervisor"


@pytest.mark.asyncio
async def test_forecast_summary_message_includes_material_id(sample_state, mock_history):
    forecast_json = json.dumps({
        "forecast_qty": 350.0,
        "confidence_low": 300.0,
        "confidence_high": 400.0,
        "trend_pct": 5.0,
        "seasonal_note": "",
        "rationale": "Stable demand.",
    })

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content=forecast_json))

    with patch("app.agents.forecast.get_shipment_history") as mock_hist, \
         patch("app.agents.forecast.get_llm", return_value=mock_llm):
        mock_hist.ainvoke = AsyncMock(return_value=mock_history)

        from app.agents.forecast import forecast_agent
        command = await forecast_agent(sample_state)

    msg = command.update["messages"][0].content
    assert "M-1042" in msg
    assert "350.0" in msg


@pytest.mark.asyncio
async def test_forecast_uses_material_id_from_state(sample_state, mock_history):
    sample_state["material_id"] = "M-9999"

    forecast_json = json.dumps({
        "forecast_qty": 100.0,
        "confidence_low": 80.0,
        "confidence_high": 120.0,
        "trend_pct": -2.0,
        "seasonal_note": "",
        "rationale": "Declining trend.",
    })

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content=forecast_json))

    with patch("app.agents.forecast.get_shipment_history") as mock_hist, \
         patch("app.agents.forecast.get_llm", return_value=mock_llm):
        mock_hist.ainvoke = AsyncMock(return_value=mock_history)

        from app.agents.forecast import forecast_agent
        command = await forecast_agent(sample_state)

    # Verify the tool was called with the correct material ID
    mock_hist.ainvoke.assert_called_once()
    call_args = mock_hist.ainvoke.call_args[0][0]
    assert call_args["material_id"] == "M-9999"


@pytest.mark.asyncio
async def test_forecast_handles_empty_history(sample_state):
    forecast_json = json.dumps({
        "forecast_qty": 0.0,
        "confidence_low": 0.0,
        "confidence_high": 0.0,
        "trend_pct": 0.0,
        "seasonal_note": "No history available",
        "rationale": "Insufficient data to forecast.",
    })

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content=forecast_json))

    with patch("app.agents.forecast.get_shipment_history") as mock_hist, \
         patch("app.agents.forecast.get_llm", return_value=mock_llm):
        mock_hist.ainvoke = AsyncMock(return_value=[])

        from app.agents.forecast import forecast_agent
        command = await forecast_agent(sample_state)

    assert command.update["forecast_result"]["forecast_qty"] == 0.0
    assert command.goto == "supervisor"
