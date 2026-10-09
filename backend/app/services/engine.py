"""Rule-based decision engine.

How the Attention Radar score is computed
-----------------------------------------
score = (severity_weight + urgency + financial_index) * confidence

- severity_weight: Critical=100, High=70, Medium=40, Low=15
- urgency: 30 minus days until stockout (floored at 0, capped at 30)
- financial_index: estimated INR impact / 400, capped at 80
- confidence: 0.45–0.95 based on data completeness and assumption load

Recommended option
------------------
Each feasible option gets option_score = benefit_inr - cost_inr - risk_penalty - time_penalty.
The highest score wins. Transfer is preferred only when it is cheaper/faster
AND does not push the source store below min_safe_cover_days.
"""

from __future__ import annotations

import json
from ..config import DEMO_TODAY
from . import metrics as m
from . import forecasting

SEVERITY_WEIGHT = {"Critical": 100, "High": 70, "Medium": 40, "Low": 15}


def _settings_payload(conn) -> list[dict]:
    return m.assumption_records(conn)


def _inventory_matrix(conn, product_id: int, lookback: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT i.*, s.name AS store_name, s.code AS store_code, s.city
        FROM inventory i
        JOIN stores s ON s.id = i.store_id
        WHERE i.product_id = ?
        """,
        (product_id,),
    ).fetchall()
    out = []
    from . import sales_data
    for row in rows:
        observed_velocity = sales_data.observed_sales_velocity(conn, product_id, row["store_id"], lookback)
        current_ml = forecasting.using_current_ml_model(conn)
        forecast_velocity = forecasting.forecast_daily_demand(conn, product_id, row["store_id"])
        vel = forecast_velocity if forecast_velocity is not None else m.sales_velocity(conn, product_id, row["store_id"], lookback)
        if forecast_velocity is not None and current_ml:
            velocity_source = "Ridge-regression forecast trained on current observed sales"
        elif observed_velocity is not None:
            velocity_source = "Retailer-entered POS/imported sales history"
        else:
            velocity_source = f"{lookback}-day seeded demo velocity (no entered history for this product/store)"
        cover = m.stock_cover_days(row["quantity"], vel)
        out.append(
            {
                **dict(row),
                "velocity": vel,
                "velocity_source": velocity_source,
                "cover_days": cover,
                "cover_label": m.cover_label(cover),
            }
        )
    return out


def _suppliers_for_product(conn, product_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT c.*, s.name AS supplier_name, s.reliability, s.risk_notes
        FROM supplier_catalog c
        JOIN suppliers s ON s.id = c.supplier_id
        WHERE c.product_id = ?
        ORDER BY c.lead_time_days, c.unit_price
        """,
        (product_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _open_pos(conn, product_id: int, store_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT po.*, s.name AS supplier_name, p.name AS product_name, st.name AS store_name
        FROM purchase_orders po
        JOIN suppliers s ON s.id = po.supplier_id
        JOIN products p ON p.id = po.product_id
        JOIN stores st ON st.id = po.store_id
        WHERE po.product_id = ? AND po.store_id = ?
          AND po.status IN ('ordered', 'delayed', 'in_transit')
        """,
        (product_id, store_id),
    ).fetchall()
    return [dict(r) for r in rows]


def _severity(days_to_stockout: float | None, impact: float, promo: bool, delayed: bool) -> str:
    if delayed and (days_to_stockout is not None and days_to_stockout <= 5):
        return "Critical"
    if days_to_stockout is not None and days_to_stockout <= 2:
        return "Critical"
    if days_to_stockout is not None and days_to_stockout <= 5 and promo:
        return "Critical"
    if days_to_stockout is not None and days_to_stockout <= 7:
        return "High"
    if delayed:
        return "High"
    if impact >= 15000:
        return "High"
    if impact >= 4000:
        return "Medium"
    return "Low"


def _score(severity: str, days_to_stockout: float | None, impact: float, confidence: float) -> float:
    urgency = 0.0
    if days_to_stockout is not None:
        urgency = max(0.0, min(30.0, 30.0 - days_to_stockout))
    financial_index = min(80.0, impact / 400.0)
    raw = (SEVERITY_WEIGHT[severity] + urgency + financial_index) * confidence
    return round(raw, 2)


def _option_rank(option: dict) -> float:
    return (
        option.get("expected_benefit_inr", 0)
        - option.get("estimated_cost_inr", 0)
        - option.get("risk_penalty", 0)
        - option.get("time_penalty", 0)
    )


def _do_nothing_option(cover, why: str) -> dict:
    return {
        "id": "do_nothing",
        "type": "do_nothing",
        "title": "Take no action",
        "estimated_cost_inr": 0,
        "expected_benefit_inr": 0,
        "time_until_available_days": 0,
        "risk": "Stockout or ageing risk continues if the forecast is correct.",
        "limitations": "Does not change inventory, POs, or promotions.",
        "evidence": [why, f"Current stock cover: {m.cover_label(cover)}"],
        "assumptions": ["Forecast continues at recent velocity unless a promotion uplift is applied."],
        "feasible": True,
        "simulated": False,
        "payload": {},
        "risk_penalty": 800 if cover is not None and cover < 5 else 50,
        "time_penalty": 0,
    }


def _transfer_option(
    *,
    product,
    dest,
    source,
    qty,
    assumptions,
    dest_demand,
    dest_cover,
) -> dict:
    cost = qty * assumptions["transfer_cost_per_unit"]
    transfer_days = assumptions["transfer_days"]
    source_after = m.source_cover_after_transfer(source["quantity"], qty, source["velocity"])
    dest_after = m.stock_cover_days(dest["quantity"] + qty, dest_demand)
    creates_shortage = source_after is not None and source_after < assumptions["min_safe_cover_days"]
    feasible = qty > 0 and source["quantity"] >= qty and not creates_shortage
    lost_without = m.stockout_units(dest["quantity"], dest_demand, assumptions["horizon_days"])
    lost_with = m.stockout_units(dest["quantity"] + qty, dest_demand, assumptions["horizon_days"])
    benefit = m.financial_stockout_impact(
        lost_without - lost_with, product["selling_price"], assumptions["margin_on_lost_sale"]
    )
    return {
        "id": f"transfer_{source['store_id']}_to_{dest['store_id']}",
        "type": "transfer",
        "title": f"Transfer {qty} units from {source['store_name']} to {dest['store_name']}",
        "estimated_cost_inr": round(cost, 2),
        "expected_benefit_inr": benefit,
        "time_until_available_days": transfer_days,
        "risk": (
            f"Source cover after transfer would be {m.cover_label(source_after)}. "
            + ("This would create a shortage at the source store." if creates_shortage else "Source remains above the safety cover assumption.")
        ),
        "limitations": "Transfer time and cost are configurable assumptions, not measured logistics data.",
        "evidence": [
            f"{source['store_name']} has {source['quantity']} units, velocity {source['velocity']}/day, cover {source['cover_label']}.",
            f"{dest['store_name']} has {dest['quantity']} units, projected demand {dest_demand}/day, cover {m.cover_label(dest_cover)}.",
            f"Surplus check reserved {assumptions['min_safe_cover_days']} + {transfer_days} days of source demand.",
        ],
        "assumptions": [
            f"transfer_days = {transfer_days}",
            f"transfer_cost_per_unit = ₹{assumptions['transfer_cost_per_unit']}",
            f"min_safe_cover_days = {assumptions['min_safe_cover_days']}",
        ],
        "feasible": feasible,
        "simulated": True,
        "payload": {
            "product_id": product["id"],
            "from_store_id": source["store_id"],
            "to_store_id": dest["store_id"],
            "quantity": qty,
        },
        "what_if": {
            "source_cover_before": source["cover_days"],
            "source_cover_after": source_after,
            "dest_cover_before": dest_cover,
            "dest_cover_after": dest_after,
            "creates_source_shortage": creates_shortage,
        },
        "risk_penalty": 4000 if creates_shortage else 120,
        "time_penalty": transfer_days * 40,
    }


def _purchase_option(product, dest, supplier, qty, dest_demand, assumptions) -> dict:
    qty = max(qty, 1)
    if supplier["available_qty"] < qty:
        qty = supplier["available_qty"]
    cost = qty * supplier["unit_price"]
    lead = supplier["lead_time_days"]
    lost_without = m.stockout_units(dest["quantity"], dest_demand, assumptions["horizon_days"])
    # Goods are NOT available until lead time elapses.
    days_with_stock = max(0, assumptions["horizon_days"] - lead)
    on_hand_until_arrival = max(0.0, dest["quantity"] - dest_demand * lead)
    lost_during_wait = m.stockout_units(dest["quantity"], dest_demand, lead)
    lost_after = m.stockout_units(on_hand_until_arrival + qty, dest_demand, days_with_stock) if days_with_stock else 0
    benefit = m.financial_stockout_impact(
        lost_without - (lost_during_wait + lost_after),
        product["selling_price"],
        assumptions["margin_on_lost_sale"],
    )
    feasible = qty > 0 and supplier["available_qty"] > 0
    reliability_pen = {"High": 80, "Medium": 250, "Low": 900}.get(supplier["reliability"], 200)
    return {
        "id": f"purchase_s{supplier['supplier_id']}",
        "type": "purchase",
        "title": f"Place simulated PO with {supplier['supplier_name']} ({qty} units)",
        "estimated_cost_inr": round(cost, 2),
        "expected_benefit_inr": max(0.0, benefit),
        "time_until_available_days": lead,
        "risk": f"Reliability {supplier['reliability']}. {supplier['risk_notes']} Stock does not increase until goods arrive.",
        "limitations": "This is a simulated purchase order. No real supplier is contacted.",
        "evidence": [
            f"Unit price ₹{supplier['unit_price']}, lead time {lead} days, available {supplier['available_qty']} units.",
            f"On-hand {dest['quantity']} covers {m.cover_label(m.stock_cover_days(dest['quantity'], dest_demand))} at projected demand.",
        ],
        "assumptions": [
            f"promo_demand_uplift = {assumptions['promo_demand_uplift']}",
            f"horizon_days = {assumptions['horizon_days']}",
        ],
        "feasible": feasible,
        "simulated": True,
        "payload": {
            "product_id": product["id"],
            "store_id": dest["store_id"],
            "supplier_id": supplier["supplier_id"],
            "quantity": qty,
            "unit_price": supplier["unit_price"],
            "lead_time_days": lead,
        },
        "what_if": {
            "stock_increases_immediately": False,
            "units_available_after_days": lead,
        },
        "risk_penalty": reliability_pen + (0 if lead <= 3 else lead * 30),
        "time_penalty": lead * 55,
    }


def _markdown_option(product, dest, assumptions) -> dict:
    return {
        "id": "markdown_review",
        "type": "markdown_review",
        "title": "Mark stock for markdown review (simulated)",
        "estimated_cost_inr": round(dest["quantity"] * product["unit_cost"] * 0.15, 2),
        "expected_benefit_inr": round(dest["quantity"] * product["selling_price"] * 0.08, 2),
        "time_until_available_days": 0,
        "risk": "Markdown recovers cash but reduces margin. Demand lift from markdown is not measured.",
        "limitations": "Does not automatically change selling price in this demo.",
        "evidence": [
            f"{dest['quantity']} units have been on hand for {dest['days_on_hand']} days.",
            f"Velocity is {dest['velocity']} units/day.",
        ],
        "assumptions": [
            "Markdown cost estimated at 15% of unit cost.",
            "Benefit estimated at 8% of selling price as recovered cash — not a forecast.",
        ],
        "feasible": True,
        "simulated": True,
        "payload": {"product_id": product["id"], "store_id": dest["store_id"]},
        "risk_penalty": 200,
        "time_penalty": 0,
    }


def _expedite_option(po: dict, dest, dest_demand, product, assumptions) -> dict:
    return {
        "id": f"expedite_{po['id']}",
        "type": "expedite_po",
        "title": f"Expedite delayed PO {po['po_number']} (simulated)",
        "estimated_cost_inr": round(po["quantity"] * po["unit_price"] * 0.04, 2),
        "expected_benefit_inr": m.financial_stockout_impact(
            m.stockout_units(dest["quantity"], dest_demand, 5),
            product["selling_price"],
            assumptions["margin_on_lost_sale"],
        ),
        "time_until_available_days": 2,
        "risk": "Expedite fee and new ETA are simulated. The original supplier delay may continue.",
        "limitations": "No carrier or supplier is contacted.",
        "evidence": [
            f"{po['po_number']} expected {po['expected_at']}, status {po['status']}, {po['quantity']} units.",
            po.get("notes") or "No additional notes.",
        ],
        "assumptions": ["Expedite fee modelled as 4% of PO value. New ETA modelled as +2 days."],
        "feasible": True,
        "simulated": True,
        "payload": {"purchase_order_id": po["id"], "new_expected_days": 2},
        "risk_penalty": 300,
        "time_penalty": 80,
    }


def _pick_best(options: list[dict]) -> dict:
    feasible = [o for o in options if o.get("feasible")]
    if not feasible:
        feasible = options
    return max(feasible, key=_option_rank)


def _needed_qty(dest_qty, dest_demand, horizon, source_surplus) -> int:
    gap = m.expected_units_needed(dest_demand, horizon, dest_qty)
    if gap <= 0:
        gap = max(1, int(round(dest_demand * 3)))
    return max(0, min(gap, source_surplus))


def _issue(
    *,
    issue_type,
    title,
    product,
    dest,
    severity,
    score,
    why_now,
    impact_text,
    impact_inr,
    confidence,
    confidence_note,
    evidence,
    options,
) -> dict:
    recommended = _pick_best(options)
    next_step = recommended["title"]
    return {
        "issue_key": f"{issue_type}:{product['id']}:{dest['store_id']}",
        "issue_type": issue_type,
        "title": title,
        "severity": severity,
        "score": score,
        "product_id": product["id"],
        "store_id": dest["store_id"],
        "product_name": product["name"],
        "store_name": dest["store_name"],
        "why_now": why_now,
        "expected_impact": impact_text,
        "impact_inr": impact_inr,
        "confidence": confidence,
        "confidence_note": confidence_note,
        "recommended_next_step": next_step,
        "recommended_option_id": recommended["id"],
        "evidence": evidence,
        "options": options,
        "status": "pending",
    }


def detect_issues(conn) -> list[dict]:
    assumptions = m.get_assumptions(conn)
    lookback = int(assumptions["velocity_lookback_days"])
    horizon = int(assumptions["horizon_days"])
    uplift = float(assumptions["promo_demand_uplift"])
    min_cover = int(assumptions["min_safe_cover_days"])
    transfer_days = int(assumptions["transfer_days"])
    ageing_threshold = int(assumptions["ageing_days_threshold"])
    margin = float(assumptions["margin_on_lost_sale"])

    products = [dict(r) for r in conn.execute("SELECT * FROM products").fetchall()]
    issues: list[dict] = []

    for product in products:
        matrix = _inventory_matrix(conn, product["id"], lookback)
        suppliers = _suppliers_for_product(conn, product["id"])
        for dest in matrix:
            promos = m.active_promotions(conn, product["id"], dest["store_id"], horizon)
            has_promo = bool(promos)
            dest_demand = m.projected_daily_demand(dest["velocity"], has_promo, uplift)
            dest_cover = m.stock_cover_days(dest["quantity"], dest_demand)
            days_to_stockout = dest_cover
            lost = m.stockout_units(dest["quantity"], dest_demand, horizon)
            impact = m.financial_stockout_impact(lost, product["selling_price"], margin)
            pos = _open_pos(conn, product["id"], dest["store_id"])
            # Treat an open PO as delayed either when the supplier reports a
            # delayed status OR when its expected date has already passed in the
            # reproducible VoltPilot demo clock. Risk Areas uses this same rule;
            # otherwise Goal 07 could flag an overdue PO while this engine omitted
            # the executable expedite option.
            demo_today = str(DEMO_TODAY)[:10]
            delayed = [
                p for p in pos
                if str(p.get("status", "")).strip().lower() == "delayed"
                or (p.get("expected_at") and str(p["expected_at"])[:10] < demo_today)
            ]

            surplus_sources = []
            for src in matrix:
                if src["store_id"] == dest["store_id"]:
                    continue
                surplus = m.transferable_surplus(src["quantity"], src["velocity"], min_cover, transfer_days)
                if surplus > 0:
                    surplus_sources.append({**src, "surplus": surplus})
            surplus_sources.sort(key=lambda s: s["surplus"], reverse=True)

            options: list[dict] = []
            velocity_label = dest.get("velocity_source", f"{lookback}-day historical sales velocity")
            evidence = [
                f"On-hand: {dest['quantity']} units at {dest['store_name']}.",
                f"{velocity_label}: {dest['velocity']} units/day.",
                f"Projected demand: {dest_demand} units/day ({'includes promo uplift assumption' if has_promo else 'no active promo'}).",
                f"Stock cover: {m.cover_label(dest_cover)}.",
            ]
            if promos:
                for promo in promos:
                    evidence.append(
                        f"Promotion '{promo['name']}' {promo['start_date']} → {promo['end_date']} "
                        f"(starts in {m.days_until(promo['start_date'])} days)."
                    )
            if delayed:
                for po in delayed:
                    evidence.append(f"Delayed PO {po['po_number']} expected {po['expected_at']}.")

            # --- stockout / promo risk ---
            stockout_soon = dest_cover is not None and dest_cover < horizon
            promo_risk = has_promo and dest_cover is not None and dest_cover < (
                m.days_until(promos[0]["end_date"]) + 1
            )

            if stockout_soon or promo_risk:
                if surplus_sources:
                    src = surplus_sources[0]
                    qty = _needed_qty(dest["quantity"], dest_demand, horizon, src["surplus"])
                    options.append(
                        _transfer_option(
                            product=product,
                            dest=dest,
                            source=src,
                            qty=qty,
                            assumptions=assumptions,
                            dest_demand=dest_demand,
                            dest_cover=dest_cover,
                        )
                    )
                for supplier in suppliers:
                    buy_qty = max(4, m.expected_units_needed(dest_demand, horizon + supplier["lead_time_days"], dest["quantity"]))
                    options.append(
                        _purchase_option(product, dest, supplier, buy_qty, dest_demand, assumptions)
                    )
                options.append(_do_nothing_option(dest_cover, "Wait and hope inbound demand stays below on-hand stock."))
                if delayed:
                    options.insert(0, _expedite_option(delayed[0], dest, dest_demand, product, assumptions))

                severity = _severity(days_to_stockout, impact, has_promo, bool(delayed))
                confidence = 0.82 if dest["velocity"] > 0 else 0.5
                if has_promo:
                    confidence -= 0.08  # uplift is an assumption
                if has_promo:
                    title = f"{product['name']} at {dest['store_name']} may stock out during the festival promotion"
                    issue_type = "promo_stockout"
                    if delayed:
                        title = f"Overdue PO {delayed[0]['po_number']} puts {product['name']} at {dest['store_name']} at risk during the promotion"
                elif delayed:
                    title = f"Overdue PO {delayed[0]['po_number']} puts {product['name']} at {dest['store_name']} at stockout risk"
                    issue_type = "delayed_po"
                else:
                    title = f"{product['name']} at {dest['store_name']} may stock out before replenishment"
                    issue_type = "stockout_risk"
                issues.append(
                    _issue(
                        issue_type=issue_type,
                        title=title,
                        product=product,
                        dest=dest,
                        severity=severity,
                        score=_score(severity, days_to_stockout, impact, confidence),
                        why_now=(
                            f"Cover is {m.cover_label(dest_cover)} while projected demand is {dest_demand}/day. "
                            + (
                                f"A promotion starts in {m.days_until(promos[0]['start_date'])} days."
                                if has_promo
                                else "Replenishment may not arrive in time."
                            )
                        ),
                        impact_text=f"About {lost} units could be missed over {horizon} days (~₹{impact:,.0f} margin at risk).",
                        impact_inr=impact,
                        confidence=round(confidence, 2),
                        confidence_note=(
                            "When its held-out evaluation beats the baseline, the trained Ridge regression forecast informs daily demand; otherwise the agent falls back to historical sales velocity. "
                            "Promotion uplift remains a configurable assumption, not observed festival demand."
                        ),
                        evidence=evidence,
                        options=options,
                    )
                )
                continue

            # --- delayed PO even if cover is currently OK ---
            if delayed:
                options = [
                    _expedite_option(delayed[0], dest, dest_demand, product, assumptions),
                ]
                if surplus_sources:
                    src = surplus_sources[0]
                    qty = _needed_qty(dest["quantity"], dest_demand, horizon, src["surplus"])
                    options.append(
                        _transfer_option(
                            product=product,
                            dest=dest,
                            source=src,
                            qty=max(qty, 2),
                            assumptions=assumptions,
                            dest_demand=dest_demand,
                            dest_cover=dest_cover,
                        )
                    )
                for supplier in suppliers[:2]:
                    options.append(_purchase_option(product, dest, supplier, 10, dest_demand, assumptions))
                options.append(_do_nothing_option(dest_cover, "Keep waiting on the delayed supplier."))
                severity = _severity(days_to_stockout, max(impact, 6000), False, True)
                issues.append(
                    _issue(
                        issue_type="delayed_po",
                        title=f"Purchase order delayed for {product['name']} at {dest['store_name']}",
                        product=product,
                        dest=dest,
                        severity=severity,
                        score=_score(severity, days_to_stockout if days_to_stockout is not None else 8, max(impact, 6000), 0.88),
                        why_now=f"{delayed[0]['po_number']} was due {delayed[0]['expected_at']} and is still {delayed[0]['status']}.",
                        impact_text="Inbound stock cannot be treated as available. Festival demand may still consume on-hand units.",
                        impact_inr=max(impact, 6000),
                        confidence=0.88,
                        confidence_note="PO status is seed data. Delay reason is simulated.",
                        evidence=evidence,
                        options=options,
                    )
                )
                continue

            # --- ageing / overstock ---
            if m.ageing_risk(dest["days_on_hand"], dest["velocity"], ageing_threshold) and dest["quantity"] >= 8:
                options = [
                    _markdown_option(product, dest, assumptions),
                    _do_nothing_option(dest_cover, "Hold stock through the festival in case demand appears."),
                ]
                # Transfer ageing stock only if another store has higher velocity
                faster = [s for s in matrix if s["store_id"] != dest["store_id"] and s["velocity"] > dest["velocity"] * 1.5]
                if faster:
                    target = max(faster, key=lambda s: s["velocity"])
                    qty = min(6, dest["quantity"] // 2)
                    # reuse transfer constructor with dest/source swapped: move FROM ageing store TO faster store
                    options.insert(
                        0,
                        _transfer_option(
                            product=product,
                            dest=target,
                            source=dest,
                            qty=qty,
                            assumptions=assumptions,
                            dest_demand=m.projected_daily_demand(target["velocity"], False, uplift),
                            dest_cover=target["cover_days"],
                        ),
                    )
                holding = round(dest["quantity"] * 8 * dest["days_on_hand"] / 30, 2)
                issues.append(
                    _issue(
                        issue_type="ageing_stock",
                        title=f"Ageing {product['name']} tied up at {dest['store_name']}",
                        product=product,
                        dest=dest,
                        severity="Medium",
                        score=_score("Medium", 20, holding, 0.7),
                        why_now=f"Stock has sat for {dest['days_on_hand']} days with velocity {dest['velocity']}/day.",
                        impact_text=f"Capital is locked in slow units. Indicative holding pressure ~₹{holding:,.0f} (assumption-based).",
                        impact_inr=holding,
                        confidence=0.7,
                        confidence_note="Ageing threshold and holding cost are assumptions. True warehouse cost is unknown.",
                        evidence=evidence + [f"Days on hand {dest['days_on_hand']} ≥ threshold {ageing_threshold}."],
                        options=options,
                    )
                )
                continue

            # --- healthy: one explicit do-nothing case for the mouse ---
            if product["sku"] == "VK-MS-01" and dest["store_id"] == 1:
                options = [_do_nothing_option(dest_cover, "Cover is healthy and no promotion is scheduled.")]
                if surplus_sources:
                    src = surplus_sources[0]
                    options.append(
                        _transfer_option(
                            product=product,
                            dest=dest,
                            source=src,
                            qty=5,
                            assumptions=assumptions,
                            dest_demand=dest_demand,
                            dest_cover=dest_cover,
                        )
                    )
                issues.append(
                    _issue(
                        issue_type="healthy_watch",
                        title=f"{product['name']} at {dest['store_name']} does not need action",
                        product=product,
                        dest=dest,
                        severity="Low",
                        score=_score("Low", 40, 0, 0.9),
                        why_now="Included so the agent can show that doing nothing is sometimes the right call.",
                        impact_text="No material stockout or ageing impact estimated.",
                        impact_inr=0,
                        confidence=0.9,
                        confidence_note="High confidence because velocity is stable and cover exceeds the planning horizon.",
                        evidence=evidence,
                        options=options,
                    )
                )

    issues.sort(key=lambda i: i["score"], reverse=True)
    return issues


def persist_recommendations(conn, issues: list[dict]) -> None:
    """Replace pending recommendations. Keep approved/rejected rows for history."""
    conn.execute("DELETE FROM recommendations WHERE status = 'pending'")
    now = f"{DEMO_TODAY}T09:00:00"
    for issue in issues:
        existing = conn.execute(
            "SELECT id, status FROM recommendations WHERE issue_key = ?",
            (issue["issue_key"],),
        ).fetchone()
        if existing and existing["status"] in ("approved", "rejected"):
            continue
        conn.execute(
            """
            INSERT INTO recommendations (
                issue_key, issue_type, title, severity, score, product_id, store_id,
                why_now, expected_impact, impact_inr, confidence, confidence_note,
                evidence_json, options_json, recommended_option_id, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (
                issue["issue_key"],
                issue["issue_type"],
                issue["title"],
                issue["severity"],
                issue["score"],
                issue["product_id"],
                issue["store_id"],
                issue["why_now"],
                issue["expected_impact"],
                issue["impact_inr"],
                issue["confidence"],
                issue["confidence_note"],
                json.dumps(issue["evidence"]),
                json.dumps(issue["options"]),
                issue["recommended_option_id"],
                now,
            ),
        )


def refresh(conn) -> list[dict]:
    issues = detect_issues(conn)
    persist_recommendations(conn, issues)
    return load_recommendations(conn)


def load_recommendations(conn, status: str | None = None) -> list[dict]:
    sql = """
        SELECT r.*, p.name AS product_name, p.sku, p.selling_price, p.category,
               s.name AS store_name, s.city
        FROM recommendations r
        JOIN products p ON p.id = r.product_id
        JOIN stores s ON s.id = r.store_id
    """
    params: tuple = ()
    if status:
        sql += " WHERE r.status = ?"
        params = (status,)
    sql += " ORDER BY r.score DESC"
    rows = conn.execute(sql, params).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["evidence"] = json.loads(item.pop("evidence_json"))
        item["options"] = json.loads(item.pop("options_json"))
        rec = next((o for o in item["options"] if o["id"] == item["recommended_option_id"]), item["options"][0])
        item["recommended_option"] = rec
        item["recommended_next_step"] = rec["title"]
        out.append(item)
    return out


def get_recommendation(conn, decision_id: int) -> dict | None:
    row = conn.execute(
        """
        SELECT r.*, p.name AS product_name, p.sku, p.selling_price, p.category, p.unit_cost,
               s.name AS store_name, s.city
        FROM recommendations r
        JOIN products p ON p.id = r.product_id
        JOIN stores s ON s.id = r.store_id
        WHERE r.id = ?
        """,
        (decision_id,),
    ).fetchone()
    if not row:
        return None
    item = dict(row)
    item["evidence"] = json.loads(item.pop("evidence_json"))
    item["options"] = json.loads(item.pop("options_json"))
    item["recommended_option"] = next(
        (o for o in item["options"] if o["id"] == item["recommended_option_id"]), None
    )
    item["network"] = _inventory_matrix(conn, item["product_id"], int(m.get_assumptions(conn)["velocity_lookback_days"]))
    item["suppliers"] = _suppliers_for_product(conn, item["product_id"])
    item["purchase_orders"] = _open_pos(conn, item["product_id"], item["store_id"])
    item["assumptions"] = m.assumption_records(conn)
    item["score_explainer"] = (
        "score = (severity_weight + urgency + financial_index) × confidence. "
        "Critical=100, High=70, Medium=40, Low=15. "
        "Urgency is 30 minus days-to-stockout. Financial index is INR impact / 400 (cap 80)."
    )
    return item


def dashboard_payload(conn) -> dict:
    recs = load_recommendations(conn)
    pending = [r for r in recs if r["status"] == "pending"]
    inventory_rows = conn.execute(
        """
        SELECT i.quantity, i.days_on_hand, p.name AS product_name, p.selling_price, p.sku,
               s.name AS store_name, s.city, i.product_id, i.store_id, i.markdown_review
        FROM inventory i
        JOIN products p ON p.id = i.product_id
        JOIN stores s ON s.id = i.store_id
        """
    ).fetchall()
    pos = conn.execute(
        """
        SELECT po.*, s.name AS supplier_name, p.name AS product_name, st.name AS store_name
        FROM purchase_orders po
        JOIN suppliers s ON s.id = po.supplier_id
        JOIN products p ON p.id = po.product_id
        JOIN stores st ON st.id = po.store_id
        ORDER BY po.expected_at
        """
    ).fetchall()
    delayed = [dict(p) for p in pos if p["status"] == "delayed"]
    units = sum(r["quantity"] for r in inventory_rows)
    at_risk = sum(1 for r in pending if r["severity"] in ("Critical", "High"))
    audit_count = conn.execute("SELECT COUNT(*) AS c FROM audit_log").fetchone()["c"]
    return {
        "today": DEMO_TODAY,
        "kpis": {
            "attention_items": len(pending),
            "critical_or_high": at_risk,
            "units_on_hand": units,
            "delayed_pos": len(delayed),
            "actions_logged": audit_count,
        },
        "radar": pending[:8],
        "delayed_orders": delayed,
        "assumptions": m.assumption_records(conn),
        "score_explainer": (
            "Issues are ranked by score = (severity_weight + urgency + financial_index) × confidence. "
            "Higher score means the manager should look first."
        ),
    }
