from __future__ import annotations

from operator import eq, ge, gt, le, lt, ne
from typing import TYPE_CHECKING

from .schema import PolicyDecision, PolicyRule

if TYPE_CHECKING:
    from app.models.procurement import ProcurementRecommendation

_OPS = {"<": lt, "<=": le, ">": gt, ">=": ge, "==": eq, "!=": ne}


def evaluate_rules(
    proposal: ProcurementRecommendation,
    rules: list[PolicyRule],
) -> PolicyDecision:
    """Evaluate a procurement proposal against extracted policy rules.

    Decision order (fixed — do not reorder):
    1. Forbidden vendor (rule explicitly denies this vendor_id) → denied
    2. No rules at all → needs_human
    3. Condition field absent in proposal (category mismatch) → needs_human
    4. Ambiguous threshold (None) → needs_human
    5. Amount/qty matches threshold → apply rule.on_violation
       5a. Rule requires preferred vendor but proposal uses another → needs_human
    6. No rule fired → auto_approved

    The LLM never calls this function — only the policy agent does.
    """
    amount = proposal.estimated_cost

    # Step 1: Forbidden vendor — deny immediately before any threshold check.
    for rule in rules:
        if (
            rule.vendor_constraint
            and rule.vendor_constraint == proposal.vendor_id
            and rule.on_violation == "denied"
        ):
            return PolicyDecision(
                outcome="denied",
                rule_id_fired=rule.rule_id,
                rationale=f"Vendor {proposal.vendor_id} is explicitly forbidden by rule {rule.rule_id}.",
                explanation=rule.description,
                amount_usd=amount,
                threshold_usd=rule.threshold or 0.0,
            )

    # Step 2: No rules → needs_human.
    if not rules:
        return PolicyDecision(
            outcome="needs_human",
            rule_id_fired="DEFAULT",
            rationale="No policy rules found — defaulting to human review.",
            explanation="No rules were extracted from policy documents.",
            amount_usd=amount,
        )

    for rule in rules:
        # Step 3: Category mismatch — condition_field not on proposal.
        field_val = getattr(proposal, rule.condition_field, None)
        if field_val is None:
            return PolicyDecision(
                outcome="needs_human",
                rule_id_fired=rule.rule_id,
                rationale=f"Condition field '{rule.condition_field}' not present in proposal.",
                explanation=rule.description,
                amount_usd=amount,
            )

        # Step 4: Ambiguous threshold — policy text had no numeric threshold.
        if rule.threshold is None:
            return PolicyDecision(
                outcome="needs_human",
                rule_id_fired=rule.rule_id,
                rationale="Policy rule has no numeric threshold — ambiguity routes to human review.",
                explanation=rule.source_excerpt,
                amount_usd=amount,
            )

        # Step 5: Evaluate threshold.
        try:
            numeric_val = float(field_val)
        except (TypeError, ValueError):
            # Non-numeric field; only == / != make sense.
            if rule.operator not in ("==", "!="):
                continue
            matched = _OPS[rule.operator](str(field_val), str(rule.threshold))
        else:
            matched = _OPS[rule.operator](numeric_val, rule.threshold)

        if not matched:
            continue

        # Step 5a: Vendor constraint on a matched rule.
        if rule.vendor_constraint and proposal.vendor_id != rule.vendor_constraint:
            if rule.on_violation == "denied":
                # Forbidden-vendor rule targets a different vendor — skip it.
                continue
            # Preferred-vendor required but not used → needs_human.
            return PolicyDecision(
                outcome="needs_human",
                rule_id_fired=rule.rule_id,
                rationale=(
                    f"Rule {rule.rule_id} requires vendor {rule.vendor_constraint} "
                    f"but proposal uses {proposal.vendor_id}."
                ),
                explanation=rule.description,
                amount_usd=amount,
                threshold_usd=rule.threshold,
            )

        return PolicyDecision(
            outcome=rule.on_violation,
            rule_id_fired=rule.rule_id,
            rationale=f"Rule '{rule.description}' matched: {rule.condition_field} {rule.operator} {rule.threshold}.",
            explanation=rule.source_excerpt,
            amount_usd=amount,
            threshold_usd=rule.threshold,
        )

    # Step 6: No rule fired — proposal is within all thresholds.
    return PolicyDecision(
        outcome="auto_approved",
        rule_id_fired="NONE",
        rationale="No policy rule triggered — proposal is within all thresholds.",
        explanation="All rules evaluated; none matched.",
        amount_usd=amount,
    )
