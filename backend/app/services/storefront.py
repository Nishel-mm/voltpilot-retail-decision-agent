"""VoltPilot demo store catalog helpers.

The starter dataset only contains eight analytical SKUs. This module safely adds
extra checkout-friendly demonstration products to an existing database without
resetting the user's data. All products and transactions are explicitly synthetic.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from ..config import DEMO_TODAY, business_date

TODAY = date.fromisoformat(DEMO_TODAY)

# SKU, name, category, unit_cost, selling_price, initial inventory by store code,
# and baseline daily units by store code. Names/prices are illustrative demo data.
STORE_PRODUCTS = [
    {
        "sku": "VK-LT-14",
        "name": "OrbitBook 14-inch Laptop",
        "category": "Laptops",
        "unit_cost": 42000,
        "selling_price": 54990,
        "stock": {"MUM": 4, "BLR": 6, "DEL": 3, "HYD": 2},
        "velocity": {"MUM": 0.50, "BLR": 0.40, "DEL": 0.45, "HYD": 0.25},
        "days_on_hand": 18,
    },
    {
        "sku": "VK-LT-16",
        "name": "OrbitBook Pro 16-inch Laptop",
        "category": "Laptops",
        "unit_cost": 62000,
        "selling_price": 79990,
        "stock": {"MUM": 2, "BLR": 3, "DEL": 2, "HYD": 1},
        "velocity": {"MUM": 0.20, "BLR": 0.25, "DEL": 0.20, "HYD": 0.15},
        "days_on_hand": 16,
    },
    {
        "sku": "VK-HP-02",
        "name": "StudioWave Wireless Headphones",
        "category": "Headphones",
        "unit_cost": 1900,
        "selling_price": 3499,
        "stock": {"MUM": 20, "BLR": 18, "DEL": 9, "HYD": 12},
        "velocity": {"MUM": 1.00, "BLR": 1.20, "DEL": 1.50, "HYD": 0.70},
        "days_on_hand": 22,
    },
    {
        "sku": "VK-MN-24",
        "name": "VisionPlus 24-inch Monitor",
        "category": "Monitors",
        "unit_cost": 5400,
        "selling_price": 7999,
        "stock": {"MUM": 7, "BLR": 8, "DEL": 5, "HYD": 6},
        "velocity": {"MUM": 0.40, "BLR": 0.30, "DEL": 0.40, "HYD": 0.25},
        "days_on_hand": 20,
    },
    {
        "sku": "VK-KB-01",
        "name": "MechType Wireless Keyboard",
        "category": "Accessories",
        "unit_cost": 900,
        "selling_price": 1799,
        "stock": {"MUM": 18, "BLR": 12, "DEL": 14, "HYD": 10},
        "velocity": {"MUM": 0.80, "BLR": 0.70, "DEL": 0.80, "HYD": 0.60},
        "days_on_hand": 17,
    },
]


def ensure_store_catalog(conn) -> bool:
    """Idempotently add demo POS products, their inventory and sale history.

    Returns True when any product, inventory row, or initial history was added.
    Existing quantities and records are never overwritten.
    """
    changed = False
    stores = conn.execute("SELECT id, code FROM stores ORDER BY id").fetchall()
    if not stores:
        return False

    for item in STORE_PRODUCTS:
        row = conn.execute("SELECT id FROM products WHERE sku = ?", (item["sku"],)).fetchone()
        if row:
            product_id = int(row["id"])
        else:
            cur = conn.execute(
                "INSERT INTO products (sku, name, category, unit_cost, selling_price) VALUES (?, ?, ?, ?, ?) RETURNING id",
                (item["sku"], item["name"], item["category"], item["unit_cost"], item["selling_price"]),
            )
            product_id = int(cur.fetchone()["id"])
            changed = True

        for store in stores:
            store_id = int(store["id"])
            code = store["code"]
            inventory = conn.execute(
                "SELECT id FROM inventory WHERE product_id = ? AND store_id = ?",
                (product_id, store_id),
            ).fetchone()
            if not inventory:
                conn.execute(
                    "INSERT INTO inventory (product_id, store_id, quantity, days_on_hand, last_counted_at, markdown_review) VALUES (?, ?, ?, ?, ?, 0)",
                    (product_id, store_id, item["stock"].get(code, 0), item["days_on_hand"], TODAY.isoformat()),
                )
                changed = True

            existing_sales = conn.execute(
                "SELECT COUNT(*) AS c FROM sales_daily WHERE product_id = ? AND store_id = ?",
                (product_id, store_id),
            ).fetchone()["c"]
            if not existing_sales:
                base = float(item["velocity"].get(code, 0.0))
                for offset in range(14, 0, -1):
                    day = TODAY - timedelta(days=offset)
                    weekend_factor = 1.15 if day.weekday() in (4, 5, 6) else (0.9 if day.weekday() == 0 else 1.0)
                    wobble = (1.0, 0.9, 1.1, 1.0, 1.05, 0.95, 1.0)[day.weekday()]
                    units = max(0, int(round(base * weekend_factor * wobble)))
                    conn.execute(
                        "INSERT INTO sales_daily (product_id, store_id, sale_date, units) VALUES (?, ?, ?, ?)",
                        (product_id, store_id, day.isoformat(), units),
                    )
                changed = True
    return changed


def _stock_status(quantity: int) -> tuple[str, str]:
    quantity = int(quantity or 0)
    if quantity <= 0:
        return "out_of_stock", "Out of stock"
    if quantity <= 3:
        return "low_stock", "Low stock"
    return "in_stock", "In stock"


def _local_timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def create_store_product(conn, body) -> dict:
    """Create a new catalog product and create per-store inventory rows.

    The selected store receives the supplied opening quantity; all other stores
    get a zero-quantity row, so the SKU is visible in the inventory network and
    zero stock can be flagged without fabricating availability.
    """
    import json
    from fastapi import HTTPException

    store = conn.execute("SELECT * FROM stores WHERE id = ?", (body.store_id,)).fetchone()
    if not store:
        raise HTTPException(404, "Selected store was not found.")
    sku = body.sku.strip().upper()
    name = body.name.strip()
    category = body.category.strip()
    note = (body.note or "Added from Store & Product Vault").strip()[:400]
    if not sku or not name or not category:
        raise HTTPException(422, "SKU, product name and category are required.")
    if float(body.selling_price) <= 0 or float(body.unit_cost) < 0:
        raise HTTPException(422, "Selling price must be positive and unit cost cannot be negative.")
    duplicate = conn.execute("SELECT id, name FROM products WHERE UPPER(sku) = UPPER(?)", (sku,)).fetchone()
    if duplicate:
        raise HTTPException(409, f"SKU {sku} already exists for {duplicate['name']}. Use Receive stock to add inventory for an existing SKU.")

    cursor = conn.execute(
        "INSERT INTO products (sku, name, category, unit_cost, selling_price) VALUES (?, ?, ?, ?, ?) RETURNING id",
        (sku, name, category, round(float(body.unit_cost), 2), round(float(body.selling_price), 2)),
    )
    product_id = int(cursor.fetchone()["id"])
    timestamp = _local_timestamp()
    # Create inventory only at the selected store. Other stores are not silently
    # marked out of stock for a SKU they may not carry; Receive stock can add the
    # SKU to another store later when that store actually receives it.
    quantity = int(body.initial_stock)
    conn.execute(
        "INSERT INTO inventory (product_id, store_id, quantity, days_on_hand, last_counted_at, markdown_review) VALUES (?, ?, ?, 0, ?, 0)",
        (product_id, int(body.store_id), quantity, business_date().isoformat()),
    )
    status, label = _stock_status(quantity)
    store_quantities = [{"store_id": int(body.store_id), "quantity": quantity, "stock_status": status, "stock_status_label": label}]
    if quantity > 0:
        conn.execute(
            """INSERT INTO inventory_movements (product_id, store_id, movement_type, quantity_delta, quantity_after, reference_type, reference_id, note, actor, created_at)
               VALUES (?, ?, 'opening_stock', ?, ?, 'product_create', ?, ?, 'Store Manager', ?)""",
            (product_id, int(body.store_id), quantity, quantity, sku, note, timestamp),
        )

    details = {
        "product_id": product_id, "sku": sku, "name": name, "category": category,
        "unit_cost": float(body.unit_cost), "selling_price": float(body.selling_price),
        "selected_store_id": int(body.store_id), "initial_stock": int(body.initial_stock),
        "stock_by_store": store_quantities, "note": note,
    }
    conn.execute(
        """INSERT INTO audit_log (recommendation_id, decision, option_id, option_type, actor, timestamp, summary, result, details_json, executed)
           VALUES (NULL, 'product_created', ?, 'catalog_product', 'Store Manager', ?, ?, ?, ?, 1)""",
        (sku, timestamp, f"New product added: {name} ({sku})",
         f"Product saved to the connected database with opening stock of {int(body.initial_stock)} at {store['name']}; other stores are not marked as carrying this SKU until stock is received there.", json.dumps(details)),
    )
    # Refresh the actual decision engine against the same database the store uses.
    from . import engine
    engine.refresh(conn)
    status, label = _stock_status(int(body.initial_stock))
    return {"ok": True, "product": {"id": product_id, "product_id": product_id, "sku": sku, "name": name, "category": category, "unit_cost": round(float(body.unit_cost), 2), "selling_price": round(float(body.selling_price), 2), "available_qty": int(body.initial_stock), "stock_status": status, "stock_status_label": label}, "stock_by_store": store_quantities, "recommendations_refreshed": True, "message": f"{name} was added to the product catalog at {store['name']} and saved in the connected database."}


def receive_store_stock(conn, body) -> dict:
    """Increase on-hand stock at a store and refresh agent recommendations."""
    import json
    from fastapi import HTTPException

    product = conn.execute("SELECT * FROM products WHERE id = ?", (body.product_id,)).fetchone()
    store = conn.execute("SELECT * FROM stores WHERE id = ?", (body.store_id,)).fetchone()
    if not product:
        raise HTTPException(404, "Product not found.")
    if not store:
        raise HTTPException(404, "Store not found.")
    inventory = conn.execute("SELECT * FROM inventory WHERE product_id = ? AND store_id = ?", (body.product_id, body.store_id)).fetchone()
    if inventory is None:
        conn.execute(
            "INSERT INTO inventory (product_id, store_id, quantity, days_on_hand, last_counted_at, markdown_review) VALUES (?, ?, 0, 0, ?, 0)",
            (body.product_id, body.store_id, business_date().isoformat()),
        )
        previous = 0
    else:
        previous = int(inventory["quantity"])
    quantity = int(body.quantity)
    after = previous + quantity
    if after > 1000000:
        raise HTTPException(422, "Resulting stock exceeds the allowed demo quantity.")
    timestamp = _local_timestamp()
    note = (body.note or "Stock received at store").strip()[:400]
    conn.execute(
        "UPDATE inventory SET quantity = ?, last_counted_at = ? WHERE product_id = ? AND store_id = ?",
        (after, business_date().isoformat(), body.product_id, body.store_id),
    )
    reference = f"RCV-{business_date().strftime('%Y%m%d')}-{body.product_id}-{body.store_id}-{timestamp[-8:].replace(':', '')}"
    conn.execute(
        """INSERT INTO inventory_movements (product_id, store_id, movement_type, quantity_delta, quantity_after, reference_type, reference_id, note, actor, created_at)
           VALUES (?, ?, 'stock_receipt', ?, ?, 'stock_receipt', ?, ?, 'Store Manager', ?)""",
        (body.product_id, body.store_id, quantity, after, reference, note, timestamp),
    )
    status, label = _stock_status(after)
    details = {"product_id": int(product["id"]), "sku": product["sku"], "product_name": product["name"], "store_id": int(store["id"]), "store_name": store["name"], "quantity_before": previous, "quantity_received": quantity, "quantity_after": after, "stock_status": status, "note": note, "reference": reference}
    conn.execute(
        """INSERT INTO audit_log (recommendation_id, decision, option_id, option_type, actor, timestamp, summary, result, details_json, executed)
           VALUES (NULL, 'stock_received', ?, 'inventory_receipt', 'Store Manager', ?, ?, ?, ?, 1)""",
        (reference, timestamp, f"Stock received: {product['name']} at {store['name']}",
         f"Quantity increased from {previous} to {after}. VoltPilot recommendations refreshed.", json.dumps(details)),
    )
    from . import engine
    engine.refresh(conn)
    return {"ok": True, "product_id": int(product["id"]), "sku": product["sku"], "product_name": product["name"], "store_id": int(store["id"]), "store_name": store["name"], "quantity_before": previous, "quantity_received": quantity, "quantity_after": after, "stock_status": status, "stock_status_label": label, "reference": reference, "recommendations_refreshed": True, "message": f"Received {quantity} units of {product['name']}; on-hand stock is now {after} at {store['name']}."}


def list_inventory_movements(conn, store_id: int | None = None, product_id: int | None = None, limit: int = 100) -> dict:
    from fastapi import HTTPException
    if store_id is not None and not conn.execute("SELECT id FROM stores WHERE id = ?", (store_id,)).fetchone():
        raise HTTPException(404, "Store not found.")
    if product_id is not None and not conn.execute("SELECT id FROM products WHERE id = ?", (product_id,)).fetchone():
        raise HTTPException(404, "Product not found.")
    where, params = [], []
    if store_id is not None:
        where.append("im.store_id = ?"); params.append(store_id)
    if product_id is not None:
        where.append("im.product_id = ?"); params.append(product_id)
    sql = """SELECT im.*, p.sku, p.name AS product_name, s.name AS store_name
             FROM inventory_movements im JOIN products p ON p.id = im.product_id
             JOIN stores s ON s.id = im.store_id"""
    if where: sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY im.id DESC LIMIT ?"
    params.append(max(1, min(int(limit), 500)))
    return {"items": [dict(r) for r in conn.execute(sql, params).fetchall()], "count_note": "Stock movements are persisted in the configured database; quantities are derived from the inventory table."}


def catalog_payload(conn, store_id: int) -> dict:
    from fastapi import HTTPException
    from .metrics import get_assumptions, sales_velocity, stock_cover_days

    stores = [dict(r) for r in conn.execute("SELECT * FROM stores ORDER BY name").fetchall()]
    if not stores:
        return {
            "store": None, "stores": [], "categories": [], "items": [],
            "business_date": business_date().isoformat(), "demo_tax_rate": 0.18,
            "data_origin": "No retailer data has been entered yet. Create a store to begin.",
        }
    selected_store = next((row for row in stores if int(row["id"]) == int(store_id)), None)
    if selected_store is None:
        raise HTTPException(404, "Store not found. Choose an existing store.")

    lookback = int(get_assumptions(conn).get("velocity_lookback_days", 14))
    rows = conn.execute(
        """SELECT p.id AS product_id, p.sku, p.name, p.category, p.unit_cost,
                  p.selling_price, i.quantity AS available_qty, i.days_on_hand,
                  i.markdown_review, i.last_counted_at
           FROM products p
           JOIN inventory i ON i.product_id = p.id
           WHERE i.store_id = ?
           ORDER BY p.category, p.name""",
        (store_id,),
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        velocity = sales_velocity(conn, item["product_id"], store_id, lookback)
        item["daily_sales_velocity"] = round(float(velocity), 3)
        item["stock_cover_days"] = stock_cover_days(item["available_qty"], velocity)
        quantity = int(item["available_qty"] or 0)
        item["stock_status"] = "out_of_stock" if quantity <= 0 else ("low_stock" if quantity <= 3 else "in_stock")
        item["stock_status_label"] = "Out of stock" if quantity <= 0 else ("Low stock" if quantity <= 3 else "In stock")
        item["low_stock_threshold"] = 3
        items.append(item)
    categories = sorted({item["category"] for item in items})
    return {
        "store": selected_store,
        "stores": stores,
        "categories": categories,
        "items": items,
        "demo_date": business_date().isoformat(),
        "business_date": business_date().isoformat(),
        "demo_tax_rate": 0.18,
        "demo_note": "Catalog and quantities come from retailer-entered data. Checkout is simulated; no payment is taken. The 18% tax line is illustrative and is not a statutory tax invoice.",
        "data_origin": "Current database records; no sample product is added automatically to hosted PostgreSQL.",
    }


def _sale_summary_rows(conn, store_id: int | None = None, limit: int = 50) -> list[dict]:
    sql = """SELECT rt.id, rt.invoice_number, rt.store_id, st.name AS store_name,
                    rt.customer_name, rt.payment_method, rt.subtotal, rt.tax_rate,
                    rt.tax_amount, rt.total_amount, rt.status, rt.created_at,
                    rt.simulated, COUNT(ri.id) AS line_count,
                    COALESCE(SUM(ri.quantity), 0) AS units_sold
             FROM retail_transactions rt
             JOIN stores st ON st.id = rt.store_id
             LEFT JOIN retail_transaction_items ri ON ri.transaction_id = rt.id"""
    params: list = []
    if store_id is not None:
        sql += " WHERE rt.store_id = ?"
        params.append(store_id)
    sql += " GROUP BY rt.id ORDER BY rt.id DESC LIMIT ?"
    params.append(max(1, min(int(limit), 100)))
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def list_sales(conn, store_id: int | None = None, limit: int = 50) -> dict:
    if store_id is not None and not conn.execute("SELECT id FROM stores WHERE id = ?", (store_id,)).fetchone():
        from fastapi import HTTPException
        raise HTTPException(404, "Store not found.")
    return {"items": _sale_summary_rows(conn, store_id, limit), "demo_note": "Simulated point-of-sale transactions stored in the configured database. No real payment was processed."}


def sale_detail(conn, sale_id: int) -> dict | None:
    sale = conn.execute(
        """SELECT rt.*, st.name AS store_name, st.code AS store_code
           FROM retail_transactions rt JOIN stores st ON st.id = rt.store_id
           WHERE rt.id = ?""", (sale_id,)
    ).fetchone()
    if not sale:
        return None
    items = conn.execute(
        """SELECT ri.*, p.sku, p.name AS product_name, p.category
           FROM retail_transaction_items ri JOIN products p ON p.id = ri.product_id
           WHERE ri.transaction_id = ? ORDER BY ri.id""", (sale_id,)
    ).fetchall()
    # Every receipt is accompanied by a fresh analysis snapshot calculated from
    # the same SQLite connection after the sale has been committed. This makes
    # the data->agent connection visible to the demonstrator without pretending
    # that unrelated risk counts must all change after every sale.
    from . import risk_areas
    overview = risk_areas.get_overview(conn)
    summary = [
        {"id": area["id"], "number": area["number"], "title": area["title"],
         "status": area["status"], "issue_count": area["issue_count"],
         "severity": area["severity"]}
        for area in overview["items"]
    ]
    return {
        "sale": dict(sale),
        "items": [dict(row) for row in items],
        "agent_analysis": {
            "last_analyzed_at": overview["last_analyzed_at"],
            "latest_sale_at": overview["latest_sale_at"],
            "items": summary,
            "data_origin": overview["data_origin"],
            "note": "Calculated from the current SQLite data after the sale. Only objectives whose detector criteria are affected by the changed data should change; other objectives may correctly remain unchanged."
        },
        "demo_note": "Simulated sale; payment was not processed by a real payment provider."
    }


def complete_checkout(conn, body) -> dict:
    """Commit a sale, stock decrement, sales-history update, and audit entry atomically."""
    import json
    from uuid import uuid4
    from datetime import datetime, timezone
    from fastapi import HTTPException

    store = conn.execute("SELECT * FROM stores WHERE id = ?", (body.store_id,)).fetchone()
    if not store:
        raise HTTPException(404, "Store not found.")

    # Aggregate repeated product lines to validate and decrement each SKU once.
    requested: dict[int, int] = {}
    for line in body.items:
        requested[line.product_id] = requested.get(line.product_id, 0) + line.quantity
    if not requested:
        raise HTTPException(422, "Add at least one product before checkout.")

    lines = []
    for product_id, quantity in requested.items():
        row = conn.execute(
            """SELECT p.id AS product_id, p.sku, p.name, p.category, p.unit_cost,
                      p.selling_price, i.quantity AS available_qty
               FROM products p JOIN inventory i ON i.product_id = p.id
               WHERE p.id = ? AND i.store_id = ?""",
            (product_id, body.store_id),
        ).fetchone()
        if not row:
            raise HTTPException(404, f"Product {product_id} is not available in this store's catalog.")
        if quantity > int(row["available_qty"]):
            raise HTTPException(409, f"Only {row['available_qty']} units of {row['name']} are available at {store['name']}.")
        data = dict(row)
        data["quantity"] = quantity
        data["unit_price"] = round(float(row["selling_price"]), 2)
        data["unit_cost"] = round(float(row["unit_cost"]), 2)
        data["line_total"] = round(data["unit_price"] * quantity, 2)
        lines.append(data)

    subtotal = round(sum(line["line_total"] for line in lines), 2)
    tax_rate = 0.18  # visibly labelled demo estimate only; not a tax-compliance calculation
    tax_amount = round(subtotal * tax_rate, 2)
    total_amount = round(subtotal + tax_amount, 2)
    invoice_number = f"VK-{business_date().strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}"
    created_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    customer_name = (body.customer_name or "").strip()[:100]
    payment_method = body.payment_method

    # First write starts a transaction. Any exception below rolls the whole checkout back.
    cur = conn.execute(
        """INSERT INTO retail_transactions (
               invoice_number, store_id, customer_name, payment_method, subtotal,
               tax_rate, tax_amount, total_amount, status, created_at, simulated
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'sold', ?, 1) RETURNING id""",
        (invoice_number, body.store_id, customer_name, payment_method, subtotal,
         tax_rate, tax_amount, total_amount, created_at),
    )
    sale_id = int(cur.fetchone()["id"])

    for line in lines:
        upd = conn.execute(
            """UPDATE inventory SET quantity = quantity - ?
               WHERE product_id = ? AND store_id = ? AND quantity >= ?""",
            (line["quantity"], line["product_id"], body.store_id, line["quantity"]),
        )
        if upd.rowcount != 1:
            raise HTTPException(409, f"Stock changed during checkout for {line['name']}. Refresh the vault and try again.")
        after_row = conn.execute(
            "SELECT quantity FROM inventory WHERE product_id = ? AND store_id = ?",
            (line["product_id"], body.store_id),
        ).fetchone()
        conn.execute(
            """INSERT INTO inventory_movements (product_id, store_id, movement_type, quantity_delta, quantity_after, reference_type, reference_id, note, actor, created_at)
               VALUES (?, ?, 'sale', ?, ?, 'retail_transaction', ?, ?, 'Store POS', ?)""",
            (line["product_id"], body.store_id, -line["quantity"], int(after_row["quantity"]), invoice_number,
             f"POS sale invoice {invoice_number}", created_at),
        )
        conn.execute(
            """INSERT INTO retail_transaction_items (
                   transaction_id, product_id, quantity, unit_price, unit_cost, line_total
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (sale_id, line["product_id"], line["quantity"], line["unit_price"], line["unit_cost"], line["line_total"]),
        )

        # POS observations use the actual business date so the live risk engine
        # and observed-data forecaster can learn from real entered transactions.
        sale_business_date = business_date().isoformat()
        existing = conn.execute(
            """SELECT id FROM sales_daily WHERE product_id = ? AND store_id = ? AND sale_date = ?
               ORDER BY id DESC LIMIT 1""",
            (line["product_id"], body.store_id, sale_business_date),
        ).fetchone()
        if existing:
            conn.execute("UPDATE sales_daily SET units = units + ? WHERE id = ?", (line["quantity"], existing["id"]))
        else:
            conn.execute(
                "INSERT INTO sales_daily (product_id, store_id, sale_date, units) VALUES (?, ?, ?, ?)",
                (line["product_id"], body.store_id, sale_business_date, line["quantity"]),
            )

    details = {
        "sale_id": sale_id, "invoice_number": invoice_number, "store_id": body.store_id,
        "store_name": store["name"], "payment_method": payment_method,
        "customer_name": customer_name, "subtotal": subtotal,
        "tax_rate": tax_rate, "tax_amount": tax_amount, "total_amount": total_amount,
        "items": [{"product_id": l["product_id"], "sku": l["sku"], "product_name": l["name"],
                   "quantity": l["quantity"], "unit_price": l["unit_price"], "line_total": l["line_total"]} for l in lines],
        "inventory_decremented": True, "sales_history_updated": True,
        "payment_simulated": True,
    }
    conn.execute(
        """INSERT INTO audit_log (
               recommendation_id, decision, option_id, option_type, actor, timestamp,
               summary, result, details_json, executed
           ) VALUES (NULL, 'sale_completed', ?, 'retail_sale', ?, ?, ?, ?, ?, 1)""",
        (invoice_number, "Store POS", created_at, f"POS sale {invoice_number}",
         f"Simulated sale recorded at {store['name']}; inventory and sales history updated in SQLite.", json.dumps(details)),
    )

    # A completed sale changes inventory/demand. Recompute recommendations inside
    # the same transaction so the next dashboard load reflects the new store state.
    from . import engine
    engine.refresh(conn)

    from . import risk_areas
    risk_snapshot = risk_areas.get_overview(conn)
    return {
        "ok": True, "id": sale_id, "invoice_number": invoice_number,
        "store_id": body.store_id, "store_name": store["name"],
        "customer_name": customer_name, "payment_method": payment_method,
        "subtotal": subtotal, "tax_rate": tax_rate, "tax_amount": tax_amount,
        "total_amount": total_amount, "status": "sold", "created_at": created_at,
        "simulated": True, "items": details["items"],
        "agent_analysis": {
            "last_analyzed_at": risk_snapshot["last_analyzed_at"],
            "latest_sale_at": risk_snapshot["latest_sale_at"],
            "items": [{"id": area["id"], "number": area["number"], "title": area["title"],
                       "status": area["status"], "issue_count": area["issue_count"], "severity": area["severity"]}
                      for area in risk_snapshot["items"]],
            "data_origin": risk_snapshot["data_origin"],
        },
        "message": "Sale saved. Inventory, sales history, and current risk analysis were updated from the connected database; payment is simulated.",
        "demo_note": "18% tax is an illustrative demo estimate only, not a statutory tax invoice. No real payment was taken.",
    }
