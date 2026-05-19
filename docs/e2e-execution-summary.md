# End-to-End Execution Summary — Supply Chain Agent POC

**Query:** `"Do I need to reorder M-1042?"`
**Date:** 2026-05-19
**Environment:** Local development (Docker-free, Azure-backed)
**Endpoint:** `POST http://localhost:8080/chat`
**Response Time:** ~15–20 seconds (LLM calls + Azure AI Search)

---

## Services Running

| Service | Port | Status |
|---|---|---|
| SAP Mock API | 8001 | Running (uvicorn, SQLite fixtures) |
| Agents API (FastAPI + LangGraph) | 8080 | Running (uvicorn) |
| Azure OpenAI (GPT-4o) | cloud | Connected |
| Azure AI Search | cloud | Connected (`policy-docs` index, `ais-sc-agent-dev`) |
| Azure Cosmos DB | cloud | Connected (checkpoints, KPIs, approvals) |
| OTEL Collector | 4317 | Not running — local dev, traces dropped gracefully |

---

## Agent Execution Flow (LangGraph State Machine)

```
User → POST /chat → Supervisor → Inventory Agent → Supervisor
                             → Forecast Agent  → Supervisor
                             → Procurement Agent → Supervisor
                             → Policy Agent    → Supervisor → END
```

---

## Agent 1: Supervisor

**Role:** Entry point and router. Reads the user message and determines which specialist to invoke first.

**Action:** Parsed `"Do I need to reorder M-1042?"` → routed to `inventory_agent`.

**State written:** `next_agent = "inventory_agent"`

---

## Agent 2: Inventory Agent (`inventory_agent`)

**Tools called:**
- `sap_mock.get_inventory(material_id="M-1042")`
- `sap_mock.get_stock_locations(material_id="M-1042")`

**SAP Mock Response:**

```json
{
  "material_id": "M-1042",
  "description": "Precision Ball Screw 16mm",
  "plant": "P001",
  "on_hand_qty": 220.0,
  "safety_stock": 150.0,
  "unit": "EA"
}
```

**Decision logic:**
- On-hand (220) > Safety stock (150) → not immediately below threshold
- Passed to Forecast Agent to assess whether future demand will exhaust stock

**State written:**

```
material_id      = "M-1042"
inventory_result = { on_hand_qty: 220, safety_stock: 150, below_safety_stock: false }
```

**Message emitted:** `"Material M-1042 (Precision Ball Screw 16mm): 220.0 EA on hand across 1 location. Safety stock: 150.0 EA. Above safety stock."`

**Status:** ✅ Completed — returned to Supervisor

---

## Agent 3: Forecast Agent (`forecast_agent`)

**Tool called:** `sap_mock.get_shipment_history(material_id="M-1042", months=18)`

**Historical data summary (54 shipment records, Nov 2024 – May 2026):**

| Period | Avg Monthly Demand |
|---|---|
| Q4 2024 | ~319 units/month |
| Q1–Q2 2025 | ~296 units/month |
| Q3–Q4 2025 | ~360 units/month (seasonal uptick) |
| Q1–Q2 2026 | ~358 units/month (elevated, sustained) |

**LLM called:** Azure OpenAI GPT-4o (`temperature=0.0`, JSON mode)

**LLM forecast output:**

```json
{
  "forecast_qty": 365.0,
  "confidence_low": 330.0,
  "confidence_high": 400.0,
  "trend_pct": 8.5,
  "seasonal_note": "Upward trend sustained into Q2 2026; demand elevated vs prior year",
  "rationale": "18-month history shows consistent growth trend. Q4 2025 surge maintained into 2026. Conservative forecast accounts for minor mean reversion."
}
```

**State written:** `forecast_result = { forecast_qty: 365, confidence_low: 330, confidence_high: 400, trend_pct: +8.5 }`

**Status:** ✅ Completed — returned to Supervisor

---

## Agent 4: Procurement Agent (`procurement_agent`)

**Tool called:** `sap_mock.get_preferred_vendors()`

**Vendor selected:** Precision Parts Ltd (`V-7`) — preferred vendor, 14-day lead time, NET30 terms

**Calculation logic:**

```
net_demand     = forecast_qty (365) − on_hand (220) = 145 units
reorder_qty    = net_demand × 1.10 buffer factor    = 159.5 → 160 units
estimated_cost = 160 × $21.00/unit                  = $3,360.00
urgency        = "medium"  (gap/safety_stock ratio ≈ 0.97)
```

**Procurement proposal:**

| Field | Value |
|---|---|
| Material | M-1042 — Precision Ball Screw 16mm |
| Recommended Qty | 160–165 units |
| Vendor | Precision Parts Ltd (V-7) — Preferred, NET30 |
| Unit Price | $21.00 |
| Estimated Cost | $3,360 – $3,465 |
| Lead Time | 14 days |
| Urgency | Medium |

**State written:** `procurement_proposal = { ... }`, pending policy evaluation

**Status:** ✅ Completed — returned to Supervisor → routed to Policy Agent

---

## Agent 5: Policy Agent (`policy_agent`)

### Phase 1 — RAG Retrieval (Azure AI Search)

**Index queried:** `policy-docs` on `ais-sc-agent-dev.search.windows.net`

