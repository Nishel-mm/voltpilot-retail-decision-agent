import sqlite3

from app.database import init_schema
from app.services.initial_store_setup import bootstrap_store_catalog


def test_bootstrap_adds_store_catalog_and_stock_without_analytics():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_schema(conn)
    try:
        assert bootstrap_store_catalog(conn) is True
        assert conn.execute("SELECT COUNT(*) FROM stores").fetchone()[0] == 4
        assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 13
        assert conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0] == 52
        for table in (
            "sales_daily",
            "sales_history_observations",
            "retail_transactions",
            "suppliers",
            "supplier_catalog",
            "promotions",
            "purchase_orders",
            "recommendations",
            "audit_log",
        ):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
        # A second startup must not reset or overwrite the initial catalogue.
        assert bootstrap_store_catalog(conn) is False
        conn.execute(
            "UPDATE inventory SET quantity = 1 WHERE product_id = 1 AND store_id = 1"
        )
        assert bootstrap_store_catalog(conn) is False
        assert conn.execute(
            "SELECT quantity FROM inventory WHERE product_id = 1 AND store_id = 1"
        ).fetchone()[0] == 1
    finally:
        conn.close()
