from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph

from .analytics import analytics_agent
from .forecast import forecast_agent
from .inventory import inventory_agent
from .knowledge import knowledge_agent
from .policy import policy_agent
from .procurement import procurement_agent
from .state import GraphState
from .supervisor import supervisor

_SPECIALIST_NODES = {
    "inventory_agent": inventory_agent,
    "forecast_agent": forecast_agent,
    "procurement_agent": procurement_agent,
    "policy_agent": policy_agent,
    "knowledge_agent": knowledge_agent,
    "analytics_agent": analytics_agent,
}


def _route_from_supervisor(state: GraphState) -> str:
    next_agent = state.get("next_agent", "END")
    if next_agent in ("END", "__end__", ""):
        return END
    if next_agent in _SPECIALIST_NODES:
        return next_agent
    return END


def build_graph(checkpointer: BaseCheckpointSaver | None = None):
    """Build and compile the LangGraph state machine."""
    graph = StateGraph(GraphState)

    graph.add_node("supervisor", supervisor)
    for name, fn in _SPECIALIST_NODES.items():
        graph.add_node(name, fn)

    graph.set_entry_point("supervisor")

    # Supervisor routes to specialists via conditional edge.
    graph.add_conditional_edges(
        "supervisor",
        _route_from_supervisor,
        {**{name: name for name in _SPECIALIST_NODES}, END: END},
    )

    # Specialists route back to supervisor via Command(goto="supervisor") —
    # no static edges needed; Command handles the return hop.

    return graph.compile(checkpointer=checkpointer)


_graph = None


def get_graph(checkpointer: BaseCheckpointSaver | None = None):
    global _graph
    if _graph is None:
        _graph = build_graph(checkpointer=checkpointer)
    return _graph
