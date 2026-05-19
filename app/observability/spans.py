from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Optional

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from .attributes import Attr

_tracer = trace.get_tracer("supply-chain-agent")


@contextmanager
def agent_span(agent_name: str, turn: int = 0):
    """Mandatory wrapper for every agent node body."""
    with _tracer.start_as_current_span(f"agent.{agent_name}") as span:
        span.set_attribute(Attr.AGENT_NAME, agent_name)
        span.set_attribute(Attr.AGENT_TURN, turn)
        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


@contextmanager
def tool_span(tool_name: str, **attrs):
    """Mandatory wrapper for every tool call body."""
    start = time.perf_counter()
    with _tracer.start_as_current_span(f"tool.{tool_name}") as span:
        span.set_attribute(Attr.TOOL_NAME, tool_name)
        for k, v in attrs.items():
            span.set_attribute(k, v)
        try:
            yield span
            span.set_attribute(Attr.TOOL_DURATION_MS, int((time.perf_counter() - start) * 1000))
            span.set_status(Status(StatusCode.OK))
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


@contextmanager
def policy_evaluation_span(amount_usd: float, threshold_usd: float):
    """Mandatory wrapper for the deterministic policy evaluation block."""
    with _tracer.start_as_current_span("policy.evaluation") as span:
        span.set_attribute(Attr.POLICY_AMOUNT_USD, amount_usd)
        span.set_attribute(Attr.POLICY_THRESHOLD_USD, threshold_usd)
        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


# Backward-compat alias used by existing code.
policy_span = policy_evaluation_span


@contextmanager
def rag_span(query: str, top_k: int, doc_types: Optional[list[str]] = None):
    with _tracer.start_as_current_span("rag.retrieval") as span:
        span.set_attribute(Attr.RAG_QUERY, query[:200])
        span.set_attribute(Attr.RAG_TOP_K, top_k)
        if doc_types:
            span.set_attribute(Attr.RAG_DOC_TYPES, ",".join(doc_types))
        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise
