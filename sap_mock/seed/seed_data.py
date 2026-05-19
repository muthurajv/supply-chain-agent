"""Deterministic seed data for the SAP mock database."""
from datetime import date, timedelta, datetime
import random


MATERIALS = [
    {"material_id": "M-1001", "description": "Hydraulic Pump Assembly", "plant": "P001", "on_hand_qty": 45.0, "safety_stock": 20.0, "unit": "EA"},
    {"material_id": "M-1002", "description": "Control Valve DN50", "plant": "P001", "on_hand_qty": 180.0, "safety_stock": 50.0, "unit": "EA"},
    {"material_id": "M-1003", "description": "Bearing SKF 6210", "plant": "P002", "on_hand_qty": 320.0, "safety_stock": 100.0, "unit": "EA"},
    {"material_id": "M-1004", "description": "Gasket Set Type-A", "plant": "P001", "on_hand_qty": 95.0, "safety_stock": 40.0, "unit": "SET"},
    {"material_id": "M-1005", "description": "Electric Motor 7.5kW", "plant": "P002", "on_hand_qty": 12.0, "safety_stock": 5.0, "unit": "EA"},
    {"material_id": "M-1006", "description": "PLC Module Siemens S7", "plant": "P001", "on_hand_qty": 8.0, "safety_stock": 3.0, "unit": "EA"},
    {"material_id": "M-1007", "description": "Pneumatic Cylinder 100mm", "plant": "P003", "on_hand_qty": 55.0, "safety_stock": 25.0, "unit": "EA"},
    {"material_id": "M-1008", "description": "Filter Element 10 Micron", "plant": "P002", "on_hand_qty": 240.0, "safety_stock": 80.0, "unit": "EA"},
    {"material_id": "M-1009", "description": "Coupling Flexible Size 6", "plant": "P001", "on_hand_qty": 75.0, "safety_stock": 30.0, "unit": "EA"},
    {"material_id": "M-1042", "description": "Precision Ball Screw 16mm", "plant": "P001", "on_hand_qty": 220.0, "safety_stock": 150.0, "unit": "EA"},
]

STOCK_LOCATIONS = [
    {"material_id": "M-1001", "plant": "P001", "storage_loc": "SL-01", "qty": 30.0},
    {"material_id": "M-1001", "plant": "P001", "storage_loc": "SL-02", "qty": 15.0},
    {"material_id": "M-1042", "plant": "P001", "storage_loc": "SL-01", "qty": 150.0},
    {"material_id": "M-1042", "plant": "P001", "storage_loc": "SL-03", "qty": 70.0},
    {"material_id": "M-1003", "plant": "P002", "storage_loc": "SL-04", "qty": 320.0},
]

VENDORS = [
    {"vendor_id": "V-1", "name": "Apex Industrial Supplies", "lead_time_days": 7, "preferred": True, "payment_terms": "NET30", "contact_email": "orders@apex.com"},
    {"vendor_id": "V-2", "name": "TechParts GmbH", "lead_time_days": 14, "preferred": False, "payment_terms": "NET45", "contact_email": "orders@techparts.de"},
    {"vendor_id": "V-3", "name": "FastTrack Components", "lead_time_days": 3, "preferred": False, "payment_terms": "NET15", "contact_email": "sales@fasttrack.com"},
    {"vendor_id": "V-7", "name": "Precision Parts Ltd", "lead_time_days": 14, "preferred": True, "payment_terms": "NET30", "contact_email": "supply@precisionparts.com"},
    {"vendor_id": "V-9", "name": "GlobalMech Distributors", "lead_time_days": 21, "preferred": False, "payment_terms": "NET60", "contact_email": "orders@globalmech.com"},
]


def generate_shipment_history(material_id: str, months: int = 18) -> list[dict]:
    """Generate deterministic 18-month shipment history per material."""
    rng = random.Random(hash(material_id) & 0xFFFF)
    base_qty = {
        "M-1001": 30, "M-1002": 80, "M-1003": 150, "M-1004": 60,
        "M-1005": 8, "M-1006": 4, "M-1007": 35, "M-1008": 120,
        "M-1009": 45, "M-1042": 300,
    }.get(material_id, 50)

    records = []
    today = date.today()
    start = today - timedelta(days=months * 30)

    for i in range(months * 3):
        shipment_date = start + timedelta(days=i * 10 + rng.randint(0, 5))
        if shipment_date > today:
            break
        seasonal_factor = 1.0 + 0.12 * (1 if shipment_date.month in [10, 11, 12] else -0.05)
        trend_factor = 1.0 + 0.01 * (i // 3)
        qty = round(base_qty * seasonal_factor * trend_factor * rng.uniform(0.8, 1.2))
        records.append({
            "material_id": material_id,
            "shipment_date": shipment_date,
            "qty": float(qty),
            "plant": "P001",
            "customer": f"CUST-{rng.randint(100, 200)}",
        })
    return records


async def seed_database(session):
    from sqlalchemy import select
    from ..models import MaterialDB, StockLocationDB, VendorDB, ShipmentHistoryDB

    existing = await session.execute(select(MaterialDB).limit(1))
    if existing.scalar():
        return  # already seeded

    for m in MATERIALS:
        session.add(MaterialDB(**m))

    for sl in STOCK_LOCATIONS:
        session.add(StockLocationDB(**sl))

    for v in VENDORS:
        session.add(VendorDB(**v))

    for mat in MATERIALS:
        for record in generate_shipment_history(mat["material_id"]):
            session.add(ShipmentHistoryDB(**record))

    await session.commit()
