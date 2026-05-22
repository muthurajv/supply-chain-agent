# ADR-002: Deterministic Python policy evaluation — LLM extracts, Python decides

**Date:** 2025-05-01  
**Status:** Accepted

## Context

Every procurement proposal must pass a policy gate before execution. The policy
library lives as unstructured prose in Azure AI Search. Two approaches were
considered:

1. **LLM-as-judge**: feed the proposal and retrieved policy text to the LLM and
   ask it to approve or deny.
2. **LLM-extracts + Python-decides**: use the LLM to parse policy prose into
   structured `PolicyRule` objects, then run a deterministic Python evaluator
   against the proposal.

Option 1 is simpler but fails audit requirements: the same inputs can produce
different outputs across model versions, temperature jitter, or prompt changes.
A compliance team cannot reproduce a two-week-old approval decision.

## Decision

Use **option 2**. The LLM (with `temperature=0.0`) extracts `PolicyRule` objects
from policy text; `app/policy/evaluator.py` applies them in a fixed decision order
(forbidden vendor → denied; no matching rule → needs_human; category mismatch →
needs_human; amount over threshold → on_violation; preferred vendor required but
not preferred → needs_human; else auto_approved). The evaluator has no LLM call.

Extraction results are cached by `hash(policy_text)` so re-running on the same
document version is idempotent.

## Consequences

- Every approval decision is fully reproducible from: (a) the proposal snapshot,
  (b) the policy index version, (c) the deterministic evaluator code. All three
  are recorded in the approval queue document.
- The evaluator must achieve 100% branch coverage (CI gate). Adding a new decision
  branch requires adding parametrized test cases in the same PR.
- If the LLM cannot extract a numeric threshold from ambiguous policy language, it
  must emit `max_amount_usd=None` and set `on_violation="needs_human"` — never
  guess a number (§7.3). This routes ambiguous cases to humans rather than
  auto-approving them.
- Changing the evaluator decision order is a breaking change to existing audit
  trails. Any reorder requires an ADR update and a policy index version bump.
