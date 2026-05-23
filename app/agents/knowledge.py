from __future__ import annotations

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from app.config import get_settings
from app.llm.client import get_llm
from app.observability.attributes import Attr
from app.observability.spans import agent_span, record_llm_usage
from app.tools.rag_tools import retrieve_policy_docs

from .state import GraphState


async def knowledge_node(state: GraphState) -> Command:
    """Retrieve relevant policy or episodic documents and summarize for the requesting agent."""
    turn = state.get("turn", 0)
    with agent_span("knowledge", turn=turn) as span:
        last_message = state["messages"][-1].content if state["messages"] else ""
        query = last_message or "procurement policy approval thresholds"

        docs = await retrieve_policy_docs.ainvoke({"query": query, "top_k": 5})

        if not docs:
            content = "No relevant policy documents found for this query."
        else:
            llm = get_llm(temperature=0.0)
            doc_text = "\n\n".join(f"[{d['doc_id']}] {d['title']}\n{d['content']}" for d in docs)
            response = await llm.ainvoke([
                {"role": "user", "content": f"Summarize the following policy documents relevant to: '{query}'\n\n{doc_text}"},
            ])
            record_llm_usage("knowledge", response, get_settings().azure_openai_deployment)
            content = response.content

        span.set_attribute(Attr.AGENT_DECISION, f"retrieved {len(docs)} docs")

        return Command(
            goto="supervisor",
            update={
                "messages": [HumanMessage(content=content, name="knowledge_agent")],
            },
        )


knowledge_agent = knowledge_node
