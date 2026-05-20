"""Unit tests for GET/POST /approvals routes."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock, patch

from azure.cosmos import exceptions as cosmos_exceptions


def _async_iter(items: list):
    """Wrap a list as an async generator for mocking Cosmos query_items."""
    async def _gen():
        for item in items:
            yield item
    return _gen()


def _mock_container(items: list | None = None, item: dict | None = None):
    """Build a mock Cosmos container with common operations pre-configured."""
    container = MagicMock()
    container.query_items = MagicMock(return_value=_async_iter(items or []))
    container.read_item = AsyncMock(return_value=item or {})
    container.upsert_item = AsyncMock(return_value={})
    return container


def _mock_client_and_container(container):
    client = MagicMock()
    client.close = AsyncMock()
    return client, container


@pytest.fixture
async def client(fake_env):
    from app.api.routes.approvals import router

    app = FastAPI()
    app.include_router(router)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# GET /approvals
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_pending_approvals_returns_items(client):
    pending = [
        {
            "id": "APQ-001",
            "material_id": "M-1042",
            "vendor_id": "V-7",
            "estimated_cost": 3696.0,
            "urgency": "medium",
            "rule_id_fired": "FALLBACK-R2",
            "rationale": "Between $5k–$25k.",
            "created_at": "2024-01-15T00:00:00Z",
            "status": "pending",
        }
    ]
    container = _mock_container(items=pending)
    mock_client, _ = _mock_client_and_container(container)

    with patch("app.api.routes.approvals._get_approval_container", return_value=(mock_client, container)):
        resp = await client.get("/approvals")

    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["approvals"][0]["id"] == "APQ-001"


@pytest.mark.asyncio
async def test_list_pending_approvals_returns_empty_when_none(client):
    container = _mock_container(items=[])
    mock_client, _ = _mock_client_and_container(container)

    with patch("app.api.routes.approvals._get_approval_container", return_value=(mock_client, container)):
        resp = await client.get("/approvals")

    assert resp.status_code == 200
    assert resp.json()["count"] == 0


# ---------------------------------------------------------------------------
# GET /approvals/{id}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_approval_returns_item(client):
    item = {"id": "APQ-001", "status": "pending", "material_id": "M-1042"}

    with patch("azure.cosmos.aio.CosmosClient.from_connection_string") as mock_ctor:
        mock_cosmos = MagicMock()
        mock_cosmos.close = AsyncMock()
        mock_db = MagicMock()
        mock_container = MagicMock()
        mock_container.read_item = AsyncMock(return_value=item)
        mock_ctor.return_value = mock_cosmos
        mock_cosmos.get_database_client.return_value = mock_db
        mock_db.get_container_client.return_value = mock_container

        resp = await client.get("/approvals/APQ-001")

    assert resp.status_code == 200
    assert resp.json()["id"] == "APQ-001"


@pytest.mark.asyncio
async def test_get_approval_returns_404_when_not_found(client):
    with patch("azure.cosmos.aio.CosmosClient.from_connection_string") as mock_ctor:
        mock_cosmos = MagicMock()
        mock_cosmos.close = AsyncMock()
        mock_db = MagicMock()
        mock_container = MagicMock()
        mock_container.read_item = AsyncMock(
            side_effect=cosmos_exceptions.CosmosResourceNotFoundError(message="Not found", status_code=404, headers={})
        )
        mock_ctor.return_value = mock_cosmos
        mock_cosmos.get_database_client.return_value = mock_db
        mock_db.get_container_client.return_value = mock_container

        resp = await client.get("/approvals/MISSING")

    assert resp.status_code == 404
    assert "MISSING" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /approvals/{id}/decide
# ---------------------------------------------------------------------------

def _pending_item(approval_id: str = "APQ-001") -> dict:
    return {
        "id": approval_id,
        "status": "pending",
        "material_id": "M-1042",
        "vendor_id": "V-7",
        "estimated_cost": 8500.0,
    }


@pytest.mark.asyncio
async def test_decide_approval_approved_sets_status(client):
    item = _pending_item()

    with patch("azure.cosmos.aio.CosmosClient.from_connection_string") as mock_ctor:
        mock_cosmos = MagicMock()
        mock_cosmos.close = AsyncMock()
        mock_db = MagicMock()
        mock_container = MagicMock()
        mock_container.read_item = AsyncMock(return_value=dict(item))
        mock_container.upsert_item = AsyncMock(return_value={})
        mock_ctor.return_value = mock_cosmos
        mock_cosmos.get_database_client.return_value = mock_db
        mock_db.get_container_client.return_value = mock_container

        resp = await client.post(
            "/approvals/APQ-001/decide",
            json={"approved": True, "reason": "Looks good."},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "approved"
    assert body["approval_id"] == "APQ-001"
    assert body["thread_resumed"] is False


@pytest.mark.asyncio
async def test_decide_approval_rejected_sets_status(client):
    item = _pending_item()

    with patch("azure.cosmos.aio.CosmosClient.from_connection_string") as mock_ctor:
        mock_cosmos = MagicMock()
        mock_cosmos.close = AsyncMock()
        mock_db = MagicMock()
        mock_container = MagicMock()
        mock_container.read_item = AsyncMock(return_value=dict(item))
        mock_container.upsert_item = AsyncMock(return_value={})
        mock_ctor.return_value = mock_cosmos
        mock_cosmos.get_database_client.return_value = mock_db
        mock_db.get_container_client.return_value = mock_container

        resp = await client.post(
            "/approvals/APQ-001/decide",
            json={"approved": False, "reason": "Over budget."},
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"


@pytest.mark.asyncio
async def test_decide_approval_returns_409_when_already_decided(client):
    already_decided = {**_pending_item(), "status": "approved"}

    with patch("azure.cosmos.aio.CosmosClient.from_connection_string") as mock_ctor:
        mock_cosmos = MagicMock()
        mock_cosmos.close = AsyncMock()
        mock_db = MagicMock()
        mock_container = MagicMock()
        mock_container.read_item = AsyncMock(return_value=already_decided)
        mock_ctor.return_value = mock_cosmos
        mock_cosmos.get_database_client.return_value = mock_db
        mock_db.get_container_client.return_value = mock_container

        resp = await client.post(
            "/approvals/APQ-001/decide",
            json={"approved": True, "reason": ""},
        )

    assert resp.status_code == 409
    assert "approved" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_decide_approval_returns_404_when_not_found(client):
    with patch("azure.cosmos.aio.CosmosClient.from_connection_string") as mock_ctor:
        mock_cosmos = MagicMock()
        mock_cosmos.close = AsyncMock()
        mock_db = MagicMock()
        mock_container = MagicMock()
        mock_container.read_item = AsyncMock(
            side_effect=cosmos_exceptions.CosmosResourceNotFoundError(message="Not found", status_code=404, headers={})
        )
        mock_ctor.return_value = mock_cosmos
        mock_cosmos.get_database_client.return_value = mock_db
        mock_db.get_container_client.return_value = mock_container

        resp = await client.post(
            "/approvals/MISSING/decide",
            json={"approved": True, "reason": ""},
        )

    assert resp.status_code == 404
