import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .config import DATA_DIR, DB_PATH, DATABASE_URL, USE_POSTGRES

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS stores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    city TEXT NOT NULL,
    region TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    unit_cost REAL NOT NULL,
    selling_price REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    store_id INTEGER NOT NULL REFERENCES stores(id),
    quantity INTEGER NOT NULL,
    days_on_hand INTEGER NOT NULL,
    last_counted_at TEXT NOT NULL,
    markdown_review INTEGER NOT NULL DEFAULT 0,
    UNIQUE(product_id, store_id)
);

CREATE TABLE IF NOT EXISTS sales_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    store_id INTEGER NOT NULL REFERENCES stores(id),
    sale_date TEXT NOT NULL,
    units INTEGER NOT NULL
);

-- Historical sales explicitly imported by the retailer (not seeded demo sales).
-- Actual POS sales are read from retail_transactions/retail_transaction_items.
CREATE TABLE IF NOT EXISTS sales_history_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    store_id INTEGER NOT NULL REFERENCES stores(id),
    sale_date TEXT NOT NULL,
    units INTEGER NOT NULL CHECK (units >= 0),
    imported_at TEXT NOT NULL,
    UNIQUE(product_id, store_id, sale_date)
);
CREATE INDEX IF NOT EXISTS idx_sales_history_product_store_date
    ON sales_history_observations(product_id, store_id, sale_date);

CREATE TABLE IF NOT EXISTS suppliers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    reliability TEXT NOT NULL,
    risk_notes TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS supplier_catalog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    unit_price REAL NOT NULL,
    lead_time_days INTEGER NOT NULL,
    available_qty INTEGER NOT NULL,
    UNIQUE(supplier_id, product_id)
);

CREATE TABLE IF NOT EXISTS promotions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    product_id INTEGER NOT NULL REFERENCES products(id),
    store_id INTEGER,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    po_number TEXT UNIQUE NOT NULL,
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    store_id INTEGER NOT NULL REFERENCES stores(id),
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    status TEXT NOT NULL,
    ordered_at TEXT NOT NULL,
    expected_at TEXT NOT NULL,
    received_at TEXT,
    notes TEXT,
    simulated INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS supplier_delivery_updates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(id),
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
    status_reported TEXT NOT NULL,
    previous_expected_at TEXT NOT NULL,
    revised_expected_at TEXT NOT NULL,
    supplier_contact TEXT NOT NULL,
    note TEXT NOT NULL,
    reported_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_key TEXT UNIQUE NOT NULL,
    issue_type TEXT NOT NULL,
    title TEXT NOT NULL,
    severity TEXT NOT NULL,
    score REAL NOT NULL,
    product_id INTEGER NOT NULL REFERENCES products(id),
    store_id INTEGER NOT NULL REFERENCES stores(id),
    why_now TEXT NOT NULL,
    expected_impact TEXT NOT NULL,
    impact_inr REAL NOT NULL,
    confidence REAL NOT NULL,
    confidence_note TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    options_json TEXT NOT NULL,
    recommended_option_id TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recommendation_id INTEGER REFERENCES recommendations(id),
    decision TEXT NOT NULL,
    option_id TEXT,
    option_type TEXT,
    actor TEXT NOT NULL DEFAULT 'Store Manager',
    timestamp TEXT NOT NULL,
    summary TEXT NOT NULL,
    result TEXT NOT NULL,
    details_json TEXT NOT NULL,
    executed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT NOT NULL,
    source TEXT NOT NULL
);

-- Simulated point-of-sale records. A checkout and its line items are committed
-- in one SQLite transaction; this is a demo billing ledger, not a payment gateway.
CREATE TABLE IF NOT EXISTS retail_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_number TEXT UNIQUE NOT NULL,
    store_id INTEGER NOT NULL REFERENCES stores(id),
    customer_name TEXT NOT NULL DEFAULT '',
    payment_method TEXT NOT NULL,
    subtotal REAL NOT NULL,
    tax_rate REAL NOT NULL DEFAULT 0.18,
    tax_amount REAL NOT NULL,
    total_amount REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'sold',
    created_at TEXT NOT NULL,
    simulated INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS retail_transaction_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id INTEGER NOT NULL REFERENCES retail_transactions(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price REAL NOT NULL,
    unit_cost REAL NOT NULL,
    line_total REAL NOT NULL
);

