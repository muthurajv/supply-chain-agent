"""Unit tests for the deterministic policy evaluator — 100% branch coverage required (§7).

Every branch in app/policy/evaluator.py must be hit by at least one test case.
Use pytest.mark.parametrize for exhaustive table-driven coverage.
"""
from __future__ import annotations

import pytest

from app.models.procurement import ProcurementRecommendation
from app.policy.evaluator import evaluate_rules
from app.policy.schema import PolicyDecision, PolicyRule


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _proposal(
    cost: float = 3000.0,
    vendor_id: str = "V-7",
    qty: float = 200.0,
    urgency: str = "medium",
) -> ProcurementRecommendation:
    return ProcurementRecommendation(
        material_id="M-1042",
        description="Precision Ball Screw 16mm",
        recommended_qty=qty,
        vendor_id=vendor_id,
        vendor_name="Precision Parts Ltd",
        unit_price=21.0,
        estimated_cost=cost,
        lead_time_days=14,
        urgency=urgency,
        rationale="Test proposal",
    )


def _rule(
    rule_id: str = "P-TEST-01",
    condition_field: str = "estimated_cost",
    operator: str = "<",
    threshold: float | None = 5000.0,
    vendor_constraint: str | None = None,
    on_violation: str = "auto_approved",
    source_excerpt: str = "Test rule.",
) -> PolicyRule:
    return PolicyRule(
        rule_id=rule_id,
        description=f"Test rule {rule_id}",
        condition_field=condition_field,
        operator=operator,
        threshold=threshold,
        vendor_constraint=vendor_constraint,
        on_violation=on_violation,
        source_excerpt=source_excerpt,
    )


# Standard three-tier rules used across multiple tests.
STANDARD_RULES = [
    _rule("P-PROC-01", operator="<", threshold=5000.0, vendor_constraint="V-7", on_violation="auto_approved"),
    _rule("P-PROC-02", operator="<=", threshold=25000.0, on_violation="needs_human"),
    _rule("P-PROC-03", operator=">", threshold=25000.0, on_violation="denied"),
]


# ---------------------------------------------------------------------------
# Step 1: Forbidden vendor → denied
# ---------------------------------------------------------------------------

def test_forbidden_vendor_is_denied_immediately():
    """A rule that explicitly denies vendor V-BAD triggers before any threshold check."""
    rules = [
        _rule("P-DENY-01", vendor_constraint="V-BAD", on_violation="denied"),
        _rule("P-AUTO-01", operator="<", threshold=1_000_000.0, on_violation="auto_approved"),
    ]
    decision = evaluate_rules(_proposal(cost=100.0, vendor_id="V-BAD"), rules)
    assert decision.outcome == "denied"
    assert decision.rule_id_fired == "P-DENY-01"


def test_forbidden_vendor_rule_does_not_trigger_for_other_vendors():
    """The forbidden-vendor rule is skipped when the proposal uses a different vendor."""
    rules = [
        _rule("P-DENY-01", vendor_constraint="V-BAD", on_violation="denied"),
        _rule("P-AUTO-01", operator="<", threshold=5000.0, on_violation="auto_approved"),
    ]
    decision = evaluate_rules(_proposal(cost=100.0, vendor_id="V-7"), rules)
    assert decision.outcome == "auto_approved"


# ---------------------------------------------------------------------------
# Step 2: No rules → needs_human
# ---------------------------------------------------------------------------

def test_no_rules_returns_needs_human():
    decision = evaluate_rules(_proposal(), [])
    assert decision.outcome == "needs_human"
    assert decision.rule_id_fired == "DEFAULT"


# ---------------------------------------------------------------------------
# Step 3: Category mismatch → needs_human
# ---------------------------------------------------------------------------

def test_category_mismatch_returns_needs_human():
    """condition_field that doesn't exist on the proposal → needs_human."""
    rules = [_rule(condition_field="nonexistent_field")]
    decision = evaluate_rules(_proposal(), rules)
    assert decision.outcome == "needs_human"
    assert "nonexistent_field" in decision.rationale


# ---------------------------------------------------------------------------
# Step 4: Ambiguous threshold (None) → needs_human
# ---------------------------------------------------------------------------

def test_ambiguous_threshold_returns_needs_human():
    rules = [_rule(threshold=None, on_violation="needs_human")]
    decision = evaluate_rules(_proposal(), rules)
    assert decision.outcome == "needs_human"
    assert "ambiguous" in decision.rationale.lower() or "no numeric threshold" in decision.rationale.lower()


