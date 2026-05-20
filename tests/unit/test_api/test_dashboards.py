"""Unit tests for GET /dashboards routes."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch


@pytest.fixture
async def client(fake_env):
    from app.api.routes.dashboards import router

    app = FastAPI()
    app.include_router(router)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_get_kpi_returns_200_when_found(client):
    record = {
        "name": "inventory_health",
        "value": 100.0,
        "unit": "%",
        "narrative": "All materials above safety stock.",
        "computed_at": "2024-01-15T00:00:00Z",
    }

    with patch("app.api.routes.dashboards.read_kpi", new_callable=AsyncMock) as mock_read:
        mock_read.return_value = record
        resp = await client.get("/dashboards/inventory_health")

    assert resp.status_code == 200
    data = resp.json()
    assert data["kpi"] == "inventory_health"
    assert data["value"] == 100.0
    assert data["unit"] == "%"
    assert data["narrative"] == "All materials above safety stock."


@pytest.mark.asyncio
async def test_get_kpi_returns_404_when_not_found(client):
    with patch("app.api.routes.dashboards.read_kpi", new_callable=AsyncMock) as mock_read:
        mock_read.return_value = None
        resp = await client.get("/dashboards/nonexistent_kpi")

    assert resp.status_code == 404
    assert "nonexistent_kpi" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_list_kpis_returns_names_and_timestamps(client):
    kpi_list = [
        {"name": "inventory_health", "computed_at": "2024-01-15T00:00:00Z"},
        {"name": "open_purchase_orders", "computed_at": "2024-01-15T01:00:00Z"},
    ]

    with patch("app.api.routes.dashboards.list_kpis", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = kpi_list
        resp = await client.get("/dashboards")

    assert resp.status_code == 200
    body = resp.json()
    assert "kpis" in body
    assert len(body["kpis"]) == 2
    names = [k["name"] for k in body["kpis"]]
    assert "inventory_health" in names
    assert "open_purchase_orders" in names
