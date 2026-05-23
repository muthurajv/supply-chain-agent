"""POST /chat — interactive user queries via Web UI or Teams."""
import time
import uuid

from fastapi import APIRouter, Depends, Request
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel

from app.agents.graph import get_graph
from app.api.middleware.auth import validate_token
from app.config import get_settings
from app.observability.metrics import (
    workflow_duration_histogram,
    workflow_requests_counter,
    workflows_in_progress_counter,
)

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    thread_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    thread_id: str
    trace_id: str
    approval_required: bool = False
    approval_queue_id: str | None = None


@router.post("", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    request: Request,
    user_id: str = Depends(validate_token),
):
    thread_id = payload.thread_id or str(uuid.uuid4())
    trace_id = getattr(request.state, "trace_id", "unknown")

    if get_settings().app_env == "development":
        checkpointer = MemorySaver()
    else:
        from app.memory.checkpointer import CosmosDBCheckpointer
        checkpointer = CosmosDBCheckpointer()
    graph = get_graph(checkpointer=checkpointer)

    initial_state = {
        "messages": [HumanMessage(content=payload.message)],
        "next_agent": "supervisor",
        "trace_id": trace_id,
        "user_id": user_id,
        "approval_required": False,
    }

    config = {"configurable": {"thread_id": thread_id}}
    workflow_requests_counter().add(1, {"status": "started"})
    workflows_in_progress_counter().add(1)
    t0 = time.perf_counter()
    try:
        final_state = await graph.ainvoke(initial_state, config=config)
        workflow_requests_counter().add(1, {"status": "completed"})
    except Exception:
        workflow_requests_counter().add(1, {"status": "failed"})
        raise
    finally:
        workflow_duration_histogram().record(time.perf_counter() - t0)
        workflows_in_progress_counter().add(-1)

    agent_messages = [
        m for m in final_state.get("messages", [])
        if hasattr(m, "name") and m.name and m.name != "supervisor"
    ]
    reply = agent_messages[-1].content if agent_messages else "Processing complete."

    return ChatResponse(
        reply=reply,
        thread_id=thread_id,
        trace_id=trace_id,
        approval_required=final_state.get("approval_required", False),
        approval_queue_id=final_state.get("approval_queue_id"),
    )
