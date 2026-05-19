# Runbook: Policy Extraction Mismatch

**Trigger**: `tests/eval/test_policy_extraction.py` fails after a policy re-index, or the governance dashboard shows an unexpected spike in `policy.outcome = denied` or a single rule firing > 90 % of decisions.

---

## Symptoms

- CI eval suite fails with extracted rules that differ from expected snapshots.
- `ops/diff_policy_rules.py` shows `source_excerpt` changes without a corresponding compliance sign-off in the PR.
- Auto-approval rate drops sharply (< 50 % for > 1 h) — governance dashboard alert fires.
- A rule that previously auto-approved proposals now routes them to `needs_human` or `denied`.

---

## Diagnosis

### 1. Run the rule diff tool
```bash
python ops/diff_policy_rules.py v3 v4
```

Inspect every rule whose `source_excerpt` changed. Any semantic change requires compliance sign-off (CLAUDE.md §10 step 5).

### 2. Check the current extracted rules against the live index
```bash
# Trigger extraction on a known policy doc and capture output
curl -X POST https://<api-host>/agent/invoke \
  -H "Content-Type: application/json" \
  -d '{"agent": "policy", "input": {"query": "procurement approval threshold"}}'
```

Compare the `rule_id_fired` in the response traces with expected rules.

### 3. Inspect extraction spans in Jaeger / Grafana Tempo

Filter by span name `policy.extraction`. Check:
- `rag.result_count` — how many rules were extracted
- Whether the span is hitting the `lru_cache` (no LLM call spans nested inside) or invoking the LLM fresh

If `rag.result_count = 0`, the LLM returned an empty rule set. The policy agent falls back to `_FALLBACK_RULES`, which may have different thresholds than the live policy.

### 4. Compare policy index versions
```bash
# Check which index version is active
grep policy_index app/config.py
```

The active index version must match the one used when the eval snapshots were recorded.

### 5. Check for LLM temperature drift
`_cached_extraction` enforces `temperature=0.0`. If a code change accidentally raised it, extraction may be non-deterministic. Verify:
```bash
grep -n "temperature" app/policy/extraction.py
# Must show temperature=0.0 — any other value is a bug
```

---

## Remediation

### Case A — Policy document updated without re-indexing

Re-index the policy library:
```bash
python ops/reindex_policies.py
```

Bump the policy index version in `app/config.py`:
```python
policy_index: str = "policies-v4"   # increment from current
```

Run the eval suite to confirm clean extraction:
```bash
pytest tests/eval/test_policy_extraction.py -v
```

Deploy the updated config. The new index takes effect on the next API call (no pod restart required if config is env-var backed).

### Case B — Extraction returns empty rules (`rag.result_count = 0`)

1. Verify the Azure AI Search index is populated:
   ```bash
   curl -s "https://<search-endpoint>/indexes/<policy-index>/docs/$count?api-version=2023-10-01-Preview" \
     -H "api-key: <search-key>"
   ```
   If count is 0, the re-index job failed. Re-run `ops/reindex_policies.py` and check for errors.

2. Verify the RAG query is reaching the index — check `rag_span` attributes in traces for `rag.result_count`.

3. If the index is populated but extraction still returns 0, the LLM system prompt may have regressed. Roll back `app/policy/extraction.py` to the previous version and redeploy.

### Case C — Extracted rules diverge semantically from policy intent

1. Do **not** deploy the new index until compliance has reviewed and signed off on the rule diff.
2. Keep the previous index version active in `app/config.py`.
3. Open a PR with the `ops/diff_policy_rules.py` output attached and request compliance sign-off before merging.

### Case D — lru_cache is serving stale rules after a re-index

The `_cached_extraction` cache is in-process and keyed by `hash(policy_text)`. A re-index changes the document content, so the hash changes and the cache is bypassed automatically. However, if the pod was not restarted after a config change (policy index version bump), it may still be querying the old index.

```bash
kubectl rollout restart deployment/agents-api -n supply-chain
```

---

## Prevention

- Run `pytest tests/eval/test_policy_extraction.py` in CI on every PR that touches `app/policy/`, `app/tools/rag_tools.py`, or `app/config.py`.
- Require compliance sign-off (named reviewer in PR) for any PR that changes `policy_index` in `app/config.py`.
- Store rule snapshots in `tests/fixtures/policy_rules/` and diff them in PR descriptions.

---

## Escalation

Any semantic change to an extracted rule that affects approval thresholds must be escalated to the compliance officer before deployment. Do not unilaterally adjust thresholds to fix a failing test — the policy document is the source of truth.
