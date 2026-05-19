"""Upload policy documents to Azure AI Search.

Reads JSON files from the policies/ directory, generates embeddings via
Azure OpenAI, creates the search index if it does not exist, and upserts
all documents.

Usage:
    uv run python ops/upload_policies.py
    uv run python ops/upload_policies.py --dry-run
    uv run python ops/upload_policies.py --index policies-v4
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
EMBEDDING_DIMENSIONS = 3072  # text-embedding-3-large


def get_embedding(client: AzureOpenAI, text: str, deployment: str) -> list[float]:
    response = client.embeddings.create(input=text, model=deployment)
    return response.data[0].embedding


def build_index_schema(index_name: str) -> SearchIndex:
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


def load_policy_docs() -> list[dict]:
    docs = []
    for path in sorted(POLICIES_DIR.glob("*.json")):
        with path.open(encoding="utf-8") as f:
            docs.append(json.load(f))
    return docs


def create_or_update_index(index_client: SearchIndexClient, index_name: str) -> None:
    schema = build_index_schema(index_name)
    index_client.create_or_update_index(schema)
    print(f"Index '{index_name}' ready.")


def upload_documents(
    search_client: SearchClient,
    openai_client: AzureOpenAI,
    docs: list[dict],
    embedding_deployment: str,
    dry_run: bool,
) -> None:
    batch = []
    for doc in docs:
        print(f"  Embedding {doc['doc_id']}: {doc['title']} ...", end=" ", flush=True)
        if not dry_run:
            vector = get_embedding(openai_client, doc["content"], embedding_deployment)
        else:
            vector = [0.0] * EMBEDDING_DIMENSIONS
        batch.append({**doc, "content_vector": vector})
        print("done")

    if dry_run:
        print(f"\n[dry-run] Would upload {len(batch)} document(s) to Azure AI Search.")
        return

    result = search_client.upload_documents(documents=batch)
    succeeded = sum(1 for r in result if r.succeeded)
    failed = len(result) - succeeded
    print(f"\nUploaded {succeeded}/{len(batch)} documents. Failed: {failed}.")
    if failed:
        for r in result:
            if not r.succeeded:
                print(f"  FAILED: {r.key} — {r.error_message}")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload policy documents to Azure AI Search.")
    parser.add_argument("--index", default=None, help="Override index name from config.")
    parser.add_argument("--dry-run", action="store_true", help="Validate without uploading.")
    args = parser.parse_args()

    settings = get_settings()
    index_name = args.index or settings.azure_search_index_policy

    credential = AzureKeyCredential(settings.azure_search_key)
    index_client = SearchIndexClient(endpoint=settings.azure_search_endpoint, credential=credential)
    search_client = SearchClient(
        endpoint=settings.azure_search_endpoint,
        index_name=index_name,
        credential=credential,
    )
    openai_client = AzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_key,
        api_version=settings.azure_openai_api_version,
    )

    docs = load_policy_docs()
    if not docs:
        print(f"No policy documents found in {POLICIES_DIR}. Exiting.")
        sys.exit(1)

    print(f"Found {len(docs)} policy document(s) in {POLICIES_DIR}/")
    print(f"Target index: {index_name}")
    print(f"Search endpoint: {settings.azure_search_endpoint}\n")

    if not args.dry_run:
        create_or_update_index(index_client, index_name)

    upload_documents(
        search_client=search_client,
        openai_client=openai_client,
        docs=docs,
        embedding_deployment=settings.azure_openai_embedding_deployment,
        dry_run=args.dry_run,
    )

    print("\nDone. Run a test query:")
    print(f"  az search document search --service-name <name> --index-name {index_name} --query-type semantic --search 'purchase requisition approval threshold'")


if __name__ == "__main__":
    main()
