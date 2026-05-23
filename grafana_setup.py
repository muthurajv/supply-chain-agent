"""
grafana_setup.py — Verify Grafana Cloud stack and create a service account token.

Dashboards are managed directly in Grafana Cloud (not stored in this repo).
All credentials must be set in .env — never pass tokens on the command line in CI.

Usage:
    # Verify the stack is reachable and Loki data is flowing
    python grafana_setup.py check

    # Create a service account + token (requires an admin token in .env)
    python grafana_setup.py create-token
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env", override=True)

# ── Config ────────────────────────────────────────────────────────────────────

STACK_URL = os.getenv("GRAFANA_STACK_URL", "")
API_KEY   = os.getenv("GRAFANA_API_KEY", "")
LOKI_USER = os.getenv("GRAFANA_LOKI_USERNAME", "")
LOKI_PASS = os.getenv("GRAFANA_LOKI_PASSWORD", "")

SA_NAME       = "supply-chain-dashboard-importer"
SA_TOKEN_NAME = "supply-chain-import-token"


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _request(method: str, path: str, token: str, body: dict | None = None) -> tuple[int, dict]:
    url = f"{STACK_URL.rstrip('/')}{path}"
    data = json.dumps(body).encode() if body else None
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
        "Accept":        "application/json",
    }
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body_bytes = exc.read()
        try:
            return exc.code, json.loads(body_bytes)
        except Exception:
            return exc.code, {"raw": body_bytes.decode(errors="replace")}


def _loki_check() -> bool:
    """Return True if recent supply-chain-agent logs exist in Loki."""
    loki_url = os.getenv("GRAFANA_LOKI_ENDPOINT", "")
    if not loki_url or not LOKI_USER:
        return False
    auth = base64.b64encode(f"{LOKI_USER}:{API_KEY}".encode()).decode()
    now_ns = int(time.time() * 1e9)
    start  = now_ns - int(3600 * 1e9)
    import urllib.parse
    p = urllib.parse.urlencode({
        "query": '{service_name="supply-chain-agent"}',
        "start": str(start), "end": str(now_ns), "limit": "1",
    })
    req = urllib.request.Request(
        f"{loki_url}/loki/api/v1/query_range?{p}",
        headers={"Authorization": f"Basic {auth}"},
    )
    try:
        result = json.loads(urllib.request.urlopen(req, timeout=10).read())
        return len(result.get("data", {}).get("result", [])) > 0
    except Exception:
        return False


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_check(_args) -> int:
    print(f"\n{'='*60}")
    print("  GRAFANA STACK HEALTH CHECK")
    print(f"{'='*60}\n")

    if not STACK_URL:
        print("ERROR: GRAFANA_STACK_URL not set in .env")
        return 1

    print(f"  Stack URL : {STACK_URL}")
    try:
        req = urllib.request.Request(f"{STACK_URL}/api/health")
        with urllib.request.urlopen(req, timeout=10) as resp:
            info = json.loads(resp.read())
        print(f"  Status    : OK  (Grafana {info.get('version', '?')})")
    except Exception as exc:
        print(f"  Status    : UNREACHABLE — {exc}")
        return 1

    print(f"\n  Checking Loki telemetry data…")
    if _loki_check():
        print("  Loki      : OK  (supply-chain-agent logs present)")
    else:
        print("  Loki      : WARNING — no recent logs found (is the app running?)")

    print(f"\n  Dashboards are managed in Grafana Cloud — open {STACK_URL}\n")
    return 0


def cmd_create_token(args) -> int:
    admin_token = os.getenv("GRAFANA_SA_TOKEN", "")
    if not admin_token:
        print("ERROR: set GRAFANA_SA_TOKEN in .env (needs admin role)")
        return 1
    if not STACK_URL:
        print("ERROR: set GRAFANA_STACK_URL in .env")
        return 1

    print(f"\n  Creating service account '{SA_NAME}'…")

    status, resp = _request("POST", "/api/serviceaccounts", admin_token, {
        "name": SA_NAME, "role": "Editor", "isDisabled": False,
    })
    if status == 201:
        sa_id = resp["id"]
        print(f"  Created SA  id={sa_id}")
    elif status in (200, 409):
        _, list_resp = _request(
            "GET", f"/api/serviceaccounts/search?query={SA_NAME}", admin_token
        )
        sas = list_resp.get("serviceAccounts", [])
        if not sas:
            print(f"ERROR: SA exists but couldn't be found: {resp}")
            return 1
        sa_id = sas[0]["id"]
        print(f"  SA exists   id={sa_id}")
    else:
        print(f"ERROR: {status} — {resp}")
        return 1

    status, tok_resp = _request(
        "POST", f"/api/serviceaccounts/{sa_id}/tokens", admin_token,
        {"name": SA_TOKEN_NAME},
    )
    if status not in (200, 201):
        print(f"ERROR creating token: {status} — {tok_resp}")
        return 1

    token = tok_resp["key"]
    print(f"\n  Token created (shown once only):")
    print(f"  {token}")
    print(f"\n  Add to .env:  GRAFANA_SA_TOKEN={token}\n")
    return 0


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawTextHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("check", help="Verify stack reachability and Loki data")
    sub.add_parser("create-token", help="Create Grafana service account + token")

    args = parser.parse_args()
    dispatch = {
        "check":        cmd_check,
        "create-token": cmd_create_token,
    }
    fn = dispatch.get(args.command)
    if fn is None:
        parser.print_help()
        return 1
    return fn(args)


if __name__ == "__main__":
    sys.exit(main())
