"""Fake RAG retrievers for use in tests (§8.3 — never call real Azure AI Search)."""
from __future__ import annotations

POLICY_DOCS_FIXTURE = [
    {
        "doc_id": "POL-001",
        "title": "Procurement Approval Policy",
        "content": (
            "Preferred vendor purchase requisitions below $5,000 are pre-approved. "
            "Purchase requisitions between $5,000 and $25,000 require manager approval. "
            "Purchase requisitions above $25,000 must follow the executive approval process."
        ),
        "doc_type": "policy",
        "effective_date": "2024-01-01",
        "score": 0.95,
    }
]

EMPTY_DOCS_FIXTURE: list[dict] = []
