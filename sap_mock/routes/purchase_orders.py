import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..database import get_db
from ..models import PurchaseOrderDB, PurchaseOrderCreate, PurchaseOrderResponse

router = APIRouter(prefix="/po", tags=["purchase-orders"])


@router.get("/open", response_model=list[PurchaseOrderResponse])
async def get_open_pos(
    material_id: str = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    query = select(PurchaseOrderDB).where(PurchaseOrderDB.status == "open")
    if material_id:
        query = query.where(PurchaseOrderDB.material_id == material_id)
    result = await db.execute(query)
    pos = result.scalars().all()
    return [_po_to_response(po) for po in pos]


@router.post("/create", response_model=PurchaseOrderResponse, status_code=201)
async def create_purchase_order(payload: PurchaseOrderCreate, db: AsyncSession = Depends(get_db)):
    pr_number = f"PR-{uuid.uuid4().hex[:8].upper()}"
    po = PurchaseOrderDB(
        pr_number=pr_number,
        material_id=payload.material_id,
        vendor_id=payload.vendor_id,
        qty=payload.qty,
        unit_price=payload.unit_price,
        total_value=round(payload.qty * payload.unit_price, 2),
        status="open",
        created_at=datetime.utcnow(),
    )
    db.add(po)
    await db.commit()
    await db.refresh(po)
    return _po_to_response(po)


@router.get("/{pr_number}", response_model=PurchaseOrderResponse)
async def get_purchase_order(pr_number: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(PurchaseOrderDB).where(PurchaseOrderDB.pr_number == pr_number))
    po = result.scalar_one_or_none()
    if not po:
        raise HTTPException(status_code=404, detail=f"PO {pr_number} not found")
    return _po_to_response(po)


def _po_to_response(po: PurchaseOrderDB) -> PurchaseOrderResponse:
    return PurchaseOrderResponse(
        pr_number=po.pr_number, material_id=po.material_id, vendor_id=po.vendor_id,
        qty=po.qty, unit_price=po.unit_price, total_value=po.total_value,
        status=po.status, created_at=po.created_at,
    )
