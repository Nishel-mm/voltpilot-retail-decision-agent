"""Forecasting must train from observed POS/import data, never seeded demo history."""
import os
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["VOLTPILOT_DB"] = str(ROOT / "data" / f"test_observed_forecast_{uuid.uuid4().hex}.db")

from fastapi.testclient import TestClient
from app.main import app


def _csv_history(days=48):
    rows = ["date,sku,store_code,units"]
    start = date(2026, 7, 1)
    for index in range(days):
        # This dataset exists only inside the test, to exercise import/training.
        units = [0, 1, 2, 1, 3, 2, 1][index % 7]
        rows.append(f"{(start + timedelta(days=index)).isoformat()},VK-EB-01,MUM,{units}")
        rows.append(f"{(start + timedelta(days=index)).isoformat()},VK-HS-01,DEL,{(index + 2) % 4}")
    return "\n".join(rows) + "\n"


def test_seeded_demo_sales_do_not_make_forecast_ready_or_trainable():
    with TestClient(app) as client:
        status = client.get("/api/forecast/status")
        assert status.status_code == 200, status.text
        body = status.json()
        assert body["pos_transactions"] == 0
        assert body["imported_daily_rows"] == 0
        assert body["training_examples_available"] == 0
        assert body["ready_to_train"] is False
        blocked = client.post("/api/forecast/train")
        assert blocked.status_code == 400, blocked.text
        assert "will not generate synthetic training history" in blocked.json()["detail"]


def test_csv_import_trains_on_only_observed_rows_and_pos_change_stales_model():
    with TestClient(app) as client:
        imported = client.post("/api/forecast/import-history", json={"csv_text": _csv_history()})
        assert imported.status_code == 200, imported.text
        assert imported.json()["imported_rows"] == 96

        status = client.get("/api/forecast/status").json()
        assert status["ready_to_train"] is True
        assert status["imported_daily_rows"] == 96
        assert status["pos_transactions"] == 0
        assert status["data_origin"].startswith("Observed Store & POS transactions")

        training = client.post("/api/forecast/train")
        assert training.status_code == 200, training.text
        trained = training.json()
        assert trained["trained"] is True
        assert trained["training_samples"] >= 20
        assert trained["test_samples"] >= 7
        assert "generated synthetic history" in trained["data_origin"]
        assert trained["history_days"] == 48

        status_after_train = client.get("/api/forecast/status").json()
        assert status_after_train["stale"] is False

        # A real user-entered sale is a new observation and makes the prior model stale.
        sku = f"STALE-{uuid.uuid4().hex[:8].upper()}"
        product = client.post("/api/store/products", json={
            "store_id": 1, "sku": sku, "name": "Stale-model test product", "category": "Accessories",
            "unit_cost": 10, "selling_price": 20, "initial_stock": 2,
        })
        assert product.status_code == 200, product.text
        pid = product.json()["product"]["id"]
        sale = client.post("/api/store/checkout", json={"store_id": 1, "payment_method": "cash", "items": [{"product_id": pid, "quantity": 1}]})
        assert sale.status_code == 200, sale.text
        status_after_sale = client.get("/api/forecast/status").json()
        assert status_after_sale["stale"] is True
        assert status_after_sale["selected_forecaster"] != "ridge_regression"


def test_import_rejects_unknown_sku_and_pos_date_overlap():
    with TestClient(app) as client:
        bad = client.post("/api/forecast/import-history", json={"csv_text": "date,sku,store_code,units\n2026-09-01,UNKNOWN,MUM,1\n"})
        assert bad.status_code == 422
        assert "unknown SKU" in bad.json()["detail"]

        # Create POS data first, then import the same product/store/day from its transaction timestamp.
        sale = client.post("/api/store/checkout", json={"store_id": 1, "payment_method": "cash", "items": [{"product_id": 2, "quantity": 1}]})
        assert sale.status_code == 200, sale.text
        pos_date = sale.json()["created_at"][:10]
        overlap = client.post("/api/forecast/import-history", json={"csv_text": f"date,sku,store_code,units\n{pos_date},VK-EB-01,MUM,5\n"})
        assert overlap.status_code == 422
        assert "already has POS sales" in overlap.json()["detail"]
