"""Bootstrap the initial Store & POS catalogue without synthetic analytics.

Used only for a brand-new hosted PostgreSQL database. It creates the familiar
VoltPilot store locations, the existing starter catalog, and opening inventory
so the Store & POS is usable on first launch. It deliberately does NOT create
sales history, transactions, suppliers, supplier offers, promotions, purchase
orders, forecasts, recommendations, or historical audit events.

Quantities and prices are starter values carried over from the existing local
prototype so the UI is not blank. Retailers should edit/replace them to match
actual opening counts and prices before relying on the system operationally.
"""
from __future__ import annotations
from datetime import date

from ..config import business_date

STORES = [
    ("MUM", "VoltKart Mumbai Andheri", "Mumbai", "West"),
    ("BLR", "VoltKart Bengaluru Koramangala", "Bengaluru", "South"),
    ("DEL", "VoltKart Delhi Connaught Place", "New Delhi", "North"),
    ("HYD", "VoltKart Hyderabad Banjara Hills", "Hyderabad", "South"),
]

# sku, name, category, unit_cost, selling_price, stock_by_store_code
PRODUCTS = [
    ("VK-TV-55", "NovaVision 55-inch Smart TV", "Home Entertainment", 28990, 39990, {"MUM": 4, "BLR": 12, "DEL": 6, "HYD": 5}),
    ("VK-EB-01", "AirBeat TWS Wireless Earbuds", "Audio", 420, 799, {"MUM": 48, "BLR": 40, "DEL": 6, "HYD": 36}),
    ("VK-SW-18", "PulseFit Smartwatch 1.8\"", "Wearables", 640, 1199, {"MUM": 18, "BLR": 22, "DEL": 20, "HYD": 19}),
    ("VK-PB-10", "SlimCell 10000mAh Power Bank", "Charging", 310, 649, {"MUM": 30, "BLR": 28, "DEL": 32, "HYD": 26}),
    ("VK-SP-01", "BoomMini Bluetooth Speaker", "Audio", 260, 549, {"MUM": 24, "BLR": 22, "DEL": 20, "HYD": 8}),
    ("VK-HS-01", "StormX Wired Gaming Headset", "Audio", 480, 899, {"MUM": 3, "BLR": 10, "DEL": 9, "HYD": 8}),
    ("VK-SB-01", "VoltBar 2.1 Soundbar", "Home Entertainment", 4200, 6990, {"MUM": 4, "BLR": 3, "DEL": 3, "HYD": 14}),
    ("VK-MS-01", "SilentClick Wireless Mouse", "Computer", 140, 299, {"MUM": 60, "BLR": 55, "DEL": 58, "HYD": 52}),
    ("VK-LT-14", "OrbitBook 14-inch Laptop", "Laptops", 42000, 54990, {"MUM": 4, "BLR": 6, "DEL": 3, "HYD": 2}),
    ("VK-LT-16", "OrbitBook Pro 16-inch Laptop", "Laptops", 62000, 79990, {"MUM": 2, "BLR": 3, "DEL": 2, "HYD": 1}),
    ("VK-HP-02", "StudioWave Wireless Headphones", "Headphones", 1900, 3499, {"MUM": 20, "BLR": 18, "DEL": 9, "HYD": 12}),
    ("VK-MN-24", "VisionPlus 24-inch Monitor", "Monitors", 5400, 7999, {"MUM": 7, "BLR": 8, "DEL": 5, "HYD": 6}),
    ("VK-KB-01", "MechType Wireless Keyboard", "Accessories", 900, 1799, {"MUM": 18, "BLR": 12, "DEL": 14, "HYD": 10}),
]


def bootstrap_store_catalog(conn) -> bool:
    """Idempotently add starter stores/catalog/opening stock only on an empty DB."""
    store_count = int(conn.execute("SELECT COUNT(*) AS c FROM stores").fetchone()["c"])
    product_count = int(conn.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"])
    if store_count or product_count:
        return False

    for code, name, city, region in STORES:
        conn.execute(
            "INSERT INTO stores (code, name, city, region) VALUES (?, ?, ?, ?)",
            (code, name, city, region),
        )
    store_rows = conn.execute("SELECT id, code FROM stores ORDER BY id").fetchall()
    store_ids = {row["code"]: int(row["id"]) for row in store_rows}
    today = business_date().isoformat()

    for sku, name, category, cost, price, stock in PRODUCTS:
        cur = conn.execute(
            "INSERT INTO products (sku, name, category, unit_cost, selling_price) VALUES (?, ?, ?, ?, ?) RETURNING id",
            (sku, name, category, cost, price),
        )
        product_id = int(cur.fetchone()["id"])
        for code, store_id in store_ids.items():
            # Opening stock is current stock, not historical sales/forecast evidence.
            conn.execute(
                """INSERT INTO inventory (product_id, store_id, quantity, days_on_hand, last_counted_at, markdown_review)
                   VALUES (?, ?, ?, 0, ?, 0)""",
                (product_id, store_id, int(stock.get(code, 0)), today),
            )
    return True
