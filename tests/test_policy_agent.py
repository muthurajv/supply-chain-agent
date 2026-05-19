"""Regression tests for policy agent outcomes — imports from canonical location."""
from __future__ import annotations

import pytest

from app.models.procurement import ProcurementRecommendation
from app.policy.evaluator import evaluate_rules
from app.policy.schema import PolicyRule


def _make_proposal(cost: float, vendor_id: str = "V-7") -> ProcurementRecommendation:
    return ProcurementRecommendation(
        material_id="M-1042",
        description="Precision Ball Screw 16mm",
        recommended_qty=200.0,
        vendor_id=vendor_id,
        vendor_name="Precision Parts Ltd",
        unit_price=21.0,
        estimated_cost=cost,
        lead_time_days=14,
        urgency="medium",
        rationale="Test proposal",
    )


STANDARD_RULES = [
    PolicyRule(
        rule_id="P-PROC-03-R1",
        description="Auto-approve preferred vendor PRs under $5,000",
        condition_field="estimated_cost",
        operator="<",
        threshold=5000.0,
        vendor_constraint="V-7",
        on_violation="auto_approved",
        source_excerpt="Preferred vendor PRs below $5,000 are pre-approved.",
    ),
    PolicyRule(
        rule_id="P-PROC-03-R2",
        description="Human review for PRs $5,000–$25,000",
        condition_field="estimated_cost",
        operator="<=",
        threshold=25000.0,
        vendor_constraint=None,
        on_violation="needs_human",
        source_excerpt="PRs between $5,000 and $25,000 require manager approval.",
    ),
    PolicyRule(
        rule_id="P-PROC-03-R3",
        description="Deny PRs over $25,000",
        condition_field="estimated_cost",
        operator=">",
        threshold=25000.0,
        vendor_constraint=None,
        on_violation="denied",
        source_excerpt="PRs above $25,000 must follow the executive approval process.",
    ),
]


def test_auto_approved_preferred_vendor_under_threshold():
    proposal = _make_proposal(cost=4200.0, vendor_id="V-7")
    decision = evaluate_rules(proposal, STANDARD_RULES)
    assert decision.outcome == "auto_approved"
    assert decision.rule_id_fired == "P-PROC-03-R1"
    assert decision.amount_usd == 4200.0


def test_needs_human_above_auto_threshold():
    proposal = _make_proposal(cost=12000.0, vendor_id="V-7")
    decision = evaluate_rules(proposal, STANDARD_RULES)
    assert decision.outcome == "needs_human"
    assert decision.rule_id_fired == "P-PROC-03-R2"


def test_denied_exceeds_max_threshold():
    proposal = _make_proposal(cost=30000.0)
    decision = evaluate_rules(proposal, STANDARD_RULES)
    assert decision.outcome == "denied"
    assert decision.rule_id_fired == "P-PROC-03-R3"


def test_vendor_constraint_prevents_auto_approve():
    """V-2 doesn't satisfy the V-7 constraint on R1 → needs_human."""
    proposal = _make_proposal(cost=3000.0, vendor_id="V-2")
    decision = evaluate_rules(proposal, STANDARD_RULES)
    assert decision.outcome == "needs_human"


def test_no_rules_defaults_to_needs_human():
    proposal = _make_proposal(cost=1000.0)
    decision = evaluate_rules(proposal, [])
    assert decision.outcome == "needs_human"
    assert decision.rule_id_fired == "DEFAULT"


def test_exact_threshold_boundary():
    """R1 is strict < so cost=5000.0 does NOT match; falls through to R2."""
    proposal = _make_proposal(cost=5000.0, vendor_id="V-7")
    decision = evaluate_rules(proposal, STANDARD_RULES)
    assert decision.outcome == "needs_human"
