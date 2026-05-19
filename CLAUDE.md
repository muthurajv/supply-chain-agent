# CLAUDE.md

> Project guide for the Supply Chain Agentic AI POC. This file is the contract
> between human contributors and AI coding assistants working in this repo.
> Read it fully before making any change.

---

## 1. Project overview

A proof-of-concept Agentic AI system for supply-chain operations. One user-facing
service exposes six specialist agents coordinated by a supervisor, all running
inside a single LangGraph state machine on AKS. The POC mocks SAP, uses
LLM-based forecasting, and gates every action through a deterministic policy
engine. C-suite dashboards refresh on a schedule.

**Capabilities in scope**

- Inventory lookup
- Shipment forecasting (LLM reasoning over history)
- Procurement recommendations
- SAP integration (mocked for POC)
- Policy approvals (auto-approve under threshold, human above)
- RAG retrieval over policy docs, SOPs, contracts
- Executive analytics (pre-computed KPIs)

**Out of scope for POC**

- Real SAP S/4HANA connectivity (use `sap_mock` adapter)
- Real Teams/email approval routing (write to queue, log event)
- Multi-tenancy (single tenant only)
- FinOps hard cost caps (observe spend, don't enforce yet)
- Red-team automation (manual prompt-injection passes on Policy Agent only)

---

## 2. Tech stack — fixed, do not substitute

| Layer            | Technology                                             |
| ---------------- | ------------------------------------------------------ |
| Orchestration    | LangGraph                                              |
| LLM              | Azure OpenAI GPT-4o, `text-embedding-3-large`          |
| Retrieval        | Azure AI Search (hybrid: keyword + vector)             |
| API              | FastAPI                                                |
| Runtime          | AKS (Azure Kubernetes Service)                         |
| State / queue    | Azure Cosmos DB (NoSQL)                                |
| Observability    | OpenTelemetry → Azure Monitor + Grafana                |
| Auth             | Azure AD / Entra ID                                    |
| Language         | Python 3.11                                            |
| Package manager  | `uv`                                                   |
| Testing          | `pytest`, `pytest-asyncio`                             |

Do not introduce new top-level dependencies without an ADR in `docs/adr/`.

---

## 3. Architecture

### 3.1 Topology

Single supervisor + specialist agents in **one** LangGraph. Specialists return
to the supervisor via `Command(goto="supervisor")`; the supervisor decides the
next hop or ends the run.

```
   ┌──────────────┐
   │  Supervisor  │  ◄────────┐
   └──────┬───────┘           │
          │                   │
  ┌───────┴────────────────┐  │
  ▼       ▼      ▼      ▼  │  ▼
Inv  Forecast Proc  Policy Know Analytics
  │       │      │      │  │
  └───────┴──────┴──────┴──┘
            return to Supervisor
```

### 3.2 Specialist responsibilities

| Agent       | Reads                 | Produces                   | Tools used                                  |
| ----------- | --------------------- | -------------------------- | ------------------------------------------- |
| Inventory   | user message          | `inventory_snapshot`       | `sap_mock.get_inventory`                    |
| Forecast    | `inventory_snapshot`  | `forecast`                 | `sap_mock.get_shipment_history`, LLM        |
| Procurement | inventory + forecast  | `procurement_proposal`     | `sap_mock.get_vendors`, LLM, `create_pr`    |
| Policy      | `procurement_proposal`| `policy_decision`          | `rag.retrieve`, LLM (extract), Python eval  |
| Knowledge   | query                 | retrieved chunks           | `rag.retrieve` (Azure AI Search)            |
| Analytics   | scheduled trigger     | KPI rows                   | `sap_mock.*`, episodic memory, LLM          |

### 3.3 Approval flow (most safety-critical path)

1. Any agent producing an action with `$_value` emits a **proposal** to state.
2. Supervisor routes to Policy Agent.
3. Policy Agent:
   - calls Knowledge Agent to retrieve relevant policy chunks,
   - LLM extracts structured `PolicyRule` objects (flexible authoring),
   - **deterministic Python** evaluates proposal against rules (audit-grade gate),
   - returns one of: `auto_approved`, `needs_human`, `denied`.
4. `auto_approved` → Supervisor routes back to the proposing agent for execution.
5. `needs_human` → `interrupt()` pauses the graph; proposal written to
   Approval Queue (Cosmos); human resumes via `/approvals/{id}/decide`.
6. `denied` → graph ends with explanation.

**Invariant**: an LLM never decides approval. The LLM extracts rules; Python
evaluates them. Every approval decision is reproducible from the same inputs.

### 3.4 State shape

Defined in `app/agents/state.py`. The only shared mutable surface between
nodes. Adding a field requires:

- updating the `TypedDict`,
- documenting the producer agent in the docstring,
- ensuring the Cosmos checkpointer can serialize it.

---

## 4. Repository layout

```
.
├── CLAUDE.md                  # this file
├── README.md                  # human-facing quickstart
├── pyproject.toml             # uv-managed dependencies
├── docker/
│   ├── api.Dockerfile
│   ├── sap-mock.Dockerfile
│   └── otel-collector.yaml
├── k8s/
│   ├── api-deployment.yaml
│   ├── sap-mock-deployment.yaml
│   ├── analytics-cronjob.yaml
│   ├── otel-collector.yaml
│   └── ingress.yaml
├── app/
│   ├── main.py                # FastAPI entrypoint
│   ├── api/
│   │   ├── chat.py            # POST /chat
│   │   ├── invoke.py          # POST /agent/invoke
│   │   ├── dashboards.py      # GET /dashboards/{kpi}
│   │   └── approvals.py       # GET/POST /approvals
│   ├── agents/
│   │   ├── graph.py           # build_graph()
│   │   ├── state.py           # GraphState TypedDict
│   │   ├── supervisor.py
│   │   ├── inventory.py
│   │   ├── forecast.py
│   │   ├── procurement.py
│   │   ├── policy.py
│   │   ├── knowledge.py
│   │   └── analytics.py
│   ├── tools/
│   │   ├── sap_mock.py        # HTTP client to sap-mock service
│   │   ├── rag.py             # Azure AI Search wrapper
│   │   └── kpi_store.py       # Cosmos read/write
│   ├── policy/
│   │   ├── extraction.py      # LLM-based PolicyRule extraction
│   │   ├── evaluator.py       # deterministic threshold check
│   │   └── schema.py          # PolicyRule, PolicyDecision
│   ├── observability/
│   │   ├── bootstrap.py       # init_telemetry()
│   │   ├── attributes.py      # Attr class (attribute name constants)
│   │   ├── redaction.py       # PIIRedactionProcessor
│   │   └── wrappers.py        # agent_span(), tool_span()
│   ├── llm/
│   │   └── client.py          # AzureChatOpenAI factory
│   └── config.py              # pydantic-settings
├── sap_mock/                  # separate FastAPI service
│   ├── main.py
│   ├── fixtures/
│   │   ├── materials.json
│   │   ├── vendors.json
│   │   └── shipment_history.json
│   └── routes/
├── tests/
│   ├── unit/
│   │   ├── test_policy_evaluator.py    # MUST exist and pass
│   │   ├── test_agents/
│   │   └── test_otel/
│   ├── integration/
│   │   └── test_graph_end_to_end.py
│   └── fixtures/
├── grafana/
│   ├── operational-dashboard.json
│   └── governance-dashboard.json
└── docs/
    ├── adr/                   # architecture decision records
    └── runbooks/
```

---

## 5. Coding conventions

### 5.1 Python style

- Python 3.11. Use modern syntax: `list[int]` over `List[int]`, `X | None`
  over `Optional[X]`, `match` statements where they aid clarity.
- `from __future__ import annotations` at the top of every module.
- Type hints on every function signature, public and private.
- Pydantic v2 for every external contract (HTTP, LLM structured output,
  Cosmos document shapes). Plain dataclasses are not allowed for these.
- `ruff` for lint, `ruff format` for formatting. Run before committing.
- Docstrings: one-line summary, blank line, details. Use the imperative mood.

### 5.2 Agent nodes — required structure

Every specialist node must follow this shape:

```python
def my_node(state: GraphState) -> Command:
    with agent_span("my_agent", turn=state.get("turn", 0)) as span:
        # 1. Read what you need from state — never mutate state directly.
        # 2. Call tools through wrappers in app/tools/* (never raw clients).
        # 3. Use structured output for any LLM call that drives logic.
        # 4. Emit a Command(goto="supervisor", update={...}) at the end.
        # 5. Always append a HumanMessage(name="my_agent", ...) summarizing
        #    what this node did, so the supervisor sees provenance.
        ...
        return Command(goto="supervisor", update={...})
```

**Forbidden in agent nodes**:

- Calling another agent directly. Route through the supervisor.
- Mutating state outside the `Command.update`.
- Raising exceptions for control flow. Return a decision in state.
- Logging via `print` or `logging`. Use span attributes and events.

### 5.3 Tool calls — required structure

Every tool function lives in `app/tools/`, wraps its body in `tool_span()`, and
sets the standard attributes. No raw HTTP, no raw SDK calls inside agent
nodes — always go through a tool wrapper.

```python
def get_inventory(material_id: str) -> Inventory:
    with tool_span("sap_mock.get_inventory", **{Attr.SAP_MOCK: True}) as span:
        response = requests.get(f"{settings.sap_mock_url}/inventory/{material_id}")
        span.set_attribute(Attr.TOOL_RESULT_SIZE, len(response.content))
        return Inventory.model_validate(response.json())
```

### 5.4 LLM calls

- One factory in `app/llm/client.py`. Never instantiate `AzureChatOpenAI`
  elsewhere.
- Default `temperature=0.0`. Anything higher requires a comment explaining why.
- Always use `.with_structured_output(SomeModel)` when the result drives a
  decision. Free-text output is allowed only for user-facing prose.
- Never let the LLM execute a side-effect-bearing action. The LLM proposes;
  Python executes after a deterministic check (policy or otherwise).

### 5.5 Naming

| Thing             | Convention                                  |
| ----------------- | ------------------------------------------- |
| Modules / files   | `snake_case`                                |
| Classes / models  | `PascalCase`                                |
| Functions / vars  | `snake_case`                                |
| Constants         | `UPPER_SNAKE_CASE`                          |
| Agent names       | lowercase single word: `inventory`, `policy`|
| Tool names        | `domain.action`: `sap_mock.get_inventory`   |
| OTEL attributes   | `namespace.field`: `policy.outcome`         |
| Policy rule IDs   | `P-{DOMAIN}-{NN}`: `P-PROC-03`              |
| Cosmos containers | `kebab-case`: `approval-queue`              |

---

## 6. Observability — required, not optional

### 6.1 The rule

**No code path produces a side effect without a span.** This includes tool
calls, LLM calls, Cosmos writes, queue writes, and approval-state changes.

### 6.2 Where to instrument

| Surface                | Mechanism                                          |
| ---------------------- | -------------------------------------------------- |
| FastAPI HTTP requests  | `FastAPIInstrumentor` (auto)                       |
| Outbound HTTP          | `RequestsInstrumentor` (auto)                      |
| Azure OpenAI calls     | `opentelemetry-instrumentation-openai-v2` (auto)   |
| Agent nodes            | `agent_span(name, turn=...)` (manual, mandatory)   |
| Tool calls             | `tool_span(name, **attrs)` (manual, mandatory)     |
| Policy evaluations     | `policy_evaluation_span(...)` (manual, mandatory)  |

### 6.3 Attribute discipline

All attribute names live in `app/observability/attributes.py` as the `Attr`
class. **Do not use string literals in `set_attribute` calls.** New attributes
go in `Attr` first; the test suite verifies no raw strings appear in node code.

OTEL GenAI semantic conventions are used as-is where they apply
(`gen_ai.system`, `gen_ai.request.model`, `gen_ai.usage.*`). Domain attributes
use the project namespaces: `agent.*`, `tool.*`, `policy.*`, `procurement.*`,
`forecast.*`, `rag.*`, `sap.*`.

### 6.4 PII redaction

Redaction runs in `PIIRedactionProcessor` before export — never at the call
site. Free-text attributes that may carry user input belong in `REDACT_ATTRS`
in `app/observability/redaction.py`. When adding a new free-text attribute,
add it to that set in the same PR.

User IDs are hashed: `Attr.USER_ID_HASH` carries `sha256(user_id)[:16]`, never
the raw value.

### 6.5 Export pipeline

```
App pods ──OTLP──▶ OTEL Collector ──┬──▶ Azure Monitor (Application Insights)
                                    └──▶ Prometheus / Grafana Tempo
```

Local dev exports to a local collector that writes to console + Jaeger UI on
`localhost:16686`.

---

## 7. The Policy Agent — extra rules

Because this is the audit-grade gate, it has stricter rules than other agents.

1. **The LLM never decides approval.** It only extracts rules. The decision
   function in `app/policy/evaluator.py` is pure Python with no LLM call.
2. **Extraction is cached by `hash(policy_text)`.** Re-running extraction on
   the same document version must produce identical rules. `temperature=0.0`
   is mandatory.
3. **Ambiguity routes to humans.** If extraction sees "large purchases require
   approval" without a numeric threshold, emit a rule with
   `max_amount_usd=None` and `on_violation="needs_human"`. Never guess a
   number.
4. **Every rule carries `source_excerpt`** — the literal sentence from the
   policy doc. This is the audit artifact.
5. **The evaluator's decision order is fixed**:
   forbidden vendor → denied; no matching rule → needs_human; category
   mismatch → needs_human; amount over threshold → on_violation;
   preferred-vendor required but not preferred → needs_human; else
   auto_approved.
6. **Every decision emits a span** with `policy.outcome`, `policy.rule_id`,
   `policy.threshold_usd`, `policy.amount_usd`, `policy.explanation`.
7. **The `test_policy_evaluator.py` suite must achieve 100% branch coverage.**
   CI fails below that.

---

## 8. Testing

### 8.1 Layers

| Layer       | Scope                                              | Speed     |
| ----------- | -------------------------------------------------- | --------- |
| Unit        | Single agent or tool, all deps mocked              | < 1s each |
| Integration | Full graph with `sap_mock` + in-memory Cosmos      | < 30s     |
| Contract    | `sap_mock` matches the documented SAP shape        | < 5s      |
| Eval        | Forecast accuracy, policy rule precision (offline) | minutes   |

### 8.2 Required tests for every PR that touches…

- **An agent node** → unit test for happy path + at least one failure mode.
- **A tool** → contract test that the response shape matches the Pydantic
  model.
- **The policy evaluator** → exhaustive table-driven cases. Use
  `pytest.mark.parametrize` with explicit `(rules, proposal, expected)`
  tuples.
- **An OTEL attribute** → assertion in the relevant span test.

### 8.3 Determinism

Tests must not call live Azure OpenAI. Mock at the LLM factory level. Tests
must not call the real Azure AI Search; use a fake retriever from
`tests/fixtures/retrievers.py`.

For the eval suite, snapshot LLM outputs into `tests/fixtures/llm_snapshots/`.
Re-record only when prompt or model changes; reference the PR that updated
them.

---

## 9. Adding a new specialist agent

Follow this checklist exactly. The Inventory agent is the reference
implementation.

1. Define the state additions in `app/agents/state.py`. Document the producer.
2. Create `app/agents/{name}.py` with one `def {name}_node(state) -> Command`.
3. Wrap the body in `agent_span("{name}", turn=...)`.
4. Add the agent to `Route.next` Literal in `app/agents/supervisor.py`.
5. Add a one-line description to the supervisor system prompt under
   "Specialists".
6. Register the node in `app/agents/graph.py`.
7. Add a tool to `app/tools/` if the agent needs a new external call.
8. Add a unit test in `tests/unit/test_agents/test_{name}.py`.
9. Add the agent to the integration test's expected hop list when relevant.
10. Update `CLAUDE.md` section 3.2 (the responsibility table).

If you skip any step, CI will fail or future contributors will hit
undocumented behavior.

---

## 10. Adding or changing a policy

The policy text itself lives in the Azure AI Search index, not in code. To
change policies:

1. Update the source document in the policy library (out-of-band, owned by
   compliance).
2. Re-index via the indexing job (`ops/reindex_policies.py`).
3. Bump the policy index version in `app/config.py`
   (`policy_index = "policies-v4"`).
4. Run the eval suite (`tests/eval/test_policy_extraction.py`) to confirm the
   new rules extract cleanly.
5. Inspect the rule diff: `python ops/diff_policy_rules.py v3 v4`. Any rule
   whose `source_excerpt` changed semantically requires sign-off in the PR
   description.
6. Roll the API deployment; the new index version takes effect on next call.

---

## 11. Deployment

### 11.1 Environments

| Env   | Cluster              | LLM deployment | Policy index    | Mode |
| ----- | -------------------- | -------------- | --------------- | ---- |
| local | docker-compose       | gpt-4o-dev     | policies-local  | mock |
| dev   | aks-dev              | gpt-4o-dev     | policies-v3     | mock |
| poc   | aks-poc              | gpt-4o-prod    | policies-v3     | mock |

There is no `prod` for the POC. Promotion to a real environment requires the
SAP adapter swap, which is a separate ADR.

### 11.2 Pods

| Workload        | Kind        | Replicas | Notes                                  |
| --------------- | ----------- | -------- | -------------------------------------- |
| `agents-api`    | Deployment  | 2        | Stateless. Behind ingress + AAD auth.  |
| `sap-mock`      | Deployment  | 1        | Stateless. ClusterIP only.             |
| `otel-collector`| DaemonSet   | per-node | Receives OTLP, fans out.               |
| `analytics-job` | CronJob     | -        | Runs every 6h, hits `/agent/invoke`.   |

### 11.3 Secrets

All secrets injected via Azure Key Vault + CSI driver. **Never** commit a
secret, never put one in a ConfigMap, never log one. The Key Vault references
live in `k8s/secrets-provider.yaml`. Required keys:

- `azure-openai-api-key`
- `cosmos-conn-str`
- `azure-search-key`
- `aad-client-secret`

### 11.4 Image build

`docker build -f docker/api.Dockerfile -t {acr}/agents-api:{git-sha} .`

Tags use the git SHA — never `latest`. The deployment manifest is templated
through Helm; do not edit raw YAML for releases.

### 11.5 Rollout

```
make build      # builds + pushes both images
make deploy     # helm upgrade --install
make smoke      # hits /healthz and one /chat sanity query
```

---

## 12. Dashboards

Two Grafana dashboards ship with the repo at `grafana/`.

### 12.1 Operational dashboard

Panels:

- Request rate per endpoint
- p50 / p95 / p99 end-to-end latency
- LLM token spend per agent per day
- Tool error rate per tool
- Active LangGraph runs (in-flight + interrupted)
- Cosmos throughput consumption (RU/s)

Alerts on this dashboard:

- p95 `/chat` latency > 12s for 5m
- Any tool error rate > 5% over 10m
- Approval queue depth > 50

### 12.2 Governance dashboard

Panels:

- Auto-approval rate (rolling 24h, target ≥ 80%)
- Decisions split by `policy.outcome`
- Rule firing frequency (which `policy.rule_id` fires most)
- Average approval cycle time (proposal → human decision)
- Denied count by reason

Alerts on this dashboard:

- Auto-approval rate < 50% for 1h (signals rule drift or LLM regression)
- Any `policy.outcome=denied` count spike > 3σ above 7-day baseline
- Single rule firing > 90% of decisions (signals over-broad rule)

---

## 13. Runbooks

Located in `docs/runbooks/`. Required runbooks:

- `approval-queue-stuck.md` — what to do when approvals pile up
- `forecast-confidence-collapse.md` — when forecast bands go to zero
- `policy-extraction-mismatch.md` — when extracted rules diverge from policy
- `azure-openai-quota-exhausted.md` — failover and queueing
- `cosmos-throttled.md` — RU/s scaling
- `otel-collector-down.md` — fallback to local buffering

Every PR that introduces a new failure mode must add or update a runbook.

---

## 14. Local development

```bash
# one-time
uv sync
cp .env.example .env  # fill in Azure OpenAI keys etc.
docker-compose up -d cosmos-emulator otel-collector jaeger

# run the stack
make dev   # starts sap-mock and agents-api with hot reload

# verify
curl localhost:8080/healthz
curl -X POST localhost:8080/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Do I need to reorder M-1042?"}'

# traces
open http://localhost:16686  # Jaeger
```

---

## 15. When uncertain — escalation rules for AI assistants

If you are an AI assistant working in this repo and you encounter any of the
following, **stop and ask** rather than guessing:

1. The user asks you to add an LLM call to the policy evaluation path.
   This violates section 7 and must not happen.
2. The user asks you to remove an OTEL span.
   Spans on side effects are mandatory (section 6.1).
3. The user asks you to commit a secret or hardcode an API key.
   Always refuse; point at Key Vault (section 11.3).
4. The user asks you to change a `Attr` constant's string value.
   Existing dashboards depend on the literal string. Add a new attribute
   instead and migrate dashboards in a follow-up.
5. The user asks you to skip tests "for now".
   Required tests in section 8.2 are not optional.
6. The user asks you to call SAP directly from an agent node.
   Always go through the `sap_mock` tool wrapper, even in prod (the adapter
   pattern is what makes the swap to real SAP a single config change).

If a change feels like it would violate an invariant in this file, raise it
in the PR description rather than working around it silently.

---

## 16. Glossary

- **Agent** — a node in the LangGraph state machine with a focused
  responsibility, its own scoped prompt, and its own tool subset.
- **Specialist** — any agent other than the supervisor.
- **Proposal** — an action with side effects produced by a specialist,
  awaiting policy evaluation.
- **Policy rule** — a structured `PolicyRule` extracted from policy prose,
  used by the deterministic evaluator.
- **Threshold gate** — the deterministic Python check inside the Policy Agent.
- **Episodic memory** — past trips, past procurement decisions, past forecasts.
- **Semantic memory** — vendor preferences, learned patterns, vectorized.
- **Working state** — the in-flight `GraphState` for one user request.
- **Interrupt** — LangGraph's mechanism for pausing a graph awaiting human input.
- **KPI store** — Cosmos container holding pre-computed values for the
  executive dashboard read path.

---

*Last updated: keep this header current. Bump on any structural change.*
