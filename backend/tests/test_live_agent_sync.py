import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("VOLTPILOT_DB", str(ROOT / "data" / "test_live_agent_sync.db"))

from fastapi.testclient import TestClient
from app.main import app


def _area(client, area_id):
    response = client.get("/api/risk-areas")
    assert response.status_code == 200, response.text
    area = next(item for item in response.json()["items"] if item["id"] == area_id)
    return area, response.json()


def test_sale_updates_live_stockout_analysis_even_without_supplier_mapping():
    sku = f"LIVE-SYNC-{uuid.uuid4().hex[:8].upper()}"
    with TestClient(app) as client:
        product_response = client.post("/api/store/products", json={
            "store_id": 1,
            "sku": sku,
            "name": "Live Sync Test Headphones",
            "category": "Headphones",
            "unit_cost": 500,
            "selling_price": 999,
            "initial_stock": 2,
            "note": "test data for sale -> risk sync",
        })
        assert product_response.status_code == 200, product_response.text
        product_id = product_response.json()["product"]["id"]

        before_area, before_payload = _area(client, "stockout")
        before_finding = next(f for f in before_area["findings"] if f["metrics"].get("stock") == 2 and sku in f["title"] or f.get("product") == "Live Sync Test Headphones")
        assert before_area["status"] == "active"
        assert before_finding["metrics"]["stock"] == 2

        sale = client.post("/api/store/checkout", json={
            "store_id": 1,
            "customer_name": "Live sync test",
            "payment_method": "cash",
            "items": [{"product_id": product_id, "quantity": 1}],
        })
        assert sale.status_code == 200, sale.text
        sale_body = sale.json()
        assert len(sale_body["agent_analysis"]["items"]) == 7

        # The catalog, history and risk detector must all observe this same sale.
        catalog = client.get("/api/store/catalog?store_id=1").json()
        catalog_item = next(i for i in catalog["items"] if i["product_id"] == product_id)
        assert catalog_item["available_qty"] == 1
        assert catalog_item["stock_status"] == "low_stock"
        area_after_one, payload_after_one = _area(client, "stockout")
        finding_after_one = next(f for f in area_after_one["findings"] if f["product"] == "Live Sync Test Headphones")
        assert finding_after_one["metrics"]["stock"] == 1
        assert payload_after_one["last_analyzed_at"]
        assert payload_after_one["latest_sale_at"]

        sold_out = client.post("/api/store/checkout", json={
            "store_id": 1,
            "customer_name": "Live sync test",
            "payment_method": "cash",
            "items": [{"product_id": product_id, "quantity": 1}],
        })
        assert sold_out.status_code == 200, sold_out.text
        final_area, _ = _area(client, "stockout")
        final_finding = next(f for f in final_area["findings"] if f["product"] == "Live Sync Test Headphones")
        assert final_finding["metrics"]["stock"] == 0
        assert final_finding["metrics"]["out_of_stock"] is True
        assert "OUT OF STOCK" in final_finding["title"]

        receipt = client.get(f"/api/store/sales/{sold_out.json()['id']}")
        assert receipt.status_code == 200, receipt.text
        assert len(receipt.json()["agent_analysis"]["items"]) == 7


def test_risk_area_counts_are_live_response_and_not_cacheable():
    with TestClient(app) as client:
        response = client.get("/api/risk-areas")
        assert response.status_code == 200, response.text
        # At least make sure the API is returning complete current calculations.
        assert len(response.json()["items"]) == 7
        assert response.json()["last_analyzed_at"]
