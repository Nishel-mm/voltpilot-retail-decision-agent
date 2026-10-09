import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("VOLTPILOT_DB", str(ROOT / "data" / "test_voltpilot.db"))

from fastapi.testclient import TestClient
from app.main import app


def test_store_catalog_contains_product_departments():
    with TestClient(app) as client:
        response = client.get("/api/store/catalog?store_id=1")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["items"]
        assert "Laptops" in body["categories"]
        assert "Headphones" in body["categories"]
        assert all(item["available_qty"] >= 0 for item in body["items"])


def test_checkout_decrements_stock_and_persists_receipt():
    with TestClient(app) as client:
        catalog = client.get("/api/store/catalog?store_id=1").json()
        product = next(item for item in catalog["items"] if item["sku"] == "VK-MN-24")
        before = product["available_qty"]
        assert before >= 1

        response = client.post("/api/store/checkout", json={
            "store_id": 1, "customer_name": "Demo QA", "payment_method": "upi",
            "items": [{"product_id": product["product_id"], "quantity": 1}],
        })
        assert response.status_code == 200, response.text
        sale = response.json()
        assert sale["status"] == "sold"
        assert sale["simulated"] is True
        assert sale["total_amount"] > sale["subtotal"]

        after_catalog = client.get("/api/store/catalog?store_id=1").json()
        after = next(item for item in after_catalog["items"] if item["sku"] == "VK-MN-24")["available_qty"]
        assert after == before - 1

        receipt = client.get(f"/api/store/sales/{sale['id']}")
        assert receipt.status_code == 200
        assert receipt.json()["sale"]["invoice_number"] == sale["invoice_number"]
        assert receipt.json()["items"][0]["quantity"] == 1

        history = client.get("/api/store/sales?store_id=1")
        assert history.status_code == 200
        assert any(item["invoice_number"] == sale["invoice_number"] for item in history.json()["items"])


def test_checkout_rejects_quantity_above_available_stock():
    with TestClient(app) as client:
        catalog = client.get("/api/store/catalog?store_id=1").json()
        product = next(item for item in catalog["items"] if item["sku"] == "VK-LT-16")
        before = product["available_qty"]
        response = client.post("/api/store/checkout", json={
            "store_id": 1, "payment_method": "cash",
            "items": [{"product_id": product["product_id"], "quantity": before + 1}],
        })
        assert response.status_code == 409
        after = client.get("/api/store/catalog?store_id=1").json()
        assert next(item for item in after["items"] if item["sku"] == "VK-LT-16")["available_qty"] == before
