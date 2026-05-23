from __future__ import annotations

import json

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from app.config import get_settings
from app.llm.client import get_llm
from app.observability.attributes import Attr
from app.observability.spans import agent_span, record_llm_usage
from app.tools.sap_tools import get_shipment_history

from .state import GraphState

_FORECAST_SYSTEM = """You are a supply chain demand forecasting specialist.
Given historical shipment data, produce a forecast for the next month.

Reasoning steps you MUST follow:
1. Calculate average monthly demand and trend (month-over-month % change)
2. Identify seasonal patterns (Q4 uplift, summer dip, etc.)
3. Note any gaps or anomalies in the data
4. Project next month demand with conservative and optimistic bounds

Return ONLY valid JSON:
{
  "forecast_qty": <float>,
  "confidence_low": <float>,
  "confidence_high": <float>,
  "trend_pct": <float>,
  "seasonal_note": "<string>",
  "rationale": "<2-3 sentence explanation>"
}"""


async def forecast_node(state: GraphState) -> Command:
    """Forecast next-month demand using historical shipment data and LLM reasoning."""
    turn = state.get("turn", 0)
    with agent_span("forecast", turn=turn) as span:
        material_id = state.get("material_id", "M-1042")
        history = await get_shipment_history.ainvoke({"material_id": material_id, "months": 18})

        llm = get_llm(temperature=0.0, json_mode=True)
        response = await llm.ainvoke([
            {"role": "system", "content": _FORECAST_SYSTEM},
            {
                "role": "user",
                "content": f"Material: {material_id}\nHistory ({len(history)} records):\n{json.dumps(history, default=str)}",
            },
        ])
        record_llm_usage("forecast", response, get_settings().azure_openai_deployment)

        result = json.loads(response.content)
        span.set_attribute(Attr.FORECAST_QTY, result.get("forecast_qty", 0))
        span.set_attribute(Attr.FORECAST_TREND_PCT, result.get("trend_pct", 0))
        span.set_attribute(Attr.AGENT_DECISION, f"forecast={result.get('forecast_qty')}, trend={result.get('trend_pct')}%")

        summary = (
            f"Forecast for {material_id} (next month): {result['forecast_qty']} units "
            f"(range {result['confidence_low']}–{result['confidence_high']}). "
            f"Trend: {result['trend_pct']:+.1f}%. {result['rationale']}"
        )

        return Command(
            goto="supervisor",
            update={
                "messages": [HumanMessage(content=summary, name="forecast_agent")],
                "forecast_result": result,
            },
        )


forecast_agent = forecast_node
