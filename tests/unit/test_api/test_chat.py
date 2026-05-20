"""Unit tests for POST /chat and GET /healthz routes."""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from langchain_core.messages import HumanMessage
from unittest.mock import AsyncMock, MagicMock, patch


def _final_state(reply: str = "Reorder recommended.", approval_required: bool = False) -> dict:
    return {
        "messages": [
            HumanMessage(content="Do I need to reorder M-1042?"),
            HumanMessage(content=reply, name="procurement_agent"),
        ],
        "approval_required": approval_required,
        "approval_queue_id": "APQ-001" if approval_required else None,
        "policy_decision": None,
        "kpi_results": None,
    }


@pytest.fixture
async def client(fake_env):
    from app.api.routes.chat import router, validate_token

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[validate_token] = lambda: "test-user"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# POST /chat
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_chat_returns_200_with_last_agent_reply(client):
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value=_final_state("Reorder 176 units from V-7."))

    with patch("app.api.routes.chat.get_graph", return_value=mock_graph):
        resp = await client.post("/chat", json={"message": "Do I need to reorder M-1042?"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["reply"] == "Reorder 176 units from V-7."
    assert "thread_id" in body
    assert "trace_id" in body
    assert body["approval_required"] is False


@pytest.mark.asyncio
async def test_chat_generates_uuid_thread_id_when_not_provided(client):
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value=_final_state())

    with patch("app.api.routes.chat.get_graph", return_value=mock_graph):
        resp = await client.post("/chat", json={"message": "Hello"})

    thread_id = resp.json()["thread_id"]
    assert len(thread_id) == 36  # UUID4 format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx


@pytest.mark.asyncio
async def test_chat_uses_provided_thread_id(client):
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value=_final_state())

    with patch("app.api.routes.chat.get_graph", return_value=mock_graph):
        resp = await client.post("/chat", json={"message": "Hello", "thread_id": "my-thread-99"})

    assert resp.json()["thread_id"] == "my-thread-99"


@pytest.mark.asyncio
async def test_chat_sets_approval_required_flag(client):
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value=_final_state(approval_required=True))

    with patch("app.api.routes.chat.get_graph", return_value=mock_graph):
        resp = await client.post("/chat", json={"message": "Buy $20k of parts."})

    body = resp.json()
    assert body["approval_required"] is True
    assert body["approval_queue_id"] == "APQ-001"
