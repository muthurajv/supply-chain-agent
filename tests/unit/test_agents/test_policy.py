"""Unit tests for the Policy agent — happy path + failure modes (§8.2, §7)."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.procurement import ProcurementRecommendation


def _proposal(estimated_cost: float, vendor_id: str = "V-7") -> ProcurementRecommendation:
    return ProcurementRecommendation(
        material_id="M-1042",
        description="Precision Ball Screw 16mm",
        recommended_qty=round(estimated_cost / 21.0),
        vendor_id=vendor_id,
        vendor_name="Precision Parts Ltd",
        unit_price=21.0,
        estimated_cost=estimated_cost,
        lead_time_days=14,
        urgency="medium",
        rationale="Test proposal.",
    )


@pytest.fixture
def state_with_proposal(sample_state):
    """State with a procurement proposal that triggers auto-approval ($3,696, V-7)."""
    sample_state["procurement_proposal"] = _proposal(3696.0)
    return sample_state


# ---------------------------------------------------------------------------
# Happy path — auto_approved
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_policy_auto_approves_under_threshold(state_with_proposal):
    """$3,696 with V-7 vendor → FALLBACK-R1 → auto_approved."""
    with patch("app.agents.policy.retrieve_policy_docs") as mock_docs:
        mock_docs.ainvoke = AsyncMock(return_value=[])  # empty → use _FALLBACK_RULES

        from app.agents.policy import policy_agent
        command = await policy_agent(state_with_proposal)

    decision = command.update["policy_decision"]
    assert decision.outcome == "auto_approved"
    assert decision.rule_id_fired == "FALLBACK-R1"
    assert command.update["approval_required"] is False
    assert command.goto == "supervisor"


@pytest.mark.asyncio
async def test_policy_auto_approved_message_contains_rule_id(state_with_proposal):
    with patch("app.agents.policy.retrieve_policy_docs") as mock_docs:
        mock_docs.ainvoke = AsyncMock(return_value=[])

        from app.agents.policy import policy_agent
        command = await policy_agent(state_with_proposal)

    msg = command.update["messages"][0].content
    assert "FALLBACK-R1" in msg
    assert "AUTO-APPROVED" in msg


# ---------------------------------------------------------------------------
# No proposal in state
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_policy_returns_message_when_no_proposal(sample_state):
    sample_state["procurement_proposal"] = None

    from app.agents.policy import policy_agent
    command = await policy_agent(sample_state)

    assert command.goto == "supervisor"
    assert "No procurement proposal" in command.update["messages"][0].content


# ---------------------------------------------------------------------------
# denied path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_policy_denied_when_cost_exceeds_cap(sample_state):
    """$30,000 exceeds the $25k executive cap → FALLBACK-R3 → denied."""
    sample_state["procurement_proposal"] = _proposal(30_000.0)

    with patch("app.agents.policy.retrieve_policy_docs") as mock_docs:
        mock_docs.ainvoke = AsyncMock(return_value=[])

        from app.agents.policy import policy_agent
        command = await policy_agent(sample_state)

    decision = command.update["policy_decision"]
    assert decision.outcome == "denied"
    assert command.update.get("next_agent") == "__end__"
    assert command.goto == "supervisor"


@pytest.mark.asyncio
async def test_policy_denied_message_contains_denied(sample_state):
    sample_state["procurement_proposal"] = _proposal(30_000.0)

    with patch("app.agents.policy.retrieve_policy_docs") as mock_docs:
        mock_docs.ainvoke = AsyncMock(return_value=[])

        from app.agents.policy import policy_agent
        command = await policy_agent(sample_state)

    assert "DENIED" in command.update["messages"][0].content


# ---------------------------------------------------------------------------
# needs_human path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_policy_needs_human_for_mid_range_cost(sample_state):
    """$10,000 is between $5k and $25k → FALLBACK-R2 → needs_human → interrupt."""
    sample_state["procurement_proposal"] = _proposal(10_000.0)

    with patch("app.agents.policy.retrieve_policy_docs") as mock_docs, \
         patch("app.agents.policy._write_approval_queue", new_callable=AsyncMock) as mock_queue, \
         patch("app.agents.policy.interrupt") as mock_interrupt:

        mock_docs.ainvoke = AsyncMock(return_value=[])
        mock_queue.return_value = "APQ-ABCD1234"

        from app.agents.policy import policy_agent
        command = await policy_agent(sample_state)

    mock_interrupt.assert_called_once()
    interrupt_payload = mock_interrupt.call_args[0][0]
    assert interrupt_payload["reason"] == "approval_required"
    assert interrupt_payload["queue_id"] == "APQ-ABCD1234"

    decision = command.update["policy_decision"]
    assert decision.outcome == "needs_human"
    assert command.update["approval_required"] is True
    assert command.update["approval_queue_id"] == "APQ-ABCD1234"


@pytest.mark.asyncio
async def test_policy_needs_human_writes_to_approval_queue(sample_state):
    sample_state["procurement_proposal"] = _proposal(10_000.0)

    with patch("app.agents.policy.retrieve_policy_docs") as mock_docs, \
         patch("app.agents.policy._write_approval_queue", new_callable=AsyncMock) as mock_queue, \
         patch("app.agents.policy.interrupt"):

        mock_docs.ainvoke = AsyncMock(return_value=[])
        mock_queue.return_value = "APQ-ABCD1234"

        from app.agents.policy import policy_agent
        await policy_agent(sample_state)

    mock_queue.assert_called_once()
    call_proposal, call_decision = mock_queue.call_args[0]
    assert call_proposal.estimated_cost == 10_000.0
    assert call_decision.outcome == "needs_human"


# ---------------------------------------------------------------------------
# LLM never decides (§7 invariant)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_policy_evaluation_uses_no_llm(state_with_proposal):
    """The LLM extracts rules only; evaluate_rules() decides — no LLM on the decision path."""
    with patch("app.agents.policy.retrieve_policy_docs") as mock_docs, \
         patch("app.agents.policy.extract_rules", new_callable=AsyncMock) as mock_extract:

        mock_docs.ainvoke = AsyncMock(return_value=[{"doc_id": "DOC-1", "content": "..."}])
        mock_extract.return_value = []  # extraction returns nothing → falls back to _FALLBACK_RULES

        from app.agents.policy import policy_agent
        command = await policy_agent(state_with_proposal)

    # evaluate_rules was called deterministically; auto_approved via fallback
    assert command.update["policy_decision"].outcome == "auto_approved"
