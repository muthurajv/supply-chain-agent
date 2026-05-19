from __future__ import annotations

from typing import Annotated, Optional

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from app.models.procurement import ProcurementRecommendation
from app.policy.schema import PolicyDecision


class GraphState(TypedDict):
    """Shared mutable surface for the LangGraph state machine.

    Producers:
        messages      — every agent appends a HumanMessage(name=agent_name)
        next_agent    — supervisor
        turn          — supervisor (incremented each routing cycle)
        material_id   — inventory agent (extracted from user message)
        inventory_result    — inventory agent
        forecast_result     — forecast agent
        procurement_proposal — procurement agent
        policy_decision     — policy agent
        kpi_results         — analytics agent
        approval_required   — policy agent
        approval_queue_id   — policy agent
        trace_id      — chat/invoke route (request-scoped)
        user_id       — chat/invoke route (from JWT or scheduler)
        scheduled_task — invoke route (for CronJob tasks)
    """

    messages: Annotated[list[BaseMessage], add_messages]
    next_agent: str
    turn: int
    material_id: Optional[str]
    inventory_result: Optional[dict]
    forecast_result: Optional[dict]
    procurement_proposal: Optional[ProcurementRecommendation]
    policy_decision: Optional[PolicyDecision]
    kpi_results: Optional[dict]
    approval_required: bool
    approval_queue_id: Optional[str]
    trace_id: str
    user_id: str
    scheduled_task: Optional[str]


# Keep AgentState as an alias so existing imports don't break during migration.
AgentState = GraphState
