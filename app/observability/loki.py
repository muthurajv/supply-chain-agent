"""Direct Loki push for governance audit records.

Complements the OTEL log pipeline: these records carry rich Loki labels
(policy_outcome, rule_id, scope) that enable label-based Grafana queries
and live log panel streams without requiring a Tempo trace lookup.

Silently no-ops when GRAFANA_LOKI_ENDPOINT is unset so local dev is
unaffected. Never raises — a Loki push failure must not interrupt the agent.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from app.config import get_settings

_log = logging.getLogger("supply_chain_agent.loki")


def _loki_enabled() -> bool:
    s = get_settings()
    return bool(s.grafana_loki_endpoint and s.grafana_loki_username and s.grafana_loki_password)


def _push_url() -> str:
    return get_settings().grafana_loki_endpoint.rstrip("/") + "/loki/api/v1/push"


def _auth() -> tuple[str, str]:
    s = get_settings()
    return s.grafana_loki_username, s.grafana_loki_password


async def push_policy_audit(
    *,
    agent_name: str,
    policy_outcome: str,
    rule_id: str | None,
    amount_usd: float | None,
    threshold_usd: float | None,
    explanation: str,
    proposal_id: str,
    material_id: str | None = None,
    vendor_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Push a policy decision audit record directly to Loki.

    Labels kept small (low cardinality). Full detail goes in the JSON value
    so it is searchable via LogQL `| json` filters in Grafana.
    """
    if not _loki_enabled():
        return

    record: dict[str, Any] = {
        "event": "policy.decision",
        "agent_name": agent_name,
        "policy_outcome": policy_outcome,
        "rule_id": rule_id,
        "amount_usd": amount_usd,
        "threshold_usd": threshold_usd,
        "explanation": explanation,
        "proposal_id": proposal_id,
        "material_id": material_id,
        "vendor_id": vendor_id,
    }
    if extra:
        record.update(extra)

    labels = {
        "service_name": "supply-chain-agent",
        "scope": "policy",
        "agent_name": agent_name,
        "policy_outcome": policy_outcome,
    }
    if rule_id:
        labels["rule_id"] = rule_id

    await _push(labels, record)


async def push_approval_audit(
    *,
    approval_id: str,
    decision: str,
    decided_by: str = "human",
    cycle_seconds: float | None = None,
    reason: str = "",
) -> None:
    """Push a human-approval decision record to Loki."""
    if not _loki_enabled():
        return

    record: dict[str, Any] = {
        "event": "approval.decision",
        "approval_id": approval_id,
        "decision": decision,
        "decided_by": decided_by,
        "cycle_seconds": cycle_seconds,
        "reason": reason,
    }
    labels = {
        "service_name": "supply-chain-agent",
        "scope": "approval",
        "decision": decision,
    }

    await _push(labels, record)


async def _push(labels: dict[str, str], record: dict[str, Any]) -> None:
    payload = {
        "streams": [{
            "stream": labels,
            "values": [[str(int(time.time() * 1e9)), json.dumps(record)]],
        }]
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                _push_url(),
                json=payload,
                auth=_auth(),
            )
            resp.raise_for_status()
    except Exception as exc:
        # Log but never propagate — observability must not break the main path.
        _log.warning("loki push failed: %s", exc)
