from __future__ import annotations


class Attr:
    """Canonical OTEL attribute name constants.

    All set_attribute() calls must use these constants — never raw strings.
    Existing dashboards depend on the literal strings; rename via migration only.
    """

    # Agent
    AGENT_NAME = "agent.name"
    AGENT_DECISION = "agent.decision"
    AGENT_TURN = "agent.turn"

    # Tool
    TOOL_NAME = "tool.name"
    TOOL_RESULT_SIZE = "tool.result_size"
    TOOL_DURATION_MS = "tool.duration_ms"

    # SAP Mock
    SAP_MOCK = "sap.mock"

    # Policy
    POLICY_OUTCOME = "policy.outcome"
    POLICY_RULE_ID = "policy.rule_id"
    POLICY_THRESHOLD_USD = "policy.threshold_usd"
    POLICY_AMOUNT_USD = "policy.amount_usd"
    POLICY_EXPLANATION = "policy.explanation"

    # RAG / Knowledge
    RAG_QUERY = "rag.query"
    RAG_TOP_K = "rag.top_k"
    RAG_DOC_TYPES = "rag.doc_types"
    RAG_RESULT_COUNT = "rag.result_count"

    # Procurement
    PROCUREMENT_QTY = "procurement.qty"
    PROCUREMENT_COST = "procurement.cost"
    PROCUREMENT_URGENCY = "procurement.urgency"

    # Forecast
    FORECAST_QTY = "forecast.qty"
    FORECAST_TREND_PCT = "forecast.trend_pct"

    # User (PII-safe)
    USER_ID_HASH = "user.id_hash"

    # GenAI semantic conventions (as-is, do not rename)
    GEN_AI_SYSTEM = "gen_ai.system"
    GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
    GEN_AI_USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
    GEN_AI_USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
