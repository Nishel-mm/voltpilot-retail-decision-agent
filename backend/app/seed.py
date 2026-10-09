"""Reproducible VoltKart festival-rush demo data.

Product names that appear on https://volttkart.shop/ are used where they fit.
The 55-inch Smart TV scenario comes from the hackathon brief, not the public shop.
"""

from datetime import timedelta

from .config import DEFAULT_ASSUMPTIONS, business_date
from .database import connect, init_schema


TODAY = business_date()


def _wipe(conn) -> None:
    tables = [
        # POS rows must be removed before their referenced product/store rows.
        "retail_transaction_items",
        "retail_transactions",
        "inventory_movements",
        "audit_log",
        "recommendations",
        "supplier_delivery_updates",
        "purchase_orders",
        "promotions",
        "supplier_catalog",
        "suppliers",
        "sales_history_observations",
        "sales_daily",
        "inventory",
        "products",
        "stores",
        "app_settings",
    ]
    if getattr(conn, "is_postgres", False):
        for table in tables:
            conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    else:
        conn.execute("PRAGMA foreign_keys = OFF")
        for table in tables:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.execute("PRAGMA foreign_keys = ON")
    init_schema(conn)


def _insert_sales(conn, product_id: int, store_id: int, daily_units: float, days: int = 14) -> None:
    """Write integer daily sales that average to daily_units over `days`."""
    # Distribute remainder so the mean is exact enough for demos.
    base = int(daily_units)
    leftover = round((daily_units - base) * days)
    for i in range(days):
        units = base + (1 if i < leftover else 0)
        sale_date = TODAY - timedelta(days=days - 1 - i)
        conn.execute(
            """
            INSERT INTO sales_daily (product_id, store_id, sale_date, units)
            VALUES (?, ?, ?, ?)
            """,
            (product_id, store_id, sale_date.isoformat(), units),
        )


