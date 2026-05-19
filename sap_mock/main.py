from contextlib import asynccontextmanager
from fastapi import FastAPI
from .database import init_db, AsyncSessionLocal
from .seed.seed_data import seed_database
from .routes import inventory, shipments, vendors, purchase_orders, goods_receipts


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    async with AsyncSessionLocal() as session:
        await seed_database(session)
    yield


app = FastAPI(
    title="SAP Mock Service",
    description="Deterministic SAP S/4HANA mock for supply-chain agent development and testing",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(inventory.router)
app.include_router(shipments.router)
app.include_router(vendors.router)
app.include_router(purchase_orders.router)
app.include_router(goods_receipts.router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "sap-mock"}
