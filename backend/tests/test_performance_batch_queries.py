"""Guard against one-query-per-inventory-row regressions in risk analysis."""
import sqlite3

from app.database import init_schema
from app.services.initial_store_setup import bootstrap_store_catalog
from app.services import risk_areas


class CountingConnection:
    def __init__(self, connection):
        self.connection = connection
        self.execute_calls = 0

    def execute(self, *args, **kwargs):
        self.execute_calls += 1
        return self.connection.execute(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.connection, name)


def test_risk_overview_batches_database_reads_for_starter_inventory():
    raw = sqlite3.connect(":memory:")
    raw.row_factory = sqlite3.Row
    try:
        init_schema(raw)
        bootstrap_store_catalog(raw)
        assert raw.execute("SELECT COUNT(*) FROM inventory").fetchone()[0] == 52

        conn = CountingConnection(raw)
        overview = risk_areas.get_overview(conn)

        assert len(overview["items"]) == 7
        assert conn.execute_calls <= 15, (
            f"risk analysis used {conn.execute_calls} database queries; "
            "reads should be batched rather than repeated per inventory row"
        )
    finally:
        raw.close()
