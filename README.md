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
| Observability | OpenTelemetry → Grafana Cloud (Mimir + Loki + Tempo) |
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
├── observability/
│   ├── otel.py              # bootstrap: traces, metrics, logs
│   ├── metrics.py           # 17 lazy-singleton metric instruments
│   ├── spans.py             # agent_span, tool_span, record_llm_usage
│   ├── loki.py              # direct Loki push for governance audit trail
│   ├── attributes.py        # Attr class — all OTel attribute name constants
│   ├── pii.py               # PII redaction span processor
│   └── log_processor.py     # PII redaction log processor
├── llm/client.py            # AzureChatOpenAI factory (single source)
└── memory/checkpointer.py   # Cosmos DB LangGraph checkpointer

sap_mock/                    # Separate FastAPI service (SAP S/4HANA simulator)
tests/                       # Unit, integration, and contract tests
create_dashboards.py         # Grafana Cloud dashboard-as-code (4 dashboards)
populate_dashboards.py       # Traffic script to populate dashboard panels
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
# Fill in Azure OpenAI, Cosmos DB, Azure Search, and Grafana Cloud credentials

# Start local infrastructure
docker-compose up -d cosmos-emulator otel-collector jaeger

# Start the services
uv run uvicorn sap_mock.main:app --port 8001   # SAP mock
uv run uvicorn app.main:app --port 8000        # Agents API
```

### Verify

```bash
# Health check
curl localhost:8000/healthz

# Chat query
curl -X POST localhost:8000/chat \
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

## Observability

The system emits all three OpenTelemetry signals — traces, metrics, and logs — to Grafana Cloud.

### Export Pipeline

```
App (OTLP/HTTPS) ──▶ Grafana Cloud OTLP Gateway
                          ├── Mimir   (metrics / Prometheus-compatible)
                          ├── Tempo   (distributed traces)
                          └── Loki    (structured logs)

                      + Direct Loki Push (policy & approval audit records)
```

Metrics export every 30 seconds. Traces are sampled at 100% for the POC.

### Metric Instruments

All 17 instruments are lazy singletons in `app/observability/metrics.py`. Names match dashboard PromQL queries exactly.

| Metric | Type | Labels | Emitted by |
|--------|------|--------|------------|
| `http_request_duration_seconds` | Histogram | method, route, status_code | `TracingMiddleware` |
| `workflow_requests_total` | Counter | status | `chat.py` |
| `workflows_in_progress` | UpDownCounter | — | `chat.py` |
| `workflow_total_duration_seconds` | Histogram | — | `chat.py` |
| `agent_execution_duration_seconds` | Histogram | agent_name | `agent_span()` |
| `supervisor_routing_total` | Counter | next_agent | `supervisor.py` |
| `llm_tokens_consumed_total` | Counter | agent_name, token_type | `record_llm_usage()` |
| `llm_estimated_cost_usd_USD` | Counter | agent_name | `record_llm_usage()` |
| `inventory_below_safety_stock_total` | Counter | material_id | `inventory.py` |
| `procurement_recommendations_total` | Counter | urgency, vendor_id | `procurement.py` |
| `forecast_confidence_range_units` | Histogram | material_id | `forecast.py` |
| `rag_retrieval_score` | Histogram | index_name | `rag_tools.py` |
| `compliance_checks_total` | Counter | outcome | `policy.py` |
| `compliance_flags_requiring_review_total` | Counter | rule_id | `policy.py` |
| `audit_records_written_total` | Counter | — | `policy.py` |
| `approval_cycle_duration_seconds` | Histogram | outcome | `approvals.py` |
| `human_review_queue_depth` | Observable Gauge | — | `approvals.py` |

### Span Types

| Span | Emitted by | Key attributes |
|------|-----------|----------------|
| `agent.{name}` | `agent_span()` | agent.name, agent.turn, agent.decision |
| `tool.{name}` | `tool_span()` | tool.name, tool.duration_ms, tool.result_size |
| `policy.evaluation` | `policy_evaluation_span()` | policy.amount_usd, policy.threshold_usd, policy.outcome |
| `llm.call` | `llm_span()` | gen_ai.system, gen_ai.request.model, gen_ai.usage.* |
| `rag.retrieval` | `rag_span()` | rag.query, rag.top_k, rag.result_count |
| `http` | `TracingMiddleware` + `FastAPIInstrumentor` | http.method, http.route, http.status_code |
| outbound HTTP | `HTTPXClientInstrumentor` (auto) | url, method, status |

### Loki Audit Trail

Two dedicated audit streams are pushed directly to Loki alongside the OTEL log pipeline:

