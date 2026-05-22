"""Unit tests for POST /agent/invoke."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from langchain_core.messages import HumanMessage
from unittest.mock import AsyncMock, MagicMock, patch


def _final_state(
    kpi_results: dict | None = None,
    policy_outcome: str | None = None,
) -> dict:
    state: dict = {
        "messages": [HumanMessage(content="refresh_executive_kpis")],
        "kpi_results": kpi_results,
        "policy_decision": None,
    }
    if policy_outcome:
        pd = MagicMock()
        pd.outcome = policy_outcome
        pd.rule_id_fired = "P-PROC-01"
        state["policy_decision"] = pd
    return state


@pytest.fixture
async def client(fake_env):
    from app.api.routes.invoke import router

    app = FastAPI()
    app.include_router(router)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_invoke_returns_200_and_completed_status(client):
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value=_final_state(kpi_results={"revenue": 1_000_000}))

    with patch("app.api.routes.invoke.get_graph", return_value=mock_graph), \
         patch("app.api.routes.invoke.CosmosDBCheckpointer"):
        resp = await client.post("/agent/invoke", json={"task": "refresh_executive_kpis"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    assert body["kpi_results"] == {"revenue": 1_000_000}


@pytest.mark.asyncio
async def test_invoke_generates_thread_id_when_not_provided(client):
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value=_final_state())

    with patch("app.api.routes.invoke.get_graph", return_value=mock_graph), \
         patch("app.api.routes.invoke.CosmosDBCheckpointer"):
        resp = await client.post("/agent/invoke", json={"task": "refresh_executive_kpis"})

    thread_id = resp.json()["thread_id"]
    # UUID4 format: 8-4-4-4-12 hex digits with hyphens = 36 chars
    assert len(thread_id) == 36
    assert thread_id.count("-") == 4


@pytest.mark.asyncio
async def test_invoke_uses_provided_thread_id(client):
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value=_final_state())

    with patch("app.api.routes.invoke.get_graph", return_value=mock_graph), \
         patch("app.api.routes.invoke.CosmosDBCheckpointer"):
        resp = await client.post(
            "/agent/invoke",
            json={"task": "refresh_executive_kpis", "thread_id": "cron-thread-42"},
        )

    assert resp.json()["thread_id"] == "cron-thread-42"


@pytest.mark.asyncio
async def test_invoke_returns_policy_decision_when_present(client):
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(
        return_value=_final_state(policy_outcome="auto_approved")
    )

    with patch("app.api.routes.invoke.get_graph", return_value=mock_graph), \
         patch("app.api.routes.invoke.CosmosDBCheckpointer"):
        resp = await client.post("/agent/invoke", json={"task": "procurement_check"})

    pd = resp.json()["policy_decision"]
    assert pd is not None
    assert pd["outcome"] == "auto_approved"
    assert pd["rule_id_fired"] == "P-PROC-01"


@pytest.mark.asyncio
async def test_invoke_returns_null_policy_decision_when_absent(client):
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value=_final_state())

    with patch("app.api.routes.invoke.get_graph", return_value=mock_graph), \
         patch("app.api.routes.invoke.CosmosDBCheckpointer"):
        resp = await client.post("/agent/invoke", json={"task": "refresh_executive_kpis"})

    assert resp.json()["policy_decision"] is None


@pytest.mark.asyncio
async def test_invoke_response_includes_trace_id(client):
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value=_final_state())

    with patch("app.api.routes.invoke.get_graph", return_value=mock_graph), \
         patch("app.api.routes.invoke.CosmosDBCheckpointer"):
        resp = await client.post("/agent/invoke", json={"task": "refresh_executive_kpis"})

    assert "trace_id" in resp.json()
