from fastapi import FastAPI, APIRouter, HTTPException
from starlette.middleware.cors import CORSMiddleware
import os
import random
import string
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import databases
import sqlalchemy

DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://localhost/monstock')

database = databases.Database(DATABASE_URL)
metadata = sqlalchemy.MetaData()

zones = sqlalchemy.Table(
    "zones", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("name", sqlalchemy.String(255)),
    sqlalchemy.Column("description", sqlalchemy.Text, default=""),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=datetime.utcnow),
    sqlalchemy.Column("updated_at", sqlalchemy.DateTime, default=datetime.utcnow),
)

products = sqlalchemy.Table(
    "products", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("name", sqlalchemy.String(255)),
    sqlalchemy.Column("reference", sqlalchemy.String(255)),
    sqlalchemy.Column("zone_id", sqlalchemy.Integer),
    sqlalchemy.Column("quantity", sqlalchemy.Integer, default=0),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=datetime.utcnow),
    sqlalchemy.Column("updated_at", sqlalchemy.DateTime, default=datetime.utcnow),
)

stock_movements = sqlalchemy.Table(
    "stock_movements", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("product_id", sqlalchemy.Integer),
    sqlalchemy.Column("product_name", sqlalchemy.String(255)),
    sqlalchemy.Column("zone_name", sqlalchemy.String(255)),
    sqlalchemy.Column("movement_type", sqlalchemy.String(10)),
    sqlalchemy.Column("quantity", sqlalchemy.Integer),
    sqlalchemy.Column("note", sqlalchemy.Text, default=""),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=datetime.utcnow),
)

engine = sqlalchemy.create_engine(DATABASE_URL)
metadata.create_all(engine)

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

@app.on_event("startup")
async def startup():
    await database.connect()

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

@api_router.post("/zones")
async def create_zone(zone: ZoneCreate):
    query = zones.insert().values(name=zone.name, description=zone.description, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
    last_id = await database.execute(query)
    return {"id": last_id, "name": zone.name, "description": zone.description}

@api_router.get("/zones")
async def get_zones():
    query = zones.select()
    rows = await database.fetch_all(query)
    return [{"id": r["id"], "name": r["name"], "description": r["description"]} for r in rows]

@api_router.delete("/zones/{zone_id}")
async def delete_zone(zone_id: int):
    await database.execute(zones.delete().where(zones.c.id == zone_id))
    await database.execute(products.delete().where(products.c.zone_id == zone_id))
    return {"message": "Zone deleted"}

@api_router.post("/products")
async def create_product(product: ProductCreate):
    ref = product.reference
    if not ref or ref.strip() == "":
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        random_chars = ''.join(random.choices(string.digits, k=4))
        ref = f"MS-{timestamp}-{random_chars}"
    query = products.insert().values(name=product.name, reference=ref, zone_id=product.zone_id, quantity=product.quantity, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
    last_id = await database.execute(query)
    return {"id": last_id, "name": product.name, "reference": ref, "zone_id": product.zone_id, "quantity": product.quantity}

@api_router.get("/products")
async def get_products(zone_id: Optional[int] = None, search: Optional[str] = None):
    query = products.select()
    if zone_id:
        query = query.where(products.c.zone_id == zone_id)
    if search:
        query = query.where(products.c.name.ilike(f"%{search}%") | products.c.reference.ilike(f"%{search}%"))
    rows = await database.fetch_all(query)
    return [{"id": r["id"], "name": r["name"], "reference": r["reference"], "zone_id": r["zone_id"], "quantity": r["quantity"]} for r in rows]

@api_router.get("/products/by-reference/{reference}")
async def get_product_by_reference(reference: str):
    query = products.select().where(products.c.reference == reference)
    row = await database.fetch_one(query)
    if not row:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"id": row["id"], "name": row["name"], "reference": row["reference"], "zone_id": row["zone_id"], "quantity": row["quantity"]}

@api_router.delete("/products/{product_id}")
async def delete_product(product_id: int):
    await database.execute(products.delete().where(products.c.id == product_id))
    await database.execute(stock_movements.delete().where(stock_movements.c.product_id == product_id))
    return {"message": "Product deleted"}

@api_router.post("/stock-movements")
async def create_movement(movement: MovementCreate):
    query = products.select().where(products.c.id == movement.product_id)
    product = await database.fetch_one(query)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if movement.movement_type == "out" and product["quantity"] < movement.quantity:
        raise HTTPException(status_code=400, detail="Insufficient stock")
    new_qty = product["quantity"] + movement.quantity if movement.movement_type == "in" else product["quantity"] - movement.quantity
    await database.execute(products.update().where(products.c.id == movement.product_id).values(quantity=new_qty))
    zone_query = zones.select().where(zones.c.id == product["zone_id"])
    zone = await database.fetch_one(zone_query)
    zone_name = zone["name"] if zone else "Unknown"
    mv_query = stock_movements.insert().values(product_id=movement.product_id, product_name=product["name"], zone_name=zone_name, movement_type=movement.movement_type, quantity=movement.quantity, note=movement.note, created_at=datetime.utcnow())
    last_id = await database.execute(mv_query)
    return {"id": last_id, "product_id": movement.product_id, "product_name": product["name"], "zone_name": zone_name, "movement_type": movement.movement_type, "quantity": movement.quantity, "note": movement.note}

@api_router.get("/stock-movements")
async def get_movements():
    query = stock_movements.select().order_by(stock_movements.c.created_at.desc())
    rows = await database.fetch_all(query)
    return [{"id": r["id"], "product_id": r["product_id"], "product_name": r["product_name"], "zone_name": r["zone_name"], "movement_type": r["movement_type"], "quantity": r["quantity"], "note": r["note"], "created_at": str(r["created_at"])} for r in rows]

@api_router.get("/stats")
async def get_stats():
    total_products = await database.fetch_val(sqlalchemy.select(sqlalchemy.func.count()).select_from(products))
    total_zones = await database.fetch_val(sqlalchemy.select(sqlalchemy.func.count()).select_from(zones))
    total_stock = await database.fetch_val(sqlalchemy.select(sqlalchemy.func.coalesce(sqlalchemy.func.sum(products.c.quantity), 0)))
    total_movements = await database.fetch_val(sqlalchemy.select(sqlalchemy.func.count()).select_from(stock_movements))
    return {"total_products": total_products or 0, "total_zones": total_zones or 0, "total_stock": total_stock or 0, "total_movements": total_movements or 0}

@api_router.get("/")
async def root():
    return {"message": "Mon Stock API"}

app.include_router(api_router)
app.add_middleware(CORSMiddleware, allow_credentials=True, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
