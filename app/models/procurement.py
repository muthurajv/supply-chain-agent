from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ProcurementRecommendation(BaseModel):
    """Procurement proposal produced by the procurement agent."""

    material_id: str
    description: str
    recommended_qty: float
    vendor_id: str
    vendor_name: str
    unit_price: float
    estimated_cost: float
    lead_time_days: int
    urgency: Literal["low", "medium", "high", "critical"]
    rationale: str
