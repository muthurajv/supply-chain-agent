# ADR-003: SAP mock adapter pattern — HTTP client behind a tool wrapper

**Date:** 2025-05-01  
**Status:** Accepted

## Context

The POC cannot connect to a real SAP S/4HANA instance. However, the transition
from mock to real SAP must be achievable without touching agent code, because
the six specialist agents are being built in parallel with the SAP integration
work stream.

Options considered:

1. **Inline mocks**: agent nodes call Python functions that return hardcoded data.
2. **HTTP adapter**: a separate `sap-mock` FastAPI service returns the same JSON
   shapes that the real SAP OData adapter will return; agents call it through
   `app/tools/sap_tools.py`.
3. **SQLite in-process**: fixture data loaded into SQLite, queried via SQLAlchemy.

## Decision

Use **option 2**: a standalone `sap_mock` FastAPI service backed by JSON fixtures.
All agent nodes access SAP data exclusively through `app/tools/sap_tools.py`, which
calls the mock service over HTTP. The base URL is `SAP_MOCK_BASE_URL` in config.

The real SAP adapter (out of scope for POC, per §1) will be a drop-in replacement
at `SAP_MOCK_BASE_URL` — same routes, same response shapes, different backing system.

## Consequences

- Swapping to real SAP requires changing one config value (`SAP_MOCK_BASE_URL`).
  No agent code changes.
- The `sap_mock` service is deployed as its own K8s Deployment (ClusterIP only,
  not exposed externally) so it can be replaced by a real SAP gateway service.
- Tool calls must always go through `app/tools/sap_tools.py`. Direct HTTP calls
  from agent nodes are forbidden (§5.3 and §15.6). The integration tests verify
  this by running against the live mock service.
- Adding a new SAP endpoint requires: a new route in `sap_mock/routes/`, a new
  fixture in `sap_mock/fixtures/`, a new function in `app/tools/sap_tools.py`,
  and a contract test that validates the response against the Pydantic model.
