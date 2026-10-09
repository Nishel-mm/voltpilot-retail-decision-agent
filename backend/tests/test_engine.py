import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["VOLTPILOT_DB"] = str(ROOT / "data" / "test_voltpilot.db")

from app.database import connect, init_schema
from app.seed import seed
from app.services import engine, executor
from app.services.metrics import sales_velocity, transferable_surplus


def fresh():
    conn = connect()
    init_schema(conn)
    seed(conn)
    engine.refresh(conn)
    return conn


def test_tv_mumbai_velocity_is_about_two():
    conn = fresh()
    vel = sales_velocity(conn, 1, 1, 14)
    assert 1.8 <= vel <= 2.2
    conn.close()


def test_transfer_surplus_exists_in_bengaluru():
    surplus = transferable_surplus(12, 0.5, 7, 1)
    assert surplus >= 7


def test_radar_includes_tv_stockout_and_prefers_transfer_when_feasible():
    conn = fresh()
    recs = engine.load_recommendations(conn, status="pending")
    tv = next(r for r in recs if "NovaVision" in r["title"] and "Mumbai" in r["title"])
    assert tv["severity"] in ("Critical", "High")
    rec_opt = tv["recommended_option"]
    assert rec_opt["type"] == "transfer"
    types = {o["type"] for o in tv["options"] if o["feasible"]}
    assert "purchase" in types
    assert "do_nothing" in types
    conn.close()


def test_healthy_mouse_recommends_do_nothing():
    conn = fresh()
    recs = engine.load_recommendations(conn)
    mouse = next(r for r in recs if r["issue_type"] == "healthy_watch")
    assert mouse["recommended_option"]["type"] == "do_nothing"
    conn.close()


def test_approve_transfer_moves_stock_atomically():
    conn = fresh()
    recs = engine.load_recommendations(conn, status="pending")
    tv = next(r for r in recs if r["recommended_option"]["type"] == "transfer" and r["product_id"] == 1)
    before_src = conn.execute(
        "SELECT quantity FROM inventory WHERE product_id = 1 AND store_id = ?",
        (tv["recommended_option"]["payload"]["from_store_id"],),
    ).fetchone()["quantity"]
    before_dst = conn.execute(
        "SELECT quantity FROM inventory WHERE product_id = 1 AND store_id = ?",
        (tv["recommended_option"]["payload"]["to_store_id"],),
    ).fetchone()["quantity"]
    qty = tv["recommended_option"]["payload"]["quantity"]
    result = executor.approve(conn, tv["id"])
    assert result["ok"]
    after_src = conn.execute(
        "SELECT quantity FROM inventory WHERE product_id = 1 AND store_id = ?",
        (tv["recommended_option"]["payload"]["from_store_id"],),
    ).fetchone()["quantity"]
    after_dst = conn.execute(
        "SELECT quantity FROM inventory WHERE product_id = 1 AND store_id = ?",
        (tv["recommended_option"]["payload"]["to_store_id"],),
    ).fetchone()["quantity"]
    assert after_src == before_src - qty
    assert after_dst == before_dst + qty
    dup = executor.approve(conn, tv["id"])
    assert not dup["ok"]
    conn.close()


def test_reject_does_not_change_inventory():
    conn = fresh()
    recs = engine.load_recommendations(conn, status="pending")
    tv = next(r for r in recs if r["product_id"] == 1 and "Mumbai" in r["store_name"])
    before = [dict(r) for r in conn.execute("SELECT * FROM inventory").fetchall()]
    result = executor.reject(conn, tv["id"], "not now")
    assert result["ok"]
    after = [dict(r) for r in conn.execute("SELECT * FROM inventory").fetchall()]
    assert before == after
    conn.close()