# ---------------------------------------------------------------------------
# Step 5: Amount matches threshold → apply on_violation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cost,expected_outcome,expected_rule", [
    (4200.0, "auto_approved", "P-PROC-01"),   # < 5000, preferred vendor
    (4999.99, "auto_approved", "P-PROC-01"),  # boundary just below 5000
    (5000.0, "needs_human", "P-PROC-02"),     # exactly 5000: R1 is strict <, falls to R2
    (12000.0, "needs_human", "P-PROC-02"),    # between 5k and 25k
    (25000.0, "needs_human", "P-PROC-02"),    # exactly 25000 matches R2 (<=)
    (30000.0, "denied", "P-PROC-03"),         # > 25000
])
def test_threshold_boundaries(cost, expected_outcome, expected_rule):
    decision = evaluate_rules(_proposal(cost=cost, vendor_id="V-7"), STANDARD_RULES)
    assert decision.outcome == expected_outcome, f"cost={cost}: expected {expected_outcome}, got {decision.outcome}"
    assert decision.rule_id_fired == expected_rule


# ---------------------------------------------------------------------------
# Step 5a: Preferred-vendor constraint → needs_human when vendor doesn't match
# ---------------------------------------------------------------------------

def test_preferred_vendor_required_but_wrong_vendor_is_needs_human():
    """R1 requires V-7 but proposal uses V-2 → needs_human (not auto_approved)."""
    decision = evaluate_rules(_proposal(cost=3000.0, vendor_id="V-2"), STANDARD_RULES)
    # R1 fires on threshold (<5000) but V-2 ≠ V-7 → needs_human
    assert decision.outcome == "needs_human"
    assert "V-7" in decision.rationale or "V-2" in decision.rationale


def test_preferred_vendor_constraint_does_not_block_non_constrained_rules():
    """When no vendor_constraint is set, any vendor is accepted."""
    rules = [_rule(operator="<", threshold=5000.0, vendor_constraint=None, on_violation="auto_approved")]
    decision = evaluate_rules(_proposal(cost=100.0, vendor_id="V-ANYONE"), rules)
    assert decision.outcome == "auto_approved"


# ---------------------------------------------------------------------------
# Step 6: No rule fires → auto_approved
# ---------------------------------------------------------------------------

def test_no_rule_fires_returns_auto_approved():
    """When proposal values don't satisfy any rule condition → auto_approved."""
    rules = [_rule(operator=">", threshold=1_000_000.0, on_violation="needs_human")]
    decision = evaluate_rules(_proposal(cost=100.0), rules)
    assert decision.outcome == "auto_approved"
    assert decision.rule_id_fired == "NONE"


# ---------------------------------------------------------------------------
# Non-numeric field: urgency comparisons
# ---------------------------------------------------------------------------

def test_urgency_eq_operator():
    rules = [_rule(condition_field="urgency", operator="==", threshold=0, on_violation="needs_human")]
    # threshold=0 → str comparison: "critical" == "0" is False → no match → auto_approved
    decision = evaluate_rules(_proposal(urgency="critical"), rules)
    assert decision.outcome == "auto_approved"


def test_urgency_neq_operator_matches():
    rules = [_rule(condition_field="urgency", operator="!=", threshold=0, on_violation="needs_human")]
    # "critical" != "0" → True → needs_human
    decision = evaluate_rules(_proposal(urgency="critical"), rules)
    assert decision.outcome == "needs_human"


def test_numeric_operator_on_string_field_is_skipped():
    """< / > operators on a string urgency field are skipped (can't cast)."""
    rules = [
        _rule(condition_field="urgency", operator="<", threshold=5.0, on_violation="denied"),
        _rule(operator="<", threshold=5000.0, on_violation="auto_approved"),
    ]
    decision = evaluate_rules(_proposal(cost=100.0), rules)
    # First rule skipped (string can't do <); second rule fires
    assert decision.outcome == "auto_approved"


# ---------------------------------------------------------------------------
# Decision fields
# ---------------------------------------------------------------------------

def test_decision_carries_amount_and_threshold():
    decision = evaluate_rules(_proposal(cost=4200.0, vendor_id="V-7"), STANDARD_RULES)
    assert decision.amount_usd == 4200.0
    assert decision.threshold_usd == 5000.0


def test_denied_decision_carries_correct_fields():
    decision = evaluate_rules(_proposal(cost=30000.0), STANDARD_RULES)
    assert decision.outcome == "denied"
    assert decision.amount_usd == 30000.0
    assert decision.threshold_usd == 25000.0
    assert decision.rule_id_fired == "P-PROC-03"