def seed(conn=None) -> None:
    own = conn is None
    if own:
        conn = connect()
    try:
        _wipe(conn)

        for key, meta in DEFAULT_ASSUMPTIONS.items():
            conn.execute(
                "INSERT INTO app_settings (key, value, description, source) VALUES (?, ?, ?, ?)",
                (key, meta["value"], meta["description"], "configurable_assumption"),
            )

        stores = [
            ("MUM", "VoltKart Mumbai Andheri", "Mumbai", "West"),
            ("BLR", "VoltKart Bengaluru Koramangala", "Bengaluru", "South"),
            ("DEL", "VoltKart Delhi Connaught Place", "New Delhi", "North"),
            ("HYD", "VoltKart Hyderabad Banjara Hills", "Hyderabad", "South"),
        ]
        conn.executemany(
            "INSERT INTO stores (code, name, city, region) VALUES (?, ?, ?, ?)",
            stores,
        )

        products = [
            # Hackathon brief scenario (not listed on volttkart.shop)
            ("VK-TV-55", "NovaVision 55-inch Smart TV", "Home Entertainment", 28990, 39990),
            # Names inspected from https://volttkart.shop/
            ("VK-EB-01", "AirBeat TWS Wireless Earbuds", "Audio", 420, 799),
            ("VK-SW-18", "PulseFit Smartwatch 1.8\"", "Wearables", 640, 1199),
            ("VK-PB-10", "SlimCell 10000mAh Power Bank", "Charging", 310, 649),
            ("VK-SP-01", "BoomMini Bluetooth Speaker", "Audio", 260, 549),
            ("VK-HS-01", "StormX Wired Gaming Headset", "Audio", 480, 899),
            ("VK-SB-01", "VoltBar 2.1 Soundbar", "Home Entertainment", 4200, 6990),
            ("VK-MS-01", "SilentClick Wireless Mouse", "Computer", 140, 299),
        ]
        conn.executemany(
            """
            INSERT INTO products (sku, name, category, unit_cost, selling_price)
            VALUES (?, ?, ?, ?, ?)
            """,
            products,
        )

        suppliers = [
            ("Apex Distributors", "High", "Lowest TV unit cost. Standard 7-day lead time. Reliable fill rate."),
            ("SwiftSource Logistics", "Medium", "Expedited 2-day TV supply. About 5% more expensive than Apex."),
            ("GadgetHub Wholesale", "High", "Primary source for earbuds, wearables, and accessories."),
            ("Deccan Components", "Low", "Cheapest soundbar lots. Frequent delays and limited availability."),
        ]
        conn.executemany(
            "INSERT INTO suppliers (name, reliability, risk_notes) VALUES (?, ?, ?)",
            suppliers,
        )

        # Catalog: TV suppliers A vs B, plus others
        catalog = [
            (1, 1, 28990, 7, 80),   # Apex TV — cheaper, slower
            (2, 1, 30440, 2, 40),   # Swift TV — ~5% more, faster
            (3, 2, 420, 4, 400),    # GadgetHub earbuds
            (3, 3, 640, 5, 200),
            (3, 4, 310, 3, 250),
            (3, 5, 260, 4, 180),
            (3, 6, 480, 6, 90),
            (3, 8, 140, 5, 300),
            (4, 7, 3900, 12, 25),   # Deccan soundbar — slow / risky
            (1, 7, 4300, 6, 40),    # Apex soundbar alternative
        ]
        conn.executemany(
            """
            INSERT INTO supplier_catalog (supplier_id, product_id, unit_price, lead_time_days, available_qty)
            VALUES (?, ?, ?, ?, ?)
            """,
            catalog,
        )

        # Inventory snapshot for 9 Oct 2026
        # product_id, store_id, qty, days_on_hand
        inventory = [
            # TV: Mumbai is about to stock out; Bengaluru is overstocked
            (1, 1, 4, 12),
            (1, 2, 12, 40),
            (1, 3, 6, 18),
            (1, 4, 5, 20),
            # AirBeat earbuds: Delhi is critically low, others healthy
            (2, 1, 48, 10),
            (2, 2, 40, 11),
            (2, 3, 6, 8),
            (2, 4, 36, 9),
            # PulseFit: Mumbai faces promo demand
            (3, 1, 18, 14),
            (3, 2, 22, 16),
            (3, 3, 20, 15),
            (3, 4, 19, 13),
            # SlimCell: balanced
            (4, 1, 30, 20),
            (4, 2, 28, 18),
            (4, 3, 32, 17),
            (4, 4, 26, 19),
            # BoomMini: mild tightness in Hyderabad
            (5, 1, 24, 12),
            (5, 2, 22, 14),
            (5, 3, 20, 11),
            (5, 4, 8, 10),
            # StormX: delayed inbound PO for Mumbai
            (6, 1, 3, 9),
            (6, 2, 10, 14),
            (6, 3, 9, 13),
            (6, 4, 8, 12),
            # Soundbar: ageing overstock in Hyderabad, slow everywhere
            (7, 1, 4, 70),
            (7, 2, 3, 80),
            (7, 3, 3, 75),
            (7, 4, 14, 140),
            # Mouse: healthy cover — doing nothing is reasonable
            (8, 1, 60, 25),
            (8, 2, 55, 22),
            (8, 3, 58, 24),
            (8, 4, 52, 21),
        ]
        counted = TODAY.isoformat()
        conn.executemany(
            """
            INSERT INTO inventory (product_id, store_id, quantity, days_on_hand, last_counted_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [(p, s, q, d, counted) for p, s, q, d in inventory],
        )

        # Sales velocities
        # TV Mumbai ~2/day, Bengaluru ~0.5/day, others ~0.6
        _insert_sales(conn, 1, 1, 2.0)
        _insert_sales(conn, 1, 2, 0.5)
        _insert_sales(conn, 1, 3, 0.6)
        _insert_sales(conn, 1, 4, 0.6)
        # Earbuds Delhi ~3/day, others ~1.2
        _insert_sales(conn, 2, 1, 1.2)
        _insert_sales(conn, 2, 2, 1.1)
        _insert_sales(conn, 2, 3, 3.0)
        _insert_sales(conn, 2, 4, 1.0)
        # PulseFit ~1.5/day
        for store in range(1, 5):
            _insert_sales(conn, 3, store, 1.5)
        # SlimCell ~0.8
        for store in range(1, 5):
            _insert_sales(conn, 4, store, 0.8)
        # BoomMini Hyd ~1.4, others 0.7
        _insert_sales(conn, 5, 1, 0.7)
        _insert_sales(conn, 5, 2, 0.7)
        _insert_sales(conn, 5, 3, 0.6)
        _insert_sales(conn, 5, 4, 1.4)
        # StormX Mumbai ~0.8
        _insert_sales(conn, 6, 1, 0.8)
        _insert_sales(conn, 6, 2, 0.4)
        _insert_sales(conn, 6, 3, 0.4)
        _insert_sales(conn, 6, 4, 0.3)
        # Soundbar almost idle
        _insert_sales(conn, 7, 1, 0.1)
        _insert_sales(conn, 7, 2, 0.1)
        _insert_sales(conn, 7, 3, 0.1)
        _insert_sales(conn, 7, 4, 0.07)
        # Mouse slow-stable
        for store in range(1, 5):
            _insert_sales(conn, 8, store, 0.5)

        promo_start = (TODAY + timedelta(days=3)).isoformat()  # 12 Oct
        promo_end = (TODAY + timedelta(days=10)).isoformat()
        conn.execute(
            """
            INSERT INTO promotions (name, product_id, store_id, start_date, end_date)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("Diwali Mega Sale — Smart TVs", 1, 1, promo_start, promo_end),
        )
        conn.execute(
            """
            INSERT INTO promotions (name, product_id, store_id, start_date, end_date)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("Festival Wearables Push", 3, 1, promo_start, promo_end),
        )

        # Delayed PO for StormX into Mumbai (expected 3 days ago)
        conn.execute(
            """
            INSERT INTO purchase_orders (
                po_number, supplier_id, product_id, store_id, quantity, unit_price,
                status, ordered_at, expected_at, received_at, notes, simulated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                "PO-88421",
                3,
                6,
                1,
                20,
                480,
                "delayed",
                (TODAY - timedelta(days=12)).isoformat(),
                (TODAY - timedelta(days=3)).isoformat(),
                None,
                "SIMULATED inbound order. Supplier has not confirmed a new ETA.",
            ),
        )
        # Healthy in-transit PO that should not raise an alarm
        conn.execute(
            """
            INSERT INTO purchase_orders (
                po_number, supplier_id, product_id, store_id, quantity, unit_price,
                status, ordered_at, expected_at, received_at, notes, simulated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                "PO-88490",
                3,
                4,
                2,
                40,
                310,
                "in_transit",
                (TODAY - timedelta(days=2)).isoformat(),
                (TODAY + timedelta(days=2)).isoformat(),
                None,
                "SIMULATED in-transit replenishment. On schedule.",
            ),
        )

        from .services import engine

        engine.refresh(conn)
        conn.commit()
    finally:
        if own:
            conn.close()
