import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["VOLTPILOT_DB"] = str(ROOT / "data" / "test_voltpilot.db")

from fastapi.testclient import TestClient
from app.main import app
from app.database import connect
from app.seed import seed
from app.services import engine


def setup_module():
    conn = connect()
    seed(conn)
    engine.refresh(conn)
    conn.close()


client = TestClient(app)


def test_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_dashboard_and_recommendations():
    dash = client.get("/api/dashboard")
    assert dash.status_code == 200
    assert dash.json()["kpis"]["attention_items"] >= 1
    recs = client.get("/api/recommendations")
    assert recs.status_code == 200
    assert len(recs.json()["items"]) >= 1


def test_invalid_decision():
    res = client.post("/api/actions/99999/approve", json={})
    assert res.status_code == 404
