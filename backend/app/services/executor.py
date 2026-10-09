"""Human-approved, simulated actions. Nothing runs without an approve call."""

from __future__ import annotations

import json
from datetime import date, timedelta

from ..config import DEMO_TODAY
from . import engine


def _now() -> str:
    return f"{DEMO_TODAY}T10:15:00"


def _option(rec: dict, option_id: str | None) -> dict | None:
    wanted = option_id or rec["recommended_option_id"]
    return next((o for o in rec["options"] if o["id"] == wanted), None)


def _log(conn, rec, decision, option, result, executed, details) -> None:
    conn.execute(
        """
        INSERT INTO audit_log (
            recommendation_id, decision, option_id, option_type, actor,
            timestamp, summary, result, details_json, executed
        ) VALUES (?, ?, ?, ?, 'Store Manager', ?, ?, ?, ?, ?)
        """,
        (
            rec["id"],
            decision,
            option["id"] if option else None,
            option["type"] if option else None,
            _now(),
            rec["title"],
            result,
            json.dumps(details),
            1 if executed else 0,
        ),
    )


def reject(conn, decision_id: int, note: str = "") -> dict:
    rec = engine.get_recommendation(conn, decision_id)
    if not rec:
        return {"ok": False, "error": "Decision not found.", "status_code": 404}
    if rec["status"] != "pending":
        return {
            "ok": False,
            "error": f"Decision already {rec['status']}. Rejection was not recorded again.",
            "status_code": 409,
        }
    option = rec.get("recommended_option")
    conn.execute("UPDATE recommendations SET status = 'rejected' WHERE id = ?", (decision_id,))
    _log(
        conn,
        rec,
        "rejected",
        option,
        "Rejected. Inventory and purchase orders were not changed.",
        False,
        {"note": note, "inventory_changed": False},
    )
    return {
        "ok": True,
        "message": "Decision rejected. No simulated operation ran.",
        "recommendation": engine.get_recommendation(conn, decision_id),
    }


def approve(conn, decision_id: int, option_id: str | None = None, note: str = "") -> dict:
    rec = engine.get_recommendation(conn, decision_id)
    if not rec:
        return {"ok": False, "error": "Decision not found.", "status_code": 404}
    if rec["status"] != "pending":
        return {
            "ok": False,
            "error": f"This action was already {rec['status']}. Duplicate execution is blocked.",
            "status_code": 409,
        }
    option = _option(rec, option_id)
    if not option:
        return {"ok": False, "error": "Option not found on this decision.", "status_code": 400}
    if not option.get("feasible"):
        return {"ok": False, "error": "That option is not feasible with current stock.", "status_code": 400}

    details = {"note": note, "option": option, "simulated": option.get("simulated", True)}

    if option["type"] == "do_nothing":
        conn.execute("UPDATE recommendations SET status = 'approved' WHERE id = ?", (decision_id,))
        _log(conn, rec, "approved", option, "Approved no-action. Records unchanged.", False, details)
        return {
            "ok": True,
            "message": "Approved: take no action. Nothing was changed in inventory.",
            "recommendation": engine.get_recommendation(conn, decision_id),
        }

    if option["type"] == "transfer":
        result = _execute_transfer(conn, option["payload"])
        if not result["ok"]:
            return result
        details["inventory_delta"] = result["delta"]
        conn.execute("UPDATE recommendations SET status = 'approved' WHERE id = ?", (decision_id,))
        _log(conn, rec, "approved", option, result["message"], True, details)
        engine.refresh(conn)
        return {
            "ok": True,
            "message": result["message"],
            "delta": result["delta"],
            "recommendation": engine.get_recommendation(conn, decision_id),
        }

    if option["type"] == "purchase":
        result = _execute_purchase(conn, option["payload"])
        conn.execute("UPDATE recommendations SET status = 'approved' WHERE id = ?", (decision_id,))
        details["purchase_order"] = result
        _log(
            conn,
            rec,
            "approved",
            option,
            result["message"],
            True,
            details,
        )
        engine.refresh(conn)
        return {
            "ok": True,
            "message": result["message"],
            "purchase_order": result,
            "recommendation": engine.get_recommendation(conn, decision_id),
        }

    if option["type"] == "expedite_po":
        result = _execute_expedite(conn, option["payload"])
        if not result["ok"]:
            return result
        conn.execute("UPDATE recommendations SET status = 'approved' WHERE id = ?", (decision_id,))
        details["purchase_order"] = result
        _log(conn, rec, "approved", option, result["message"], True, details)
        engine.refresh(conn)
        return {"ok": True, "message": result["message"], "purchase_order": result}

    if option["type"] == "markdown_review":
        conn.execute(
            """
            UPDATE inventory SET markdown_review = 1
            WHERE product_id = ? AND store_id = ?
            """,
            (option["payload"]["product_id"], option["payload"]["store_id"]),
        )
        conn.execute("UPDATE recommendations SET status = 'approved' WHERE id = ?", (decision_id,))
        msg = "Marked for markdown review (simulated). Selling price was not changed."
        _log(conn, rec, "approved", option, msg, True, details)
        engine.refresh(conn)
        return {"ok": True, "message": msg}

    return {"ok": False, "error": f"Unknown option type {option['type']}.", "status_code": 400}


