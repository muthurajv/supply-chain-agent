# Runbook: Forecast Confidence Collapse

**Trigger**: Forecast agent returning `forecast_qty: 0` or `trend_pct: 0.0` for multiple materials in succession, or the `forecast.trend_pct` span attribute consistently reading `0` in Jaeger/Grafana Tempo.

---

## Symptoms

- Procurement proposals are generated with `recommended_qty: 0` or implausibly small quantities.
- Supervisor routes to procurement with an empty or near-zero forecast.
- `forecast.qty` and `forecast.trend_pct` OTEL attributes are `0` across many traces.
- Users report the agent recommending no reorder when stock is visibly low.

---

## Diagnosis

### 1. Check recent forecast spans
In Grafana Tempo or Jaeger, filter by `agent.name = forecast` and inspect `forecast.qty` and `forecast.trend_pct` on recent spans.

### 2. Verify shipment history data is available
The forecast agent reads shipment history from the SAP mock. If the fixture data is missing or the SAP mock is unreachable, the LLM has no signal to reason over.

```bash
# Check SAP mock health
curl -s http://<sap-mock-host>:8001/health

# Verify shipment history endpoint returns data
curl -s "http://<sap-mock-host>:8001/shipment-history/M-1042" | jq 'length'
```

If the response is empty (`[]`) or the service is down, see **Case A** below.

### 3. Check the LLM structured output
The forecast agent uses `.with_structured_output()`. If the LLM returns a malformed response, LangChain may silently default numeric fields to `0`.

Check the agents-api logs for JSON parse errors or validation warnings:
```bash
kubectl logs -n supply-chain -l app=agents-api --since=1h | grep -i "forecast\|structured\|validation"
```

### 4. Check Azure OpenAI availability
If the LLM deployment is throttled or returning errors, the forecast node may be catching exceptions silently.

```bash
kubectl logs -n supply-chain -l app=agents-api --since=1h | grep -i "openai\|429\|quota\|rate"
```

If quota is exhausted, see runbook `azure-openai-quota-exhausted.md`.

### 5. Check for prompt regression
If a recent deployment changed the forecast agent prompt or the structured output schema, the LLM may no longer produce valid `forecast_qty` values.

```bash
git log --oneline app/agents/forecast.py
```

Compare the current prompt against the last known-good version.

---

## Remediation

### Case A — SAP mock not returning shipment history

Restart the sap-mock pod:
```bash
kubectl rollout restart deployment/sap-mock -n supply-chain
```

Verify fixtures are loaded:
```bash
kubectl exec -n supply-chain deploy/sap-mock -- ls /app/fixtures/
# Expected: materials.json  vendors.json  shipment_history.json
```

If `shipment_history.json` is missing or empty, redeploy the sap-mock image with the correct fixtures.

### Case B — LLM returning zero values due to schema mismatch

1. Temporarily add a `print` (or span event) in the forecast node to log the raw LLM response — **remove before merging**.
2. Identify whether the schema change broke the structured output contract.
3. Roll back the forecast agent to the previous deployment if needed:
   ```bash
   kubectl rollout undo deployment/agents-api -n supply-chain
   ```

### Case C — Episodic memory empty (first-run scenario)

If the episodic memory index has no historical forecasts yet, the LLM has nothing to anchor trend estimation. This is expected on first deployment. The forecast agent should fall back to a baseline `trend_pct = 0.0` without crashing.

No action required — trend confidence improves as the system accumulates history.

### Case D — Azure OpenAI quota exhausted

See runbook `azure-openai-quota-exhausted.md`.

---

## Prevention

- Add a Grafana alert: `forecast.qty = 0` on more than 3 consecutive traces for the same material → warn on-call.
- Pin the structured output schema version in a test snapshot (`tests/fixtures/llm_snapshots/forecast_*.json`). Re-record only when the prompt or model changes.
- Smoke-test the forecast agent in the dev environment after every deployment: `make smoke`.

---

## Escalation

If forecast collapse persists more than 30 min and the SAP mock and LLM are both healthy, escalate to the AI/ML team lead. A silent structured-output regression requires a prompt fix and a new model snapshot.
