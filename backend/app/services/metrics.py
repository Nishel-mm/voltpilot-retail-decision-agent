"""Retail math used by the decision engine.

All of these functions are deterministic. None of them call an LLM.
"""

from datetime import date, timedelta
from math import inf

from ..config import business_date


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def today() -> date:
    return business_date()


def get_assumptions(conn) -> dict[str, float | int]:
    rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
    out: dict[str, float | int] = {}
    for row in rows:
        raw = row["value"]
        if "." in raw:
            out[row["key"]] = float(raw)
        else:
            out[row["key"]] = int(raw)
    return out


def assumption_records(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT key, value, description, source FROM app_settings ORDER BY key"
    ).fetchall()
    return [dict(r) for r in rows]


def sales_velocity(conn, product_id: int, store_id: int, lookback_days: int) -> float:
    start = today() - timedelta(days=lookback_days)
    row = conn.execute(
        """
        SELECT COALESCE(SUM(units), 0) AS total, COUNT(*) AS days
        FROM sales_daily
        WHERE product_id = ? AND store_id = ? AND sale_date > ? AND sale_date <= ?
        """,
        (product_id, store_id, start.isoformat(), today().isoformat()),
    ).fetchone()
    total = row["total"] or 0
    if lookback_days <= 0:
        return 0.0
    return round(total / lookback_days, 3)


def sales_velocity_map(conn, lookback_days: int) -> dict[tuple[int, int], float]:
    """Calculate recent sales velocity for every product/store pair in one query.

    This avoids one remote PostgreSQL round trip per inventory row on dashboard
    and risk-analysis endpoints. Missing pairs are handled by callers as zero.
    """
    if lookback_days <= 0:
        return {}
    end = today()
    start = end - timedelta(days=lookback_days)
    rows = conn.execute(
        """
        SELECT product_id, store_id, COALESCE(SUM(units), 0) AS total
        FROM sales_daily
        WHERE sale_date > ? AND sale_date <= ?
        GROUP BY product_id, store_id
        """,
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    return {
        (int(row["product_id"]), int(row["store_id"])): round(float(row["total"] or 0) / lookback_days, 3)
        for row in rows
    }


def stock_cover_days(quantity: int, velocity: float) -> float | None:
    if quantity < 0:
        quantity = 0
    if velocity <= 0:
        return None  # infinite / undefined — caller must explain
    return round(quantity / velocity, 2)


def cover_label(cover: float | None) -> str:
    if cover is None:
        return "no recent sales (cover not defined)"
    return f"{cover} days"


def active_promotions(conn, product_id: int, store_id: int, horizon_days: int) -> list[dict]:
    end = today() + timedelta(days=horizon_days)
    rows = conn.execute(
        """
        SELECT * FROM promotions
        WHERE product_id = ?
          AND (store_id IS NULL OR store_id = ?)
          AND start_date <= ?
          AND end_date >= ?
        """,
        (product_id, store_id, end.isoformat(), today().isoformat()),
    ).fetchall()
    return [dict(r) for r in rows]


def days_until(iso_date: str) -> int:
    return (parse_date(iso_date) - today()).days


def projected_daily_demand(velocity: float, has_promo: bool, uplift: float) -> float:
    if velocity < 0:
        velocity = 0
    if has_promo:
        return round(velocity * (1 + uplift), 3)
    return velocity


def expected_units_needed(daily_demand: float, days: int, on_hand: int) -> int:
    projected = daily_demand * max(days, 0)
    gap = projected - on_hand
    return max(0, int(round(gap)))


def stockout_units(quantity: int, daily_demand: float, days: int) -> float:
    remaining = quantity - daily_demand * max(days, 0)
    if remaining >= 0:
        return 0.0
    return round(-remaining, 2)


def transferable_surplus(quantity: int, velocity: float, min_cover_days: int, transfer_days: int) -> int:
    """Units a store can give away without falling below the safety cover after the transfer delay."""
    if quantity <= 0:
        return 0
    reserved = 0.0
    if velocity > 0:
        reserved = velocity * (min_cover_days + transfer_days)
    surplus = int(quantity - reserved)
    return max(0, surplus)


def source_cover_after_transfer(quantity: int, qty: int, velocity: float) -> float | None:
    return stock_cover_days(quantity - qty, velocity)


def financial_stockout_impact(lost_units: float, selling_price: float, margin: float) -> float:
    return round(max(0.0, lost_units) * selling_price * margin, 2)


def ageing_risk(days_on_hand: int, velocity: float, threshold: int) -> bool:
    return days_on_hand >= threshold and velocity < 0.3
