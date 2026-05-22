from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Azure OpenAI
    azure_openai_endpoint: str
    azure_openai_key: str
    azure_openai_deployment: str = "gpt-4o"
    azure_openai_embedding_deployment: str = "text-embedding-3-large"
    azure_openai_api_version: str = "2024-08-01-preview"

    # Azure AI Search
    azure_search_endpoint: str
    azure_search_key: str
    azure_search_index_policy: str = "policies-v3"
    azure_search_index_episodic: str = "episodic-memory"

    # Active policy index version — bump when the policy library is re-indexed (§10).
    policy_index: str = "policies-v3"

    # Cosmos DB
    cosmos_connection_string: str
    cosmos_database: str = "supply-chain-agent"
    cosmos_container_checkpoints: str = "checkpoints"
    cosmos_container_kpi: str = "kpis"
    cosmos_container_approvals: str = "approval-queue"

    # SAP Mock
    sap_mock_base_url: str = "http://sap-mock:8001"

    # Auth
    entra_tenant_id: str = ""
    entra_client_id: str = ""
    entra_audience: str = ""

    # OTEL (local / K8s path)
    otlp_endpoint: str = "http://otel-collector:4317"
    otel_service_name: str = "supply-chain-agent"
    otel_service_version: str = "1.0.0"

    # Grafana Cloud (laptop / dev) — when set, overrides otlp_endpoint with HTTPS + auth
    grafana_otlp_endpoint: str = ""
    grafana_instance_id: str = ""
    grafana_api_key: str = ""

    # App
    app_env: str = "development"
    log_level: str = "INFO"

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
