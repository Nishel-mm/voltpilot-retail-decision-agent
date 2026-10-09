import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("VOLTPILOT_DB", str(ROOT / "data" / "test_product_stock.db"))

from fastapi.testclient import TestClient
from app.main import app


def test_new_product_appears_with_per_store_stock_and_flags():
    with TestClient(app) as client:
        response = client.post("/api/store/products", json={
            "store_id": 1, "sku": "TEST-NEW-900", "name": "Test New Headphones",
            "category": "Headphones", "unit_cost": 1200, "selling_price": 1999, "initial_stock": 5,
            "note": "QA new product",
        })
        assert response.status_code == 200, response.text
        created = response.json()
        product_id = created["product"]["id"]
        assert created["product"]["stock_status"] == "in_stock"
        assert len(created["stock_by_store"]) == 1
        catalog = client.get("/api/store/catalog?store_id=1").json()
        item = next(x for x in catalog["items"] if x["product_id"] == product_id)
        assert item["available_qty"] == 5
        assert item["stock_status"] == "in_stock"
        other_items = client.get("/api/store/catalog?store_id=2").json()["items"]
        assert not any(x["product_id"] == product_id for x in other_items)


def test_duplicate_sku_is_rejected():
    with TestClient(app) as client:
        body = {"store_id": 1, "sku": "TEST-DUP-900", "name": "Duplicate test", "category": "Other", "unit_cost": 1, "selling_price": 2, "initial_stock": 1}
        first = client.post("/api/store/products", json=body)
        assert first.status_code == 200, first.text
        second = client.post("/api/store/products", json=body)
        assert second.status_code == 409


def test_restock_increments_stock_and_records_movement():
    with TestClient(app) as client:
        catalog = client.get("/api/store/catalog?store_id=1").json()
        product = next(x for x in catalog["items"] if x["sku"] == "VK-LT-14")
        before = product["available_qty"]
        response = client.post("/api/store/stock-receipts", json={
            "store_id": 1, "product_id": product["product_id"], "quantity": 7, "note": "Supplier delivery received"
        })
        assert response.status_code == 200, response.text
        assert response.json()["quantity_after"] == before + 7
        updated = client.get("/api/store/catalog?store_id=1").json()
        after = next(x for x in updated["items"] if x["product_id"] == product["product_id"])
        assert after["available_qty"] == before + 7
        movements = client.get(f"/api/store/inventory-movements?store_id=1&product_id={product['product_id']}").json()["items"]
        assert any(m["movement_type"] == "stock_receipt" and m["quantity_delta"] == 7 for m in movements)


def test_out_of_stock_item_is_flagged_and_cannot_be_sold():
    with TestClient(app) as client:
        response = client.post("/api/store/products", json={
            "store_id": 1, "sku": "TEST-OOS-900", "name": "Test Sold Out Product",
            "category": "Accessories", "unit_cost": 100, "selling_price": 200, "initial_stock": 0
        })
        assert response.status_code == 200, response.text
        product_id = response.json()["product"]["id"]
        product = next(x for x in client.get("/api/store/catalog?store_id=1").json()["items"] if x["product_id"] == product_id)
        assert product["available_qty"] == 0
        assert product["stock_status"] == "out_of_stock"
        sale = client.post("/api/store/checkout", json={"store_id": 1, "payment_method": "upi", "items": [{"product_id": product_id, "quantity": 1}]})
        assert sale.status_code == 409
