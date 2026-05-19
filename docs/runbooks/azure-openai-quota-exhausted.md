# Runbook: Azure OpenAI Quota Exhausted

**Trigger**: HTTP 429 responses from Azure OpenAI, `RateLimitError` in agents-api logs, or p95 `/chat` latency > 12 s for > 5 m (operational dashboard alert).

---

## Symptoms

- agents-api logs show `openai.RateLimitError` or `429 Too Many Requests`.
- Traces in Jaeger show LLM spans with `ERROR` status and `rate_limit` in the exception message.
- End users receive 500 errors or very slow responses from `/chat`.
- `gen_ai.usage.input_tokens` and `gen_ai.usage.output_tokens` metrics spike just before the failure.

---

## Diagnosis

### 1. Confirm quota exhaustion in Azure Portal

**Azure Portal → OpenAI resource → Metrics → Token Rate (TPM)**

Check if the TPM metric is hitting the deployment quota ceiling. Also check:

**Azure OpenAI Studio → Deployments → gpt-4o-dev / gpt-4o-prod → Quota**

Note the current TPM limit and whether a quota increase request is pending.

### 2. Check agents-api logs
```bash
kubectl logs -n supply-chain -l app=agents-api --since=15m | grep -i "429\|rate_limit\|quota\|openai"
```

### 3. Identify which agent is consuming the most tokens

In Grafana, open the operational dashboard panel **"LLM token spend per agent per day"**. The highest-consuming agent is the likely culprit. Common offenders:
- **Policy agent** — extraction + evaluation calls
- **Forecast agent** — history-over-LLM calls with long context

### 4. Check whether multiple pods are amplifying usage

If `agents-api` has been scaled up recently, all replicas share the same quota:
```bash
kubectl get deployment agents-api -n supply-chain -o jsonpath='{.spec.replicas}'
```

---

## Remediation

### Immediate: Request a quota increase

**Azure Portal → OpenAI resource → Quotas → Request increase**

Standard increases are approved within minutes for PTU deployments and within hours for PAYG. File the request immediately even while applying other mitigations.

### Mitigation A — Scale down agents-api replicas temporarily

Reducing replicas limits concurrent LLM calls and prevents the quota from being exhausted faster:
```bash
kubectl scale deployment agents-api -n supply-chain --replicas=1
```

Restore after quota increase is approved:
```bash
kubectl scale deployment agents-api -n supply-chain --replicas=2
```

### Mitigation B — Enable request queuing in the API

The `/chat` and `/agent/invoke` endpoints do not currently queue requests. If the quota is exhausted, return HTTP 429 to the caller with a `Retry-After` header rather than a 500:

Temporary workaround — add rate-limit middleware at the ingress level:
```bash
# AKS ingress nginx annotation (apply to ingress.yaml, then re-apply)
nginx.ingress.kubernetes.io/limit-rpm: "30"
```

### Mitigation C — Switch to a secondary deployment

If a backup deployment exists in a different Azure region or subscription, update `AZURE_OPENAI_DEPLOYMENT` and `AZURE_OPENAI_ENDPOINT` in the Key Vault secret and restart the pods:

```bash
# Update Key Vault secret (requires Key Vault Contributor role)
az keyvault secret set --vault-name <vault> --name azure-openai-api-key --value <backup-key>

# Restart pods to pick up new secret via CSI driver
kubectl rollout restart deployment/agents-api -n supply-chain
```

### Mitigation D — Reduce token consumption per call

If the quota increase will take hours, reduce context size:
- Lower `top_k` in RAG retrieval calls (default 5 → 3) via `AZURE_SEARCH_TOP_K` env var.
- Truncate shipment history passed to the forecast agent (adjust fixture or add a `max_records` config).

These are temporary changes — revert once quota is restored.

---

## Recovery verification

After quota is restored or increased:
```bash
# Smoke test
make smoke

# Verify LLM calls are succeeding in traces
# Filter Jaeger by gen_ai.system = azure.openai — spans should show StatusCode.OK
```

Restore replica count and any temporary ingress rate-limit annotations.

---

## Prevention

- Set a Grafana alert: `gen_ai.usage.input_tokens` rate > 80 % of quota ceiling for 5 m → warn on-call before exhaustion.
- Review token spend per agent weekly. If a single agent consumes > 60 % of the budget, investigate prompt length.
- Keep a secondary Azure OpenAI deployment in a different region on standby with at least 10K TPM reserved.

---

## Escalation

If quota cannot be increased within 2 h and the system is fully unavailable, escalate to the Azure account team for an emergency quota increase. Provide the subscription ID, resource name, deployment name, and current TPM limit.
