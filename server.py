
from fastapi import FastAPI, APIRouter, HTTPException
from starlette.middleware.cors import CORSMiddleware
import os
import random
import string
import psycopg2
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://localhost/monstock')

def get_db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS zones (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255),
        description TEXT DEFAULT ''
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS products (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255),
        reference VARCHAR(255),
        zone_id INTEGER,
        quantity INTEGER DEFAULT 0
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS stock_movements (
        id SERIAL PRIMARY KEY,
        product_id INTEGER,
        product_name VARCHAR(255),
        zone_name VARCHAR(255),
        movement_type VARCHAR(10),
        quantity INTEGER,
        note TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    cur.close()
    conn.close()

init_db()

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

@api_router.post("/zones")
def create_zone(zone: ZoneCreate):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO zones (name, description) VALUES (%s, %s) RETURNING id", (zone.name, zone.description))
    zone_id = cur.fetchone()['id']
    conn.commit()
    cur.close()
    conn.close()
    return {"id": zone_id, "name": zone.name, "description": zone.description}

@api_router.get("/zones")
def get_zones():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM zones")
    zones = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(z) for z in zones]

@api_router.delete("/zones/{zone_id}")
def delete_zone(zone_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM zones WHERE id = %s", (zone_id,))
    cur.execute("DELETE FROM products WHERE zone_id = %s", (zone_id,))
    conn.commit()
    cur.close()
    conn.close()
    return {"message": "Zone deleted"}

@api_router.post("/products")
def create_product(product: ProductCreate):
    ref = product.reference
    if not ref or ref.strip() == "":
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        random_chars = ''.join(random.choices(string.digits, k=4))
        ref = f"MS-{timestamp}-{random_chars}"
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO products (name, reference, zone_id, quantity) VALUES (%s, %s, %s, %s) RETURNING id", (product.name, ref, product.zone_id, product.quantity))
    product_id = cur.fetchone()['id']
    conn.commit()
    cur.close()
    conn.close()
    return {"id": product_id, "name": product.name, "reference": ref, "zone_id": product.zone_id, "quantity": product.quantity}

@api_router.get("/products")
def get_products(zone_id: Optional[int] = None, search: Optional[str] = None):
    conn = get_db()
    cur = conn.cursor()
    query = "SELECT * FROM products WHERE 1=1"
    params = []
    if zone_id:
        query += " AND zone_id = %s"
        params.append(zone_id)
    if search:
        query += " AND (name ILIKE %s OR reference ILIKE %s)"
        params.extend([f"%{search}%", f"%{search}%"])
    cur.execute(query, params)
    products = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(p) for p in products]

@api_router.get("/products/by-reference/{reference}")
def get_product_by_reference(reference: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM products WHERE reference = %s", (reference,))
    product = cur.fetchone()
    cur.close()
    conn.close()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return dict(product)

@api_router.delete("/products/{product_id}")
def delete_product(product_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM products WHERE id = %s", (product_id,))
    cur.execute("DELETE FROM stock_movements WHERE product_id = %s", (product_id,))
    conn.commit()
    cur.close()
    conn.close()
    return {"message": "Product deleted"}

@api_router.post("/stock-movements")
def create_movement(movement: MovementCreate):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM products WHERE id = %s", (movement.product_id,))
    product = cur.fetchone()
    if not product:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Product not found")
    if movement.movement_type == "out" and product['quantity'] < movement.quantity:
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Insufficient stock")
    new_qty = product['quantity'] + movement.quantity if movement.movement_type == "in" else product['quantity'] - movement.quantity
    cur.execute("UPDATE products SET quantity = %s WHERE id = %s", (new_qty, movement.product_id))
    cur.execute("SELECT name FROM zones WHERE id = %s", (product['zone_id'],))
    zone = cur.fetchone()
    zone_name = zone['name'] if zone else "Unknown"
    cur.execute("INSERT INTO stock_movements (product_id, product_name, zone_name, movement_type, quantity, note) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id", (movement.product_id, product['name'], zone_name, movement.movement_type, movement.quantity, movement.note))
    mv_id = cur.fetchone()['id']
    conn.commit()
    cur.close()
    conn.close()
    return {"id": mv_id, "product_id": movement.product_id, "product_name": product['name'], "zone_name": zone_name, "movement_type": movement.movement_type, "quantity": movement.quantity}

@api_router.get("/stock-movements")
def get_movements():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM stock_movements ORDER BY created_at DESC")
    movements = cur.fetchall()
    cur.close()
    conn.close()
    return [{"id": m['id'], "product_id": m['product_id'], "product_name": m['product_name'], "zone_name": m['zone_name'], "movement_type": m['movement_type'], "quantity": m['quantity'], "note": m['note'], "created_at": str(m['created_at'])} for m in movements]

@api_router.get("/stats")
def get_stats():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as count FROM products")
    total_products = cur.fetchone()['count']
    cur.execute("SELECT COUNT(*) as count FROM zones")
    total_zones = cur.fetchone()['count']
    cur.execute("SELECT COALESCE(SUM(quantity), 0) as total FROM products")
    total_stock = cur.fetchone()['total']
    cur.execute("SELECT COUNT(*) as count FROM stock_movements")
    total_movements = cur.fetchone()['count']
    cur.close()
    conn.close()
    return {"total_products": total_products, "total_zones": total_zones, "total_stock": total_stock, "total_movements": total_movements}

@api_router.get("/")
def root():
    return {"message": "Mon Stock API"}

app.include_router(api_router)
app.add_middleware(CORSMiddleware, allow_credentials=True, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
