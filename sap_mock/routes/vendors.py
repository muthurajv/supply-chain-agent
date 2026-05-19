from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..database import get_db
from ..models import VendorDB, VendorResponse

router = APIRouter(prefix="/vendors", tags=["vendors"])


@router.get("/{vendor_id}", response_model=VendorResponse)
async def get_vendor(vendor_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(VendorDB).where(VendorDB.vendor_id == vendor_id))
    vendor = result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail=f"Vendor {vendor_id} not found")
    return VendorResponse(
        vendor_id=vendor.vendor_id,
        name=vendor.name,
        lead_time_days=vendor.lead_time_days,
        preferred=vendor.preferred,
        payment_terms=vendor.payment_terms,
    )


@router.get("/", response_model=list[VendorResponse])
async def list_vendors(preferred_only: bool = False, db: AsyncSession = Depends(get_db)):
    query = select(VendorDB)
    if preferred_only:
        query = query.where(VendorDB.preferred == True)
    result = await db.execute(query)
    vendors = result.scalars().all()
    return [
        VendorResponse(
            vendor_id=v.vendor_id, name=v.name, lead_time_days=v.lead_time_days,
            preferred=v.preferred, payment_terms=v.payment_terms,
        )
        for v in vendors
    ]
