# Setup Guide — Supply Chain Agentic AI POC

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11+ | |
| uv | latest | `pip install uv` |
| Azure OpenAI | — | GPT-4o + `text-embedding-3-large` deployments |
| Azure AI Search | — | For policy RAG and episodic memory |
| Azure Cosmos DB | — | NoSQL API, for checkpoints, KPIs, approvals |

---

## 1. Clone the repository

```bash
git clone https://github.com/muthurajv/supply-chain-agent.git
cd supply-chain-agent
```

---

## 2. Install dependencies

```bash
uv sync
```

For test and lint tooling:

```bash
uv sync --extra test --extra dev
```

---

## 3. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in the values below.

### Azure OpenAI

```env
AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com/
AZURE_OPENAI_KEY=<your-key>
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-large
AZURE_OPENAI_API_VERSION=2024-08-01-preview
```

Find these in **Azure Portal → your OpenAI resource → Keys and Endpoint**, and **Azure OpenAI Studio → Deployments** for deployment names.

### Azure AI Search

```env
AZURE_SEARCH_ENDPOINT=https://<your-search>.search.windows.net
AZURE_SEARCH_KEY=<your-key>
AZURE_SEARCH_INDEX_POLICY=policy-docs
AZURE_SEARCH_INDEX_EPISODIC=episodic-memory
```

Find these in **Azure Portal → your AI Search resource → Keys**.

### Azure Cosmos DB

```env
COSMOS_CONNECTION_STRING=AccountEndpoint=https://<your-cosmos>.documents.azure.com:443/;AccountKey=<key>;
COSMOS_DATABASE=supply-chain-agent
COSMOS_CONTAINER_CHECKPOINTS=checkpoints
COSMOS_CONTAINER_KPI=kpis
COSMOS_CONTAINER_APPROVALS=approval-queue
```

Find the connection string in **Cosmos DB → Keys → Primary Connection String**.

### Local service URLs (for local dev)

```env
SAP_MOCK_BASE_URL=http://localhost:8001
OTLP_ENDPOINT=http://localhost:4317
```

### Auth (optional for local dev — leave blank to skip token validation)

```env
ENTRA_TENANT_ID=<your-tenant-id>
ENTRA_CLIENT_ID=<your-client-id>
ENTRA_AUDIENCE=api://<your-client-id>
```

---

## 4. Run the SAP mock service

The SAP mock is a separate FastAPI service that simulates SAP S/4HANA. It must be running before the agents API starts.

```bash
uv run uvicorn sap_mock.main:app --host 0.0.0.0 --port 8001 --reload
```

Verify it is up:

```bash
curl http://localhost:8001/health
# {"status":"ok","service":"sap-mock"}

curl http://localhost:8001/inventory/M-1042
# returns inventory for Precision Ball Screw 16mm
```

---

## 5. Run the agents API

In a second terminal:

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

Verify it is up:

```bash
curl http://localhost:8080/healthz
# {"status":"ok","service":"supply-chain-agent","env":"development"}
```

---

## 6. Send your first request

```bash
curl -X POST http://localhost:8080/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Do I need to reorder M-1042 for next month?"}'
```

The supervisor agent will route through inventory → forecast → procurement → policy and return a structured response.

---

## 7. Run the test suite

```bash
uv run pytest
```

Expected output: **42 passed**.

To check policy evaluator branch coverage (required at 100% by CI):

```bash
uv run pytest --cov=app/policy/evaluator --cov-report=term-missing
```

---

## 8. Optional: Local observability (traces)

Run Jaeger to view distributed traces:

```bash
docker run -d --name jaeger \
  -p 16686:16686 \
  -p 4317:4317 \
  jaegertracing/all-in-one:latest
```

Open **http://localhost:16686** after sending requests. Traces appear under the `supply-chain-agent` service.

---

## Service map

| Service | Port | Purpose |
|---|---|---|
| `sap_mock` | 8001 | Deterministic SAP S/4HANA mock — inventory, vendors, purchase orders, shipment history |
| `agents-api` | 8080 | LangGraph supervisor + 6 specialist agents; exposes `/chat`, `/agent/invoke`, `/approvals`, `/dashboards` |
| Jaeger (optional) | 16686 | Distributed trace UI |

---

## Key API endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/healthz` | Health check |
| `POST` | `/chat` | Natural-language supply-chain query |
| `POST` | `/agent/invoke` | Direct graph invocation (structured input) |
| `GET` | `/approvals` | List pending human-approval items |
| `GET` | `/approvals/{id}` | Get a specific approval request |
| `POST` | `/approvals/{id}/decide` | Approve or reject a pending action |
| `GET` | `/dashboards/{kpi}` | Pre-computed executive KPI read |

---

## Project structure

```
supply-chain-agent/
├── app/
│   ├── agents/          # LangGraph nodes: supervisor + 6 specialists
│   ├── api/             # FastAPI routes and middleware
│   ├── llm/             # Azure OpenAI factory (single entry point)
│   ├── models/          # Pydantic contracts
│   ├── observability/   # OTEL spans, attributes, PII redaction
│   ├── policy/          # Rule extraction (LLM) + evaluation (deterministic)
│   └── tools/           # SAP mock client, RAG, KPI store
├── sap_mock/            # Standalone SAP mock FastAPI service
├── tests/               # Unit, integration, and contract tests
├── deploy/              # Dockerfiles and Kubernetes manifests
├── CLAUDE.md            # Architectural contract for contributors
└── SETUP.md             # This file
```

---

## Troubleshooting

**`ValidationError` on startup** — a required env var is missing. Check that `.env` is populated and in the project root.

**`Connection refused` on SAP mock calls** — the SAP mock service is not running. Start it first (step 4) before the agents API.

**`no such table` in tests** — run `uv run pytest` from the project root, not from inside a subdirectory.

**Azure OpenAI 401** — double-check `AZURE_OPENAI_KEY` and that the deployment name in `AZURE_OPENAI_DEPLOYMENT` matches exactly what is shown in Azure OpenAI Studio.

**Cosmos DB errors in local dev** — you can use the [Azure Cosmos DB Emulator](https://learn.microsoft.com/en-us/azure/cosmos-db/how-to-develop-emulator) locally. Set `COSMOS_CONNECTION_STRING` to the emulator connection string.
