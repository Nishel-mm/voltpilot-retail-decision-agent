"""Backend-driven analysis for VoltPilot's seven retail risk areas.

Counts and findings are calculated from current SQLite data on each request.
No LLM or external service is used. Unsupported data is explicitly marked as missing.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from ..config import DEMO_TODAY
from .metrics import get_assumptions, sales_velocity, stock_cover_days

TODAY = date.fromisoformat(DEMO_TODAY)

AREA_META = [
    {"id": "stockout", "number": "01", "title": "Fast sellers & stockout prevention", "short": "Fast sellers that may run out before replenishment", "description": "Compare current stock cover with supplier lead times and upcoming demand.", "icon": "stockout"},
    {"id": "ageing", "number": "02", "title": "Ageing stock & value risk", "short": "Slow-moving stock tying up capital", "description": "Find inventory with long days on hand and low recent sales velocity.", "icon": "ageing"},
    {"id": "promotions", "number": "03", "title": "Promotion, weekend & event spikes", "short": "Demand changes around promotions and events", "description": "Inspect upcoming promotions and estimate stock exposure using the configured uplift assumption.", "icon": "promotions"},
    {"id": "launches", "number": "04", "title": "Older models losing demand", "short": "Potential cannibalisation from new launches", "description": "Compare older-model demand before and after a linked new-model launch.", "icon": "launches"},
    {"id": "suppliers", "number": "05", "title": "Supplier trade-offs", "short": "Price versus lead time and supply constraints", "description": "Compare supplier prices, lead times, available quantities and reliability.", "icon": "suppliers"},
    {"id": "imbalance", "number": "06", "title": "Inter-store inventory imbalance", "short": "Surplus in one store while another is nearly out", "description": "Compare stock cover across stores and identify possible transfer candidates.", "icon": "imbalance"},
    {"id": "purchase-orders", "number": "07", "title": "Late purchase orders", "short": "Overdue deliveries that may create stock gaps", "description": "Detect overdue or delayed inbound orders and relate them to current stock exposure.", "icon": "purchase-orders"},
]


def _assumptions(conn):
    a = get_assumptions(conn)
    return {
        "lookback": int(a.get("velocity_lookback_days", 14)),
        "promo_uplift": float(a.get("promo_demand_uplift", 0.4)),
        "transfer_days": int(a.get("transfer_days", 1)),
        "min_safe_cover": int(a.get("min_safe_cover_days", 7)),
        "ageing_days": int(a.get("ageing_days_threshold", 90)),
    }


def _inventory_rows(conn):
    rows = conn.execute("""
        SELECT i.product_id, i.store_id, i.quantity, i.days_on_hand,
               p.name AS product_name, p.sku, p.category, p.unit_cost, p.selling_price,
               s.name AS store_name, s.city, s.code AS store_code
        FROM inventory i
        JOIN products p ON p.id = i.product_id
        JOIN stores s ON s.id = i.store_id
        ORDER BY p.name, s.name
    """).fetchall()
    return [dict(r) for r in rows]


def _promotion_for_pair(conn, product_id, store_id, horizon=30):
    end = (TODAY + timedelta(days=horizon)).isoformat()
    rows = conn.execute("""
        SELECT id, name, start_date, end_date, store_id
        FROM promotions
        WHERE product_id = ? AND (store_id IS NULL OR store_id = ?)
          AND start_date <= ? AND end_date >= ?
        ORDER BY start_date
    """, (product_id, store_id, end, TODAY.isoformat())).fetchall()
    return [dict(r) for r in rows]


def _supplier_rows(conn, product_id):
    rows = conn.execute("""
        SELECT c.supplier_id, c.unit_price, c.lead_time_days, c.available_qty,
               s.name AS supplier_name, s.reliability, s.risk_notes
        FROM supplier_catalog c JOIN suppliers s ON s.id = c.supplier_id
        WHERE c.product_id = ?
        ORDER BY c.unit_price, c.lead_time_days
    """, (product_id,)).fetchall()
    return [dict(r) for r in rows]


def _make_finding(title, severity, product=None, store=None, evidence=None, recommendation=None, metrics=None):
    return {
        "title": title,
        "severity": severity,
        "product": product or "—",
        "store": store or "—",
        "evidence": evidence or [],
        "recommendation": recommendation or "Review this signal and confirm the next step.",
        "metrics": metrics or {},
    }


def _analyze(conn):
    a = _assumptions(conn)
    rows = _inventory_rows(conn)
    velocity = {}
    for r in rows:
        velocity[(r["product_id"], r["store_id"])] = sales_velocity(
            conn, r["product_id"], r["store_id"], a["lookback"]
        )

    result = {meta["id"]: {**meta, "status": "clear", "issue_count": 0, "severity": "Low", "findings": [], "data_note": None} for meta in AREA_META}

    # 01: Stockout before replenishment. Never hide an empty/low-stock shelf just
    # because a newly added SKU has no supplier mapping or sales history yet.
    stockout_findings = []
    for r in rows:
        quantity = int(r["quantity"] or 0)
        v = velocity[(r["product_id"], r["store_id"])]
        suppliers = _supplier_rows(conn, r["product_id"])
        promos = _promotion_for_pair(conn, r["product_id"], r["store_id"], horizon=30)
        demand = v * (1 + a["promo_uplift"] if promos else 1)
        cover = quantity / demand if demand > 0 else None
        lead = min(int(s["lead_time_days"]) for s in suppliers) if suppliers else None

        out_of_stock = quantity <= 0
        supplier_risk = (cover is not None and lead is not None and
                         (cover < lead + a["transfer_days"] or cover <= 3))
        low_stock_without_supply_context = quantity <= 3 and (lead is None or v <= 0)
        low_cover_without_supplier = quantity > 0 and lead is None and cover is not None and cover <= 3
        if not (out_of_stock or supplier_risk or low_stock_without_supply_context or low_cover_without_supplier):
            continue

        if out_of_stock:
            severity = "Critical"
            title = f"{r['product_name']} is OUT OF STOCK at {r['store_name']}"
        elif lead is None:
            severity = "High" if quantity <= 1 else "Medium"
            title = f"{r['product_name']} has low stock; replenishment lead time is unknown"
        else:
            severity = "Critical" if cover is not None and cover <= 2 else "High"
            title = f"{r['product_name']} may run out before replenishment"

        evidence = [f"On hand: {quantity} units", f"Recent sales velocity: {v:.2f} units/day" if v > 0 else "Recent sales velocity unavailable or zero", f"Estimated stock cover: {cover:.2f} days" + (" (promotion-adjusted)" if promos else "") if cover is not None else "Stock cover cannot be estimated without a positive demand history"]
        if lead is not None:
            gap = max(0, round((demand or 0) * (lead + a["transfer_days"]) - quantity))
            evidence.extend([f"Fastest listed supplier lead time: {lead} days", f"Potential gap through lead time plus transfer buffer: about {gap} units"])
        else:
            gap = max(0, round((demand or 0) * a["transfer_days"] - quantity))
            evidence.append("No supplier option/lead time is mapped for this SKU; add supplier data to compare replenishment feasibility.")
        if out_of_stock:
            recommendation = "Treat this as a current shelf gap. Check a safe inter-store transfer, record inbound supplier options, and keep checkout blocked until stock is received. Require manager approval for simulated actions."
        elif lead is None:
            recommendation = "Check store surplus and register supplier price, lead time, available quantity and MOQ. Until lead time is known, show this as a data-backed low-stock warning rather than claiming a precise arrival-time stockout."
        else:
            recommendation = "Check safe inter-store surplus first, then compare supplier lead time and cost. Require manager approval before any simulated action."
        stockout_findings.append(_make_finding(
            title, severity, r["product_name"], r["store_name"], evidence,
            recommendation,
            {"stock": quantity, "velocity": v, "cover_days": round(cover, 2) if cover is not None else None,
             "fastest_lead_days": lead, "estimated_gap_units": gap, "out_of_stock": out_of_stock,
             "supplier_data_available": bool(suppliers)}
        ))
    result["stockout"]["findings"] = sorted(
        stockout_findings,
        key=lambda f: (not f["metrics"].get("out_of_stock", False), f["severity"] not in ("Critical", "High"), f["metrics"].get("cover_days") if f["metrics"].get("cover_days") is not None else 999)
    )

    # 02: Ageing inventory
    ageing = []
    for r in rows:
        v = velocity[(r["product_id"], r["store_id"])]
        # A fully sold-out SKU no longer has ageing capital on the shelf.
        if int(r["quantity"] or 0) > 0 and r["days_on_hand"] >= a["ageing_days"] and v < 0.3:
            capital = round(r["quantity"] * r["unit_cost"], 2)
            ageing.append(_make_finding(
                f"{r['product_name']} has ageing inventory",
                "High" if r["days_on_hand"] >= a["ageing_days"] * 1.35 else "Medium",
                r["product_name"], r["store_name"],
                [f"Recorded days on hand: {r['days_on_hand']}", f"Recent sales velocity: {v:.2f} units/day", f"Units on hand: {r['quantity']}", f"Inventory cost tied up (not a depreciation estimate): ₹{capital:,.0f}"],
                "Review markdown, bundle, transfer, or supplier-return eligibility. The current dataset does not contain a depreciation curve, so value loss is not fabricated.",
                {"days_on_hand": r["days_on_hand"], "velocity": v, "quantity": r["quantity"], "capital_tied_inr": capital}
            ))
    result["ageing"]["findings"] = sorted(ageing, key=lambda f: f["metrics"].get("days_on_hand", 0), reverse=True)

    # 03: Upcoming/active promotions plus observed weekend demand spikes.
    # Global promotions are evaluated separately for each store inventory row so
    # their demand/coverage actually reacts to sales at that store.
    promos = conn.execute("""
        SELECT pr.*, p.name AS product_name, p.unit_cost, p.selling_price,
               s.name AS promotion_store_name, i.store_id AS inventory_store_id,
               inv_store.name AS inventory_store_name, i.quantity
        FROM promotions pr JOIN products p ON p.id = pr.product_id
        LEFT JOIN stores s ON s.id = pr.store_id
        LEFT JOIN inventory i ON i.product_id = pr.product_id
             AND (pr.store_id IS NULL OR i.store_id = pr.store_id)
        LEFT JOIN stores inv_store ON inv_store.id = i.store_id
        WHERE pr.start_date <= ? AND pr.end_date >= ?
        ORDER BY pr.start_date, inv_store.name
    """, ((TODAY + timedelta(days=30)).isoformat(), TODAY.isoformat())).fetchall()
    promo_findings = []
    for pr in promos:
        effective_store_id = pr["store_id"] if pr["store_id"] is not None else pr["inventory_store_id"]
        store_name = pr["promotion_store_name"] or pr["inventory_store_name"] or "Store scope unavailable"
        v = velocity.get((pr["product_id"], effective_store_id), 0.0) if effective_store_id is not None else 0.0
        days_to_start = (date.fromisoformat(pr["start_date"]) - TODAY).days
        promo_days = max(1, (date.fromisoformat(pr["end_date"]) - max(TODAY, date.fromisoformat(pr["start_date"]))).days + 1)
        qty = int(pr["quantity"] or 0)
        estimate = round(v * (1 + a["promo_uplift"]) * promo_days, 1) if v > 0 else None
        evidence = [f"Promotion: {pr['name']}", f"Window: {pr['start_date']} to {pr['end_date']}", f"Starts in {max(0, days_to_start)} day(s)" if days_to_start >= 0 else "Promotion is already active", f"Configured uplift assumption: +{a['promo_uplift']*100:.0f}%", f"Store on hand: {qty} units", f"Estimated promotion-window demand: {estimate} units" if estimate is not None else "Store-specific sales history unavailable for this promotion scope"]
        promo_findings.append(_make_finding(
            f"Demand spike watch: {pr['product_name']}",
            "High" if (qty <= 0 or (estimate is not None and qty < estimate)) else "Medium",
            pr["product_name"], store_name, evidence,
            "Recheck projected demand and stock cover before/during the promotion. Uplift is a configurable assumption, not measured promotion performance.",
            {"days_to_start": days_to_start, "promo_days": promo_days, "inventory": qty, "estimated_demand": estimate, "uplift_assumption": a["promo_uplift"], "store_id": effective_store_id}
        ))

    # Detect a measured Saturday/Sunday uplift only when there are enough daily
    # observations; missing records for a new SKU are not silently treated as 0.
    weekend_findings = []
    history_start = (TODAY - timedelta(days=max(28, a["lookback"] * 2))).isoformat()
    for r in rows:
        daily = conn.execute("""
            SELECT sale_date, SUM(units) AS units
            FROM sales_daily
            WHERE product_id = ? AND store_id = ? AND sale_date > ? AND sale_date <= ?
            GROUP BY sale_date ORDER BY sale_date
        """, (r["product_id"], r["store_id"], history_start, TODAY.isoformat())).fetchall()
        weekday_values, weekend_values = [], []
        for item in daily:
            day = date.fromisoformat(item["sale_date"])
            # Saturday/Sunday are treated as weekend days in this detector.
            (weekend_values if day.weekday() >= 5 else weekday_values).append(float(item["units"] or 0))
        if len(weekend_values) < 2 or len(weekday_values) < 3:
            continue
        weekend_avg = sum(weekend_values) / len(weekend_values)
        weekday_avg = sum(weekday_values) / len(weekday_values)
        if weekday_avg > 0 and weekend_avg >= weekday_avg * 1.25 and weekend_avg - weekday_avg >= 0.25:
            uplift = round((weekend_avg / weekday_avg - 1) * 100, 1)
            weekend_findings.append(_make_finding(
                f"Weekend demand runs higher for {r['product_name']}",
                "High" if int(r["quantity"] or 0) <= weekend_avg * 3 else "Medium",
                r["product_name"], r["store_name"],
                [f"Average Saturday/Sunday sales: {weekend_avg:.2f} units/day across {len(weekend_values)} recorded weekend days", f"Average weekday sales: {weekday_avg:.2f} units/day across {len(weekday_values)} recorded weekdays", f"Observed weekend uplift: {uplift:.1f}%", f"Current on-hand stock: {int(r['quantity'] or 0)} units"],
                "Plan weekend replenishment against the observed higher sales rate and verify the pattern with more history. This is a historical signal, not proof that every upcoming weekend will repeat it.",
                {"weekend_avg_units_per_day": round(weekend_avg, 3), "weekday_avg_units_per_day": round(weekday_avg, 3), "weekend_uplift_percent": uplift, "weekend_days_observed": len(weekend_values), "weekday_days_observed": len(weekday_values), "inventory": int(r["quantity"] or 0)}
            ))
    result["promotions"]["findings"] = promo_findings + weekend_findings
    result["promotions"]["data_note"] = "Promotion demand uses a configurable uplift assumption. Weekend spikes are flagged only when at least 2 recorded weekend days and 3 recorded weekdays are available; event spikes require event/promotion records in the database."

    # 04: New-launch cannibalisation. Current schema has no launch mapping or launch history.
    result["launches"]["status"] = "needs_data"
    result["launches"]["data_note"] = "The current database has no old-model → successor-model relationship or product launch date. Add those records before claiming a demand decline is caused by a new launch."
    result["launches"]["findings"] = [_make_finding(
        "Product-launch relationship data is required", "Low", evidence=[
            "Products currently store SKU, name, category, unit cost and selling price.",
            "No successor-model mapping, launch date, or pre/post-launch demand comparison exists in the schema."
        ], recommendation="Add model family, predecessor/successor SKU, launch date, and time-series sales around launch. Then compare older-model velocity before and after launch. Do not infer cannibalisation from product names alone.")]

    # 05: Supplier price / speed / reliability tradeoffs
    supplier_findings = []
    products = conn.execute("SELECT id, name, sku FROM products ORDER BY name").fetchall()
    for p in products:
        catalog = _supplier_rows(conn, p["id"])
        if len(catalog) < 2:
            continue
        cheapest = min(catalog, key=lambda x: x["unit_price"])
        fastest = min(catalog, key=lambda x: (x["lead_time_days"], x["unit_price"]))
        if cheapest["supplier_id"] == fastest["supplier_id"]:
            # Still include when reliability differs substantially, otherwise no explicit trade-off.
            reliabilities = {x["reliability"] for x in catalog}
            if len(reliabilities) < 2:
                continue
        premium = ((fastest["unit_price"] / cheapest["unit_price"]) - 1) * 100 if cheapest["unit_price"] else 0
        supplier_findings.append(_make_finding(
            f"Supplier trade-off: {p['name']}", "Medium", p["name"], "Multi-store supply",
            [f"Lowest listed price: {cheapest['supplier_name']} at ₹{cheapest['unit_price']:,.0f}/unit; lead time {cheapest['lead_time_days']} days", f"Fastest listed option: {fastest['supplier_name']} at ₹{fastest['unit_price']:,.0f}/unit; lead time {fastest['lead_time_days']} days", f"Fastest option price premium over cheapest: {premium:.1f}%", f"Fastest option available quantity: {fastest['available_qty']} units", "MOQ is not stored in the current supplier schema; it must be supplied before MOQ-aware order sizing."],
            "Compare the cost premium with stockout risk and required arrival date. Validate MOQ and supplier reliability before proposing an order.",
            {"supplier_options": len(catalog), "cheapest_price": cheapest["unit_price"], "cheapest_lead_days": cheapest["lead_time_days"], "fastest_price": fastest["unit_price"], "fastest_lead_days": fastest["lead_time_days"], "fastest_premium_percent": round(premium, 2)}
        ))
    result["suppliers"]["findings"] = supplier_findings

    # 06: Inter-store imbalance
    by_product = defaultdict(list)
    for r in rows:
        v = velocity[(r["product_id"], r["store_id"])]
        cover = stock_cover_days(r["quantity"], v)
        by_product[r["product_id"]].append({**r, "velocity": v, "cover": cover})
    imbalance_findings = []
    for pid, stores in by_product.items():
        viable = [s for s in stores if s["cover"] is not None]
        if len(viable) < 2:
            continue
        destination = min(viable, key=lambda s: s["cover"])
        source_candidates = [s for s in viable if s["store_id"] != destination["store_id"] and s["cover"] >= a["min_safe_cover"] * 1.5]
        if destination["cover"] < 5 and source_candidates:
            source = max(source_candidates, key=lambda s: s["cover"])
            max_transfer = max(0, int(source["quantity"] - source["velocity"] * (a["min_safe_cover"] + a["transfer_days"])))
            if max_transfer > 0:
                imbalance_findings.append(_make_finding(
                    f"{destination['product_name']}: stock imbalance across stores", "High" if destination["cover"] < 3 else "Medium",
                    destination["product_name"], destination["store_name"],
                    [f"Low-cover store: {destination['store_name']} has {destination['quantity']} units and {destination['cover']:.2f} days of historical cover", f"Potential source: {source['store_name']} has {source['quantity']} units and {source['cover']:.2f} days of historical cover", f"Estimated transferable surplus: up to {max_transfer} units while preserving configured safe cover plus transfer time", "Historical cover is based on recent sales velocity; promotion-adjusted cover may be lower."],
                    "Evaluate a transfer and calculate the source store's cover after transfer before choosing transfer over purchase.",
                    {"destination_cover_days": destination["cover"], "source_cover_days": source["cover"], "max_transfer_units": max_transfer, "source_store": source["store_name"]}
                ))
    result["imbalance"]["findings"] = imbalance_findings

    # 07: Late purchase orders
    po_rows = conn.execute("""
        SELECT po.*, p.name AS product_name, p.sku, s.name AS store_name, su.name AS supplier_name
        FROM purchase_orders po JOIN products p ON p.id=po.product_id
        JOIN stores s ON s.id=po.store_id JOIN suppliers su ON su.id=po.supplier_id
        WHERE lower(po.status) IN ('delayed', 'late', 'overdue')
           OR (po.received_at IS NULL AND lower(po.status) NOT IN ('received', 'cancelled', 'rejected') AND po.expected_at < ?)
        ORDER BY po.expected_at
    """, (TODAY.isoformat(),)).fetchall()
    late_findings = []
    for po in po_rows:
        expected = date.fromisoformat(po["expected_at"])
        overdue = max(0, (TODAY - expected).days)
        v = velocity.get((po["product_id"], po["store_id"]), 0.0)
        inv = next((r for r in rows if r["product_id"] == po["product_id"] and r["store_id"] == po["store_id"]), None)
        cover = (inv["quantity"] / v) if inv and v > 0 else None
        reported_delayed = str(po["status"]).lower() in ("delayed", "late", "overdue")
        po_title = f"{po['po_number']} delivery reported delayed" if reported_delayed and overdue == 0 else f"{po['po_number']} is overdue"
        late_findings.append(_make_finding(
            po_title, "High" if (overdue >= 2 or reported_delayed) and (cover is None or cover < 7) else "Medium",
            po["product_name"], po["store_name"],
            [f"Supplier: {po['supplier_name']}", f"Supplier-reported status: {po['status']}", f"Expected arrival (latest ETA): {po['expected_at']}", f"Days past latest ETA: {overdue}", f"PO quantity: {po['quantity']} units", f"Current inventory: {inv['quantity']} units" if inv else "Current inventory row unavailable", f"Estimated current cover: {cover:.2f} days" if cover is not None else "Current sales cover cannot be calculated"],
            "Request a revised ETA (simulated in this prototype), inspect alternative supply or a safe store transfer, and do not count ordered stock as available until received.",
            {"po_number": po["po_number"], "days_overdue": overdue, "quantity": po["quantity"], "cover_days": round(cover, 2) if cover is not None else None}
        ))
    result["purchase-orders"]["findings"] = late_findings

    # Finalize status and counts; counts always reflect finding rows above.
    for key, area in result.items():
        area["issue_count"] = 0 if area["status"] == "needs_data" else len(area["findings"])
        if area["status"] != "needs_data":
            if area["issue_count"]:
                area["status"] = "active"
            else:
                area["status"] = "clear"
        severities = [f["severity"] for f in area["findings"]]
        area["severity"] = "Critical" if "Critical" in severities else "High" if "High" in severities else "Medium" if "Medium" in severities else "Low"
        area["findings"] = area["findings"][:30]
    latest_sale = conn.execute("SELECT MAX(created_at) AS value FROM retail_transactions").fetchone()["value"]
    latest_activity = conn.execute("SELECT MAX(timestamp) AS value FROM audit_log").fetchone()["value"]
    return {
        "today": DEMO_TODAY,
        "last_analyzed_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "latest_sale_at": latest_sale,
        "latest_activity_at": latest_activity,
        "items": [result[m["id"]] for m in AREA_META],
        "data_origin": "Live calculation from the current SQLite demo database on every request. A sale affects only risk areas whose evidence or thresholds are changed by that sale; supplier trade-offs or missing product-launch metadata will not arbitrarily change. Demo business date is fixed for reproducibility."
    }


def get_overview(conn):
    return _analyze(conn)


def get_detail(conn, area_id: str):
    overview = _analyze(conn)
    area = next((item for item in overview["items"] if item["id"] == area_id), None)
    if area is None:
        return None
    return {
        **area,
        "today": overview["today"],
        "last_analyzed_at": overview["last_analyzed_at"],
        "latest_sale_at": overview["latest_sale_at"],
        "latest_activity_at": overview["latest_activity_at"],
        "data_origin": overview["data_origin"],
    }
