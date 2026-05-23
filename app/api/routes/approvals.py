from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from azure.cosmos import exceptions as cosmos_exceptions
from azure.cosmos.aio import CosmosClient
from fastapi import APIRouter, HTTPException
from langgraph.types import Command
from pydantic import BaseModel

from app.agents.graph import get_graph
from app.config import get_settings
from app.memory.checkpointer import CosmosDBCheckpointer
from app.observability.attributes import Attr
from app.observability.loki import push_approval_audit
from app.observability.metrics import set_human_review_queue_depth
from app.observability.otel import get_meter
from app.observability.spans import tool_span

router = APIRouter(prefix="/approvals", tags=["approvals"])

_cycle_histogram = None


def _get_cycle_histogram():
    global _cycle_histogram
    if _cycle_histogram is None:
        _cycle_histogram = get_meter().create_histogram(
            "approval.cycle_duration_seconds",
            unit="s",
            description="Time from proposal creation to human approval decision",
        )
    return _cycle_histogram


class ApprovalDecision(BaseModel):
    approved: bool
    reason: str = ""


async def _get_approval_container():
    s = get_settings()
    client = CosmosClient.from_connection_string(s.cosmos_connection_string)
    db = client.get_database_client(s.cosmos_database)
    return client, db.get_container_client(s.cosmos_container_approvals)


@router.get("")
async def list_pending_approvals():
    """List all pending approval queue items."""
    client, container = await _get_approval_container()
    try:
        items = []
        async for item in container.query_items(
            query="SELECT * FROM c WHERE c.status = 'pending' ORDER BY c.created_at DESC",
        ):
            items.append({
                "id": item["id"],
                "material_id": item.get("material_id"),
                "vendor_id": item.get("vendor_id"),
                "estimated_cost": item.get("estimated_cost"),
                "urgency": item.get("urgency"),
                "rule_id_fired": item.get("rule_id_fired"),
                "rationale": item.get("rationale"),
                "created_at": item.get("created_at"),
            })
        set_human_review_queue_depth(len(items))
        return {"approvals": items, "count": len(items)}
    finally:
        await client.close()


@router.get("/{approval_id}")
async def get_approval(approval_id: str):
    """Get a specific approval queue item."""
    s = get_settings()
    client = CosmosClient.from_connection_string(s.cosmos_connection_string)
    try:
        db = client.get_database_client(s.cosmos_database)
        container = db.get_container_client(s.cosmos_container_approvals)
        item = await container.read_item(item=approval_id, partition_key=approval_id)
        return item
    except cosmos_exceptions.CosmosResourceNotFoundError:
        raise HTTPException(status_code=404, detail=f"Approval '{approval_id}' not found.")
    finally:
        await client.close()


@router.post("/{approval_id}/decide")
async def decide_approval(approval_id: str, payload: ApprovalDecision):
    """Record a human approval decision and resume the paused graph.

    Resuming the LangGraph thread sends Command(resume=...) which continues
    the policy agent from after the interrupt() call (§3.3 step 5).
    """
    s = get_settings()
    cosmos_client = CosmosClient.from_connection_string(s.cosmos_connection_string)

    try:
        db = cosmos_client.get_database_client(s.cosmos_database)
        container = db.get_container_client(s.cosmos_container_approvals)

        try:
            item = await container.read_item(item=approval_id, partition_key=approval_id)
        except cosmos_exceptions.CosmosResourceNotFoundError:
            raise HTTPException(status_code=404, detail=f"Approval '{approval_id}' not found.")

        if item.get("status") != "pending":
            raise HTTPException(status_code=409, detail=f"Approval '{approval_id}' is already {item['status']}.")

        # Record how long the proposal waited before a decision (skip if timestamp absent).
        cycle_secs: float | None = None
        if item.get("created_at"):
            created_at = datetime.fromisoformat(item["created_at"])
            cycle_secs = (datetime.now(timezone.utc) - created_at).total_seconds()

        # Update the queue record.
        item["status"] = "approved" if payload.approved else "rejected"
        item["decided_at"] = datetime.now(timezone.utc).isoformat()
        item["decision_reason"] = payload.reason
        with tool_span("cosmos.update_approval") as span:
            await container.upsert_item(item)
            span.set_attribute(Attr.POLICY_OUTCOME, item["status"])
        if cycle_secs is not None:
            _get_cycle_histogram().record(cycle_secs, {Attr.POLICY_OUTCOME: item["status"]})

        await push_approval_audit(
            approval_id=approval_id,
            decision=item["status"],
            cycle_seconds=cycle_secs,
            reason=payload.reason,
        )

        # Resume the paused LangGraph thread so the policy agent can continue.
        thread_id = item.get("thread_id")
        if thread_id:
            checkpointer = CosmosDBCheckpointer()
            graph = get_graph(checkpointer=checkpointer)
            config = {"configurable": {"thread_id": thread_id}}
            with tool_span("graph.resume") as resume_span:
                await graph.ainvoke(
                    Command(resume={"approved": payload.approved, "reason": payload.reason}),
                    config=config,
                )
                resume_span.set_attribute(Attr.AGENT_DECISION, item["status"])

        return {
            "approval_id": approval_id,
            "status": item["status"],
            "decided_at": item["decided_at"],
            "thread_resumed": thread_id is not None,
        }
    finally:
        await cosmos_client.close()
