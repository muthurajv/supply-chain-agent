"""Eval tests for policy rule extraction — snapshot-based, no live LLM (§8.1, §8.3).

Snapshots in tests/fixtures/llm_snapshots/ record what a well-behaved LLM should
return for each policy fixture. Re-record only when the extraction prompt or model
changes; reference the PR that updated them (§8.3).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from tests.fixtures.retrievers import POLICY_DOCS_FIXTURE

_SNAPSHOTS = Path(__file__).parent.parent / "fixtures" / "llm_snapshots"


def _snapshot(name: str) -> str:
    """Load snapshot file content as a string (AIMessage.content format)."""
    return (_SNAPSHOTS / name).read_text()


def _mock_llm(snapshot_name: str) -> MagicMock:
    llm = MagicMock()
    llm.invoke = MagicMock(return_value=AIMessage(content=_snapshot(snapshot_name)))
    return llm


@pytest.fixture(autouse=True)
def clear_extraction_cache():
    """Reset the lru_cache between tests so mocks don't bleed across runs."""
    from app.policy.extraction import _cached_extraction
    _cached_extraction.cache_clear()
    yield
    _cached_extraction.cache_clear()


# ---------------------------------------------------------------------------
# Group 1 — Standard three-rule extraction
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_standard_extraction_returns_three_rules():
    with patch("app.policy.extraction.get_llm", return_value=_mock_llm("policy_extraction_standard.json")):
        from app.policy.extraction import extract_rules
        rules = await extract_rules(POLICY_DOCS_FIXTURE)

    assert len(rules) == 3


@pytest.mark.asyncio
async def test_standard_extraction_rules_are_pydantic_objects():
    from app.policy.schema import PolicyRule

    with patch("app.policy.extraction.get_llm", return_value=_mock_llm("policy_extraction_standard.json")):
        from app.policy.extraction import extract_rules
        rules = await extract_rules(POLICY_DOCS_FIXTURE)

    assert all(isinstance(r, PolicyRule) for r in rules)


@pytest.mark.asyncio
async def test_standard_extraction_first_rule_is_auto_approved():
    with patch("app.policy.extraction.get_llm", return_value=_mock_llm("policy_extraction_standard.json")):
        from app.policy.extraction import extract_rules
        rules = await extract_rules(POLICY_DOCS_FIXTURE)

    auto = next(r for r in rules if r.on_violation == "auto_approved")
    assert auto.threshold == 5000.0
    assert auto.operator == "<"
    assert auto.condition_field == "estimated_cost"


@pytest.mark.asyncio
async def test_standard_extraction_source_excerpts_are_non_empty():
    with patch("app.policy.extraction.get_llm", return_value=_mock_llm("policy_extraction_standard.json")):
        from app.policy.extraction import extract_rules
        rules = await extract_rules(POLICY_DOCS_FIXTURE)

    assert all(r.source_excerpt for r in rules), "Every rule must carry a source_excerpt audit artifact"


@pytest.mark.asyncio
async def test_standard_extraction_rule_ids_are_unique():
    with patch("app.policy.extraction.get_llm", return_value=_mock_llm("policy_extraction_standard.json")):
        from app.policy.extraction import extract_rules
        rules = await extract_rules(POLICY_DOCS_FIXTURE)

    ids = [r.rule_id for r in rules]
    assert len(ids) == len(set(ids)), "rule_id values must be unique"


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["auto_approved", "needs_human"])
async def test_standard_extraction_contains_outcome(outcome: str):
    with patch("app.policy.extraction.get_llm", return_value=_mock_llm("policy_extraction_standard.json")):
        from app.policy.extraction import extract_rules
        rules = await extract_rules(POLICY_DOCS_FIXTURE)

    assert any(r.on_violation == outcome for r in rules)


# ---------------------------------------------------------------------------
# Group 2 — Edge cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_docs_returns_empty_without_calling_llm():
    mock_llm = _mock_llm("policy_extraction_standard.json")

    with patch("app.policy.extraction.get_llm", return_value=mock_llm):
        from app.policy.extraction import extract_rules
        rules = await extract_rules([])

    assert rules == []
    mock_llm.invoke.assert_not_called()