- `{scope="policy"}` — every policy decision with outcome, rule_id, amount_usd
- `{scope="approval"}` — every human approval decision with cycle_seconds

Labels are kept low-cardinality (enum values only); full detail is in the JSON log body, queryable via `| json` in LogQL.

### Grafana Dashboards

Four dashboards defined as code in `create_dashboards.py`. Recreate at any time:

```bash
python create_dashboards.py
```

| Dashboard | UID | Purpose | Panels |
|-----------|-----|---------|--------|
| Operational | `sc-operational` | HTTP traffic, agent performance, LLM cost | 15 |
| Governance | `sc-governance` | Policy decisions, approval cycle, compliance | 11 |
| Logs & Traces | `sc-logs-traces` | Live logs, errors, LLM calls, routing | 5 |
| Executive Summary | `sc-executive` | C-suite KPIs: throughput, cost, success rate | 10 |

**Operational dashboard panels:**
- Request rate per endpoint (owned `http_request_duration_seconds_count`)
- p50 / p95 / p99 latency for `/chat`
- Workflows in progress, queue depth, workflow duration P95, completed rate
- Agent execution duration P95 by agent
- Supervisor routing decisions (bargauge by next_agent)
- LLM tokens per agent, estimated LLM cost per agent (USD/h)
- Procurement recommendations by urgency
- Inventory safety stock violations by material
- RAG retrieval score P50 and P95
- Tool error rate

**Governance dashboard panels:**
- Compliance checks total, auto-approval rate, flags requiring review, audit records (24 h)
- Policy decision outcomes over time, rule firing frequency
- Approval cycle time P50/P95, human review queue depth
- Procurement recommendations trend, forecast confidence range
- Policy decision audit trail (Loki log stream)

**Executive Summary dashboard panels:**
- Requests today, LLM cost today, approval queue depth, auto-approval rate
- Request throughput trend, LLM cost trend by agent
- Workflow success rate, approval cycle time P50
- Agent routing trend, procurement recommendations by urgency

### Populate Dashboards with Test Data

```bash
# Start SAP mock and agents API first, then:
python populate_dashboards.py
```

Drives 3 rounds of traffic across all agent paths (inventory, forecast, procurement, policy, knowledge, analytics). Panels populate within 30–60 seconds as the OTLP metric reader flushes.

## Running Tests

```bash
# All tests
uv run pytest tests/ -v

# Unit tests only
uv run pytest tests/unit/ -v

# Policy evaluator (must maintain 100% branch coverage)
uv run pytest tests/unit/test_policy_evaluator.py -v --cov=app/policy/evaluator

# Observability / metrics tests
uv run pytest tests/unit/test_otel/ -v
```

### Test Output (metrics suite)

```
tests/unit/test_otel/test_metrics.py::TestLazyInit::test_singletons_are_none_before_first_call PASSED
tests/unit/test_otel/test_metrics.py::TestLazyInit::test_workflow_requests_counter_returns_same_object PASSED
... (10 lazy-init tests)
tests/unit/test_otel/test_metrics.py::TestInstrumentNames::test_workflow_requests_counter_name PASSED
... (8 instrument name tests)
tests/unit/test_otel/test_metrics.py::TestHumanReviewQueueDepth::test_observe_callback_returns_current_depth PASSED
... (6 observable gauge tests)
tests/unit/test_otel/test_metrics.py::TestNewDomainMetrics::test_new_singletons_none_before_first_call PASSED
... (15 domain metric tests)

39 passed in 0.77s
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
| `OTLP_ENDPOINT` | OTEL collector gRPC endpoint (local dev, default: `http://otel-collector:4317`) |
| `GRAFANA_OTLP_ENDPOINT` | Grafana Cloud OTLP/HTTPS gateway URL |
| `GRAFANA_INSTANCE_ID` | Grafana Cloud instance ID (for Basic auth) |
| `GRAFANA_API_KEY` | Grafana Cloud API key |
| `GRAFANA_LOKI_ENDPOINT` | Loki push endpoint for direct audit records |
| `GRAFANA_LOKI_USERNAME` | Loki username |
| `GRAFANA_LOKI_PASSWORD` | Loki password |
| `GRAFANA_STACK_URL` | Grafana Cloud stack URL (for `create_dashboards.py`) |
| `GRAFANA_SA_TOKEN` | Grafana service account token (Editor role) |
| `APP_ENV` | `development` or `production` |

Secrets are injected via Azure Key Vault + CSI driver in AKS. Never commit secrets or put them in ConfigMaps.
