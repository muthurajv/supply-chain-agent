from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class PolicyRule(BaseModel):
    """Structured rule extracted from a policy document by the LLM.

    source_excerpt is the audit artifact — the literal sentence the rule came from.
    threshold=None means the policy was ambiguous; on_violation must be needs_human.
    """

    rule_id: str
    description: str
    condition_field: str
    operator: Literal["<", "<=", ">", ">=", "==", "!="]
    threshold: float | None
    vendor_constraint: str | None = None
    on_violation: Literal["auto_approved", "needs_human", "denied"]
    source_excerpt: str = ""


class PolicyDecision(BaseModel):
    """Outcome from the deterministic policy evaluator."""

    outcome: Literal["auto_approved", "needs_human", "denied"]
    rule_id_fired: str
    policy_doc_ids: list[str] = []
    rationale: str = ""
    amount_usd: float = 0.0
    threshold_usd: float = 0.0
    explanation: str = ""
