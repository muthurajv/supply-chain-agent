from __future__ import annotations

import uuid
from datetime import datetime, timezone

from azure.cosmos.aio import CosmosClient
from langchain_core.messages import HumanMessage
from langgraph.types import Command, interrupt

from app.config import get_settings
from app.observability.attributes import Attr
from app.observability.spans import agent_span, policy_evaluation_span
from app.policy.evaluator import evaluate_rules
from app.policy.extraction import extract_rules
from app.policy.schema import PolicyDecision, PolicyRule
from app.tools.rag_tools import retrieve_policy_docs

from .state import GraphState

_FALLBACK_RULES: list[PolicyRule] = [
    PolicyRule(
        rule_id="FALLBACK-R1",
        description="Auto-approve preferred vendor PRs under $5,000",
        condition_field="estimated_cost",
        operator="<",
        threshold=5000.0,
        vendor_constraint="V-7",
        on_violation="auto_approved",
        source_excerpt="Preferred vendor purchase requisitions below $5,000 are pre-approved.",
    ),
    PolicyRule(
        rule_id="FALLBACK-R2",
        description="Human review for PRs $5,000–$25,000",
        condition_field="estimated_cost",
        operator="<=",
        threshold=25000.0,
        vendor_constraint=None,
        on_violation="needs_human",
        source_excerpt="Purchase requisitions between $5,000 and $25,000 require manager approval.",
    ),
    PolicyRule(
        rule_id="FALLBACK-R3",
        description="Deny PRs exceeding $25,000 — requires executive approval outside this workflow",
        condition_field="estimated_cost",
        operator=">",
        threshold=25000.0,
        vendor_constraint=None,
        on_violation="denied",
        source_excerpt="Purchase requisitions above $25,000 must follow the executive approval process.",
    ),
]


async def _write_approval_queue(proposal, decision: PolicyDecision) -> str:
    settings = get_settings()
    client = CosmosClient.from_connection_string(settings.cosmos_connection_string)
    try:
        db = client.get_database_client(settings.cosmos_database)
        container = db.get_container_client(settings.cosmos_container_approvals)
        queue_id = f"APQ-{uuid.uuid4().hex[:8].upper()}"
        await container.upsert_item({
            "id": queue_id,
            "material_id": proposal.material_id,
            "vendor_id": proposal.vendor_id,
            "estimated_cost": proposal.estimated_cost,
            "recommended_qty": proposal.recommended_qty,
            "urgency": proposal.urgency,
            "rule_id_fired": decision.rule_id_fired,
            "rationale": decision.rationale,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        return queue_id
    finally:
        await client.close()


async def policy_node(state: GraphState) -> Command:
    """Evaluate procurement proposal against policy rules.

    Phase 1 (LLM): extract structured PolicyRule objects from retrieved policy docs.
    Phase 2 (Python): deterministic evaluate_rules() — no LLM involvement (§7).
    """
    turn = state.get("turn", 0)
    with agent_span("policy", turn=turn) as span:
        proposal = state.get("procurement_proposal")
        if not proposal:
            return Command(
                goto="supervisor",
                update={
                    "messages": [HumanMessage(content="No procurement proposal to evaluate.", name="policy_agent")],
                },
            )

        # Phase 1: retrieve policy docs and extract rules via LLM.
        docs = await retrieve_policy_docs.ainvoke({
            "query": f"procurement approval threshold preferred vendor {proposal.vendor_id}",
            "top_k": 5,
            "doc_type": "policy",
        })
        doc_ids = [d["doc_id"] for d in docs]

        rules = await extract_rules(docs) if docs else _FALLBACK_RULES
        if not rules:
            rules = _FALLBACK_RULES

        # Phase 2: deterministic evaluation — LLM never decides approval.
        with policy_evaluation_span(
            amount_usd=proposal.estimated_cost,
            threshold_usd=rules[0].threshold or 0.0 if rules else 0.0,
        ) as policy_s:
            decision = evaluate_rules(proposal, rules)
            decision.policy_doc_ids = doc_ids

            policy_s.set_attribute(Attr.POLICY_RULE_ID, decision.rule_id_fired)
            policy_s.set_attribute(Attr.POLICY_OUTCOME, decision.outcome)
            policy_s.set_attribute(Attr.POLICY_AMOUNT_USD, decision.amount_usd)
            policy_s.set_attribute(Attr.POLICY_THRESHOLD_USD, decision.threshold_usd)
            policy_s.set_attribute(Attr.POLICY_EXPLANATION, decision.explanation[:500])

        span.set_attribute(Attr.AGENT_DECISION, decision.outcome)

        if decision.outcome == "needs_human":
            queue_id = await _write_approval_queue(proposal, decision)
            summary = (
                f"Procurement proposal for {proposal.material_id} ({proposal.recommended_qty} units, "
                f"${proposal.estimated_cost:,.2f}) requires human approval. "
                f"Queued as {queue_id}. Rule: {decision.rationale}"
            )

            # interrupt() pauses the graph here; execution resumes when the human
            # calls POST /approvals/{queue_id}/decide with Command(resume=...).
            interrupt({"reason": "approval_required", "queue_id": queue_id})

            # Reached only after graph resume.
            return Command(
                goto="supervisor",
                update={
                    "messages": [HumanMessage(content=summary, name="policy_agent")],
                    "policy_decision": decision,
                    "approval_required": True,
                    "approval_queue_id": queue_id,
                },
            )

        if decision.outcome == "denied":
            summary = (
                f"Procurement proposal DENIED. ${proposal.estimated_cost:,.2f} exceeds policy limits. "
                f"Rule: {decision.rationale}"
            )
            return Command(
                goto="supervisor",
                update={
                    "messages": [HumanMessage(content=summary, name="policy_agent")],
                    "policy_decision": decision,
                    "next_agent": "__end__",
                },
            )

        # auto_approved
        summary = (
            f"Procurement proposal AUTO-APPROVED per rule {decision.rule_id_fired}. "
            f"${proposal.estimated_cost:,.2f} within threshold. Rationale: {decision.rationale}"
        )
        return Command(
            goto="supervisor",
            update={
                "messages": [HumanMessage(content=summary, name="policy_agent")],
                "policy_decision": decision,
                "approval_required": False,
            },
        )


policy_agent = policy_node
