# Runbook: OTEL Collector Down

**Trigger**: No traces appearing in Jaeger or Grafana Tempo for > 5 m, or `otel-collector` DaemonSet pods in `CrashLoopBackOff` / `Pending` state.

---

## Symptoms

- Jaeger UI shows no traces for the `supply-chain-agent` service.
- Grafana dashboards show gaps in all agent/tool metrics.
- agents-api logs show OTLP export errors:
  ```
  Failed to export spans. The request could not be executed.
  opentelemetry.exporter.otlp.proto.grpc._exporter: Failed to export ...
  ```
- `kubectl get pods -n supply-chain` shows `otel-collector` DaemonSet pods not Running.

Note: The application continues to serve requests when the collector is down. Spans are buffered in the `BatchSpanProcessor` queue (default 2048 spans) and dropped when the buffer is full. **No user-facing functionality is lost**, but observability is degraded.

---

## Diagnosis

### 1. Check DaemonSet pod status
```bash
kubectl get pods -n supply-chain -l app=otel-collector
kubectl describe pod <otel-collector-pod> -n supply-chain
```

Look for:
- `CrashLoopBackOff` — collector is crashing on startup (bad config or missing secret)
- `OOMKilled` — collector exceeded its memory limit
- `Pending` — node resource pressure or unschedulable

### 2. Check collector logs
```bash
kubectl logs -n supply-chain -l app=otel-collector --since=15m
```

Common error patterns:
- `failed to load config` — `otel-collector.yaml` has a syntax error or references a missing component
- `connection refused` — the collector cannot reach Azure Monitor or Prometheus endpoints
- `invalid API key` — Application Insights instrumentation key is wrong or expired

### 3. Check agents-api OTLP export errors
```bash
kubectl logs -n supply-chain -l app=agents-api --since=15m | grep -i "otlp\|export\|collector\|span"
```

### 4. Verify the collector config
```bash
kubectl get configmap otel-collector-config -n supply-chain -o yaml
```

Compare against the canonical config in `docker/otel-collector.yaml` in the repo.

---

## Remediation

### Case A — Collector pod is CrashLoopBackOff due to bad config

1. Identify the config error from the pod logs (step 2 above).
2. Fix the config in `docker/otel-collector.yaml` and redeploy:
   ```bash
   kubectl apply -f k8s/otel-collector.yaml -n supply-chain
   ```
3. If the config was corrupted in the ConfigMap directly (not from the file), restore it:
   ```bash
   kubectl create configmap otel-collector-config \
     --from-file=otel-collector.yaml=docker/otel-collector.yaml \
     -n supply-chain --dry-run=client -o yaml | kubectl apply -f -
   kubectl rollout restart daemonset/otel-collector -n supply-chain
   ```

### Case B — Collector pod is OOMKilled

Increase the memory limit in `k8s/otel-collector.yaml`:
```yaml
resources:
  limits:
    memory: "512Mi"   # increase from 256Mi
  requests:
    memory: "128Mi"
```

Apply and restart:
```bash
kubectl apply -f k8s/otel-collector.yaml -n supply-chain
```

If OOM is caused by a batch export backlog (Azure Monitor endpoint slow), reduce the batch size:
```yaml
# in otel-collector.yaml exporters section
batch:
  send_batch_size: 512      # reduce from 1024
  timeout: 5s
```

### Case C — Azure Monitor / Application Insights endpoint unreachable

1. Verify the instrumentation key is valid:
   ```bash
   az keyvault secret show --vault-name <vault> --name appinsights-instrumentation-key
   ```
2. Test connectivity from a pod:
   ```bash
   kubectl run -it --rm debug --image=curlimages/curl -n supply-chain -- \
     curl -v https://dc.services.visualstudio.com/v2/track
   ```
3. If the endpoint is unreachable, the collector will buffer spans locally. Check whether an egress network policy is blocking outbound traffic to `*.monitor.azure.com`:
   ```bash
   kubectl get networkpolicies -n supply-chain
   ```

### Case D — Fallback to local buffering (spans not lost immediately)

The `BatchSpanProcessor` in agents-api buffers up to 2048 spans in memory. During a collector outage lasting < ~5 min at normal traffic, most spans are retained and will be exported once the collector recovers.

To extend the buffer and reduce span loss during a longer outage, temporarily increase the batch size via env var (no code change needed if the app reads this from config):
```bash
kubectl set env deployment/agents-api -n supply-chain \
  OTEL_BSP_MAX_EXPORT_BATCH_SIZE=4096 \
  OTEL_BSP_MAX_QUEUE_SIZE=8192
kubectl rollout restart deployment/agents-api -n supply-chain
```

Revert after the collector is healthy:
```bash
kubectl set env deployment/agents-api -n supply-chain \
  OTEL_BSP_MAX_EXPORT_BATCH_SIZE- \
  OTEL_BSP_MAX_QUEUE_SIZE-
```

### Case E — Node-level issue (DaemonSet pod not scheduled)

```bash
kubectl get nodes
kubectl describe node <affected-node>
```

If the node is under memory or disk pressure, the DaemonSet pod may not be scheduled. Cordon the node and allow it to drain:
```bash
kubectl cordon <node-name>
kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data
```

The DaemonSet pod will reschedule on a healthy node. Uncordon after the node recovers:
```bash
kubectl uncordon <node-name>
```

---

## Recovery verification

After the collector is running:
```bash
# Confirm pods are Running
kubectl get pods -n supply-chain -l app=otel-collector

# Send a test request and verify the trace appears in Jaeger
curl -X POST https://<api-host>/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "healthcheck trace"}'

# Open Jaeger UI and search for service=supply-chain-agent
open http://localhost:16686  # or the cluster Jaeger endpoint
```

Verify Grafana dashboards resume populating within one scrape interval (default 30 s for metrics).

---

## Prevention

- Set a Grafana alert: no spans received from `supply-chain-agent` for > 5 m → page on-call.
- Set a Kubernetes alert: `otel-collector` DaemonSet has < expected number of ready pods for > 2 m.
- Pin the OTEL collector image version in `k8s/otel-collector.yaml` — avoid `latest` tags.
- Test the collector config in CI: `otelcol validate --config docker/otel-collector.yaml`.

---

## Escalation

If the collector cannot be recovered within 30 min and an incident is in progress requiring trace evidence, export spans directly from agents-api to a local Jaeger instance as a temporary diagnostic measure:

```bash
# Port-forward a local Jaeger instance
kubectl port-forward svc/jaeger -n supply-chain 16686:16686 4317:4317

# Temporarily point agents-api at the local collector
kubectl set env deployment/agents-api -n supply-chain \
  OTLP_ENDPOINT=http://localhost:4317
```

Revert once the DaemonSet collector is healthy.
