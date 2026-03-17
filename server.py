from fastapi import FastAPI, APIRouter, HTTPException
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import random
import string
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from bson import ObjectId

mongo_url = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
db_name = os.environ.get('DB_NAME', 'monstock_db')
client = AsyncIOMotorClient(mongo_url)
db = client[db_name]

app = FastAPI()
api_router = APIRouter(prefix="/api")

class ZoneCreate(BaseModel):
    name: str
    description: Optional[str] = ""

class ProductCreate(BaseModel):
    name: str
    reference: Optional[str] = ""
    zone_id: str
    quantity: int = 0

class MovementCreate(BaseModel):
    product_id: str
    movement_type: str
    quantity: int
    note: Optional[str] = ""

@api_router.post("/zones")
async def create_zone(zone: ZoneCreate):
    zone_dict = zone.dict()
    zone_dict["created_at"] = datetime.utcnow()
    zone_dict["updated_at"] = datetime.utcnow()
    result = await db.zones.insert_one(zone_dict)
    zone_dict["id"] = str(result.inserted_id)
    return zone_dict

@api_router.get("/zones")
async def get_zones():
    zones = await db.zones.find().to_list(1000)
    return [{**z, "id": str(z["_id"])} for z in zones]

@api_router.delete("/zones/{zone_id}")
async def delete_zone(zone_id: str):
    await db.zones.delete_one({"_id": ObjectId(zone_id)})
    await db.products.delete_many({"zone_id": zone_id})
    return {"message": "Zone deleted"}

@api_router.post("/products")
async def create_product(product: ProductCreate):
    product_dict = product.dict()
    # Auto-generate reference if empty
    if not product_dict.get("reference") or product_dict["reference"].strip() == "":
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        random_chars = ''.join(random.choices(string.digits, k=4))
        product_dict["reference"] = f"MS-{timestamp}-{random_chars}"
    product_dict["created_at"] = datetime.utcnow()
    product_dict["updated_at"] = datetime.utcnow()
    result = await db.products.insert_one(product_dict)
    product_dict["id"] = str(result.inserted_id)
    return product_dict

@api_router.get("/products")
async def get_products(zone_id: Optional[str] = None, search: Optional[str] = None):
    query = {}
    if zone_id:
        query["zone_id"] = zone_id
    if search:
        query["$or"] = [{"name": {"$regex": search, "$options": "i"}}, {"reference": {"$regex": search, "$options": "i"}}]
    products = await db.products.find(query).to_list(1000)
    return [{**p, "id": str(p["_id"])} for p in products]

@api_router.get("/products/by-reference/{reference}")
async def get_product_by_reference(reference: str):
    product = await db.products.find_one({"reference": reference})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return {**product, "id": str(product["_id"])}

@api_router.delete("/products/{product_id}")
async def delete_product(product_id: str):
    await db.products.delete_one({"_id": ObjectId(product_id)})
    await db.stock_movements.delete_many({"product_id": product_id})
    return {"message": "Product deleted"}

@api_router.post("/stock-movements")
async def create_movement(movement: MovementCreate):
    product = await db.products.find_one({"_id": ObjectId(movement.product_id)})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if movement.movement_type == "out" and product["quantity"] < movement.quantity:
        raise HTTPException(status_code=400, detail="Insufficient stock")
    new_qty = product["quantity"] + movement.quantity if movement.movement_type == "in" else product["quantity"] - movement.quantity
    await db.products.update_one({"_id": ObjectId(movement.product_id)}, {"$set": {"quantity": new_qty}})
    zone = await db.zones.find_one({"_id": ObjectId(product["zone_id"])})
    movement_dict = movement.dict()
    movement_dict["product_name"] = product["name"]
    movement_dict["zone_name"] = zone["name"] if zone else "Unknown"
    movement_dict["created_at"] = datetime.utcnow()
    result = await db.stock_movements.insert_one(movement_dict)
    movement_dict["id"] = str(result.inserted_id)
    return movement_dict

@api_router.get("/stock-movements")
async def get_movements():
    movements = await db.stock_movements.find().sort("created_at", -1).to_list(1000)
    return [{**m, "id": str(m["_id"])} for m in movements]

@api_router.get("/stats")
async def get_stats():
    total_products = await db.products.count_documents({})
    total_zones = await db.zones.count_documents({})
    pipeline = [{"$group": {"_id": None, "total": {"$sum": "$quantity"}}}]
    result = await db.products.aggregate(pipeline).to_list(1)
    total_stock = result[0]["total"] if result else 0
    total_movements = await db.stock_movements.count_documents({})
    return {"total_products": total_products, "total_zones": total_zones, "total_stock": total_stock, "total_movements": total_movements}

@api_router.get("/")
async def root():
    return {"message": "Mon Stock API"}

app.include_router(api_router)
app.add_middleware(CORSMiddleware, allow_credentials=True, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])redentials=True, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
