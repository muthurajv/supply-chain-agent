"""GET /dashboards/{kpi} — serves pre-computed KPIs to the executive dashboard.

No LLM call on this path — reads directly from Cosmos KPI store.
"""
from fastapi import APIRouter, HTTPException
from app.tools.kpi_tools import read_kpi, list_kpis

router = APIRouter(prefix="/dashboards", tags=["dashboards"])


@router.get("/{kpi_name}")
async def get_kpi(kpi_name: str):
    record = await read_kpi(kpi_name)
    if not record:
        raise HTTPException(status_code=404, detail=f"KPI '{kpi_name}' not found. Run a scheduled refresh first.")
    return {
        "kpi": kpi_name,
        "value": record.get("value"),
        "unit": record.get("unit"),
        "narrative": record.get("narrative"),
        "computed_at": record.get("computed_at"),
    }


@router.get("")
async def list_available_kpis():
    kpis = await list_kpis()
    return {"kpis": [{"name": k["name"], "computed_at": k.get("computed_at")} for k in kpis]}
