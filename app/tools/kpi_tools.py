"""Cosmos DB KPI store — read and write computed executive KPIs."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from azure.cosmos import exceptions as cosmos_exceptions
from azure.cosmos.aio import CosmosClient

from app.config import get_settings
from app.observability.attributes import Attr
from app.observability.spans import tool_span

_cosmos_client: CosmosClient | None = None


def _get_cosmos_client() -> CosmosClient:
    global _cosmos_client
    if _cosmos_client is None:
        _cosmos_client = CosmosClient.from_connection_string(get_settings().cosmos_connection_string)
    return _cosmos_client


async def _get_kpi_container():
    settings = get_settings()
    client = _get_cosmos_client()
    db = client.get_database_client(settings.cosmos_database)
    return db.get_container_client(settings.cosmos_container_kpi)


async def read_kpi(name: str) -> Optional[dict]:
    """Read a KPI record by name. Returns None if not found."""
    with tool_span("cosmos.read_kpi") as span:
        container = await _get_kpi_container()
        try:
            item = await container.read_item(item=name, partition_key=name)
            span.set_attribute(Attr.TOOL_RESULT_SIZE, len(str(item)))
            return item
        except cosmos_exceptions.CosmosResourceNotFoundError:
            span.set_attribute(Attr.TOOL_RESULT_SIZE, 0)
            return None


async def write_kpi(name: str, value: float, unit: str, narrative: str) -> dict:
    """Write or overwrite a KPI record."""
    with tool_span("cosmos.write_kpi") as span:
        container = await _get_kpi_container()
        record = {
            "id": name,
            "name": name,
            "value": value,
            "unit": unit,
            "narrative": narrative,
            "computed_at": datetime.utcnow().isoformat(),
        }
        await container.upsert_item(record)
        span.set_attribute(Attr.TOOL_RESULT_SIZE, len(str(record)))
        return record


async def list_kpis() -> list[dict]:
    """List all available KPI records."""
    with tool_span("cosmos.list_kpis") as span:
        container = await _get_kpi_container()
        items = []
        async for item in container.read_all_items():
            items.append(item)
        span.set_attribute(Attr.TOOL_RESULT_SIZE, len(items))
        return items
