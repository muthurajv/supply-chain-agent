"""Unit tests for the Supervisor agent — happy path + failure modes (§8.2)."""
from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_supervisor_routes_to_inventory_on_new_query(sample_state):
    sample_state["inventory_result"] = None
    sample_state["forecast_result"] = None

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(
        return_value=AIMessage(content=json.dumps({"next": "inventory_agent"}))
    )

    with patch("app.agents.supervisor.get_llm", return_value=mock_llm):
        from app.agents.supervisor import supervisor
        result = await supervisor(sample_state)

    assert result["next_agent"] == "inventory_agent"
    assert result["turn"] == 1


@pytest.mark.asyncio
async def test_supervisor_routes_to_end_after_auto_approval(sample_state):
    from app.policy.schema import PolicyDecision

    sample_state["policy_decision"] = PolicyDecision(
        outcome="auto_approved",
        rule_id_fired="P-PROC-01",
        explanation="Under threshold.",
        rationale="Auto-approved.",
        amount_usd=4200.0,
        threshold_usd=5000.0,
    )

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(
        return_value=AIMessage(content=json.dumps({"next": "END"}))
    )

    with patch("app.agents.supervisor.get_llm", return_value=mock_llm):
        from app.agents.supervisor import supervisor
        result = await supervisor(sample_state)

    assert result["next_agent"] == "END"


@pytest.mark.asyncio
async def test_supervisor_increments_turn_counter(sample_state):
    sample_state["turn"] = 2

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(
        return_value=AIMessage(content=json.dumps({"next": "forecast_agent"}))
    )

    with patch("app.agents.supervisor.get_llm", return_value=mock_llm):
        from app.agents.supervisor import supervisor
        result = await supervisor(sample_state)

    assert result["turn"] == 3


@pytest.mark.asyncio
async def test_supervisor_defaults_to_end_on_missing_next_key(sample_state):
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(
        return_value=AIMessage(content=json.dumps({"decision": "something_else"}))
    )

    with patch("app.agents.supervisor.get_llm", return_value=mock_llm):
        from app.agents.supervisor import supervisor
        result = await supervisor(sample_state)

    assert result["next_agent"] == "END"


@pytest.mark.asyncio
async def test_supervisor_routes_analytics_for_scheduled_task(sample_state):
    sample_state["scheduled_task"] = "refresh_executive_kpis"

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(
        return_value=AIMessage(content=json.dumps({"next": "analytics_agent"}))
    )

    with patch("app.agents.supervisor.get_llm", return_value=mock_llm):
        from app.agents.supervisor import supervisor
        result = await supervisor(sample_state)

    assert result["next_agent"] == "analytics_agent"
