import os, base64, json, urllib.request, urllib.parse, time
from collections import Counter
from dotenv import load_dotenv
load_dotenv('.env', override=True)

loki_url  = os.getenv('GRAFANA_LOKI_ENDPOINT')
loki_user = os.getenv('GRAFANA_LOKI_USERNAME')
api_key   = os.getenv('GRAFANA_API_KEY')
auth = base64.b64encode(f'{loki_user}:{api_key}'.encode()).decode()
now_ns = int(time.time() * 1e9)
h1_ns  = now_ns - int(3600  * 1e9)
h24_ns = now_ns - int(86400 * 1e9)

def loki(q, start=h1_ns, limit=500):
    p = urllib.parse.urlencode({'query': q, 'start': str(start), 'end': str(now_ns), 'limit': str(limit)})
    req = urllib.request.Request(
        f'{loki_url}/loki/api/v1/query_range?{p}',
        headers={'Authorization': f'Basic {auth}'}
    )
    return json.loads(urllib.request.urlopen(req, timeout=15).read()).get('data', {}).get('result', [])

def fmt(ts):
    return time.strftime('%H:%M:%S', time.localtime(int(ts) // 1_000_000_000))

def get_lbl(lbl, *keys):
    for k in keys:
        v = lbl.get(k)
        if v:
            return v
    return '?'

# Pull all entries once
all_entries = [
    (ts, s['stream'], msg)
    for s in loki('{service_name="supply-chain-agent"}')
    for ts, msg in s['values']
]
all_entries.sort(key=lambda x: x[0])

http_entries = [e for e in all_entries if e[1].get('http_route')]
pol_entries  = [e for e in all_entries if e[1].get('scope_name', '').endswith('.policy')]
err_entries  = [e for e in all_entries if e[1].get('severity_text', '') == 'ERROR']

pol_24h = [
    (ts, s['stream'], msg)
    for s in loki('{service_name="supply-chain-agent", scope_name="supply_chain_agent.policy"}', start=h24_ns)
    for ts, msg in s['values']
]

levels   = Counter(e[1].get('severity_text', 'INFO') for e in all_entries)
scopes   = Counter(e[1].get('scope_name', '') for e in all_entries if e[1].get('scope_name'))
routes   = Counter(e[1].get('http_route', '') for e in all_entries if e[1].get('http_route'))
outcomes = Counter(
    get_lbl(e[1], 'policy.outcome', 'policy_outcome')
    for e in pol_entries if get_lbl(e[1], 'policy.outcome', 'policy_outcome') != '?'
)
rules = Counter(
    get_lbl(e[1], 'policy.rule_id', 'policy_rule_id')
    for e in pol_entries if get_lbl(e[1], 'policy.rule_id', 'policy_rule_id') != '?'
)
oc_24h = Counter(
    get_lbl(e[1], 'policy.outcome', 'policy_outcome')
    for e in pol_24h if get_lbl(e[1], 'policy.outcome', 'policy_outcome') != '?'
)

W   = 68
SEP = '=' * W
SEP2 = '-' * W
TS  = time.strftime('%Y-%m-%d %H:%M:%S')

# ── LOGS & TRACES ─────────────────────────────────────────────────────────────
print(SEP)
print('  LOGS & TRACES DASHBOARD  --  live from Grafana Cloud / Loki')
print(f'  Refreshed: {TS}')
print(SEP)

print('\n  PANEL 1  HTTP Request Log Stream')
print(f'  {"TIME":8s}  {"STATUS":6s}  {"ROUTE":<22s}  TRACE ID')
print(f'  {SEP2}')
for ts, lbl, msg in http_entries[-10:]:
    tid = lbl.get('otelTraceID', '?')
    print(f'  {fmt(ts)}  {lbl.get("http_status_code","?"):6s}  {lbl.get("http_route","?"):<22s}  {tid}')

print('\n  PANEL 2  Policy Decision Stream')
print(f'  {"TIME":8s}  {"OUTCOME":<16s}  {"RULE":<22s}  TURN  TRACE ID')
print(f'  {SEP2}')
if pol_entries:
    for ts, lbl, msg in pol_entries:
        oc   = get_lbl(lbl, 'policy.outcome', 'policy_outcome')
        rule = get_lbl(lbl, 'policy.rule_id', 'policy_rule_id')
        turn = get_lbl(lbl, 'agent.turn', 'agent_turn')
        tid  = lbl.get('otelTraceID', '?')
        print(f'  {fmt(ts)}  {oc:<16s}  {rule:<22s}  {turn:<4s}  {tid}')
else:
    print('  (none in last hour)')

print('\n  PANEL 3  Error Log Stream')
if err_entries:
    for ts, lbl, msg in err_entries[-5:]:
        print(f'  {fmt(ts)}  {msg[:65]}')
else:
    print('  (no errors -- clean run)')

print('\n  PANEL 5  Log Volume by Severity (last 1h)')
for lvl, cnt in sorted(levels.items(), key=lambda x: -x[1]):
    bar = '#' * min(cnt, 48)
    print(f'  {lvl:<8s}  {cnt:4d}  {bar}')

print('\n  PANEL 6  Activity by Agent / Scope (last 1h)')
for sc, cnt in sorted(scopes.items(), key=lambda x: -x[1])[:8]:
    short = sc.replace('supply_chain_agent.', '').replace('azure.cosmos._cosmos_http_logging_policy', 'cosmos')
    bar = '#' * min(cnt, 48)
    print(f'  {short:<26s}  {cnt:3d}  {bar}')

print(f'\n  Total log lines in Grafana Cloud Loki (last 1h): {len(all_entries)}')

# ── OPERATIONAL ───────────────────────────────────────────────────────────────
print(f'\n{SEP}')
print('  OPERATIONAL DASHBOARD  --  live from Grafana Cloud / Loki + Mimir')
print(f'  Refreshed: {TS}')
print(SEP)

print('\n  PANEL 1  Request Count per Endpoint (last 1h)')
for rt, cnt in sorted(routes.items(), key=lambda x: -x[1]):
    bar = '#' * min(cnt * 4, 48)
    print(f'  {rt:<30s}  {cnt:3d} req  {bar}')

print('\n  PANEL 4  Tool Error Rate')
if err_entries:
    err_tools = Counter(e[1].get('scope_name', 'unknown') for e in err_entries)
    for tool, cnt in err_tools.most_common(5):
        print(f'  {tool:<30s}  {cnt} error(s)')
else:
    print('  All tools healthy -- 0 errors')

httpx_cnt = scopes.get('httpx', 0)
print(f'\n  PANEL 3  Outbound calls (LLM + SAP via httpx): {httpx_cnt}')
print('  PANEL 5  Active LangGraph runs   --> langgraph_active_runs  (Mimir/Grafana UI)')
print('  PANEL 6  Approval queue depth    --> approval_queue_depth   (Mimir/Grafana UI)')

# ── GOVERNANCE ────────────────────────────────────────────────────────────────
print(f'\n{SEP}')
print('  GOVERNANCE DASHBOARD  --  live from Grafana Cloud / Loki')
print(f'  Refreshed: {TS}')
print(SEP)

print('\n  PANEL 1  Auto-Approval Rate (rolling 24h)   target >= 80%')
if oc_24h:
    total_24 = sum(oc_24h.values())
    auto_24  = oc_24h.get('auto_approved', 0)
    rate     = round(auto_24 * 100 / total_24)
    filled   = '#' * (rate // 2)
    empty    = '-' * (50 - rate // 2)
    print(f'  [{filled}{empty}] {rate}%')
    status = 'OK (meets target)' if rate >= 80 else 'ALERT: below 80% target'
    print(f'  {auto_24}/{total_24} auto-approved  --  {status}')
else:
    print('  (no decisions in last 24h)')

print('\n  PANEL 2  Decisions by policy.outcome')
if outcomes:
    total = sum(outcomes.values())
    for oc, cnt in sorted(outcomes.items(), key=lambda x: -x[1]):
        pct = round(cnt * 100 / total)
        bar = '#' * min(pct // 2 + 1, 48)
        print(f'  {oc:<18s}  {cnt:3d}  ({pct:3d}%)  {bar}')
else:
    print('  (no decisions in last hour)')

print('\n  PANEL 3  Rule Firing Frequency')
if rules:
    total_r = sum(rules.values())
    for rule, cnt in sorted(rules.items(), key=lambda x: -x[1]):
        pct = round(cnt * 100 / total_r)
        bar = '#' * min(cnt * 8, 48)
        flag = '  <-- ALERT: >90% of decisions' if pct > 90 else ''
        print(f'  {rule:<24s}  {cnt}x  ({pct}%){flag}')
else:
    print('  (no rule firings)')

print('\n  PANEL 4  Avg Approval Cycle Time  --> approval_cycle_duration_seconds (Mimir/Grafana UI)')

print('\n  PANEL 5  Denied Proposals (audit table)')
denied = [e for e in pol_entries if get_lbl(e[1], 'policy.outcome', 'policy_outcome') == 'denied']
if denied:
    print(f'  {"TIME":8s}  {"RULE":<22s}  TRACE ID')
    for ts, lbl, msg in denied:
        rule = get_lbl(lbl, 'policy.rule_id', 'policy_rule_id')
        tid  = lbl.get('otelTraceID', '?')
        print(f'  {fmt(ts)}  {rule:<22s}  {tid}')
else:
    print('  (no denied proposals)')

print(f'\n{SEP}')
