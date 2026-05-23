"""
grafana_setup.py — Check Grafana stack, create service account token, and import dashboards.

Usage:
    # Step 1 — check the stack is reachable
    python grafana_setup.py check

    # Step 2 — create a service account + token (requires admin token)
    python grafana_setup.py create-token --admin-token glsa_xxx

    # Step 3 — import all three dashboards (requires SA token with Editor role)
    python grafana_setup.py import-dashboards --token glsa_xxx

    # All steps in one go
    python grafana_setup.py all --admin-token glsa_xxx
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

STACK_URL   = os.getenv("GRAFANA_STACK_URL", "https://muthuraj1.grafana.net")
API_KEY     = os.getenv("GRAFANA_API_KEY", "")
LOKI_USER   = os.getenv("GRAFANA_LOKI_USERNAME", "")
LOKI_PASS   = os.getenv("GRAFANA_LOKI_PASSWORD", "")
DASHBOARDS  = Path("grafana/dashboards")

SA_NAME     = "supply-chain-dashboard-importer"
SA_TOKEN_NAME = "supply-chain-import-token"

DATASOURCE_MAP = {
    "DS_PROMETHEUS": {"type": "prometheus", "name": "grafanacloud-prom"},
    "DS_LOKI":       {"type": "loki",       "name": "grafanacloud-logs"},
}


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
    """Verify Loki data is flowing using the ingest key."""
    loki_url = os.getenv("GRAFANA_LOKI_ENDPOINT", "")
    if not loki_url or not LOKI_USER:
        return False
    auth = base64.b64encode(f"{LOKI_USER}:{API_KEY}".encode()).decode()
    now_ns  = int(time.time() * 1e9)
    start   = now_ns - int(3600 * 1e9)
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
        streams = result.get("data", {}).get("result", [])
        return len(streams) > 0
    except Exception:
        return False


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_check(_args) -> int:
    print(f"\n{'='*60}")
    print("  GRAFANA STACK HEALTH CHECK")
    print(f"{'='*60}\n")

    # 1. Stack reachability
    print(f"  Stack URL : {STACK_URL}")
    try:
        req = urllib.request.Request(f"{STACK_URL}/api/health")
        with urllib.request.urlopen(req, timeout=10) as resp:
            info = json.loads(resp.read())
        print(f"  Status    : OK  (Grafana {info.get('version', '?')})")
    except Exception as exc:
        print(f"  Status    : UNREACHABLE — {exc}")
        return 1

    # 2. Loki data
    print(f"\n  Checking Loki telemetry data…")
    if _loki_check():
        print("  Loki      : OK  (supply-chain-agent logs present)")
    else:
        print("  Loki      : WARNING — no recent logs found")

    print(f"\n  To import dashboards you need a Grafana Service Account token")
    print(f"  with Editor role. Create one at:")
    print(f"  {STACK_URL}/org/serviceaccounts")
    print(f"  Then run:  python grafana_setup.py import-dashboards --token glsa_xxx\n")
    return 0


def cmd_create_token(args) -> int:
    admin_token = args.admin_token or os.getenv("GRAFANA_SA_TOKEN", "")
    if not admin_token:
        print("ERROR: provide --admin-token or set GRAFANA_SA_TOKEN in .env")
        return 1

    print(f"\n  Creating service account '{SA_NAME}'…")

    # Create or find service account
    status, resp = _request("POST", "/api/serviceaccounts", admin_token, {
        "name": SA_NAME, "role": "Editor", "isDisabled": False,
    })
    if status == 201:
        sa_id = resp["id"]
        print(f"  Created SA  id={sa_id}")
    elif status == 200:
        sa_id = resp["id"]
        print(f"  SA exists   id={sa_id}")
    elif status == 409:
        # Already exists — find it
        _, list_resp = _request("GET", "/api/serviceaccounts/search?query=" + SA_NAME, admin_token)
        sas = list_resp.get("serviceAccounts", [])
        if not sas:
            print(f"ERROR: SA exists but couldn't find it: {resp}")
            return 1
        sa_id = sas[0]["id"]
        print(f"  SA exists   id={sa_id}")
    else:
        print(f"ERROR: {status} — {resp}")
        return 1

    # Create token
    status, tok_resp = _request("POST", f"/api/serviceaccounts/{sa_id}/tokens", admin_token, {
        "name": SA_TOKEN_NAME,
    })
    if status not in (200, 201):
        print(f"ERROR creating token: {status} — {tok_resp}")
        return 1

    token = tok_resp["key"]
    print(f"\n  Service Account Token (save this — shown only once):")
    print(f"  {token}")
    print(f"\n  Add to .env:  GRAFANA_SA_TOKEN={token}")
    print(f"  Then run:     python grafana_setup.py import-dashboards --token {token}\n")
    return 0


def cmd_import_dashboards(args) -> int:
    token = args.token or os.getenv("GRAFANA_SA_TOKEN", "")
    if not token:
        print("ERROR: provide --token or set GRAFANA_SA_TOKEN in .env")
        return 1

    # Verify auth first
    status, user = _request("GET", "/api/user", token)
    if status == 401:
        print(f"ERROR: 401 Unauthorized. Token invalid or expired.")
        return 1
    if status != 200:
        print(f"ERROR: {status} — {user}")
        return 1
    print(f"\n  Authenticated as: {user.get('name', '?')} ({user.get('email', '?')})")

    # Find datasource UIDs
    _, ds_list = _request("GET", "/api/datasources", token)
    ds_by_type: dict[str, str] = {}
    if isinstance(ds_list, list):
        for ds in ds_list:
            ds_by_type[ds.get("type", "")] = ds.get("uid", "")
    print(f"  Datasources found: {list(ds_by_type.keys())}")

    dashboard_files = sorted(DASHBOARDS.glob("*.json"))
    if not dashboard_files:
        print(f"ERROR: no dashboard JSON files found in {DASHBOARDS}")
        return 1

    results = []
    for path in dashboard_files:
        dash = json.loads(path.read_text())

        # Resolve __inputs datasource variables
        input_map: dict[str, str] = {}
        for inp in dash.get("__inputs", []):
            var_name  = inp["name"]          # e.g. "DS_LOKI"
            ds_type   = inp.get("pluginId", inp.get("type", ""))
            uid_override = ds_by_type.get(ds_type, "")
            input_map[f"${{{var_name}}}"] = uid_override or inp.get("value", "")

        # Apply substitutions recursively in the dashboard JSON
        dash_str = json.dumps(dash)
        for placeholder, uid in input_map.items():
            dash_str = dash_str.replace(placeholder, uid)
        dash_resolved = json.loads(dash_str)

        # Strip __inputs / __requires — not accepted by the API
        dash_resolved.pop("__inputs", None)
        dash_resolved.pop("__requires", None)
        dash_resolved["id"] = None  # let Grafana assign

        payload = {"dashboard": dash_resolved, "overwrite": True, "folderId": 0}
        status, resp = _request("POST", "/api/dashboards/db", token, payload)

        if status == 200:
            uid   = resp.get("uid", "?")
            title = dash_resolved.get("title", path.name)
            url   = f"{STACK_URL}/d/{uid}"
            print(f"  [OK]  {title}")
            print(f"        {url}")
            results.append((title, url))
        else:
            print(f"  [FAIL] {path.name} — HTTP {status}: {resp}")

    if results:
        print(f"\n  {'='*56}")
        print("  DASHBOARD LINKS")
        print(f"  {'='*56}")
        for title, url in results:
            print(f"  {title}")
            print(f"  {url}")
        print()
    return 0


def cmd_all(args) -> int:
    rc = cmd_check(args)
    if rc:
        return rc
    rc = cmd_create_token(args)
    if rc:
        return rc
    # re-parse token from env in case create-token set it
    args.token = os.getenv("GRAFANA_SA_TOKEN", args.admin_token)
    return cmd_import_dashboards(args)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("check", help="Verify stack reachability and Loki data")

    p_tok = sub.add_parser("create-token", help="Create Grafana service account + token")
    p_tok.add_argument("--admin-token", default="", help="Admin service account token (glsa_...)")

    p_imp = sub.add_parser("import-dashboards", help="Import all three dashboard JSONs")
    p_imp.add_argument("--token", default="", help="Service account token with Editor role")

    p_all = sub.add_parser("all", help="Check + create-token + import-dashboards")
    p_all.add_argument("--admin-token", default="", help="Admin service account token (glsa_...)")
    p_all.add_argument("--token", default="", help="Override token for import step")

    args = parser.parse_args()

    dispatch = {
        "check":             cmd_check,
        "create-token":      cmd_create_token,
        "import-dashboards": cmd_import_dashboards,
        "all":               cmd_all,
    }

    fn = dispatch.get(args.command)
    if fn is None:
        parser.print_help()
        return 1
    return fn(args)


if __name__ == "__main__":
    sys.exit(main())
