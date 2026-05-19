from __future__ import annotations

from datetime import datetime, timezone

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from app.llm.client import get_llm
from app.observability.attributes import Attr
from app.observability.spans import agent_span
from app.tools.kpi_tools import write_kpi
from app.tools.sap_tools import get_inventory, get_open_pos

from .state import GraphState

_NARRATIVE_SYSTEM = """You are a supply chain analytics expert writing a KPI narrative for the CFO.
Given a KPI value and context, write exactly 2 sentences:
1. What the number means in business terms
2. The key driver or recommended action
Be specific, avoid jargon, use concrete numbers."""

_MATERIALS_TO_TRACK = ["M-1001", "M-1002", "M-1003", "M-1042"]


async def _compute_inventory_health() -> tuple[float, str]:
    total_below = 0
    for mid in _MATERIALS_TO_TRACK:
        inv = await get_inventory.ainvoke({"material_id": mid})
        if inv["on_hand_qty"] < inv["safety_stock"]:
            total_below += 1
    health_pct = round((1 - total_below / len(_MATERIALS_TO_TRACK)) * 100, 1)
    return health_pct, f"{total_below} of {len(_MATERIALS_TO_TRACK)} tracked materials below safety stock."


async def analytics_node(state: GraphState) -> Command:
    """Compute and store executive KPIs: inventory health, open PO count."""
    turn = state.get("turn", 0)
    with agent_span("analytics", turn=turn) as span:
        llm = get_llm(temperature=0.0)
        kpi_results: dict = {}

        # KPI 1: inventory health score
        health_pct, health_ctx = await _compute_inventory_health()
        health_resp = await llm.ainvoke([
            {"role": "system", "content": _NARRATIVE_SYSTEM},
            {"role": "user", "content": f"KPI: Inventory Health Score = {health_pct}%. Context: {health_ctx}"},
        ])
        await write_kpi("inventory_health", health_pct, "%", health_resp.content)
        kpi_results["inventory_health"] = {"value": health_pct, "unit": "%"}

        # KPI 2: open purchase orders
        open_pos = await get_open_pos.ainvoke({})
        po_count = len(open_pos)
        po_resp = await llm.ainvoke([
            {"role": "system", "content": _NARRATIVE_SYSTEM},
            {
                "role": "user",
                "content": f"KPI: Open Purchase Orders = {po_count}. Context: as of {datetime.now(timezone.utc).strftime('%Y-%m-%d')}.",
            },
        ])
        await write_kpi("open_purchase_orders", float(po_count), "count", po_resp.content)
        kpi_results["open_purchase_orders"] = {"value": po_count, "unit": "count"}

        span.set_attribute(Attr.AGENT_DECISION, f"computed {len(kpi_results)} KPIs")

        return Command(
            goto="supervisor",
            update={
                "messages": [HumanMessage(
                    content=f"Executive KPIs updated: inventory health {health_pct}%, {po_count} open POs.",
                    name="analytics_agent",
                )],
                "kpi_results": kpi_results,
            },
        )


analytics_agent = analytics_node
