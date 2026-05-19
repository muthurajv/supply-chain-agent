from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..database import get_db
from ..models import MaterialDB, StockLocationDB, InventoryResponse, StockLocationResponse

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("/{material_id}", response_model=InventoryResponse)
async def get_inventory(material_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(MaterialDB).where(MaterialDB.material_id == material_id))
    material = result.scalar_one_or_none()
    if not material:
        raise HTTPException(status_code=404, detail=f"Material {material_id} not found")
    return InventoryResponse(
        material_id=material.material_id,
        description=material.description,
        plant=material.plant,
        on_hand_qty=material.on_hand_qty,
        safety_stock=material.safety_stock,
        unit=material.unit,
        last_updated=material.last_updated,
    )


@router.get("/{material_id}/locations", response_model=list[StockLocationResponse])
async def get_stock_locations(material_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(StockLocationDB).where(StockLocationDB.material_id == material_id)
    )
    locations = result.scalars().all()
    return [StockLocationResponse(plant=loc.plant, storage_loc=loc.storage_loc, qty=loc.qty) for loc in locations]
