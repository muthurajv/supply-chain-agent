from __future__ import annotations

# Canonical location is app/policy/schema.py — re-export for backward compat.
from app.policy.schema import PolicyDecision, PolicyRule

__all__ = ["PolicyRule", "PolicyDecision"]
