from __future__ import annotations

import json

from langchain_core.messages import AIMessage, SystemMessage

from app.config import get_settings
from app.llm.client import get_llm
from app.observability.attributes import Attr
from app.observability.spans import agent_span, record_llm_usage

from .state import GraphState

ROUTER_SYSTEM = """You are the supervisor of a supply chain AI system. Your ONLY job is to decide which specialist agent to call next, or to END the workflow.

Specialists:
- inventory_agent: Look up on-hand stock, safety stock, and storage locations
- forecast_agent: Forecast next-month demand from shipment history
- procurement_agent: Recommend what to buy, how much, from which vendor (requires inventory + forecast first)
- policy_agent: Evaluate a procurement proposal against policy rules (requires procurement_proposal in state)
- knowledge_agent: Retrieve policy documents, SOPs, or vendor contract information
- analytics_agent: Compute executive KPIs (used for scheduled refresh tasks)

Rules:
1. For a reorder/procurement query: run inventory_agent → forecast_agent → procurement_agent → policy_agent in that order.
2. If policy_agent returned auto_approved: END.
3. If policy_agent returned denied: END.
4. If task is 'refresh_executive_kpis': run analytics_agent then END.
5. If the question is fully answered: END.

Return ONLY valid JSON: {"next": "<agent_name>"} or {"next": "END"}"""


def _state_summary(state: GraphState) -> str:
    parts = []
    if state.get("inventory_result"):
        inv = state["inventory_result"]
        parts.append(f"inventory_result: on_hand={inv.get('on_hand_qty')}, safety={inv.get('safety_stock')}")
    if state.get("forecast_result"):
        f = state["forecast_result"]
        parts.append(f"forecast_result: forecast_qty={f.get('forecast_qty')}, trend={f.get('trend_pct')}%")
    if state.get("procurement_proposal"):
        p = state["procurement_proposal"]
        parts.append(f"procurement_proposal: qty={p.recommended_qty}, cost=${p.estimated_cost}")
    if state.get("policy_decision"):
        pd = state["policy_decision"]
        parts.append(f"policy_decision: outcome={pd.outcome}, rule={pd.rule_id_fired}")
    if state.get("scheduled_task"):
        parts.append(f"scheduled_task: {state['scheduled_task']}")
    return "\n".join(parts) if parts else "No intermediate results yet."


async def supervisor(state: GraphState) -> dict:
    """Route to the next specialist or end the workflow."""
    turn = state.get("turn", 0) + 1
    with agent_span("supervisor", turn=turn) as span:
        llm = get_llm(temperature=0.0, json_mode=True)
        messages = [
            SystemMessage(content=ROUTER_SYSTEM),
            *state["messages"],
            AIMessage(content=f"Current state:\n{_state_summary(state)}"),
        ]
        response = await llm.ainvoke(messages)
        record_llm_usage("supervisor", response, get_settings().azure_openai_deployment)
        result = json.loads(response.content)
        next_agent = result.get("next", "END")

        span.set_attribute(Attr.AGENT_DECISION, next_agent)

    return {"next_agent": next_agent, "turn": turn, "messages": []}
