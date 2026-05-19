"""POST /agent/invoke — programmatic single-shot calls, used by the AKS CronJob."""
import uuid
from fastapi import APIRouter, Request
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from app.agents.graph import get_graph
from app.memory.checkpointer import CosmosDBCheckpointer

router = APIRouter(prefix="/agent", tags=["invoke"])


class InvokeRequest(BaseModel):
    task: str
    thread_id: str | None = None


@router.post("/invoke")
async def invoke(payload: InvokeRequest, request: Request):
    thread_id = payload.thread_id or str(uuid.uuid4())
    trace_id = getattr(request.state, "trace_id", "unknown")

    checkpointer = CosmosDBCheckpointer()
    graph = get_graph(checkpointer=checkpointer)

    initial_state = {
        "messages": [HumanMessage(content=payload.task)],
        "next_agent": "supervisor",
        "trace_id": trace_id,
        "user_id": "scheduler",
        "approval_required": False,
        "scheduled_task": payload.task,
    }

    config = {"configurable": {"thread_id": thread_id}}
    final_state = await graph.ainvoke(initial_state, config=config)

    return {
        "status": "completed",
        "thread_id": thread_id,
        "trace_id": trace_id,
        "kpi_results": final_state.get("kpi_results"),
        "policy_decision": (
            {
                "outcome": final_state["policy_decision"].outcome,
                "rule_id_fired": final_state["policy_decision"].rule_id_fired,
            }
            if final_state.get("policy_decision")
            else None
        ),
    }
