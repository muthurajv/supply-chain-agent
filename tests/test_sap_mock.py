"""Integration tests for the SAP mock service endpoints."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
async def client(tmp_path):
    """SAP mock client backed by a fresh file-based SQLite per test.

    ASGITransport (httpx 0.27+) does not trigger the ASGI lifespan, so
    init_db() and seed_database() are called manually here before the
    client starts.  Both are idempotent, so a lifespan run (if it ever
    occurs) is harmless.
    """
    import sap_mock.database as db_module
    import sap_mock.main as main_module
    from sap_mock.main import app
    from sap_mock.models import Base
    from sap_mock.seed.seed_data import seed_database

    db_path = tmp_path / "sap_test.db"
    test_url = f"sqlite+aiosqlite:///{db_path}"

    test_engine = create_async_engine(
        test_url,
        connect_args={"check_same_thread": False},
    )
    test_session_local = async_sessionmaker(test_engine, expire_on_commit=False)

    orig_engine = db_module.engine
    orig_session = db_module.AsyncSessionLocal
    db_module.engine = test_engine
    db_module.AsyncSessionLocal = test_session_local

    orig_main_session = main_module.AsyncSessionLocal
    main_module.AsyncSessionLocal = test_session_local

    # ASGITransport does not run the ASGI lifespan; init manually.
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with test_session_local() as session:
        await seed_database(session)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        db_module.engine = orig_engine
        db_module.AsyncSessionLocal = orig_session
        main_module.AsyncSessionLocal = orig_main_session
        await test_engine.dispose()


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_get_inventory(client):
    resp = await client.get("/inventory/M-1042")
    assert resp.status_code == 200
    data = resp.json()
    assert data["material_id"] == "M-1042"
    assert data["on_hand_qty"] == 220.0
    assert data["safety_stock"] == 150.0


@pytest.mark.asyncio
async def test_get_inventory_not_found(client):
    resp = await client.get("/inventory/INVALID")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_stock_locations(client):
    resp = await client.get("/inventory/M-1042/locations")
    assert resp.status_code == 200
    locations = resp.json()
    assert isinstance(locations, list)
    assert len(locations) >= 1
    assert "storage_loc" in locations[0]


@pytest.mark.asyncio
async def test_get_shipment_history(client):
    resp = await client.get("/shipments/history/M-1042?months=6")
    assert resp.status_code == 200
    history = resp.json()
    assert isinstance(history, list)
    assert len(history) > 0
    assert "qty" in history[0]


@pytest.mark.asyncio
async def test_get_vendor(client):
    resp = await client.get("/vendors/V-7")
    assert resp.status_code == 200
    vendor = resp.json()
    assert vendor["vendor_id"] == "V-7"
    assert vendor["preferred"] is True


@pytest.mark.asyncio
async def test_list_preferred_vendors(client):
    resp = await client.get("/vendors/?preferred_only=true")
    assert resp.status_code == 200
    vendors = resp.json()
    assert all(v["preferred"] for v in vendors)


@pytest.mark.asyncio
async def test_create_purchase_order(client):
    resp = await client.post("/po/create", json={
        "material_id": "M-1042",
        "vendor_id": "V-7",
        "qty": 200.0,
        "unit_price": 21.0,
    })
    assert resp.status_code == 201
    po = resp.json()
    assert po["pr_number"].startswith("PR-")
    assert po["total_value"] == 200.0 * 21.0
    assert po["status"] == "open"


@pytest.mark.asyncio
async def test_get_open_pos(client):
    await client.post("/po/create", json={
        "material_id": "M-1001",
        "vendor_id": "V-1",
        "qty": 50.0,
        "unit_price": 100.0,
    })
    resp = await client.get("/po/open?material_id=M-1001")
    assert resp.status_code == 200
    pos = resp.json()
    assert isinstance(pos, list)
