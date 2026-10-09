"""API smoke tests for the empty-analytics startup policy.

The store catalogue/opening stock may be initialized on first launch, but the
API must not invent sales history, recommendations, supplier records, POs, or
historical audit activity just to make the dashboard appear busy.
"""
from fastapi.testclient import TestClient
from app.main import app


def test_health():
    with TestClient(app) as client:
        response = client.get("/api/health")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "ok"
        assert body["service"] == "VoltPilot"


def test_dashboard_and_recommendations():
    # Using TestClient as a context manager runs FastAPI startup so schema setup
    # completes before the request. The test DB is unique per test via conftest.
    with TestClient(app) as client:
        dashboard = client.get("/api/dashboard")
        assert dashboard.status_code == 200, dashboard.text
        kpis = dashboard.json()["kpis"]
        assert kpis["attention_items"] == 0
        assert kpis["critical_or_high"] == 0
        assert kpis["delayed_pos"] == 0
        assert kpis["actions_logged"] == 0
        # Starter catalogue/opening-stock setup is permitted; it is not sales data.
        assert kpis["units_on_hand"] > 0

        recommendations = client.get("/api/recommendations")
        assert recommendations.status_code == 200, recommendations.text
        assert recommendations.json()["items"] == []


def test_invalid_decision():
    with TestClient(app) as client:
        response = client.post("/api/actions/99999/approve", json={})
        assert response.status_code == 404, response.text
