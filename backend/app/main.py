from fastapi import FastAPI, HTTPException
from datetime import date, datetime, timezone
import json
from fastapi.middleware.cors import CORSMiddleware

from .config import (DATABASE_URL, USE_POSTGRES, FRONTEND_ORIGINS, DEFAULT_ASSUMPTIONS, AUTO_SEED_DEMO, ALLOW_DEMO_RESET, business_date)
from .database import get_conn, init_schema
from .schemas import DecisionAction, HealthResponse, InventoryStockReceipt, StoreProductCreate, SupplierDeliveryUpdate, StoreCheckout, StoreCreate
from .seed import seed
from .services import engine, executor, forecasting, risk_areas, storefront
from .services.initial_store_setup import bootstrap_store_catalog
from .services.metrics import assumption_records, get_assumptions, sales_velocity_map, stock_cover_days


def create_app() -> FastAPI:
    app = FastAPI(title="VoltPilot", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=FRONTEND_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def disable_cache_for_live_api(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        return response

    @app.on_event("startup")
    def startup() -> None:
        """Initialize schema/settings without seeding production PostgreSQL with demo retail data."""
        with get_conn() as conn:
            init_schema(conn)
            # Configurable assumptions are application settings, not retailer/business data.
            for key, meta in DEFAULT_ASSUMPTIONS.items():
                existing = conn.execute("SELECT key FROM app_settings WHERE key = ?", (key,)).fetchone()
                if not existing:
                    conn.execute(
                        "INSERT INTO app_settings (key, value, description, source) VALUES (?, ?, ?, ?)",
                        (key, meta["value"], meta["description"], "configurable_assumption"),
                    )

            stores_count = int(conn.execute("SELECT COUNT(*) AS c FROM stores").fetchone()["c"])
            products_count = int(conn.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"])
            # A new database gets only the familiar store/product catalogue and
            # opening quantities. Synthetic sales, suppliers, promotions, POs and
            # recommendations are never generated on startup by default.
            if stores_count == 0 and products_count == 0:
                if AUTO_SEED_DEMO and not USE_POSTGRES:
                    # Explicit local-only opt-in for the legacy hackathon scenario.
                    seed(conn)
                    stores_count = int(conn.execute("SELECT COUNT(*) AS c FROM stores").fetchone()["c"])
                    products_count = int(conn.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"])
                else:
                    bootstrap_store_catalog(conn)
                    stores_count = int(conn.execute("SELECT COUNT(*) AS c FROM stores").fetchone()["c"])
                    products_count = int(conn.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"])

            if stores_count > 0 and products_count > 0:
                # Do not generate recommendations from opening quantities alone.
                # Refresh only after business/observed data has actually been entered.
                analytical_count = 0
                for table in ("sales_history_observations", "retail_transactions", "suppliers", "supplier_catalog", "promotions", "purchase_orders"):
                    analytical_count += int(conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"])
                if analytical_count > 0:
                    engine.refresh(conn)

    @app.get("/api/health", response_model=HealthResponse)
    def health():
        with get_conn() as conn:
            conn.execute("SELECT 1")
        return HealthResponse(
            status="ok",
            service="VoltPilot",
            today=business_date().isoformat(),
            database="postgresql" if USE_POSTGRES else "sqlite",
        )

    @app.get("/api/assumptions")
    def assumptions():
        with get_conn() as conn:
            return {"assumptions": assumption_records(conn)}

    @app.get("/api/dashboard")
    def dashboard():
        with get_conn() as conn:
            return engine.dashboard_payload(conn)

    @app.get("/api/recommendations")
    def recommendations(refresh: bool = False):
        with get_conn() as conn:
            if refresh:
                engine.refresh(conn)
            return {"items": engine.load_recommendations(conn), "score_explainer": engine.dashboard_payload(conn)["score_explainer"]}

    @app.get("/api/recommendations/{decision_id}")
    def recommendation_detail(decision_id: int):
        with get_conn() as conn:
            rec = engine.get_recommendation(conn, decision_id)
        if not rec:
            raise HTTPException(404, "Decision not found.")
        return rec

    @app.get("/api/stores")
    def list_stores():
        with get_conn() as conn:
            rows = conn.execute("SELECT * FROM stores ORDER BY name").fetchall()
            return {"items": [dict(row) for row in rows], "count": len(rows)}

    @app.post("/api/stores")
    def create_store(body: StoreCreate):
        code = body.code.strip().upper()
        name = body.name.strip()
        city = body.city.strip()
        region = body.region.strip()
        if not all((code, name, city, region)):
            raise HTTPException(422, "Store code, name, city and region are required.")
        with get_conn() as conn:
            duplicate = conn.execute("SELECT id FROM stores WHERE UPPER(code) = UPPER(?)", (code,)).fetchone()
            if duplicate:
                raise HTTPException(409, f"Store code {code} already exists.")
            cursor = conn.execute(
                "INSERT INTO stores (code, name, city, region) VALUES (?, ?, ?, ?) RETURNING id",
                (code, name, city, region),
            )
            store_id = int(cursor.fetchone()["id"])
            timestamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
            details = json.dumps({"store_id": store_id, "code": code, "name": name, "city": city, "region": region})
            conn.execute(
                """INSERT INTO audit_log (recommendation_id, decision, option_id, option_type, actor, timestamp, summary, result, details_json, executed)
                   VALUES (NULL, 'store_created', ?, 'store_setup', 'Store Manager', ?, ?, ?, ?, 1)""",
                (code, timestamp, f"Store created: {name}", "Store location created; no products or stock were invented.", details),
            )
            if int(conn.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"]) > 0:
                engine.refresh(conn)
            row = conn.execute("SELECT * FROM stores WHERE id = ?", (store_id,)).fetchone()
            return {"ok": True, "store": dict(row), "message": f"Store {name} created. Add products and opening stock when ready."}

    @app.get("/api/inventory")
    def inventory():
        with get_conn() as conn:
            assumptions = get_assumptions(conn)
            lookback = int(assumptions["velocity_lookback_days"])
            rows = conn.execute(
                """
                SELECT i.*, p.name AS product_name, p.sku, p.category, p.selling_price, p.unit_cost,
                       s.name AS store_name, s.code AS store_code, s.city, s.region
                FROM inventory i
                JOIN products p ON p.id = i.product_id
                JOIN stores s ON s.id = i.store_id
                ORDER BY p.name, s.name
                """
            ).fetchall()
            # Fetch recent sales velocity for all inventory pairs in one database
            # round trip instead of one query per row (especially costly with Neon).
            velocities = sales_velocity_map(conn, lookback)
            items = []
            for row in rows:
                item = dict(row)
                pair = (int(item["product_id"]), int(item["store_id"]))
                vel = velocities.get(pair, 0.0)
                item["velocity"] = vel
                item["cover_days"] = stock_cover_days(item["quantity"], vel)
                quantity = int(item["quantity"] or 0)
                item["stock_status"] = "out_of_stock" if quantity <= 0 else ("low_stock" if quantity <= 3 else "in_stock")
                item["stock_status_label"] = "Out of stock" if quantity <= 0 else ("Low stock" if quantity <= 3 else "In stock")
                item["low_stock_threshold"] = 3
                items.append(item)
            stores = [dict(r) for r in conn.execute("SELECT * FROM stores ORDER BY id").fetchall()]
            products = [dict(r) for r in conn.execute("SELECT * FROM products ORDER BY id").fetchall()]
            return {"items": items, "stores": stores, "products": products}

    @app.get("/api/inventory/ageing")
    def inventory_ageing():
        """Report age from recorded positive stock-in movements only; never invent dates."""
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT i.product_id, i.store_id, i.quantity,
                       p.name AS product_name, p.sku, p.category, p.unit_cost, p.selling_price,
                       s.name AS store_name, s.city,
                       MIN(substr(m.created_at, 1, 10)) AS first_recorded_stock_in
                FROM inventory i
                JOIN products p ON p.id = i.product_id
                JOIN stores s ON s.id = i.store_id
                LEFT JOIN inventory_movements m
                  ON m.product_id = i.product_id AND m.store_id = i.store_id
                 AND m.movement_type IN ('opening_stock', 'stock_receipt')
                 AND m.quantity_delta > 0
                GROUP BY i.product_id, i.store_id, i.quantity, p.name, p.sku,
                         p.category, p.unit_cost, p.selling_price, s.name, s.city
                ORDER BY p.name, s.name
                """
            ).fetchall()
            today = business_date()
            items = []
            for row in rows:
                item = dict(row)
                raw_date = item.pop("first_recorded_stock_in", None)
                age = None
                if raw_date:
                    try:
                        age = max(0, (today - date.fromisoformat(str(raw_date)[:10])).days)
                    except (TypeError, ValueError):
                        age = None
                item["stock_age_days"] = age
                item["age_status"] = "Needs data" if age is None else ("Old" if age >= 60 else ("Ageing" if age >= 30 else "Fresh"))
                item["age_source"] = "Recorded stock-in movement" if age is not None else "No recorded stock-in date"
                item["inventory_value"] = round(float(item["quantity"] or 0) * float(item["unit_cost"] or 0), 2)
                item["value_at_risk"] = item["inventory_value"] if age is not None and age >= 30 else 0.0
                items.append(item)
            return {
                "as_of": today.isoformat(),
                "ageing_policy": "Fresh: under 30 days; Ageing: 30–59 days; Old: 60+ days. Age is measured from the earliest recorded positive opening-stock/receipt movement, not batch-level FIFO age.",
                "items": items,
                "summary": {
                    "tracked": sum(1 for x in items if x["stock_age_days"] is not None),
                    "needs_data": sum(1 for x in items if x["stock_age_days"] is None),
                    "ageing_or_old": sum(1 for x in items if x["stock_age_days"] is not None and x["stock_age_days"] >= 30),
                    "value_at_risk": round(sum(x["value_at_risk"] for x in items), 2),
                },
            }

    @app.get("/api/orders")
    def orders():
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT po.*, s.name AS supplier_name, s.reliability,
                       p.name AS product_name, st.name AS store_name
                FROM purchase_orders po
                JOIN suppliers s ON s.id = po.supplier_id
                JOIN products p ON p.id = po.product_id
                JOIN stores st ON st.id = po.store_id
                ORDER BY po.expected_at
                """
            ).fetchall()
            suppliers = conn.execute(
                """
                SELECT c.*, s.name AS supplier_name, s.reliability, s.risk_notes,
                       p.name AS product_name, p.sku
                FROM supplier_catalog c
                JOIN suppliers s ON s.id = c.supplier_id
                JOIN products p ON p.id = c.product_id
                ORDER BY p.name, c.lead_time_days
                """
            ).fetchall()
            updates = conn.execute(
                """
                SELECT du.*, po.po_number, su.name AS supplier_name, p.name AS product_name,
                       st.name AS store_name
                FROM supplier_delivery_updates du
                JOIN purchase_orders po ON po.id = du.purchase_order_id
                JOIN suppliers su ON su.id = du.supplier_id
                JOIN products p ON p.id = po.product_id
                JOIN stores st ON st.id = po.store_id
                ORDER BY du.id DESC LIMIT 50
                """
            ).fetchall()
            return {
                "orders": [dict(r) for r in rows],
                "catalog": [dict(r) for r in suppliers],
                "delivery_updates": [dict(r) for r in updates],
                "notice": "Demo environment: supplier updates are simulated and stored locally. No external supplier is contacted.",
            }

    @app.post("/api/orders/{order_id}/supplier-update")
    def submit_supplier_update(order_id: int, body: SupplierDeliveryUpdate):
        """Record a vendor delivery status/ETA update in the configured database.

        This is a local hackathon simulation, not a real authenticated supplier portal.
        It does not mark inventory as received or contact the named supplier.
        """
        try:
            revised_date = date.fromisoformat(body.revised_expected_at)
        except ValueError as exc:
            raise HTTPException(422, "Revised ETA must be a valid date in YYYY-MM-DD format.") from exc
        contact = body.supplier_contact.strip()
        note = body.note.strip()
        if not contact or not note:
            raise HTTPException(422, "Supplier contact and update note are required.")

        reported_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        with get_conn() as conn:
            po = conn.execute(
                """SELECT po.*, su.name AS supplier_name, p.name AS product_name,
                          st.name AS store_name
                   FROM purchase_orders po
                   JOIN suppliers su ON su.id = po.supplier_id
                   JOIN products p ON p.id = po.product_id
                   JOIN stores st ON st.id = po.store_id
                   WHERE po.id = ?""",
                (order_id,),
            ).fetchone()
            if not po:
                raise HTTPException(404, "Purchase order not found.")
            if str(po["status"]).lower() in ("received", "cancelled", "rejected"):
                raise HTTPException(409, f"PO {po['po_number']} is {po['status']} and cannot accept delivery updates.")

            previous_eta = po["expected_at"]
            appended_note = (po["notes"] or "").strip()
            line = f"Supplier report [{reported_at}]: {body.status}; revised ETA {body.revised_expected_at}; {note}"
            combined_note = (appended_note + "\n" + line).strip()[-2000:]
            conn.execute(
                "UPDATE purchase_orders SET status = ?, expected_at = ?, notes = ? WHERE id = ?",
                (body.status, revised_date.isoformat(), combined_note, order_id),
            )
            conn.execute(
                """INSERT INTO supplier_delivery_updates (
                       purchase_order_id, supplier_id, status_reported, previous_expected_at,
                       revised_expected_at, supplier_contact, note, reported_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (order_id, po["supplier_id"], body.status, previous_eta,
                 revised_date.isoformat(), contact, note, reported_at),
            )
            details = {
                "po_number": po["po_number"], "supplier_name": po["supplier_name"],
                "supplier_contact": contact, "product_name": po["product_name"],
                "store_name": po["store_name"], "previous_expected_at": previous_eta,
                "revised_expected_at": revised_date.isoformat(), "status": body.status,
                "note": note, "inventory_changed": False,
            }
            conn.execute(
                """INSERT INTO audit_log (
                       recommendation_id, decision, option_id, option_type, actor,
                       timestamp, summary, result, details_json, executed
                   ) VALUES (NULL, 'supplier_update', NULL, 'delivery_update', ?, ?, ?, ?, ?, 0)""",
                (f"Supplier contact: {contact}", reported_at,
                 f"Delivery update for {po['po_number']}",
                 f"{po['supplier_name']} reported {body.status}; ETA changed from {previous_eta} to {revised_date.isoformat()}. Inventory unchanged.",
                 json.dumps(details)),
            )
            # Recalculate pending recommendations with the updated ETA/status.
            engine.refresh(conn)
            return {
                "ok": True,
                "message": f"Delivery update saved for {po['po_number']}. Inventory remains unchanged until the store confirms receipt.",
                "purchase_order": {
                    "id": order_id, "po_number": po["po_number"],
                    "supplier_name": po["supplier_name"], "product_name": po["product_name"],
                    "store_name": po["store_name"], "status": body.status,
                    "previous_expected_at": previous_eta,
                    "expected_at": revised_date.isoformat(),
                },
                "recommendations_refreshed": True,
            }

    @app.get("/api/orders/{order_id}/supplier-updates")
    def supplier_update_history(order_id: int):
        with get_conn() as conn:
            exists = conn.execute("SELECT id FROM purchase_orders WHERE id = ?", (order_id,)).fetchone()
            if not exists:
                raise HTTPException(404, "Purchase order not found.")
            rows = conn.execute(
                """SELECT * FROM supplier_delivery_updates
                   WHERE purchase_order_id = ? ORDER BY id DESC""", (order_id,)
            ).fetchall()
            return {"items": [dict(row) for row in rows]}

    @app.get("/api/store/catalog")
    def store_catalog(store_id: int = 1):
        with get_conn() as conn:
            return storefront.catalog_payload(conn, store_id)

    @app.post("/api/store/products")
    def create_store_product(body: StoreProductCreate):
        """Add a new catalog SKU and its opening stock, using the same database as VoltPilot analysis."""
        with get_conn() as conn:
            return storefront.create_store_product(conn, body)

    @app.post("/api/store/stock-receipts")
    def receive_store_stock(body: InventoryStockReceipt):
        """Record receipt/restocking of an existing product at a selected store."""
        with get_conn() as conn:
            return storefront.receive_store_stock(conn, body)

    @app.get("/api/store/inventory-movements")
    def inventory_movements(store_id: int | None = None, product_id: int | None = None, limit: int = 100):
        with get_conn() as conn:
            return storefront.list_inventory_movements(conn, store_id=store_id, product_id=product_id, limit=limit)

    @app.post("/api/store/checkout")
    def store_checkout(body: StoreCheckout):
        with get_conn() as conn:
            return storefront.complete_checkout(conn, body)

    @app.get("/api/store/sales")
    def store_sales(store_id: int | None = None, limit: int = 50):
        with get_conn() as conn:
            return storefront.list_sales(conn, store_id=store_id, limit=limit)

    @app.get("/api/store/sales/{sale_id}")
    def store_sale_detail(sale_id: int):
        with get_conn() as conn:
            result = storefront.sale_detail(conn, sale_id)
        if result is None:
            raise HTTPException(404, "Sale receipt not found.")
        return result

    @app.get("/api/actions")
    def actions():
        with get_conn() as conn:
            return {"items": executor.list_actions(conn)}

    @app.post("/api/actions/{decision_id}/approve")
    def approve(decision_id: int, body: DecisionAction | None = None):
        note = body.note if body else ""
        option_id = body.option_id if body else None
        with get_conn() as conn:
            result = executor.approve(conn, decision_id, option_id=option_id, note=note)
        if not result.get("ok"):
            raise HTTPException(result.get("status_code", 400), result.get("error", "Approve failed"))
        return result

    @app.post("/api/actions/{decision_id}/reject")
    def reject(decision_id: int, body: DecisionAction | None = None):
        note = body.note if body else ""
        with get_conn() as conn:
            result = executor.reject(conn, decision_id, note=note)
        if not result.get("ok"):
            raise HTTPException(result.get("status_code", 400), result.get("error", "Reject failed"))
        return result

    @app.get("/api/risk-areas")
    def risk_areas_overview():
        with get_conn() as conn:
            return risk_areas.get_overview(conn)

    @app.get("/api/risk-areas/{area_id}")
    def risk_area_detail(area_id: str):
        with get_conn() as conn:
            result = risk_areas.get_detail(conn, area_id)
        if result is None:
            raise HTTPException(404, "Risk area not found.")
        return result

    @app.get("/api/forecast/status")
    def forecast_status():
        with get_conn() as conn:
            return forecasting.get_status(conn)

    @app.post("/api/forecast/import-history")
    def forecast_import_history(payload: dict):
        csv_text = payload.get("csv_text") if isinstance(payload, dict) else None
        with get_conn() as conn:
            result = forecasting.import_history_csv(conn, csv_text)
            # Imported observations become the current sales source for the agent.
            refreshed = engine.refresh(conn)
            result["agent_recommendations_refreshed"] = len(refreshed)
            result["forecast_status"] = forecasting.get_status(conn)
            return result

    @app.post("/api/forecast/train")
    def train_forecast_model():
        try:
            with get_conn() as conn:
                result = forecasting.train_and_evaluate(conn)
                # Regenerate the pending decisions so a model that beats the baseline
                # can influence stock-risk calculations in the existing decision engine.
                refreshed = engine.refresh(conn)
                result["agent_recommendations_refreshed"] = len(refreshed)
                return result
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/forecast/predictions")
    def forecast_predictions(days_ahead: int = 7):
        try:
            with get_conn() as conn:
                return forecasting.predict_all(conn, days_ahead=days_ahead)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/reset")
    def reset():
        if USE_POSTGRES or not ALLOW_DEMO_RESET:
            raise HTTPException(403, "Demo reset is disabled for the live/real-data workspace. No data was changed.")
        with get_conn() as conn:
            seed(conn)
            storefront.ensure_store_catalog(conn)
            engine.refresh(conn)
        return {"ok": True, "message": "Local demo data reset. This action is not available on the live PostgreSQL workspace."}

    return app


app = create_app()
