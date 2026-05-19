"""Shared pytest fixtures for all tests."""
from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage


@pytest.fixture
def sample_inventory():
    return {
        "material_id": "M-1042",
        "description": "Precision Ball Screw 16mm",
        "plant": "P001",
        "on_hand_qty": 220.0,
        "safety_stock": 150.0,
        "unit": "EA",
        "last_updated": "2024-01-15T00:00:00",
        "locations": [
            {"plant": "P001", "storage_loc": "SL-01", "qty": 150.0},
            {"plant": "P001", "storage_loc": "SL-03", "qty": 70.0},
        ],
        "below_safety_stock": False,
    }


@pytest.fixture
def sample_forecast():
    return {
        "forecast_qty": 380.0,
        "confidence_low": 320.0,
        "confidence_high": 440.0,
        "trend_pct": 12.0,
        "seasonal_note": "Q4 uplift expected",
        "rationale": "Trending up 12% YoY with seasonal Q4 lift.",
    }


@pytest.fixture
def sample_state(sample_inventory, sample_forecast):
    return {
        "messages": [HumanMessage(content="Do I need to reorder M-1042 for next month?")],
        "next_agent": "supervisor",
        "turn": 0,
        "material_id": "M-1042",
        "inventory_result": sample_inventory,
        "forecast_result": sample_forecast,
        "procurement_proposal": None,
        "policy_decision": None,
        "kpi_results": None,
        "approval_required": False,
        "approval_queue_id": None,
        "trace_id": "test-trace-001",
        "user_id": "test-user",
        "scheduled_task": None,
    }
