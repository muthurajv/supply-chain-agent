"""Diff policy rules extracted from two index versions.

Runs policy extraction against all documents in both indexes and prints a
structured diff.  Any rule whose source_excerpt changed requires sign-off
in the PR description (§10 step 5).

Usage:
    uv run python ops/diff_policy_rules.py v3 v4
    uv run python ops/diff_policy_rules.py policies-v3 policies-v4

The version argument is matched against index names: if it starts with
"policies-" it is used as-is; otherwise "policies-" is prepended.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient

from app.config import get_settings
from app.policy.extraction import extract_policy_rules
from app.policy.schema import PolicyRule


def _resolve_index(version: str, settings) -> str:
    if version.startswith("policies-"):
        return version
    return f"policies-{version}"


def _fetch_all_docs(search_client: SearchClient) -> list[dict]:
    results = search_client.search(
        search_text="*",
        select=["doc_id", "title", "content"],
        top=1000,
    )
    return [{"doc_id": r["doc_id"], "title": r["title"], "content": r["content"]} for r in results]


def _extract_all_rules(docs: list[dict]) -> dict[str, PolicyRule]:
    """Return a dict keyed by rule_id → PolicyRule across all documents."""
    rules: dict[str, PolicyRule] = {}
    for doc in docs:
        extracted = extract_policy_rules(doc["content"], doc["doc_id"])
        for rule in extracted:
            rules[rule.rule_id] = rule
    return rules


@dataclass
class RuleDiff:
    added: list[PolicyRule]
    removed: list[PolicyRule]
    changed_excerpt: list[tuple[PolicyRule, PolicyRule]]  # (old, new)
    changed_threshold: list[tuple[PolicyRule, PolicyRule]]
    unchanged: list[PolicyRule]


def _diff(old: dict[str, PolicyRule], new: dict[str, PolicyRule]) -> RuleDiff:
    added, removed, changed_excerpt, changed_threshold, unchanged = [], [], [], [], []
    all_ids = set(old) | set(new)
    for rule_id in sorted(all_ids):
        if rule_id not in old:
            added.append(new[rule_id])
        elif rule_id not in new:
            removed.append(old[rule_id])
        else:
            o, n = old[rule_id], new[rule_id]
            if o.source_excerpt != n.source_excerpt:
                changed_excerpt.append((o, n))
            elif o.threshold != n.threshold or o.on_violation != n.on_violation:
                changed_threshold.append((o, n))
            else:
                unchanged.append(n)
    return RuleDiff(added, removed, changed_excerpt, changed_threshold, unchanged)


def _print_rule(rule: PolicyRule, prefix: str = "") -> None:
    print(f"{prefix}  [{rule.rule_id}] {rule.description}")
    print(f"{prefix}    condition : {rule.condition_field} {rule.operator} {rule.threshold}")
    print(f"{prefix}    violation : {rule.on_violation}")
    print(f"{prefix}    excerpt   : \"{rule.source_excerpt[:120]}\"")


def main() -> None:
    parser = argparse.ArgumentParser(description="Diff policy rules between two index versions.")
    parser.add_argument("from_version", help="Old index version (e.g. v3 or policies-v3)")
    parser.add_argument("to_version",   help="New index version (e.g. v4 or policies-v4)")
    args = parser.parse_args()

    settings = get_settings()
    credential = AzureKeyCredential(settings.azure_search_key)

    from_index = _resolve_index(args.from_version, settings)
    to_index   = _resolve_index(args.to_version,   settings)

    print(f"Comparing  {from_index}  →  {to_index}\n")

    old_client = SearchClient(settings.azure_search_endpoint, from_index, credential)
    new_client = SearchClient(settings.azure_search_endpoint, to_index,   credential)

    print(f"Fetching documents from '{from_index}' ...")
    old_docs = _fetch_all_docs(old_client)
    print(f"Fetching documents from '{to_index}' ...")
    new_docs = _fetch_all_docs(new_client)

    print(f"\nExtracting rules from {len(old_docs)} old doc(s) ...")
    old_rules = _extract_all_rules(old_docs)
    print(f"Extracting rules from {len(new_docs)} new doc(s) ...")
    new_rules = _extract_all_rules(new_docs)

    diff = _diff(old_rules, new_rules)

    # ── Summary ──────────────────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print(f"  SUMMARY: {from_index} → {to_index}")
    print(f"{'─'*60}")
    print(f"  Added           : {len(diff.added)}")
    print(f"  Removed         : {len(diff.removed)}")
    print(f"  Excerpt changed : {len(diff.changed_excerpt)}  ← REQUIRES SIGN-OFF")
    print(f"  Threshold/action: {len(diff.changed_threshold)}")
    print(f"  Unchanged       : {len(diff.unchanged)}")

    # ── Details ───────────────────────────────────────────────────────────────
    if diff.added:
        print(f"\n[ADDED] {len(diff.added)} rule(s):")
        for r in diff.added:
            _print_rule(r, prefix="+")

    if diff.removed:
        print(f"\n[REMOVED] {len(diff.removed)} rule(s):")
        for r in diff.removed:
            _print_rule(r, prefix="-")

    if diff.changed_excerpt:
        print(f"\n[EXCERPT CHANGED — SIGN-OFF REQUIRED] {len(diff.changed_excerpt)} rule(s):")
        for old_r, new_r in diff.changed_excerpt:
            print(f"  [{old_r.rule_id}]")
            print(f"    old excerpt: \"{old_r.source_excerpt[:120]}\"")
            print(f"    new excerpt: \"{new_r.source_excerpt[:120]}\"")

    if diff.changed_threshold:
        print(f"\n[THRESHOLD/ACTION CHANGED] {len(diff.changed_threshold)} rule(s):")
        for old_r, new_r in diff.changed_threshold:
            print(f"  [{old_r.rule_id}]")
            print(f"    old: {old_r.condition_field} {old_r.operator} {old_r.threshold} → {old_r.on_violation}")
            print(f"    new: {new_r.condition_field} {new_r.operator} {new_r.threshold} → {new_r.on_violation}")

    # Exit non-zero if excerpt changes require human sign-off (useful in CI)
    if diff.changed_excerpt:
        print(f"\nAction required: add sign-off note to PR description for each rule above (§10 step 5).")
        sys.exit(1)

    print("\nNo excerpt changes. Ready to bump policy_index in app/config.py.")


if __name__ == "__main__":
    main()
