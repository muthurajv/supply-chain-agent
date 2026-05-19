# Runbook: Cosmos DB Throttled

**Trigger**: HTTP 429 responses from Cosmos DB (`CosmosHttpResponseError` with status 429), or `RequestRateTooLargeException` in agents-api logs. Operational dashboard alert — Cosmos throughput consumption (RU/s) sustained at 100 % for > 5 m.

---

## Symptoms

- agents-api logs show `azure.cosmos.exceptions.CosmosHttpResponseError: Status code: 429`.
- Checkpoint saves (`CosmosDBCheckpointer.aput`) are failing or retrying excessively.
- Approval queue writes and KPI writes are slow or failing.
- p95 `/chat` latency exceeds 12 s — requests are blocking on Cosmos retries.
- Grafana panel **"Cosmos throughput consumption (RU/s)"** is pegged at the provisioned limit.

---

## Diagnosis

### 1. Check Cosmos metrics in Azure Portal

**Azure Portal → Cosmos DB account → Metrics**

- **Total Request Units** — is consumption hitting the provisioned RU/s?
- **Throttled Requests** — count of 429 responses by container
- **Normalized RU Consumption** — which container is hottest?

Key containers and their expected RU/s patterns:

| Container | Typical load | Hot scenario |
|-----------|-------------|-------------|
| `checkpoints` | Writes on every agent turn | Long multi-turn conversations |
| `approval-queue` | Low write, occasional query | Bulk approval drain operations |
| `kpis` | Writes every 6 h (CronJob) | Analytics CronJob + /dashboards reads overlap |

### 2. Identify the hot container
```bash
kubectl logs -n supply-chain -l app=agents-api --since=15m | grep -i "429\|throttl\|cosmos"
```

Look for which operation is triggering the 429: `upsert_item` (checkpoints/approvals/kpis) vs `read_item` vs `query_items`.

### 3. Check the analytics CronJob schedule

If the CronJob ran recently and wrote many KPI records at the same time as high `/chat` traffic, the combined RU consumption may have spiked:
```bash
kubectl get cronjobs -n supply-chain
kubectl get jobs -n supply-chain --sort-by=.metadata.creationTimestamp | tail -5
```

---

## Remediation

### Immediate: Scale up RU/s on the throttled container

**Azure Portal → Cosmos DB → Data Explorer → select container → Scale**

Increase RU/s in increments of 100. For autoscale containers, increase the max RU/s.

Alternatively via CLI:
```bash
az cosmosdb sql container throughput update \
  --account-name <cosmos-account> \
  --resource-group <rg> \
  --database-name supply-chain-agent \
  --name checkpoints \
  --throughput 1000
```

Common starting points:
- `checkpoints`: 400 → 1000 RU/s during high load
- `approval-queue`: 400 → 600 RU/s
- `kpis`: 400 → 600 RU/s (increase before analytics CronJob runs)

### Case A — Checkpoints container throttled during high chat traffic

The `CosmosDBCheckpointer` writes a checkpoint on every LangGraph node completion. Each turn of a complex query (inventory → forecast → procurement → policy) writes 4–6 checkpoints.

Short-term: scale up checkpoints container as above.

Medium-term: consider batching checkpoint writes or using a lighter serialization format to reduce RU/s per write. Open an ADR before implementing.

### Case B — Analytics CronJob and /chat traffic overlapping

Reschedule the CronJob to run during off-peak hours:
```bash
kubectl edit cronjob analytics-job -n supply-chain
# Change schedule from "0 */6 * * *" to "0 2,8,14,20 * * *" (2am, 8am, 2pm, 8pm)
```

### Case C — Approval queue bulk drain causing spikes

If a large backlog of approvals is being processed simultaneously, the `cosmos.update_approval` writes can spike RU/s. Rate-limit bulk drain operations:
```bash
# Add a short sleep between bulk approval calls to spread the load
for id in $(curl -s https://<api-host>/approvals | jq -r '.approvals[].id'); do
  curl -X POST https://<api-host>/approvals/$id/decide \
    -d '{"approved": true, "reason": "Bulk drain"}' \
    -H "Content-Type: application/json"
  sleep 0.5
done
```

### Case D — Switch to autoscale

If manual RU/s management is too reactive, migrate the throttled container to autoscale:

**Azure Portal → Cosmos DB → Data Explorer → container → Scale → Autoscale**

Set max RU/s to 4000 (10× current provisioned). Autoscale scales down automatically during idle periods.

---

## Recovery verification

After scaling:
```bash
# Confirm Cosmos writes succeed
curl -X POST https://<api-host>/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is the inventory for M-1042?"}'

# Check traces — cosmos.* tool spans should show StatusCode.OK
```

Verify the Cosmos RU consumption metric is below the new ceiling with headroom.

---

## Prevention

- Set a Grafana alert: normalized RU consumption > 80 % for 5 m → warn on-call.
- Pre-scale `checkpoints` container before high-traffic events (demos, load tests).
- Review RU/s consumption weekly in Azure Cost Management — right-size containers that are consistently under 20 % utilization.

---

## Escalation

If RU/s cannot be increased quickly enough (pending Azure quota increase for the region), fail fast by returning HTTP 503 from `/chat` rather than letting requests pile up and time out. Update the ingress to return 503 until Cosmos is healthy:
```bash
kubectl annotate ingress supply-chain-ingress -n supply-chain \
  nginx.ingress.kubernetes.io/custom-http-errors="503" --overwrite
```

Escalate to the Azure account team if regional throughput quota limits are the root cause.
