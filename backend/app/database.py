import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .config import DATA_DIR, DB_PATH

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


def ensure_data_dir() -> None:
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)


def connect() -> sqlite3.Connection:
    ensure_data_dir()
    conn = sqlite3.connect(DB_PATH)
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


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return dict(row)
