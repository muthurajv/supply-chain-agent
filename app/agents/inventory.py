from __future__ import annotations

import re

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from app.observability.attributes import Attr
from app.observability.spans import agent_span
from app.tools.sap_tools import get_inventory, get_stock_locations

from .state import GraphState


def _extract_material_id(text: str) -> str | None:
    match = re.search(r"M-\d{4}", text)
    return match.group(0) if match else None


async def inventory_node(state: GraphState) -> Command:
    """Look up inventory levels and storage locations for a material."""
    turn = state.get("turn", 0)
    with agent_span("inventory", turn=turn) as span:
        material_id = state.get("material_id")
        if not material_id:
            last_msg = state["messages"][-1].content if state["messages"] else ""
            material_id = _extract_material_id(last_msg) or "M-1042"

        inv = await get_inventory.ainvoke({"material_id": material_id})
        locations = await get_stock_locations.ainvoke({"material_id": material_id})

        below_safety = inv["on_hand_qty"] < inv["safety_stock"]
        summary = (
            f"Material {material_id} ({inv['description']}): "
            f"{inv['on_hand_qty']} {inv['unit']} on hand across {len(locations)} location(s). "
            f"Safety stock: {inv['safety_stock']} {inv['unit']}. "
            f"{'BELOW safety stock.' if below_safety else 'Above safety stock.'}"
        )

        span.set_attribute(Attr.AGENT_DECISION, f"on_hand={inv['on_hand_qty']}, safety={inv['safety_stock']}")

        return Command(
            goto="supervisor",
            update={
                "messages": [HumanMessage(content=summary, name="inventory_agent")],
                "material_id": material_id,
                "inventory_result": {**inv, "locations": locations, "below_safety_stock": below_safety},
            },
        )


# Graph registration name.
inventory_agent = inventory_node
