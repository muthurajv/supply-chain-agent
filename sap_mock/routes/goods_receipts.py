from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..database import get_db
from ..models import GoodsReceiptDB, GoodsReceiptResponse

router = APIRouter(prefix="/gr", tags=["goods-receipts"])


@router.get("/{po_number}", response_model=list[GoodsReceiptResponse])
async def get_goods_receipts(po_number: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(GoodsReceiptDB).where(GoodsReceiptDB.po_number == po_number)
    )
    grs = result.scalars().all()
    if not grs:
        raise HTTPException(status_code=404, detail=f"No goods receipts for PO {po_number}")
    return [
        GoodsReceiptResponse(
            po_number=gr.po_number, material_id=gr.material_id,
            received_qty=gr.received_qty, received_date=gr.received_date,
        )
        for gr in grs
    ]
