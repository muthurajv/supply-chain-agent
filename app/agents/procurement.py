from __future__ import annotations

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from app.models.procurement import ProcurementRecommendation
from app.observability.attributes import Attr
from app.observability.spans import agent_span
from app.tools.sap_tools import get_preferred_vendors

from .state import GraphState

_BUFFER_FACTOR = 1.10
_PREFERRED_VENDOR_ID = "V-7"
_DEFAULT_UNIT_PRICE = 21.0


def _urgency(gap: float, safety_stock: float) -> str:
    ratio = gap / max(safety_stock, 1)
    if ratio > 2:
        return "critical"
    if ratio > 1:
        return "high"
    if ratio > 0.5:
        return "medium"
    return "low"


async def procurement_node(state: GraphState) -> Command:
    """Recommend what to purchase, how much, from whom, and at what cost."""
    turn = state.get("turn", 0)
    with agent_span("procurement", turn=turn) as span:
        inv = state.get("inventory_result", {})
        forecast = state.get("forecast_result", {})
        material_id = state.get("material_id", "M-1042")

        on_hand = inv.get("on_hand_qty", 0)
        forecast_qty = forecast.get("forecast_qty", 0)
        safety_stock = inv.get("safety_stock", 0)

        net_demand = forecast_qty - on_hand
        reorder_qty = max(round(net_demand * _BUFFER_FACTOR, 0), 0)

        if reorder_qty <= 0:
            span.set_attribute(Attr.AGENT_DECISION, "no_reorder_needed")
            return Command(
                goto="supervisor",
                update={
                    "messages": [HumanMessage(
                        content=(
                            f"No reorder needed for {material_id}. "
                            f"On hand ({on_hand}) covers forecast demand ({forecast_qty})."
                        ),
                        name="procurement_agent",
                    )],
                },
            )

        vendors = await get_preferred_vendors.ainvoke({})
        vendor = next((v for v in vendors if v["vendor_id"] == _PREFERRED_VENDOR_ID), vendors[0] if vendors else None)
        vendor_id = vendor["vendor_id"] if vendor else _PREFERRED_VENDOR_ID
        vendor_name = vendor["name"] if vendor else "Precision Parts Ltd"
        lead_time = vendor["lead_time_days"] if vendor else 14

        est_cost = round(reorder_qty * _DEFAULT_UNIT_PRICE, 2)
        urgency = _urgency(net_demand, safety_stock)

        proposal = ProcurementRecommendation(
            material_id=material_id,
            description=inv.get("description", material_id),
            recommended_qty=reorder_qty,
            vendor_id=vendor_id,
            vendor_name=vendor_name,
            unit_price=_DEFAULT_UNIT_PRICE,
            estimated_cost=est_cost,
            lead_time_days=lead_time,
            urgency=urgency,
            rationale=(
                f"On hand: {on_hand}, forecast demand: {forecast_qty}, gap: {net_demand:.0f}. "
                f"Recommend ordering {reorder_qty} units (+{int((_BUFFER_FACTOR - 1) * 100)}% buffer) "
                f"from {vendor_name} at ${_DEFAULT_UNIT_PRICE}/unit. Estimated cost: ${est_cost:,.2f}."
            ),
        )

        span.set_attribute(Attr.PROCUREMENT_QTY, reorder_qty)
        span.set_attribute(Attr.PROCUREMENT_COST, est_cost)
        span.set_attribute(Attr.PROCUREMENT_URGENCY, urgency)
        span.set_attribute(Attr.AGENT_DECISION, f"reorder_qty={reorder_qty}, cost={est_cost}, urgency={urgency}")

        return Command(
            goto="supervisor",
            update={
                "messages": [HumanMessage(
                    content=(
                        f"Procurement recommendation for {material_id}: Order {reorder_qty} units from "
                        f"{vendor_name} ({vendor_id}), ${est_cost:,.2f} total, {lead_time}-day lead time. "
                        f"Urgency: {urgency}."
                    ),
                    name="procurement_agent",
                )],
                "procurement_proposal": proposal,
            },
        )


procurement_agent = procurement_node
