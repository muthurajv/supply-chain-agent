from pydantic import BaseModel
from datetime import date, datetime
from typing import Optional
from sqlalchemy import Column, String, Integer, Float, Boolean, Date, DateTime, ForeignKey, Text
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# SQLAlchemy ORM models

class MaterialDB(Base):
    __tablename__ = "materials"
    material_id = Column(String, primary_key=True)
    description = Column(String)
    plant = Column(String)
    on_hand_qty = Column(Float)
    safety_stock = Column(Float)
    unit = Column(String, default="EA")
    last_updated = Column(DateTime, default=datetime.utcnow)
    locations = relationship("StockLocationDB", back_populates="material")
    shipments = relationship("ShipmentHistoryDB", back_populates="material")


class StockLocationDB(Base):
    __tablename__ = "stock_locations"
    id = Column(Integer, primary_key=True, autoincrement=True)
    material_id = Column(String, ForeignKey("materials.material_id"))
    plant = Column(String)
    storage_loc = Column(String)
    qty = Column(Float)
    material = relationship("MaterialDB", back_populates="locations")


class VendorDB(Base):
    __tablename__ = "vendors"
    vendor_id = Column(String, primary_key=True)
    name = Column(String)
    lead_time_days = Column(Integer)
    preferred = Column(Boolean, default=False)
    payment_terms = Column(String)
    contact_email = Column(String)


class ShipmentHistoryDB(Base):
    __tablename__ = "shipment_history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    material_id = Column(String, ForeignKey("materials.material_id"))
    shipment_date = Column(Date)
    qty = Column(Float)
    plant = Column(String)
    customer = Column(String)
    material = relationship("MaterialDB", back_populates="shipments")


class PurchaseOrderDB(Base):
    __tablename__ = "purchase_orders"
    pr_number = Column(String, primary_key=True)
    material_id = Column(String)
    vendor_id = Column(String)
    qty = Column(Float)
    unit_price = Column(Float)
    total_value = Column(Float)
    status = Column(String, default="open")
    created_at = Column(DateTime, default=datetime.utcnow)
    goods_receipts = relationship("GoodsReceiptDB", back_populates="po")


class GoodsReceiptDB(Base):
    __tablename__ = "goods_receipts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    po_number = Column(String, ForeignKey("purchase_orders.pr_number"))
    material_id = Column(String)
    received_qty = Column(Float)
    received_date = Column(Date)
    po = relationship("PurchaseOrderDB", back_populates="goods_receipts")


# Pydantic response schemas

class InventoryResponse(BaseModel):
    material_id: str
    description: str
    plant: str
    on_hand_qty: float
    safety_stock: float
    unit: str
    last_updated: datetime


class StockLocationResponse(BaseModel):
    plant: str
    storage_loc: str
    qty: float


class VendorResponse(BaseModel):
    vendor_id: str
    name: str
    lead_time_days: int
    preferred: bool
    payment_terms: str


class ShipmentRecord(BaseModel):
    shipment_date: date
    qty: float
    plant: str
    customer: str


class PurchaseOrderCreate(BaseModel):
    material_id: str
    vendor_id: str
    qty: float
    unit_price: float


class PurchaseOrderResponse(BaseModel):
    pr_number: str
    material_id: str
    vendor_id: str
    qty: float
    unit_price: float
    total_value: float
    status: str
    created_at: datetime


class GoodsReceiptResponse(BaseModel):
    po_number: str
    material_id: str
    received_qty: float
    received_date: date
