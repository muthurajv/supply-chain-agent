from __future__ import annotations

from datetime import date
from typing import Optional

from azure.core.credentials import AzureKeyCredential
from azure.search.documents.aio import SearchClient
from azure.search.documents.models import VectorizableTextQuery
from langchain_core.tools import tool

from app.config import get_settings
from app.observability.attributes import Attr
from app.observability.spans import rag_span

_policy_client: SearchClient | None = None
_episodic_client: SearchClient | None = None


def _get_search_client(index_name: str) -> SearchClient:
    settings = get_settings()
    return SearchClient(
        endpoint=settings.azure_search_endpoint,
        index_name=index_name,
        credential=AzureKeyCredential(settings.azure_search_key),
    )


def get_policy_client() -> SearchClient:
    global _policy_client
    if _policy_client is None:
        _policy_client = _get_search_client(get_settings().azure_search_index_policy)
    return _policy_client


def get_episodic_client() -> SearchClient:
    global _episodic_client
    if _episodic_client is None:
        _episodic_client = _get_search_client(get_settings().azure_search_index_episodic)
    return _episodic_client


@tool
async def retrieve_policy_docs(
    query: str,
    top_k: int = 5,
    doc_type: Optional[str] = None,
) -> list[dict]:
    """Retrieve relevant policy documents, SOPs, or contracts using hybrid search.

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

        vector_query = VectorizableTextQuery(
            text=query,
            k_nearest_neighbors=top_k,
            fields="content_vector",
        )

        client = get_policy_client()
        async with client:
            results = await client.search(
                search_text=query,
                vector_queries=[vector_query],
                filter=filter_expr,
                top=top_k,
                select=["doc_id", "title", "content", "doc_type", "effective_date"],
            )

        docs = []
        async for result in results:
            docs.append({
                "doc_id": result.get("doc_id", ""),
                "title": result.get("title", ""),
                "content": result.get("content", ""),
                "doc_type": result.get("doc_type", ""),
                "effective_date": result.get("effective_date", ""),
                "score": result.get("@search.score", 0.0),
            })

        span.set_attribute(Attr.RAG_RESULT_COUNT, len(docs))
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

        vector_query = VectorizableTextQuery(
            text=query,
            k_nearest_neighbors=top_k,
            fields="content_vector",
        )

        client = get_episodic_client()
        async with client:
            results = await client.search(
                search_text=query,
                vector_queries=[vector_query],
                filter=filter_expr,
                top=top_k,
                select=["record_id", "content", "memory_type", "created_at"],
            )

        docs = []
        async for result in results:
            docs.append({
                "record_id": result.get("record_id", ""),
                "content": result.get("content", ""),
                "memory_type": result.get("memory_type", ""),
                "created_at": result.get("created_at", ""),
                "score": result.get("@search.score", 0.0),
            })

        span.set_attribute(Attr.RAG_RESULT_COUNT, len(docs))
        return docs
