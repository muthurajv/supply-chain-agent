# ADR-004: Cosmos DB for LangGraph state checkpointing and approval queue

**Date:** 2025-05-01  
**Status:** Accepted

## Context

LangGraph requires a checkpointer to persist graph state across node executions and
across HTTP requests (essential for interrupt/resume). The approval queue must survive
pod restarts — a paused graph could wait hours for a human decision.

Storage options evaluated:

| Option | Durability | LangGraph support | Ops overhead |
|---|---|---|---|
| In-memory | None (pod restart loses state) | Built-in | None |
| Redis | Moderate (AOF) | Community | Deploy + manage |
| PostgreSQL | High | Community | Deploy + manage |
| Cosmos DB (NoSQL) | High (geo-redundant) | First-class in LangGraph | Managed by Azure |

The project already mandates Azure (§2). Cosmos DB serverless eliminates capacity
planning for a POC with unpredictable traffic.

## Decision

Use **Cosmos DB NoSQL** for both the LangGraph checkpointer
(`app/memory/checkpointer.py`) and the approval queue. Three containers:

| Container | Purpose |
|---|---|
| `checkpoints` | LangGraph state snapshots (one doc per thread/checkpoint) |
| `kpis` | Pre-computed KPI rows for the analytics read path |
| `approval-queue` | Human approval proposals; status transitions pending→approved/rejected |

Partition key is the document `id` for all three containers.

## Consequences

- A paused graph survives pod restarts, redeployments, and node failures because
  the full `GraphState` is serialised to Cosmos after each node.
- The approval queue is queryable by status (`SELECT * FROM c WHERE c.status='pending'`)
  without a separate database; no message broker required for the POC.
- `CosmosDBCheckpointer` must only serialise JSON-safe types. Non-serialisable state
  fields (e.g. raw LLM objects) must be converted before storing (§3.4 invariant).
- Cosmos free-tier RU/s (1000 RU/s shared) is sufficient for the POC. The
  `cosmos-throttled.md` runbook covers RU scaling if the POC load exceeds this.
- Integration tests use a real Cosmos emulator (or the live dev account) — no
  in-memory fake — to catch serialisation issues before deployment (§8.3).