def _execute_transfer(conn, payload: dict) -> dict:
    product_id = payload["product_id"]
    from_id = payload["from_store_id"]
    to_id = payload["to_store_id"]
    qty = int(payload["quantity"])
    if qty <= 0:
        return {"ok": False, "error": "Transfer quantity must be positive.", "status_code": 400}
    if from_id == to_id:
        return {"ok": False, "error": "Source and destination stores must differ.", "status_code": 400}

    source = conn.execute(
        "SELECT * FROM inventory WHERE product_id = ? AND store_id = ?",
        (product_id, from_id),
    ).fetchone()
    dest = conn.execute(
        "SELECT * FROM inventory WHERE product_id = ? AND store_id = ?",
        (product_id, to_id),
    ).fetchone()
    if not source or not dest:
        return {"ok": False, "error": "Inventory row missing for this transfer.", "status_code": 400}
    if source["quantity"] < qty:
        return {
            "ok": False,
            "error": f"Insufficient source stock ({source['quantity']} < {qty}). Transfer not applied.",
            "status_code": 409,
        }

    conn.execute(
        "UPDATE inventory SET quantity = quantity - ? WHERE product_id = ? AND store_id = ?",
        (qty, product_id, from_id),
    )
    conn.execute(
        "UPDATE inventory SET quantity = quantity + ? WHERE product_id = ? AND store_id = ?",
        (qty, product_id, to_id),
    )
    after_src = conn.execute(
        "SELECT quantity FROM inventory WHERE product_id = ? AND store_id = ?",
        (product_id, from_id),
    ).fetchone()["quantity"]
    after_dst = conn.execute(
        "SELECT quantity FROM inventory WHERE product_id = ? AND store_id = ?",
        (product_id, to_id),
    ).fetchone()["quantity"]
    return {
        "ok": True,
        "message": (
            f"SIMULATED transfer complete: {qty} units moved. "
            f"Source now {after_src}, destination now {after_dst}."
        ),
        "delta": {
            "quantity": qty,
            "source_after": after_src,
            "destination_after": after_dst,
        },
    }


def _execute_purchase(conn, payload: dict) -> dict:
    today = date.fromisoformat(DEMO_TODAY)
    expected = today + timedelta(days=int(payload["lead_time_days"]))
    count = conn.execute("SELECT COUNT(*) AS c FROM purchase_orders").fetchone()["c"]
    po_number = f"PO-SIM-{today.strftime('%m%d')}-{count + 1:03d}"
    conn.execute(
        """
        INSERT INTO purchase_orders (
            po_number, supplier_id, product_id, store_id, quantity, unit_price,
            status, ordered_at, expected_at, received_at, notes, simulated
        ) VALUES (?, ?, ?, ?, ?, ?, 'ordered', ?, ?, NULL, ?, 1)
        """,
        (
            po_number,
            payload["supplier_id"],
            payload["product_id"],
            payload["store_id"],
            payload["quantity"],
            payload["unit_price"],
            today.isoformat(),
            expected.isoformat(),
            "SIMULATED purchase order. Available stock was NOT increased.",
        ),
    )
    return {
        "po_number": po_number,
        "status": "ordered",
        "expected_at": expected.isoformat(),
        "message": (
            f"SIMULATED purchase order {po_number} created. "
            f"Goods expected {expected.isoformat()}. On-hand stock is unchanged until arrival."
        ),
    }


def _execute_expedite(conn, payload: dict) -> dict:
    po = conn.execute(
        "SELECT * FROM purchase_orders WHERE id = ?",
        (payload["purchase_order_id"],),
    ).fetchone()
    if not po:
        return {"ok": False, "error": "Purchase order not found.", "status_code": 404}
    new_expected = date.fromisoformat(DEMO_TODAY) + timedelta(days=int(payload["new_expected_days"]))
    conn.execute(
        """
        UPDATE purchase_orders
        SET status = 'in_transit',
            expected_at = ?,
            notes = ?
        WHERE id = ?
        """,
        (
            new_expected.isoformat(),
            "SIMULATED expedite. Original delay cleared in the demo clock only.",
            po["id"],
        ),
    )
    return {
        "ok": True,
        "po_number": po["po_number"],
        "expected_at": new_expected.isoformat(),
        "message": (
            f"SIMULATED expedite of {po['po_number']}. New expected date {new_expected.isoformat()}. "
            "On-hand stock is still unchanged."
        ),
    }


def list_actions(conn) -> list[dict]:
    rows = conn.execute(
        """
        SELECT a.*, r.title, r.severity, r.issue_type, p.name AS product_name, s.name AS store_name
        FROM audit_log a
        LEFT JOIN recommendations r ON r.id = a.recommendation_id
        LEFT JOIN products p ON p.id = r.product_id
        LEFT JOIN stores s ON s.id = r.store_id
        ORDER BY a.id DESC
        """
    ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["details"] = json.loads(item.pop("details_json"))
        # Supplier delivery events do not reference a decision recommendation.
        item["title"] = item.get("title") or item.get("summary") or "Recorded operation"
        item["product_name"] = item.get("product_name") or item["details"].get("product_name") or "—"
        item["store_name"] = item.get("store_name") or item["details"].get("store_name") or "—"
        out.append(item)
    return out
