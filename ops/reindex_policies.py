"""Re-index policy documents to a new versioned Azure AI Search index.

Copies all documents from the source index (or re-embeds from the local
policies/ directory) into a new target index, creating it if it does not
exist.  Used as step 2 of the policy rotation procedure (§10).

Usage:
    # Re-index from local policy docs to a new index version
    uv run python ops/reindex_policies.py --to-index policies-v4

    # Clone an existing index (re-embed from source docs found in Search)
    uv run python ops/reindex_policies.py --from-index policies-v3 --to-index policies-v4

    # Dry-run: validate without writing to Search
    uv run python ops/reindex_policies.py --to-index policies-v4 --dry-run

After confirming the new index is correct, update app/config.py:
    policy_index = "policies-v4"
Then run the eval suite:
    python -m pytest tests/eval/test_policy_extraction.py -v
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
    SimpleField,
    SearchableField,
    VectorSearch,
    VectorSearchProfile,
)
from openai import AzureOpenAI

from app.config import get_settings

POLICIES_DIR = Path(__file__).parent.parent / "policies"
EMBEDDING_DIMENSIONS = 1536  # text-embedding-3-small


def _build_index_schema(index_name: str) -> SearchIndex:
    return SearchIndex(
        name=index_name,
        fields=[
            SimpleField(name="doc_id", type=SearchFieldDataType.String, key=True, filterable=True),
            SearchableField(name="title", type=SearchFieldDataType.String, sortable=True),
            SearchableField(name="content", type=SearchFieldDataType.String),
            SimpleField(name="doc_type", type=SearchFieldDataType.String, filterable=True, facetable=True),
            SimpleField(name="effective_date", type=SearchFieldDataType.String, filterable=True, sortable=True),
            SearchField(
                name="content_vector",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                searchable=True,
                vector_search_dimensions=EMBEDDING_DIMENSIONS,
                vector_search_profile_name="hnsw-profile",
            ),
        ],
        vector_search=VectorSearch(
            algorithms=[HnswAlgorithmConfiguration(name="hnsw-algo")],
            profiles=[VectorSearchProfile(name="hnsw-profile", algorithm_configuration_name="hnsw-algo")],
        ),
        semantic_search=SemanticSearch(
            configurations=[
                SemanticConfiguration(
                    name="semantic-config",
                    prioritized_fields=SemanticPrioritizedFields(
                        title_field=SemanticField(field_name="title"),
                        content_fields=[SemanticField(field_name="content")],
                    ),
                )
            ]
        ),
    )


def _get_embedding(client: AzureOpenAI, text: str, deployment: str) -> list[float]:
    response = client.embeddings.create(input=text, model=deployment)
    return response.data[0].embedding


def _load_docs_from_disk() -> list[dict]:
    docs = []
    for path in sorted(POLICIES_DIR.glob("*.json")):
        with path.open(encoding="utf-8") as f:
            docs.append(json.load(f))
    return docs


def _load_docs_from_index(search_client: SearchClient) -> list[dict]:
    """Retrieve all non-vector fields from an existing index."""
    results = search_client.search(
        search_text="*",
        select=["doc_id", "title", "content", "doc_type", "effective_date"],
        top=1000,
    )
    return [
        {
            "doc_id": r["doc_id"],
            "title": r["title"],
            "content": r["content"],
            "doc_type": r.get("doc_type", "policy"),
            "effective_date": r.get("effective_date", ""),
        }
        for r in results
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-index policy documents to a new index version.")
    parser.add_argument("--from-index", default=None, help="Source index to clone (omit to use local policies/).")
    parser.add_argument("--to-index", required=True, help="Target index name (e.g. policies-v4).")
    parser.add_argument("--dry-run", action="store_true", help="Validate without writing to Search.")
    args = parser.parse_args()

    settings = get_settings()
    credential = AzureKeyCredential(settings.azure_search_key)
    index_client = SearchIndexClient(endpoint=settings.azure_search_endpoint, credential=credential)
    to_client = SearchClient(
        endpoint=settings.azure_search_endpoint,
        index_name=args.to_index,
        credential=credential,
    )
    openai_client = AzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_key,
        api_version=settings.azure_openai_api_version,
    )

    # Load source documents
    if args.from_index:
        from_client = SearchClient(
            endpoint=settings.azure_search_endpoint,
            index_name=args.from_index,
            credential=credential,
        )
        print(f"Loading documents from index '{args.from_index}' ...")
        docs = _load_docs_from_index(from_client)
    else:
        print(f"Loading documents from {POLICIES_DIR}/ ...")
        docs = _load_docs_from_disk()

    if not docs:
        print("No documents found. Exiting.")
        sys.exit(1)

    print(f"Found {len(docs)} document(s).")
    print(f"Target index: {args.to_index}\n")

    if args.dry_run:
        print(f"[dry-run] Would create index '{args.to_index}' and upload {len(docs)} document(s).")
        print("[dry-run] No changes made.")
        return

    # Create or update the target index schema
    schema = _build_index_schema(args.to_index)
    index_client.create_or_update_index(schema)
    print(f"Index '{args.to_index}' ready.\n")

    # Embed and upload
    batch = []
    for doc in docs:
        print(f"  Embedding {doc['doc_id']}: {doc['title']} ...", end=" ", flush=True)
        vector = _get_embedding(openai_client, doc["content"], settings.azure_openai_embedding_deployment)
        batch.append({**doc, "content_vector": vector})
        print("done")

    result = to_client.upload_documents(documents=batch)
    succeeded = sum(1 for r in result if r.succeeded)
    failed = len(result) - succeeded
    print(f"\nUploaded {succeeded}/{len(batch)} documents. Failed: {failed}.")
    if failed:
        for r in result:
            if not r.succeeded:
                print(f"  FAILED: {r.key} — {r.error_message}")
        sys.exit(1)

    print(f"\nDone. Next steps (§10):")
    print(f"  1. Update app/config.py: policy_index = \"{args.to_index}\"")
    print(f"  2. python -m pytest tests/eval/test_policy_extraction.py -v")
    print(f"  3. python ops/diff_policy_rules.py {args.from_index or '<old-index>'} {args.to_index}")


if __name__ == "__main__":
    main()
