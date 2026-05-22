# ADR-001: LangGraph for multi-agent orchestration

**Date:** 2025-05-01  
**Status:** Accepted

## Context

The POC requires a supervisor that routes work across six specialist agents, persists
in-flight state across HTTP requests (for human-in-the-loop approval), and can pause
and resume a workflow after an external event (human approves or rejects a proposal).

Candidates evaluated:

| Framework | State persistence | Interrupt/resume | Cosmos checkpointer |
|---|---|---|---|
| LangGraph | Built-in (checkpointer) | `interrupt()` primitive | First-class support |
| AutoGen | Agent memory only | Not native | Custom |
| CrewAI | Not native | Not native | Custom |
| Custom Python | Roll your own | Roll your own | Roll your own |

## Decision

Use **LangGraph** as the sole orchestration layer. The graph is a single
`StateGraph` compiled once at startup; all agents are nodes. Specialist agents
return `Command(goto="supervisor")` so the supervisor controls every routing
decision. State is checkpointed to Cosmos DB after each node execution.

## Consequences

- `interrupt()` + `Command(resume=...)` gives human-in-the-loop approval with zero
  custom queue code — the graph simply pauses mid-node and resumes when the
  `/approvals/{id}/decide` endpoint calls `graph.ainvoke(Command(resume=...))`.
- The single-graph topology means one Cosmos checkpoint document per conversation
  thread; no fan-out coordination needed.
- Specialist agents cannot call each other directly — they must route through the
  supervisor. This is enforced by convention (§3.1) and tested in the integration suite.
- Upgrading LangGraph is a minor risk: the `Command` API stabilised in 0.2.x; pin
  to `>=0.2.0` and review the changelog on each bump.
