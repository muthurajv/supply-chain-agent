# Supply Chain Agentic AI

A proof-of-concept multi-agent AI system for supply-chain operations, built with LangGraph and Azure OpenAI. A single supervisor coordinates six specialist agents inside one LangGraph state machine, deployed on AKS.

## Capabilities

- **Inventory lookup** — real-time stock levels and storage locations via SAP mock
- **Demand forecasting** — LLM reasoning over 18-month shipment history
- **Procurement recommendations** — vendor selection, quantity, cost, and urgency
- **Policy approvals** — deterministic rule evaluation; auto-approve, human review, or deny
- **RAG knowledge retrieval** — hybrid search over policy docs, SOPs, and contracts
- **Executive analytics** — scheduled KPI computation with CFO-ready narratives

## Architecture

```
   ┌──────────────┐
   │  Supervisor  │ ◄────────┐
   └──────┬───────┘          │
          │                  │
  ┌───────┴──────────────┐   │
  ▼      ▼     ▼      ▼  │   ▼
Inv  Forecast Proc  Policy Know Analytics
  └──────────────────────┘
       return to Supervisor
```

Specialists never call each other directly — all routing goes through the supervisor. The Policy Agent is the only path that can pause the graph for human approval (`interrupt()`).

## Tech Stack

| Layer         | Technology                                      |
|---------------|-------------------------------------------------|
| Orchestration | LangGraph                                       |
| LLM           | Azure OpenAI GPT-4o, text-embedding-3-large     |
| Retrieval     | Azure AI Search (hybrid: keyword + vector)      |
| API           | FastAPI                                         |
| Runtime       | AKS (Azure Kubernetes Service)                  |
| State / queue | Azure Cosmos DB (NoSQL)                         |
| Observability | OpenTelemetry → Azure Monitor + Grafana         |
| Auth          | Azure AD / Entra ID                             |
| Language      | Python 3.11                                     |
| Package mgr   | uv                                              |

## Project Structure

```
app/
├── main.py                  # FastAPI entrypoint
├── config.py                # pydantic-settings
├── agents/
│   ├── graph.py             # build_graph()
│   ├── state.py             # GraphState TypedDict
│   ├── supervisor.py        # routing logic
│   ├── inventory.py
│   ├── forecast.py
│   ├── procurement.py
│   ├── policy.py
│   ├── knowledge.py
│   └── analytics.py
├── tools/
│   ├── sap_tools.py         # SAP mock HTTP client
│   ├── rag_tools.py         # Azure AI Search wrapper
│   └── kpi_tools.py         # Cosmos KPI store
├── policy/
│   ├── schema.py            # PolicyRule, PolicyDecision
│   ├── extraction.py        # LLM-based rule extraction
│   └── evaluator.py         # deterministic threshold check
├── api/routes/
│   ├── chat.py              # POST /chat
│   ├── invoke.py            # POST /agent/invoke
│   ├── dashboards.py        # GET /dashboards/{kpi}
│   └── approvals.py         # GET/POST /approvals
├── observability/           # OpenTelemetry bootstrap + span helpers
├── llm/client.py            # AzureChatOpenAI factory
└── memory/checkpointer.py   # Cosmos DB LangGraph checkpointer

sap_mock/                    # Separate FastAPI service (SAP S/4HANA simulator)
tests/                       # Unit, integration, and contract tests
deploy/k8s/                  # Kubernetes manifests
```

## Local Development

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv)
- Docker (for Cosmos emulator and OTEL collector)

### Setup

```bash
# Install dependencies
uv sync

# Configure environment
cp .env.example .env
# Fill in Azure OpenAI, Cosmos DB, and Azure Search credentials

# Start local infrastructure
docker-compose up -d cosmos-emulator otel-collector jaeger

# Start the services
make dev   # starts sap-mock + agents-api with hot reload
```

### Verify

```bash
curl localhost:8080/healthz

curl -X POST localhost:8080/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Do I need to reorder M-1042?"}'
```

Traces are available at [http://localhost:16686](http://localhost:16686) (Jaeger).

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/chat` | Interactive user query (requires Bearer token) |
| `POST` | `/agent/invoke` | Programmatic/scheduled invocation |
| `GET`  | `/dashboards/{kpi}` | Read pre-computed executive KPI |
| `GET`  | `/approvals` | List pending human approval requests |
| `POST` | `/approvals/{id}/decide` | Submit approval decision |
| `GET`  | `/healthz` | Health check |

## Approval Flow

1. Procurement agent proposes an order with a cost estimate.
2. Supervisor routes to Policy Agent.
3. Policy Agent retrieves policy docs, extracts rules via LLM, then evaluates **deterministically** in Python.
4. Result:
   - `auto_approved` → execution continues
   - `needs_human` → graph pauses; item queued in Cosmos; human calls `POST /approvals/{id}/decide`
   - `denied` → workflow ends with explanation

> **Invariant**: the LLM extracts rules; Python evaluates them. An LLM never decides an approval.

## Running Tests

```bash
# All tests
uv run pytest tests/ -v

# Unit tests only
uv run pytest tests/unit/ -v

# Policy evaluator (must maintain 100% branch coverage)
uv run pytest tests/unit/test_policy_evaluator.py -v --cov=app/policy/evaluator
```

## Deployment

```bash
make build    # build + push Docker images (tagged by git SHA)
make deploy   # helm upgrade --install
make smoke    # health check + one /chat sanity query
```

See `SETUP.md` for full deployment instructions and `docs/runbooks/` for operational runbooks.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI service endpoint |
| `AZURE_OPENAI_KEY` | Azure OpenAI API key |
| `AZURE_OPENAI_DEPLOYMENT` | Deployment name (default: `gpt-4o`) |
| `AZURE_SEARCH_ENDPOINT` | Azure AI Search endpoint |
| `AZURE_SEARCH_KEY` | Azure AI Search admin key |
| `COSMOS_CONNECTION_STRING` | Cosmos DB connection string |
| `SAP_MOCK_BASE_URL` | SAP mock service URL (default: `http://sap-mock:8001`) |
| `OTLP_ENDPOINT` | OTEL collector endpoint (default: `http://otel-collector:4317`) |
| `APP_ENV` | `development` or `production` |

Secrets are injected via Azure Key Vault + CSI driver in AKS. Never commit secrets or put them in ConfigMaps.
