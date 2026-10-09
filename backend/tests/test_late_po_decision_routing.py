"""Overdue POs must get an executable recommendation that Goal 07 can open."""
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["VOLTPILOT_DB"] = str(ROOT / "data" / f"test_late_po_{uuid.uuid4().hex}.db")

from fastapi.testclient import TestClient
from app.main import app
from app.database import get_conn
from app.seed import seed


def test_overdue_open_po_gets_expedite_option_even_if_status_not_delayed():
    with TestClient(app) as client:
        # This test requires a known overdue-PO scenario. Seed it explicitly for
        # this test only; normal application startup remains free of demo history.
        with get_conn() as conn:
            seed(conn)
            po = conn.execute("SELECT * FROM purchase_orders WHERE po_number = 'PO-88421'").fetchone()
            assert po is not None
            conn.execute(
                "UPDATE purchase_orders SET status = 'ordered', expected_at = '2026-10-06' WHERE id = ?",
                (po["id"],),
            )

        response = client.get("/api/recommendations?refresh=true")
        assert response.status_code == 200, response.text
        items = response.json()["items"]
        matching = [
            item for item in items
            if item["product_name"] == "StormX Wired Gaming Headset"
            and item["store_name"] == "VoltKart Mumbai Andheri"
            and any(
                option.get("type") == "expedite_po"
                and option.get("payload", {}).get("purchase_order_id") == po["id"]
                for option in item.get("options", [])
            )
        ]
        assert matching, "Expected an actionable recommendation containing the overdue PO expedite option"

        risk = client.get("/api/risk-areas/purchase-orders")
        assert risk.status_code == 200, risk.text
        body = risk.json()
        assert any(f.get("metrics", {}).get("po_number") == "PO-88421" for f in body.get("findings", []))
