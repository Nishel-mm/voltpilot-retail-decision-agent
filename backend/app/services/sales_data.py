"""Observed retail sales data for VoltPilot forecasting.

This module deliberately excludes sales_daily seed/demo values. Its sources are:
1) transactions actually entered through Store & POS, and
2) historical daily sales explicitly imported by the retailer from a CSV.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

MAX_IMPORT_ROWS = 20000


def _local_date(value: str) -> date:
    # retail_transactions.created_at is written with the laptop's local offset.
    # Taking the date prefix preserves the store's recorded local calendar day.
    return date.fromisoformat(str(value)[:10])


def observed_daily_rows(conn) -> list[dict[str, Any]]:
    """Aggregate imported observations and actual POS line items by date/SKU/store.

    Seeded `sales_daily` rows are intentionally never read here.
    Imported history that overlaps a POS sale on the same SKU/store/date is
    rejected by the importer to avoid accidental double counting.
    """
    aggregated: dict[tuple[int, int, str], int] = defaultdict(int)
    sources: dict[str, int] = defaultdict(int)

    try:
        rows = conn.execute(
            """SELECT product_id, store_id, sale_date, units
                 FROM sales_history_observations
                ORDER BY sale_date, product_id, store_id"""
        ).fetchall()
    except Exception:
        rows = []  # Supports a safe status check before a migration runs.
    for row in rows:
        key = (int(row["product_id"]), int(row["store_id"]), str(row["sale_date"])[:10])
        aggregated[key] += int(row["units"])
        sources["imported_daily_rows"] += 1

    try:
        pos_rows = conn.execute(
            """SELECT rti.product_id, rt.store_id, substr(rt.created_at, 1, 10) AS sale_date,
                      SUM(rti.quantity) AS units, COUNT(DISTINCT rt.id) AS txn_count
                 FROM retail_transactions rt
                 JOIN retail_transaction_items rti ON rti.transaction_id = rt.id
                WHERE rt.status = 'sold'
                GROUP BY rti.product_id, rt.store_id, substr(rt.created_at, 1, 10)
                ORDER BY sale_date, rti.product_id, rt.store_id"""
        ).fetchall()
    except Exception:
        pos_rows = []
    for row in pos_rows:
        key = (int(row["product_id"]), int(row["store_id"]), str(row["sale_date"])[:10])
        aggregated[key] += int(row["units"])
        sources["pos_product_store_days"] += 1

    result = [
        {"product_id": pid, "store_id": sid, "sale_date": day, "units": units}
        for (pid, sid, day), units in aggregated.items()
    ]
    result.sort(key=lambda r: (r["sale_date"], r["product_id"], r["store_id"]))
    return result


def observed_series_map(conn) -> dict[tuple[int, int], list[dict[str, Any]]]:
    """Create daily series only inside each pair's observed date range.

    Missing days between the first and last observed day are treated as zero
    recorded sales. No synthetic days are added before the first or after the
    last observation.
    """
    grouped: dict[tuple[int, int], dict[date, int]] = defaultdict(dict)
    for row in observed_daily_rows(conn):
        day = date.fromisoformat(row["sale_date"])
        pair = (row["product_id"], row["store_id"])
        grouped[pair][day] = grouped[pair].get(day, 0) + int(row["units"])

    series_map: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for pair, by_day in grouped.items():
        if not by_day:
            continue
        start, end = min(by_day), max(by_day)
        day = start
        series: list[dict[str, Any]] = []
        while day <= end:
            series.append({"date": day, "units": int(by_day.get(day, 0))})
            day += timedelta(days=1)
        series_map[pair] = series
    return series_map


def observed_sales_velocity(conn, product_id: int, store_id: int, lookback_days: int = 14) -> float | None:
    """Observed per-day sales rate based only on retailer-entered/imported data.

    Returns None when the retailer has no observed data for this SKU/store. When
    data exists, the mean uses at most the last `lookback_days` inside the
    observation window, rather than dividing one day's sales by an arbitrary
    14-day period.
    """
    series = observed_series_map(conn).get((int(product_id), int(store_id)))
    if not series:
        return None
    count = max(1, min(int(lookback_days), len(series)))
    vals = [float(row["units"]) for row in series[-count:]]
    return round(sum(vals) / len(vals), 4)


def data_signature(conn) -> str:
    rows = observed_daily_rows(conn)
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def data_summary(conn) -> dict[str, Any]:
    rows = observed_daily_rows(conn)
    series = observed_series_map(conn)
    pos_transactions = int(conn.execute("SELECT COUNT(*) FROM retail_transactions WHERE status='sold'").fetchone()[0])
    imported_count = 0
    try:
        imported_count = int(conn.execute("SELECT COUNT(*) FROM sales_history_observations").fetchone()[0])
    except Exception:
        pass
    dates = [date.fromisoformat(row["sale_date"]) for row in rows]
    history_span = (max(dates) - min(dates)).days + 1 if dates else 0
    unique_dates = len(set(dates))
    unique_pairs = len(series)
    return {
        "source_policy": "Uses only completed Store & POS transactions and retailer-imported daily sales CSV. Seeded sales_daily history and generated synthetic history are excluded from training.",
        "pos_transactions": pos_transactions,
        "imported_daily_rows": imported_count,
        "observed_product_store_days": len(rows),
        "observed_calendar_dates": unique_dates,
        "product_store_series": unique_pairs,
        "history_span_days": history_span,
        "first_observed_date": min(dates).isoformat() if dates else None,
        "last_observed_date": max(dates).isoformat() if dates else None,
        "total_observed_units": sum(int(r["units"]) for r in rows),
    }


def import_history_csv(conn, csv_text: str) -> dict[str, Any]:
    """Import retailer-owned historic sales: date,sku,store_code,units.

    Zero-unit rows are allowed and useful when the retailer knows the product was
    available but did not sell that day. Re-importing a date replaces its prior
    imported value; it never alters POS transaction records.
    """
    from fastapi import HTTPException

    if not isinstance(csv_text, str) or not csv_text.strip():
        raise HTTPException(422, "Choose a non-empty CSV file.")
    if len(csv_text.encode("utf-8")) > 5_000_000:
        raise HTTPException(413, "CSV is too large. Maximum supported size is 5 MB.")
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff")))
    if not reader.fieldnames:
        raise HTTPException(422, "CSV needs a header row: date,sku,store_code,units")
    normalized = {str(name).strip().lower(): name for name in reader.fieldnames if name is not None}
    date_col = normalized.get("date") or normalized.get("sale_date")
    sku_col = normalized.get("sku")
    store_col = normalized.get("store_code")
    units_col = normalized.get("units")
    if not all([date_col, sku_col, store_col, units_col]):
        raise HTTPException(422, "Required CSV columns are date,sku,store_code,units. Dates must be YYYY-MM-DD.")

    product_rows = conn.execute("SELECT id, sku FROM products").fetchall()
    store_rows = conn.execute("SELECT id, code FROM stores").fetchall()
    products = {str(r["sku"]).strip().upper(): int(r["id"]) for r in product_rows}
    stores = {str(r["code"]).strip().upper(): int(r["id"]) for r in store_rows}

    aggregated: dict[tuple[int, int, str], int] = defaultdict(int)
    line_errors: list[str] = []
    input_count = 0
    for line_no, row in enumerate(reader, start=2):
        if not row or not any(str(v or "").strip() for v in row.values()):
            continue
        input_count += 1
        if input_count > MAX_IMPORT_ROWS:
            raise HTTPException(413, f"CSV contains more than {MAX_IMPORT_ROWS} rows.")
        sku = str(row.get(sku_col) or "").strip().upper()
        store_code = str(row.get(store_col) or "").strip().upper()
        try:
            day = date.fromisoformat(str(row.get(date_col) or "").strip()).isoformat()
            raw_units = str(row.get(units_col) or "").strip()
            units = int(raw_units)
            if units < 0 or units > 1_000_000:
                raise ValueError
        except Exception:
            line_errors.append(f"Line {line_no}: invalid date or units; use YYYY-MM-DD and a non-negative whole number.")
            continue
        if sku not in products:
            line_errors.append(f"Line {line_no}: unknown SKU '{sku}'. Add the product to Store & POS first.")
            continue
        if store_code not in stores:
            line_errors.append(f"Line {line_no}: unknown store_code '{store_code}'. Use a store code from VoltPilot.")
            continue
        pid, sid = products[sku], stores[store_code]
        overlap = conn.execute(
            """SELECT 1 FROM retail_transactions rt JOIN retail_transaction_items rti ON rti.transaction_id=rt.id
                 WHERE rt.status='sold' AND rt.store_id=? AND rti.product_id=? AND substr(rt.created_at,1,10)=? LIMIT 1""",
            (sid, pid, day),
        ).fetchone()
        if overlap:
            line_errors.append(f"Line {line_no}: {sku} at {store_code} on {day} already has POS sales. Import only non-overlapping historical dates to prevent double counting.")
            continue
        aggregated[(pid, sid, day)] += units

    if line_errors:
        joined = " ".join(line_errors[:8])
        if len(line_errors) > 8:
            joined += f" Plus {len(line_errors) - 8} more row errors."
        raise HTTPException(422, joined)
    if not aggregated:
        raise HTTPException(422, "No valid history rows were found. Add daily rows for existing SKUs/store codes.")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    created = updated = 0
    for (pid, sid, day), units in aggregated.items():
        existing = conn.execute(
            "SELECT id FROM sales_history_observations WHERE product_id=? AND store_id=? AND sale_date=?",
            (pid, sid, day),
        ).fetchone()
        conn.execute(
            """INSERT INTO sales_history_observations(product_id,store_id,sale_date,units,imported_at)
                 VALUES(?,?,?,?,?)
                 ON CONFLICT(product_id,store_id,sale_date) DO UPDATE SET units=excluded.units, imported_at=excluded.imported_at""",
            (pid, sid, day, units, now),
        )
        if existing:
            updated += 1
        else:
            created += 1

    summary = data_summary(conn)
    return {"ok": True, "imported_rows": len(aggregated), "created_rows": created, "replaced_rows": updated, "data_summary": summary, "message": f"Imported {len(aggregated)} daily sales observations. Forecast training now uses retailer-entered/imported observations, not seeded demo sales."}
