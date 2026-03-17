
from fastapi import FastAPI, APIRouter, HTTPException
from starlette.middleware.cors import CORSMiddleware
import os
import random
import string
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://localhost/monstock')
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class ZoneDB(Base):
    __tablename__ = "zones"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255))
    description = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

class ProductDB(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255))
    reference = Column(String(255))
    zone_id = Column(Integer)
    quantity = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

class MovementDB(Base):
    __tablename__ = "stock_movements"
    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer)
    product_name = Column(String(255))
    zone_name = Column(String(255))
    movement_type = Column(String(10))
    quantity = Column(Integer)
    note = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

app = FastAPI()
api_router = APIRouter(prefix="/api")

class ZoneCreate(BaseModel):
    name: str
    description: Optional[str] = ""

class ProductCreate(BaseModel):
    name: str
    reference: Optional[str] = ""
    zone_id: int
    quantity: int = 0

class MovementCreate(BaseModel):
    product_id: int
    movement_type: str
    quantity: int
    note: Optional[str] = ""

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@api_router.post("/zones")
def create_zone(zone: ZoneCreate):
    db = SessionLocal()
    db_zone = ZoneDB(name=zone.name, description=zone.description)
    db.add(db_zone)
    db.commit()
    db.refresh(db_zone)
    db.close()
    return {"id": db_zone.id, "name": db_zone.name, "description": db_zone.description}

@api_router.get("/zones")
def get_zones():
    db = SessionLocal()
    zones = db.query(ZoneDB).all()
    result = [{"id": z.id, "name": z.name, "description": z.description} for z in zones]
    db.close()
    return result

@api_router.delete("/zones/{zone_id}")
def delete_zone(zone_id: int):
    db = SessionLocal()
    db.query(ZoneDB).filter(ZoneDB.id == zone_id).delete()
    db.query(ProductDB).filter(ProductDB.zone_id == zone_id).delete()
    db.commit()
    db.close()
    return {"message": "Zone deleted"}

@api_router.post("/products")
def create_product(product: ProductCreate):
    db = SessionLocal()
    ref = product.reference
    if not ref or ref.strip() == "":
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        random_chars = ''.join(random.choices(string.digits, k=4))
        ref = f"MS-{timestamp}-{random_chars}"
    db_product = ProductDB(name=product.name, reference=ref, zone_id=product.zone_id, quantity=product.quantity)
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    db.close()
    return {"id": db_product.id, "name": db_product.name, "reference": ref, "zone_id": db_product.zone_id, "quantity": db_product.quantity}

@api_router.get("/products")
def get_products(zone_id: Optional[int] = None, search: Optional[str] = None):
    db = SessionLocal()
    query = db.query(ProductDB)
    if zone_id:
        query = query.filter(ProductDB.zone_id == zone_id)
    if search:
        query = query.filter(ProductDB.name.ilike(f"%{search}%") | ProductDB.reference.ilike(f"%{search}%"))
    products = query.all()
    result = [{"id": p.id, "name": p.name, "reference": p.reference, "zone_id": p.zone_id, "quantity": p.quantity} for p in products]
    db.close()
    return result

@api_router.get("/products/by-reference/{reference}")
def get_product_by_reference(reference: str):
    db = SessionLocal()
    product = db.query(ProductDB).filter(ProductDB.reference == reference).first()
    db.close()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"id": product.id, "name": product.name, "reference": product.reference, "zone_id": product.zone_id, "quantity": product.quantity}

@api_router.delete("/products/{product_id}")
def delete_product(product_id: int):
    db = SessionLocal()
    db.query(ProductDB).filter(ProductDB.id == product_id).delete()
    db.query(MovementDB).filter(MovementDB.product_id == product_id).delete()
    db.commit()
    db.close()
    return {"message": "Product deleted"}

@api_router.post("/stock-movements")
def create_movement(movement: MovementCreate):
    db = SessionLocal()
    product = db.query(ProductDB).filter(ProductDB.id == movement.product_id).first()
    if not product:
        db.close()
        raise HTTPException(status_code=404, detail="Product not found")
    if movement.movement_type == "out" and product.quantity < movement.quantity:
        db.close()
        raise HTTPException(status_code=400, detail="Insufficient stock")
    new_qty = product.quantity + movement.quantity if movement.movement_type == "in" else product.quantity - movement.quantity
    product.quantity = new_qty
    zone = db.query(ZoneDB).filter(ZoneDB.id == product.zone_id).first()
    zone_name = zone.name if zone else "Unknown"
    db_movement = MovementDB(product_id=movement.product_id, product_name=product.name, zone_name=zone_name, movement_type=movement.movement_type, quantity=movement.quantity, note=movement.note)
    db.add(db_movement)
    db.commit()
    db.refresh(db_movement)
    db.close()
    return {"id": db_movement.id, "product_id": movement.product_id, "product_name": product.name, "zone_name": zone_name, "movement_type": movement.movement_type, "quantity": movement.quantity}

@api_router.get("/stock-movements")
def get_movements():
    db = SessionLocal()
    movements = db.query(MovementDB).order_by(MovementDB.created_at.desc()).all()
    result = [{"id": m.id, "product_id": m.product_id, "product_name": m.product_name, "zone_name": m.zone_name, "movement_type": m.movement_type, "quantity": m.quantity, "note": m.note, "created_at": str(m.created_at)} for m in movements]
    db.close()
    return result

@api_router.get("/stats")
def get_stats():
    db = SessionLocal()
    total_products = db.query(ProductDB).count()
    total_zones = db.query(ZoneDB).count()
    total_stock = sum([p.quantity for p in db.query(ProductDB).all()])
    total_movements = db.query(MovementDB).count()
    db.close()
    return {"total_products": total_products, "total_zones": total_zones, "total_stock": total_stock, "total_movements": total_movements}

@api_router.get("/")
def root():
    return {"message": "Mon Stock API"}

app.include_router(api_router)
app.add_middleware(CORSMiddleware, allow_credentials=True, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
