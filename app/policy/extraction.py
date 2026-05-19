from __future__ import annotations

import hashlib
import json
from functools import lru_cache

from opentelemetry import trace

from app.llm.client import get_llm
from app.observability.attributes import Attr

from .schema import PolicyRule

_tracer = trace.get_tracer("supply-chain-agent")

_EXTRACTION_SYSTEM = """You are a compliance analyst. Extract procurement approval rules from policy documents.

Return ONLY a JSON object with key "rules" containing an array of rule objects. Each object must have:
{
  "rule_id": "<doc_id>-R<n>",
  "description": "<one-line description>",
  "condition_field": "estimated_cost" | "recommended_qty" | "urgency",
  "operator": "<" | "<=" | ">" | ">=" | "==" | "!=",
  "threshold": <numeric value or null if ambiguous>,
  "vendor_constraint": "<vendor_id>" | null,
  "on_violation": "auto_approved" | "needs_human" | "denied",
  "source_excerpt": "<the exact sentence from the policy document this rule came from>"
}

Rules:
- If a threshold is stated numerically, use it exactly.
- If the policy says "large purchases require approval" with no number, set threshold=null and on_violation="needs_human".
- Never guess a threshold; prefer null over a fabricated number.
- source_excerpt must be the verbatim sentence — it is the audit artifact.
- Return {"rules": []} if no relevant rules are found."""


@lru_cache(maxsize=256)
def _cached_extraction(policy_text_hash: str, policy_text: str) -> list[dict]:
    """Extract rules from policy text, cached by content hash.

    Caching ensures identical policy text always produces identical rules (§7 rule 2).
    temperature=0.0 is mandatory for determinism.
    """
    with _tracer.start_as_current_span("policy.extraction") as span:
        llm = get_llm(temperature=0.0, json_mode=True)
        response = llm.invoke([
            {"role": "system", "content": _EXTRACTION_SYSTEM},
            {"role": "user", "content": f"Policy documents:\n{policy_text}\n\nExtract approval rules."},
        ])
        raw = json.loads(response.content)
        rules = raw.get("rules", raw) if isinstance(raw, dict) else raw
        span.set_attribute(Attr.RAG_RESULT_COUNT, len(rules) if isinstance(rules, list) else 0)
        return rules


async def extract_rules(policy_docs: list[dict]) -> list[PolicyRule]:
    """Extract PolicyRule objects from retrieved policy documents.

    Uses content-hash caching so re-running on the same document version is free.
    The LLM extracts rules; app/policy/evaluator.py makes the actual decision.
    """
    if not policy_docs:
        return []

    doc_text = "\n\n".join(f"[{d['doc_id']}]\n{d['content']}" for d in policy_docs)
    text_hash = hashlib.sha256(doc_text.encode()).hexdigest()

    rules_data = _cached_extraction(text_hash, doc_text)
    rules: list[PolicyRule] = []
    for r in rules_data:
        try:
            rules.append(PolicyRule(**r))
        except Exception:
            pass
    return rules
