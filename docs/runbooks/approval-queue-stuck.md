# Runbook: Approval Queue Stuck

**Trigger**: Governance dashboard alert — approval queue depth > 50, or approvals older than 24 h with status `pending`.

---

## Symptoms

- `GET /approvals` returns many items with `status: pending` and old `created_at` timestamps.
- Governance dashboard panel "Average approval cycle time" is spiking.
- Users report procurement proposals are not progressing.

---

## Diagnosis

### 1. Check queue depth
```bash
curl -s https://<api-host>/approvals | jq '.count'
```

### 2. Identify the oldest pending item
```bash
curl -s https://<api-host>/approvals | jq '[.approvals[] | {id, material_id, created_at}] | sort_by(.created_at)'
```

### 3. Check whether the LangGraph thread is still alive

Each approval item should have a `thread_id`. If it is missing or the thread no longer exists in the Cosmos checkpoints container, the graph cannot be resumed.

```bash
# Look up thread_id on a stuck item
ITEM_ID="APQ-XXXXXXXX"
curl -s https://<api-host>/approvals/$ITEM_ID | jq '.thread_id'

# Check whether the checkpoint exists (Cosmos Data Explorer or CLI)
# Container: checkpoints, partition key: thread_id
```

### 4. Check the agents-api logs for interrupt errors
```bash
kubectl logs -n supply-chain -l app=agents-api --since=1h | grep -i "interrupt\|approval\|resume"
```

---

## Remediation

### Case A — Approver is unavailable / process backlog
Manually approve or reject via API:
```bash
curl -X POST https://<api-host>/approvals/<id>/decide \
  -H "Content-Type: application/json" \
  -d '{"approved": true, "reason": "Manual override — approver unavailable"}'
```

Repeat for each stuck item. If the queue depth is large, use a loop:
```bash
curl -s https://<api-host>/approvals | jq -r '.approvals[].id' | while read id; do
  curl -X POST https://<api-host>/approvals/$id/decide \
    -H "Content-Type: application/json" \
    -d '{"approved": true, "reason": "Bulk manual approval — queue drain"}'
done
```

### Case B — Thread ID missing or checkpoint lost

The graph cannot be resumed. Mark the item rejected with an explanatory reason so the procurement agent can re-raise the proposal:

```bash
curl -X POST https://<api-host>/approvals/<id>/decide \
  -H "Content-Type: application/json" \
  -d '{"approved": false, "reason": "Thread checkpoint lost — proposal must be re-submitted"}'
```

Then notify the requesting user to re-trigger the procurement flow.

### Case C — agents-api pod is down or OOMKilled

```bash
kubectl get pods -n supply-chain -l app=agents-api
kubectl describe pod <pod-name> -n supply-chain
kubectl rollout restart deployment/agents-api -n supply-chain
```

After the pod recovers, verify `/healthz` returns `{"status":"ok"}`, then retry the resume manually (Case A).

### Case D — Cosmos approval-queue container throttled

See runbook `cosmos-throttled.md`. Scale up RU/s on the `approval-queue` container, then retry.

---

## Prevention

- Set a Grafana alert: queue depth > 50 for 15 m → page on-call.
- Set a second alert: any `pending` item with `created_at` older than 4 h → page on-call.
- Review auto-approval rate on the governance dashboard weekly. A falling rate (< 80 %) means more items reach human review — consider loosening policy thresholds.

---

## Escalation

If queue cannot be drained within 1 h of incident declaration, escalate to the procurement operations team lead and the compliance officer. Do not bulk-approve items over the $25,000 denied threshold without executive sign-off.