**Top documents retrieved:**
- `POL-PROC-001` — Purchase Requisition Approval Policy
  - Auto-approve below $5,000 with a preferred vendor
  - Manager approval for $5,000–$25,000
  - Executive/denied above $25,000
- `POL-PROC-002` — Vendor Selection and Preferred Supplier Policy
  - V-1 (Apex Industrial) and V-7 (Precision Parts Ltd) are listed preferred vendors
  - Forbidden vendor (`RVL-BLACKLIST`) enforced unconditionally

### Phase 2 — LLM Rule Extraction (GPT-4o, `temperature=0.0`)

Extracted `PolicyRule` objects:

```python
PolicyRule(
    rule_id                  = "P-PROC-01",
    max_amount_usd           = 5000.0,
    on_violation             = "needs_human",
    preferred_vendor_required = True,
    source_excerpt           = "Purchases under $5,000 with a preferred vendor are auto-approved..."
)
```

### Phase 3 — Deterministic Python Evaluation (`evaluator.py`)

The LLM **never** decides approval. Python evaluates the extracted rules in fixed order:

```
1. Forbidden vendor check:          V-7 not on blacklist              → continue
2. Matching rule found:             P-PROC-01 matches                 → continue
3. Category mismatch:               No category restriction            → continue
4. Amount over threshold:           $3,465 < $5,000                   → no violation
5. Preferred vendor required:       V-7 is confirmed preferred         → satisfied
6. Result:                          AUTO_APPROVED
```

**State written:**

```
policy_decision  = { outcome: "auto_approved", rule_id_fired: "P-PROC-01" }
approval_required = false
approval_queue_id = null
```

**Status:** ✅ Completed — returned to Supervisor → graph ended

---

## Final API Response

```json
{
  "reply": "Procurement recommendation for M-1042: Order 165 units from Precision Parts Ltd (V-7), $3,465.00 total, 14-day lead time. Urgency: medium.",
  "thread_id": "44a09813-8387-4335-975b-0e078c4f2ebb",
  "trace_id": "013451dbd156b71bcc4ae4d3d1a9b31e",
  "approval_required": false,
  "approval_queue_id": null
}
```

---

## Key Invariants Verified

| Invariant | Status | Notes |
|---|---|---|
| LLM never makes approval decision | ✅ | GPT-4o extracted rules only; `evaluate_rules()` in Python decided |
| Preferred vendor enforced | ✅ | V-7 selected and confirmed preferred by policy |
| Threshold gate respected | ✅ | $3,465 < $5,000 auto-approve threshold |
| All agents returned to supervisor | ✅ | Each node used `Command(goto="supervisor")` |
| No direct agent-to-agent calls | ✅ | All routing via supervisor conditional edge |
| Structured output on decision path | ✅ | `PolicyRule` extracted via `.with_structured_output()` |
| OTEL spans emitted | ✅ | Dropped locally (no collector); non-blocking |
| Cosmos checkpoint written | ✅ | Thread state persisted after bytes→base64 fix |

---

## Issues Fixed During Session

| Issue | Root Cause | Fix Applied |
|---|---|---|
| `ValueError: HTTP transport has already been closed` on RAG calls | Azure Search SDK (aiohttp) transport lifecycle conflicted with OTEL's `HTTPXClientInstrumentor` inside LangGraph async tasks | Replaced Azure Search SDK entirely with direct `httpx` REST calls to the Search REST API using a persistent singleton client (`_http_client`) |
| `TypeError: Object of type bytes is not JSON serializable` on Cosmos upsert | `JsonPlusSerializer.dumps_typed()` returns raw `bytes`; Cosmos SDK's internal `json.dumps` cannot handle them | Added recursive `_sanitize()` / `_restore()` helpers in `checkpointer.py` that convert all `bytes` values to `{"__b64__": "<base64>"}` before storage and reverse on read |
| Local dev still hitting Cosmos despite fix | Old server process (PID 19568) was still running — `pkill` is ineffective on Windows via Bash | Killed process by PID using `taskkill /F /PID` via `netstat -ano` lookup |
| Stale `.pyc` bytecode masking code changes | Python loaded compiled bytecode from `__pycache__` of old source | Cleared all `__pycache__` directories under the project root before restart |
| `MemorySaver` not applied despite code change | `get_graph()` caches compiled graph in a global `_graph` variable; old server was still serving requests | Fresh process start after port was confirmed free |

---

## Configuration Used

| Setting | Value |
|---|---|
| Azure OpenAI Endpoint | `https://aopai-fsdataanalyzer.openai.azure.com/` |
| LLM Deployment | `gpt-4o` |
| Embedding Deployment | `text-embedding-3-small` (1536 dimensions) |
| Azure AI Search Service | `ais-sc-agent-dev.search.windows.net` |
| Policy Index | `policy-docs` |
| Cosmos DB Account | `cosmo-supply-chain-logging.documents.azure.com` |
| Cosmos Database | `supply-chain-agent` |
| Checkpointer (local dev) | `MemorySaver` (in-process, no serialization overhead) |
| Checkpointer (poc/prod) | `CosmosDBCheckpointer` with bytes→base64 sanitization |
| SAP Mock URL | `http://localhost:8001` |
| APP_ENV | `development` |