-- Inventory movement journal: opening stock, receipts, and POS sales.
CREATE TABLE IF NOT EXISTS inventory_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    store_id INTEGER NOT NULL REFERENCES stores(id),
    movement_type TEXT NOT NULL,
    quantity_delta INTEGER NOT NULL,
    quantity_after INTEGER NOT NULL,
    reference_type TEXT,
    reference_id TEXT,
    note TEXT NOT NULL DEFAULT '',
    actor TEXT NOT NULL DEFAULT 'Store Manager',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_inventory_movements_store_created
    ON inventory_movements(store_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_inventory_movements_product_store
    ON inventory_movements(product_id, store_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_retail_transactions_store_created
    ON retail_transactions(store_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_retail_items_transaction
    ON retail_transaction_items(transaction_id);
"""


class HybridRow(dict):
    """Dictionary-style row that also supports SQLite-style numeric indexes."""
    def __init__(self, names, values):
        self._values = tuple(values)
        super().__init__(zip(names, self._values))

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


def _hybrid_row_factory(cursor):
    names = [column.name for column in (cursor.description or [])]
    return lambda values: HybridRow(names, values)


class _NoopCursor:
    rowcount = 0

    def fetchone(self):
        return None

    def fetchall(self):
        return []


class PostgresConnection:
    """Small sqlite-compatible adapter for the SQL used by this application.

    It preserves the existing `conn.execute(..., qmark placeholders ...)` API
    while using psycopg/PostgreSQL in production. SQLite remains the local default.
    """
    is_postgres = True

    def __init__(self, connection):
        self._connection = connection

    @staticmethod
    def _sql(query: str) -> str:
        return query.replace("?", "%s")

    def execute(self, query: str, params=()):
        if query.lstrip().upper().startswith("PRAGMA"):
            return _NoopCursor()
        cursor = self._connection.cursor()
        cursor.execute(self._sql(query), params or ())
        return cursor

    def executemany(self, query: str, seq_of_params):
        cursor = self._connection.cursor()
        cursor.executemany(self._sql(query), seq_of_params)
        return cursor

    def executescript(self, script: str):
        for statement in _sql_statements(script):
            self.execute(statement)

    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()

    def close(self):
        self._connection.close()


def _sql_statements(script: str) -> list[str]:
    without_comments = re.sub(r"(?m)^\s*--.*$", "", script)
    return [part.strip() for part in without_comments.split(";") if part.strip()]


def _postgres_schema(script: str) -> str:
    """Convert simple SQLite DDL to equivalent PostgreSQL DDL."""
    script = re.sub(r"(?m)^\s*PRAGMA\s+foreign_keys\s*=\s*ON\s*;?\s*$", "", script, flags=re.IGNORECASE)
    script = re.sub(r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b", "BIGSERIAL PRIMARY KEY", script, flags=re.IGNORECASE)
    script = re.sub(r"\bINTEGER\b", "BIGINT", script, flags=re.IGNORECASE)
    script = re.sub(r"\bREAL\b", "DOUBLE PRECISION", script, flags=re.IGNORECASE)
    return script


def ensure_data_dir() -> None:
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)


def connect():
    if USE_POSTGRES:
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("PostgreSQL support requires psycopg. Install backend requirements.") from exc
        connection = psycopg.connect(DATABASE_URL, row_factory=_hybrid_row_factory, connect_timeout=10)
        return PostgresConnection(connection)

    # Read the override at connection time. This also lets pytest isolate each
    # test database even though app modules were imported during collection.
    db_path = Path(os.environ.get("VOLTPILOT_DB", str(DB_PATH)))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_conn():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_schema(conn) -> None:
    if getattr(conn, "is_postgres", False):
        for statement in _sql_statements(_postgres_schema(SCHEMA)):
            conn.execute(statement)
    else:
        conn.executescript(SCHEMA)


def row_to_dict(row: Any | None) -> dict | None:
    if row is None:
        return None
    return dict(row)
