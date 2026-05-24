"""
create_dashboards.py — Create all four Grafana Cloud dashboards via REST API.

Dashboards are defined as code here (no local JSON files in the repo).
Run after deploying a new version or when recreating a Grafana stack.

Usage:
    python create_dashboards.py

Requires in .env:
    GRAFANA_STACK_URL   — e.g. https://muthuraj1.grafana.net
    GRAFANA_SA_TOKEN    — service account token with Editor role
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

from dotenv import load_dotenv

load_dotenv(".env", override=True)

STACK_URL = os.getenv("GRAFANA_STACK_URL", "").rstrip("/")
SA_TOKEN  = os.getenv("GRAFANA_SA_TOKEN", "")

_DS_PROM = "grafanacloud-prom"
_DS_LOKI = "grafanacloud-logs"

JOB = "supply-chain-agent"
SVC = "supply-chain-agent"


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _req(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    url  = f"{STACK_URL}{path}"
    data = json.dumps(body).encode() if body else None
    req  = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Authorization": f"Bearer {SA_TOKEN}",
            "Content-Type":  "application/json",
            "Accept":        "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw.decode(errors="replace")}


def _resolve_datasources() -> tuple[str, str]:
    """Return (prom_uid, loki_uid) for this stack, falling back to canonical UIDs."""
    _, ds_list = _req("GET", "/api/datasources")
    slug = STACK_URL.split("//")[-1].split(".")[0]

    prom_uid = loki_uid = ""
    for ds in (ds_list if isinstance(ds_list, list) else []):
        t, uid, name = ds.get("type", ""), ds.get("uid", ""), ds.get("name", "")
        if uid in (_DS_PROM, _DS_LOKI):
            if t == "prometheus":
                prom_uid = uid
            elif t == "loki":
                loki_uid = uid
        elif slug in name:
            if t == "prometheus" and not prom_uid:
                prom_uid = uid
            elif t == "loki" and not loki_uid:
                loki_uid = uid
        else:
            if t == "prometheus" and not prom_uid:
                prom_uid = uid
            elif t == "loki" and not loki_uid:
                loki_uid = uid

    return prom_uid or _DS_PROM, loki_uid or _DS_LOKI


def _push(dash: dict) -> None:
    payload = {"dashboard": dash, "overwrite": True, "folderId": 0}
    status, resp = _req("POST", "/api/dashboards/db", payload)
    title = dash.get("title", "?")
    if status == 200:
        uid = resp.get("uid", "?")
        print(f"  [OK]  {title}")
        print(f"        {STACK_URL}/d/{uid}")
    else:
        print(f"  [FAIL] {title} — HTTP {status}: {resp}")


# ── Panel builders ────────────────────────────────────────────────────────────

def _prom(uid: str) -> dict:
    return {"type": "prometheus", "uid": uid}

def _loki(uid: str) -> dict:
    return {"type": "loki", "uid": uid}

def _pos(h: int, w: int, x: int, y: int) -> dict:
    return {"h": h, "w": w, "x": x, "y": y}

def _timeseries(pid: int, title: str, targets: list[dict], ds: dict, pos: dict,
                unit: str = "short") -> dict:
    return {
        "id": pid, "title": title, "type": "timeseries", "gridPos": pos,
        "datasource": ds,
        "fieldConfig": {"defaults": {"unit": unit}},
        "targets": targets,
    }

def _stat(pid: int, title: str, targets: list[dict], ds: dict, pos: dict,
          unit: str = "short", thresholds: list | None = None) -> dict:
    steps = thresholds or [{"color": "green", "value": None}]
    return {
        "id": pid, "title": title, "type": "stat", "gridPos": pos,
        "datasource": ds,
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "thresholds": {"mode": "absolute", "steps": steps},
            }
        },
        "options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "background"},
        "targets": targets,
    }

def _bargauge(pid: int, title: str, targets: list[dict], ds: dict, pos: dict,
              unit: str = "short") -> dict:
    return {
        "id": pid, "title": title, "type": "bargauge", "gridPos": pos,
        "datasource": ds,
        "fieldConfig": {"defaults": {"unit": unit}},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "orientation": "horizontal"},
        "targets": targets,
    }

def _logs(pid: int, title: str, expr: str, ds: dict, pos: dict) -> dict:
    return {
        "id": pid, "title": title, "type": "logs", "gridPos": pos,
        "datasource": ds,
        "options": {"showTime": True, "showLabels": True, "wrapLogMessage": True},
        "targets": [{"expr": expr, "refId": "A"}],
    }

def _target(expr: str, legend: str = "", ref: str = "A") -> dict:
    return {"expr": expr, "legendFormat": legend, "refId": ref}


# ── Dashboard 1: Operational ──────────────────────────────────────────────────

def operational_dashboard(prom_uid: str, loki_uid: str) -> dict:
    P = _prom(prom_uid)
    L = _loki(loki_uid)
    panels = [
        # Row 1 — HTTP traffic (our controlled metric, not auto-instrumented)
        _timeseries(1, "Request Rate per Endpoint", [
            _target(
                f'sum by (route) (rate(http_request_duration_seconds_count{{job="{JOB}"}}[$__rate_interval]))',
                "{{route}}",
            ),
        ], P, _pos(8, 12, 0, 0), unit="reqps"),

        _timeseries(2, "p50 / p95 / p99 Latency — /chat", [
            _target(
                f'histogram_quantile(0.50, sum by (le) (rate(http_request_duration_seconds_bucket{{job="{JOB}",route="/chat"}}[$__rate_interval])))',
                "p50", "A",
            ),
            _target(
                f'histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{{job="{JOB}",route="/chat"}}[$__rate_interval])))',
                "p95", "B",
            ),
            _target(
                f'histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket{{job="{JOB}",route="/chat"}}[$__rate_interval])))',
                "p99", "C",
            ),
        ], P, _pos(8, 12, 12, 0), unit="s"),

        # Row 2 — Workflow stats
        _stat(3, "Workflows In Progress", [
            _target(f'sum(workflows_in_progress{{job="{JOB}"}})', "In-flight"),
        ], P, _pos(4, 6, 0, 8),
            thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 5}, {"color": "red", "value": 10}]),

        _stat(4, "Human Review Queue Depth", [
            _target(f'human_review_queue_depth{{job="{JOB}"}}', "Pending"),
        ], P, _pos(4, 6, 6, 8),
            thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 20}, {"color": "red", "value": 50}]),

        _stat(5, "Workflow Duration P95 (s)", [
            _target(
                f'histogram_quantile(0.95, sum by (le) (rate(workflow_total_duration_seconds_bucket{{job="{JOB}"}}[$__rate_interval])))',
                "p95",
            ),
        ], P, _pos(4, 6, 12, 8), unit="s",
            thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 8}, {"color": "red", "value": 12}]),

        _stat(6, "Completed Workflows (rate)", [
            _target(
                f'sum(rate(workflow_requests_total{{job="{JOB}",status="completed"}}[$__rate_interval]))',
                "req/s",
            ),
        ], P, _pos(4, 6, 18, 8), unit="reqps"),

        # Row 3 — Agent performance
        _timeseries(7, "Agent Execution Duration P95 (s)", [
            _target(
                f'histogram_quantile(0.95, sum by (le, agent_name) (rate(agent_execution_duration_seconds_bucket{{job="{JOB}"}}[$__rate_interval])))',
                "{{agent_name}}",
            ),
        ], P, _pos(8, 12, 0, 12), unit="s"),

        _bargauge(8, "Supervisor Routing — Calls per Agent", [
            _target(
                f'sum by (next_agent) (increase(supervisor_routing_total{{job="{JOB}"}}[$__rate_interval]))',
                "{{next_agent}}",
            ),
        ], P, _pos(8, 12, 12, 12)),

        # Row 4 — LLM cost & tokens
        _timeseries(9, "LLM Tokens per Agent (rate)", [
            _target(
                f'sum by (agent_name, token_type) (rate(llm_tokens_consumed_total{{job="{JOB}"}}[$__rate_interval]))',
                "{{agent_name}} / {{token_type}}",
            ),
        ], P, _pos(8, 12, 0, 20), unit="short"),

        _timeseries(10, "Estimated LLM Cost per Agent (USD / h)", [
            _target(
                f'sum by (agent_name) (rate(llm_estimated_cost_usd_USD{{job="{JOB}"}}[$__rate_interval])) * 3600',
                "{{agent_name}}",
            ),
        ], P, _pos(8, 12, 12, 20), unit="currencyUSD"),

        # Row 5 — Domain business metrics
        _timeseries(11, "Procurement Recommendations by Urgency", [
            _target(
                f'sum by (urgency) (rate(procurement_recommendations_total{{job="{JOB}"}}[$__rate_interval]))',
                "{{urgency}}",
            ),
        ], P, _pos(8, 12, 0, 28), unit="reqps"),

        _timeseries(12, "Inventory Safety Stock Violations by Material", [
            _target(
                f'sum by (material_id) (increase(inventory_below_safety_stock_total{{job="{JOB}"}}[$__rate_interval]))',
                "{{material_id}}",
            ),
        ], P, _pos(8, 12, 12, 28)),

        # Row 6 — RAG quality & tool error rate
        _stat(13, "RAG Retrieval Score P50", [
            _target(
                f'histogram_quantile(0.50, sum by (le) (rate(rag_retrieval_score_bucket{{job="{JOB}"}}[$__rate_interval])))',
                "p50",
            ),
        ], P, _pos(4, 6, 0, 36),
            thresholds=[{"color": "red", "value": None}, {"color": "orange", "value": 0.5}, {"color": "green", "value": 0.75}]),

        _stat(14, "RAG Retrieval Score P95", [
            _target(
                f'histogram_quantile(0.95, sum by (le) (rate(rag_retrieval_score_bucket{{job="{JOB}"}}[$__rate_interval])))',
                "p95",
            ),
        ], P, _pos(4, 6, 6, 36),
            thresholds=[{"color": "red", "value": None}, {"color": "orange", "value": 0.6}, {"color": "green", "value": 0.85}]),

        _timeseries(15, "Tool Error Rate", [
            _target(
                f'sum(rate({{service_name="{SVC}",severity_text="ERROR"}}[$__interval])) / sum(rate({{service_name="{SVC}"}}[$__interval]))',
                "error rate",
            ),
        ], L, _pos(4, 12, 12, 36), unit="percentunit"),
    ]
    return {
        "title": "Supply Chain — Operational",
        "uid": "sc-operational",
        "tags": ["supply-chain", "operational"],
        "time": {"from": "now-1h", "to": "now"},
        "refresh": "30s",
        "panels": panels,
    }


# ── Dashboard 2: Governance ───────────────────────────────────────────────────

def governance_dashboard(prom_uid: str, loki_uid: str) -> dict:
    P = _prom(prom_uid)
    L = _loki(loki_uid)
    panels = [
        # Row 1 — KPI stats
        _stat(1, "Compliance Checks Total (24 h)", [
            _target(f'sum(increase(compliance_checks_total{{job="{JOB}"}}[24h]))', "checks"),
        ], P, _pos(4, 6, 0, 0)),

        _stat(2, "Auto-Approval Rate (24 h)", [
            _target(
                f'sum(increase(compliance_checks_total{{job="{JOB}",outcome="auto_approved"}}[24h])) / sum(increase(compliance_checks_total{{job="{JOB}"}}[24h]))',
                "%",
            ),
        ], P, _pos(4, 6, 6, 0), unit="percentunit",
            thresholds=[{"color": "red", "value": None}, {"color": "orange", "value": 0.5}, {"color": "green", "value": 0.8}]),

        _stat(3, "Flags Requiring Human Review (24 h)", [
            _target(f'sum(increase(compliance_flags_requiring_review_total{{job="{JOB}"}}[24h]))', "flags"),
        ], P, _pos(4, 6, 12, 0),
            thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 5}, {"color": "red", "value": 20}]),

        _stat(4, "Audit Records Written (24 h)", [
            _target(f'sum(increase(audit_records_written_total{{job="{JOB}"}}[24h]))', "records"),
        ], P, _pos(4, 6, 18, 0)),

        # Row 2 — Decision trends
        _timeseries(5, "Policy Decision Outcomes Over Time", [
            _target(
                f'sum by (outcome) (rate(compliance_checks_total{{job="{JOB}"}}[$__rate_interval]))',
                "{{outcome}}",
            ),
        ], P, _pos(8, 12, 0, 4), unit="reqps"),

        _bargauge(6, "Rule Firing Frequency (24 h)", [
            _target(
                f'sum by (rule_id) (increase(compliance_flags_requiring_review_total{{job="{JOB}"}}[24h]))',
                "{{rule_id}}",
            ),
        ], P, _pos(8, 12, 12, 4)),

        # Row 3 — Approval cycle (FIXED: underscore metric name)
        _timeseries(7, "Approval Cycle Time P50 / P95 (s)", [
            _target(
                f'histogram_quantile(0.50, sum by (le) (rate(approval_cycle_duration_seconds_bucket{{job="{JOB}"}}[$__rate_interval])))',
                "p50", "A",
            ),
            _target(
                f'histogram_quantile(0.95, sum by (le) (rate(approval_cycle_duration_seconds_bucket{{job="{JOB}"}}[$__rate_interval])))',
                "p95", "B",
            ),
        ], P, _pos(8, 12, 0, 12), unit="s"),

        _timeseries(8, "Human Review Queue Depth", [
            _target(f'human_review_queue_depth{{job="{JOB}"}}', "pending"),
        ], P, _pos(8, 12, 12, 12)),

        # Row 4 — Procurement & forecast quality
        _timeseries(9, "Procurement Recommendations by Urgency", [
            _target(
                f'sum by (urgency) (rate(procurement_recommendations_total{{job="{JOB}"}}[$__rate_interval]))',
                "{{urgency}}",
            ),
        ], P, _pos(8, 12, 0, 20), unit="reqps"),

        _timeseries(10, "Forecast Confidence Range P50 (units)", [
            _target(
                f'histogram_quantile(0.50, sum by (le) (rate(forecast_confidence_range_units_bucket{{job="{JOB}"}}[$__rate_interval])))',
                "p50 band width",
            ),
        ], P, _pos(8, 12, 12, 20)),

        # Row 5 — Audit log stream
        _logs(11, "Policy Decision Audit Trail",
              f'{{service_name="{SVC}", scope="policy"}}',
              L, _pos(12, 24, 0, 28)),
    ]
    return {
        "title": "Supply Chain — Governance",
        "uid": "sc-governance",
        "tags": ["supply-chain", "governance"],
        "time": {"from": "now-24h", "to": "now"},
        "refresh": "1m",
        "panels": panels,
    }


# ── Dashboard 3: Logs & Traces ────────────────────────────────────────────────

def logs_traces_dashboard(loki_uid: str) -> dict:
    L = _loki(loki_uid)
    panels = [
        _logs(1, "Live Application Logs",
              f'{{service_name="{SVC}"}}',
              L, _pos(10, 24, 0, 0)),

        _logs(2, "Error Logs",
              f'{{service_name="{SVC}"}} |= "ERROR"',
              L, _pos(8, 12, 0, 10)),

        _logs(3, "Approval Queue Events",
              f'{{service_name="{SVC}", scope="approval"}}',
              L, _pos(8, 12, 12, 10)),

        _logs(4, "LLM Call Logs",
              f'{{service_name="{SVC}"}} |= "llm.call"',
              L, _pos(8, 12, 0, 18)),

        _logs(5, "Supervisor Routing Decisions",
              f'{{service_name="{SVC}"}} |= "supervisor"',
              L, _pos(8, 12, 12, 18)),
    ]
    return {
        "title": "Supply Chain — Logs & Traces",
        "uid": "sc-logs-traces",
        "tags": ["supply-chain", "logs"],
        "time": {"from": "now-1h", "to": "now"},
        "refresh": "30s",
        "panels": panels,
    }


# ── Dashboard 4: Executive Summary ────────────────────────────────────────────

def executive_dashboard(prom_uid: str, loki_uid: str) -> dict:
    P = _prom(prom_uid)
    panels = [
        # Row 1 — Top-level KPI stats
        _stat(1, "Requests Today", [
            _target(f'sum(increase(http_request_duration_seconds_count{{job="{JOB}"}}[24h]))', "total"),
        ], P, _pos(4, 6, 0, 0)),

        _stat(2, "LLM Cost Today (USD)", [
            _target(f'sum(increase(llm_estimated_cost_usd_USD{{job="{JOB}"}}[24h]))', "USD"),
        ], P, _pos(4, 6, 6, 0), unit="currencyUSD"),

        _stat(3, "Approval Queue Depth", [
            _target(f'human_review_queue_depth{{job="{JOB}"}}', "pending"),
        ], P, _pos(4, 6, 12, 0),
            thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 10}, {"color": "red", "value": 30}]),

        _stat(4, "Auto-Approval Rate (24 h)", [
            _target(
                f'sum(increase(compliance_checks_total{{job="{JOB}",outcome="auto_approved"}}[24h])) / sum(increase(compliance_checks_total{{job="{JOB}"}}[24h]))',
                "%",
            ),
        ], P, _pos(4, 6, 18, 0), unit="percentunit",
            thresholds=[{"color": "red", "value": None}, {"color": "orange", "value": 0.5}, {"color": "green", "value": 0.8}]),

        # Row 2 — Trend lines
        _timeseries(5, "Request Throughput (24 h)", [
            _target(
                f'sum(rate(http_request_duration_seconds_count{{job="{JOB}"}}[$__rate_interval]))',
                "req/s",
            ),
        ], P, _pos(8, 12, 0, 4), unit="reqps"),

        _timeseries(6, "LLM Cost Trend by Agent (USD/h)", [
            _target(
                f'sum by (agent_name) (rate(llm_estimated_cost_usd_USD{{job="{JOB}"}}[$__rate_interval])) * 3600',
                "{{agent_name}}",
            ),
        ], P, _pos(8, 12, 12, 4), unit="currencyUSD"),

        # Row 3 — Workflow health
        _timeseries(7, "Workflow Success Rate", [
            _target(
                f'sum(rate(workflow_requests_total{{job="{JOB}",status="completed"}}[$__rate_interval])) / sum(rate(workflow_requests_total{{job="{JOB}"}}[$__rate_interval]))',
                "success rate",
            ),
        ], P, _pos(8, 12, 0, 12), unit="percentunit"),

        _timeseries(8, "Approval Cycle Time P50 (s)", [
            _target(
                f'histogram_quantile(0.50, sum by (le) (rate(approval_cycle_duration_seconds_bucket{{job="{JOB}"}}[$__rate_interval])))',
                "p50",
            ),
        ], P, _pos(8, 12, 12, 12), unit="s"),

        # Row 4 — Agent & domain detail
        _timeseries(9, "Agent Routing — Calls Over Time", [
            _target(
                f'sum by (next_agent) (rate(supervisor_routing_total{{job="{JOB}"}}[$__rate_interval]))',
                "{{next_agent}}",
            ),
        ], P, _pos(8, 12, 0, 20), unit="reqps"),

        _timeseries(10, "Procurement Recommendations (24 h)", [
            _target(
                f'sum by (urgency) (increase(procurement_recommendations_total{{job="{JOB}"}}[$__rate_interval]))',
                "{{urgency}}",
            ),
        ], P, _pos(8, 12, 12, 20)),
    ]
    return {
        "title": "Supply Chain — Executive Summary",
        "uid": "sc-executive",
        "tags": ["supply-chain", "executive"],
        "time": {"from": "now-24h", "to": "now"},
        "refresh": "5m",
        "panels": panels,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    if not STACK_URL or not SA_TOKEN:
        print("ERROR: set GRAFANA_STACK_URL and GRAFANA_SA_TOKEN in .env")
        return 1

    print(f"\n{'='*60}")
    print("  SUPPLY CHAIN — CREATE GRAFANA DASHBOARDS")
    print(f"{'='*60}\n")

    status, user = _req("GET", "/api/user")
    if status != 200:
        print(f"ERROR: auth failed — HTTP {status}: {user}")
        return 1
    print(f"  Authenticated as: {user.get('name', '?')} ({user.get('email', '?')})")

    prom_uid, loki_uid = _resolve_datasources()
    print(f"  Prometheus UID : {prom_uid}")
    print(f"  Loki UID       : {loki_uid}\n")

    dashboards = [
        operational_dashboard(prom_uid, loki_uid),
        governance_dashboard(prom_uid, loki_uid),
        logs_traces_dashboard(loki_uid),
        executive_dashboard(prom_uid, loki_uid),
    ]

    for dash in dashboards:
        _push(dash)

    print(f"\n  Open: {STACK_URL}/dashboards\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