@pytest.mark.asyncio
async def test_ambiguous_threshold_produces_null_threshold():
    ambiguous_doc = [{"doc_id": "POL-AMB", "content": "Large purchases require approval from a manager."}]

    with patch("app.policy.extraction.get_llm", return_value=_mock_llm("policy_extraction_ambiguous.json")):
        from app.policy.extraction import extract_rules
        rules = await extract_rules(ambiguous_doc)

    assert len(rules) == 1
    assert rules[0].threshold is None, "Ambiguous threshold must stay None — never fabricated"
    assert rules[0].on_violation == "needs_human"


@pytest.mark.asyncio
async def test_vendor_constraint_preserved():
    vendor_doc = [{"doc_id": "POL-MIX", "content": "Preferred vendor V-7 PRs below $10,000 are pre-approved."}]

    with patch("app.policy.extraction.get_llm", return_value=_mock_llm("policy_extraction_mixed.json")):
        from app.policy.extraction import extract_rules
        rules = await extract_rules(vendor_doc)

    constrained = next(r for r in rules if r.vendor_constraint is not None)
    assert constrained.vendor_constraint == "V-7"


@pytest.mark.asyncio
async def test_denied_outcome_extracted():
    with patch("app.policy.extraction.get_llm", return_value=_mock_llm("policy_extraction_mixed.json")):
        from app.policy.extraction import extract_rules
        rules = await extract_rules([{"doc_id": "POL-MIX", "content": "Emergency cap $50k."}])

    assert any(r.on_violation == "denied" for r in rules)


@pytest.mark.asyncio
async def test_malformed_rule_in_llm_output_is_skipped():
    bad_output = json.dumps({"rules": [
        {"rule_id": "R1", "description": "Good rule", "condition_field": "estimated_cost",
         "operator": "<", "threshold": 1000.0, "on_violation": "auto_approved",
         "source_excerpt": "Under $1k is fine."},
        {"rule_id": "R2", "description": "Bad rule", "condition_field": "estimated_cost",
         "operator": "INVALID_OP", "threshold": 999.0, "on_violation": "auto_approved",
         "source_excerpt": "Bad operator."},
    ]})
    mock_llm = MagicMock()
    mock_llm.invoke = MagicMock(return_value=AIMessage(content=bad_output))

    with patch("app.policy.extraction.get_llm", return_value=mock_llm):
        from app.policy.extraction import extract_rules
        rules = await extract_rules([{"doc_id": "DOC-X", "content": "Some policy."}])

    assert len(rules) == 1, "Malformed rules must be skipped, not raise"
    assert rules[0].rule_id == "R1"


# ---------------------------------------------------------------------------
# Group 3 — Determinism and caching (§7 rule 2)
# ---------------------------------------------------------------------------

def test_same_policy_hash_calls_llm_only_once():
    """Identical policy text must not re-invoke the LLM (lru_cache guarantee)."""
    mock_llm = _mock_llm("policy_extraction_standard.json")

    with patch("app.policy.extraction.get_llm", return_value=mock_llm):
        from app.policy.extraction import _cached_extraction
        doc_text = "Purchase requisitions below $5,000 are pre-approved."
        import hashlib
        text_hash = hashlib.sha256(doc_text.encode()).hexdigest()

        _cached_extraction(text_hash, doc_text)
        _cached_extraction(text_hash, doc_text)

    assert mock_llm.invoke.call_count == 1, "Cache must prevent duplicate LLM calls"


def test_different_policy_hash_calls_llm_again():
    mock_llm = _mock_llm("policy_extraction_standard.json")

    with patch("app.policy.extraction.get_llm", return_value=mock_llm):
        from app.policy.extraction import _cached_extraction
        import hashlib

        text1 = "Policy A: PRs below $5,000 pre-approved."
        text2 = "Policy B: PRs below $10,000 pre-approved."
        _cached_extraction(hashlib.sha256(text1.encode()).hexdigest(), text1)
        _cached_extraction(hashlib.sha256(text2.encode()).hexdigest(), text2)

    assert mock_llm.invoke.call_count == 2


@pytest.mark.asyncio
async def test_extraction_is_deterministic_same_input_same_rules():
    """Running extraction twice on the same doc must yield identical rule objects."""
    with patch("app.policy.extraction.get_llm", return_value=_mock_llm("policy_extraction_standard.json")):
        from app.policy.extraction import extract_rules, _cached_extraction
        rules_first = await extract_rules(POLICY_DOCS_FIXTURE)
        _cached_extraction.cache_clear()
        rules_second = await extract_rules(POLICY_DOCS_FIXTURE)

    assert [r.model_dump() for r in rules_first] == [r.model_dump() for r in rules_second]
