from __future__ import annotations

import httpx
from langchain_core.tools import tool

from app.config import get_settings
from app.observability.attributes import Attr
from app.observability.spans import tool_span

_client: httpx.AsyncClient | None = None


def get_sap_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(base_url=get_settings().sap_mock_base_url, timeout=10.0)
    return _client


@tool
async def get_inventory(material_id: str) -> dict:
    """Get current inventory levels and safety stock for a material."""
    with tool_span("sap_mock.get_inventory", **{Attr.SAP_MOCK: True}) as span:
        resp = await get_sap_client().get(f"/inventory/{material_id}")
        resp.raise_for_status()
        data = resp.json()
        span.set_attribute(Attr.TOOL_RESULT_SIZE, len(str(data)))
        return data


@tool
async def get_stock_locations(material_id: str) -> list[dict]:
    """Get all stock locations and quantities for a material."""
    with tool_span("sap_mock.get_stock_locations", **{Attr.SAP_MOCK: True}) as span:
        resp = await get_sap_client().get(f"/inventory/{material_id}/locations")
        resp.raise_for_status()
        data = resp.json()
        span.set_attribute(Attr.TOOL_RESULT_SIZE, len(str(data)))
        return data


@tool
async def get_shipment_history(material_id: str, months: int = 18) -> list[dict]:
    """Get historical shipment records for a material over the past N months."""
    with tool_span("sap_mock.get_shipment_history", **{Attr.SAP_MOCK: True}) as span:
        resp = await get_sap_client().get(f"/shipments/history/{material_id}", params={"months": months})
        resp.raise_for_status()
        data = resp.json()
        span.set_attribute(Attr.TOOL_RESULT_SIZE, len(str(data)))
        return data


@tool
async def get_vendor(vendor_id: str) -> dict:
    """Get vendor details including lead time and preferred status."""
    with tool_span("sap_mock.get_vendor", **{Attr.SAP_MOCK: True}) as span:
        resp = await get_sap_client().get(f"/vendors/{vendor_id}")
        resp.raise_for_status()
        data = resp.json()
        span.set_attribute(Attr.TOOL_RESULT_SIZE, len(str(data)))
        return data


@tool
async def get_preferred_vendors() -> list[dict]:
    """Get list of all preferred vendors."""
    with tool_span("sap_mock.get_preferred_vendors", **{Attr.SAP_MOCK: True}) as span:
        resp = await get_sap_client().get("/vendors/", params={"preferred_only": True})
        resp.raise_for_status()
        data = resp.json()
        span.set_attribute(Attr.TOOL_RESULT_SIZE, len(str(data)))
        return data


@tool
async def get_open_pos(material_id: str | None = None) -> list[dict]:
    """Get open purchase orders, optionally filtered by material."""
    with tool_span("sap_mock.get_open_pos", **{Attr.SAP_MOCK: True}) as span:
        params = {}
        if material_id:
            params["material_id"] = material_id
        resp = await get_sap_client().get("/po/open", params=params)
        resp.raise_for_status()
        data = resp.json()
        span.set_attribute(Attr.TOOL_RESULT_SIZE, len(str(data)))
        return data


@tool
async def create_pr_mock(material_id: str, vendor_id: str, qty: float, unit_price: float) -> dict:
    """Create a purchase requisition in the SAP mock system."""
    with tool_span("sap_mock.create_pr", **{Attr.SAP_MOCK: True}) as span:
        resp = await get_sap_client().post(
            "/po/create",
            json={"material_id": material_id, "vendor_id": vendor_id, "qty": qty, "unit_price": unit_price},
        )
        resp.raise_for_status()
        data = resp.json()
        span.set_attribute(Attr.TOOL_RESULT_SIZE, len(str(data)))
        return data


@tool
async def get_grs(po_number: str) -> list[dict]:
    """Get goods receipts for a given purchase order."""
    with tool_span("sap_mock.get_grs", **{Attr.SAP_MOCK: True}) as span:
        resp = await get_sap_client().get(f"/gr/{po_number}")
        resp.raise_for_status()
        data = resp.json()
        span.set_attribute(Attr.TOOL_RESULT_SIZE, len(str(data)))
        return data
