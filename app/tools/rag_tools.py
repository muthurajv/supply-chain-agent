from __future__ import annotations

from datetime import date
from typing import Optional

import httpx
from langchain_core.tools import tool

from app.config import get_settings
from app.observability.attributes import Attr
from app.observability.metrics import rag_retrieval_score_histogram
from app.observability.spans import rag_span

_API_VERSION = "2024-05-01-preview"
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=15.0)
    return _http_client


async def _search(index_name: str, query: str, filter_expr: str | None, top_k: int, select: list[str]) -> list[dict]:
    """Call Azure AI Search REST API directly using a persistent httpx client."""
    s = get_settings()
    url = f"{s.azure_search_endpoint}/indexes/{index_name}/docs/search"
    headers = {"api-key": s.azure_search_key, "Content-Type": "application/json"}
    body: dict = {"search": query, "top": top_k, "select": ",".join(select)}
    if filter_expr:
        body["filter"] = filter_expr

    client = _get_http_client()
    resp = await client.post(url, headers=headers, json=body, params={"api-version": _API_VERSION})
    resp.raise_for_status()
    return resp.json().get("value", [])


@tool
async def retrieve_policy_docs(
    query: str,
    top_k: int = 5,
    doc_type: Optional[str] = None,
) -> list[dict]:
    """Retrieve relevant policy documents, SOPs, or contracts using keyword search.

    Args:
        query: Natural language search query
        top_k: Number of results to return (1-10)
        doc_type: Filter by document type ('policy', 'sop', 'contract')
    """
    with rag_span(query, top_k, [doc_type] if doc_type else None) as span:
        today_str = date.today().isoformat()
        filter_expr = f"effective_date le '{today_str}'"
        if doc_type:
            filter_expr = f"doc_type eq '{doc_type}' and {filter_expr}"

        index_name = get_settings().azure_search_index_policy
        raw = await _search(index_name, query, filter_expr, top_k,
                            ["doc_id", "title", "content", "doc_type", "effective_date"])

        docs = [
            {
                "doc_id": r.get("doc_id", ""),
                "title": r.get("title", ""),
                "content": r.get("content", ""),
                "doc_type": r.get("doc_type", ""),
                "effective_date": r.get("effective_date", ""),
                "score": r.get("@search.score", 0.0),
            }
            for r in raw
        ]

        span.set_attribute(Attr.RAG_RESULT_COUNT, len(docs))
        for doc in docs:
            rag_retrieval_score_histogram().record(doc["score"], {"index_name": index_name})
        return docs


@tool
async def retrieve_episodic_memory(
    query: str,
    top_k: int = 5,
    memory_type: Optional[str] = None,
) -> list[dict]:
    """Retrieve past agent decisions, forecasts, or approval records from episodic memory.

    Args:
        query: Natural language query
        top_k: Number of results
        memory_type: Filter by type ('procurement_decision', 'forecast', 'approval')
    """
    with rag_span(query, top_k, [memory_type] if memory_type else None) as span:
        filter_expr = f"memory_type eq '{memory_type}'" if memory_type else None
        index_name = get_settings().azure_search_index_episodic
        raw = await _search(index_name, query, filter_expr, top_k,
                            ["record_id", "content", "memory_type", "created_at"])

        docs = [
            {
                "record_id": r.get("record_id", ""),
                "content": r.get("content", ""),
                "memory_type": r.get("memory_type", ""),
                "created_at": r.get("created_at", ""),
                "score": r.get("@search.score", 0.0),
            }
            for r in raw
        ]

        span.set_attribute(Attr.RAG_RESULT_COUNT, len(docs))
        for doc in docs:
            rag_retrieval_score_histogram().record(doc["score"], {"index_name": index_name})
        return docs
