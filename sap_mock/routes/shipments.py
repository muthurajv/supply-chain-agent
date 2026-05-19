from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import date, timedelta
from ..database import get_db
from ..models import ShipmentHistoryDB, ShipmentRecord

router = APIRouter(prefix="/shipments", tags=["shipments"])


@router.get("/history/{material_id}", response_model=list[ShipmentRecord])
async def get_shipment_history(
    material_id: str,
    months: int = Query(default=18, ge=1, le=36),
    db: AsyncSession = Depends(get_db),
):
    cutoff = date.today() - timedelta(days=months * 30)
    result = await db.execute(
        select(ShipmentHistoryDB)
        .where(ShipmentHistoryDB.material_id == material_id)
        .where(ShipmentHistoryDB.shipment_date >= cutoff)
        .order_by(ShipmentHistoryDB.shipment_date)
    )
    records = result.scalars().all()
    return [
        ShipmentRecord(shipment_date=r.shipment_date, qty=r.qty, plant=r.plant, customer=r.customer)
        for r in records
    ]
