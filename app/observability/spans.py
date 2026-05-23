from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Optional

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from .attributes import Attr

_tracer = trace.get_tracer("supply-chain-agent")
_llm_logger = logging.getLogger("supply_chain_agent.llm")


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
def llm_span(agent_name: str, model: str, temperature: float = 0.0, json_mode: bool = False):
    """Wrap a single LLM call with a child span carrying GenAI semantic convention attributes."""
    with _tracer.start_as_current_span("llm.call") as span:
        span.set_attribute(Attr.AGENT_NAME, agent_name)
        span.set_attribute(Attr.GEN_AI_SYSTEM, "azure_openai")
        span.set_attribute(Attr.GEN_AI_REQUEST_MODEL, model)
        span.set_attribute("gen_ai.request.temperature", temperature)
        span.set_attribute("gen_ai.request.json_mode", json_mode)
        t0 = time.time()
        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise
        finally:
            span.set_attribute(Attr.TOOL_DURATION_MS, round((time.time() - t0) * 1000))


def record_llm_usage(agent_name: str, response, model: str) -> None:
    """Record token usage from an LLM response on the current span and emit a Loki log record."""
    usage = (getattr(response, "response_metadata", None) or {}).get("token_usage", {})
    input_tok = usage.get("prompt_tokens", 0)
    output_tok = usage.get("completion_tokens", 0)
    span = trace.get_current_span()
    span.set_attribute(Attr.GEN_AI_USAGE_INPUT_TOKENS, input_tok)
    span.set_attribute(Attr.GEN_AI_USAGE_OUTPUT_TOKENS, output_tok)
    span.set_attribute(Attr.GEN_AI_REQUEST_MODEL, model)
    _llm_logger.info(
        "llm.call",
        extra={
            "agent.name": agent_name,
            "gen_ai.request.model": model,
            "gen_ai.usage.input_tokens": input_tok,
            "gen_ai.usage.output_tokens": output_tok,
        },
    )


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
