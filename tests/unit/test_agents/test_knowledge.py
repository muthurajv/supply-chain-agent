"""Unit tests for the Knowledge agent — happy path + failure modes (§8.2)."""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_docs():
    return [
        {
            "doc_id": "POL-001",
            "title": "Procurement Approval Policy",
            "content": "Purchase requisitions below $5,000 are pre-approved for preferred vendors.",
        },
        {
            "doc_id": "POL-002",
            "title": "Vendor Selection SOP",
            "content": "Preferred vendors must be re-evaluated annually.",
        },
    ]


@pytest.mark.asyncio
async def test_knowledge_returns_summary_when_docs_found(sample_state, mock_docs):
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(
        return_value=AIMessage(content="Policy summary: pre-approved under $5k for preferred vendors.")
    )

    with patch("app.agents.knowledge.retrieve_policy_docs") as mock_rag, \
         patch("app.agents.knowledge.get_llm", return_value=mock_llm):
        mock_rag.ainvoke = AsyncMock(return_value=mock_docs)

        from app.agents.knowledge import knowledge_agent
        command = await knowledge_agent(sample_state)

    assert command.goto == "supervisor"
    msg = command.update["messages"][0]
    assert isinstance(msg, HumanMessage)
    assert "pre-approved" in msg.content


@pytest.mark.asyncio
async def test_knowledge_returns_no_docs_message_when_empty(sample_state):
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content=""))

    with patch("app.agents.knowledge.retrieve_policy_docs") as mock_rag, \
         patch("app.agents.knowledge.get_llm", return_value=mock_llm):
        mock_rag.ainvoke = AsyncMock(return_value=[])

        from app.agents.knowledge import knowledge_agent
        command = await knowledge_agent(sample_state)

    assert "No relevant policy documents found" in command.update["messages"][0].content
    assert command.goto == "supervisor"
    # LLM must NOT be called when there are no docs to summarize
    mock_llm.ainvoke.assert_not_called()


@pytest.mark.asyncio
async def test_knowledge_uses_last_message_as_query(sample_state, mock_docs):
    sample_state["messages"].append(
        HumanMessage(content="What is the preferred vendor threshold?")
    )

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="Threshold is $5,000."))

    with patch("app.agents.knowledge.retrieve_policy_docs") as mock_rag, \
         patch("app.agents.knowledge.get_llm", return_value=mock_llm):
        mock_rag.ainvoke = AsyncMock(return_value=mock_docs)

        from app.agents.knowledge import knowledge_agent
        await knowledge_agent(sample_state)

    call_args = mock_rag.ainvoke.call_args[0][0]
    assert "preferred vendor threshold" in call_args["query"]


@pytest.mark.asyncio
async def test_knowledge_message_has_knowledge_agent_name(sample_state, mock_docs):
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="Policy summary."))

    with patch("app.agents.knowledge.retrieve_policy_docs") as mock_rag, \
         patch("app.agents.knowledge.get_llm", return_value=mock_llm):
        mock_rag.ainvoke = AsyncMock(return_value=mock_docs)

        from app.agents.knowledge import knowledge_agent
        command = await knowledge_agent(sample_state)

    assert command.update["messages"][0].name == "knowledge_agent"
