"""Observed-data-only demand forecasting for VoltPilot.

Training sources are completed Store & POS transactions and daily history that
an operator explicitly imports. Seeded `sales_daily` demo velocities and
synthetic generated history are excluded. The model retrains on demand; a new
sale makes an old model stale so the operator can retrain against current data.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
from typing import Any

from . import sales_data

TEST_DAYS = 7
MIN_TRAIN_SAMPLES = 20
MIN_TEST_SAMPLES = 7
FEATURES = ["product_id", "store_id", "weekday", "month", "is_promo", "lag_1", "lag_7", "rolling_mean_7", "rolling_mean_14"]
ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "data"
MODEL_PATH = ARTIFACT_DIR / "forecast_model.json"
META_PATH = ARTIFACT_DIR / "forecast_model_metadata.json"
MODEL_NAME = "Ridge Regression (pure Python)"
DATA_ORIGIN = "Observed Store & POS transactions plus retailer-imported daily sales CSV. Seeded sales_daily data and generated synthetic history are excluded from ML training."


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _mae(actual: list[float], predicted: list[float]) -> float:
    return _mean([abs(a - p) for a, p in zip(actual, predicted)])


def _rmse(actual: list[float], predicted: list[float]) -> float:
    return math.sqrt(_mean([(a - p) ** 2 for a, p in zip(actual, predicted)]))


def _active_promo(conn, product_id: int, store_id: int, on_date: date) -> bool:
    row = conn.execute(
        """SELECT 1 FROM promotions WHERE product_id=? AND (store_id IS NULL OR store_id=?)
           AND start_date<=? AND end_date>=? LIMIT 1""",
        (product_id, store_id, on_date.isoformat(), on_date.isoformat()),
    ).fetchone()
    return row is not None


def _series_with_calendar_features(conn) -> dict[tuple[int, int], list[dict[str, Any]]]:
    series_map = sales_data.observed_series_map(conn)
    for (pid, sid), series in series_map.items():
        for item in series:
            item["is_promo"] = int(_active_promo(conn, pid, sid, item["date"]))
    return series_map


def _features_for(series: list[dict[str, Any]], index: int, product_id: int, store_id: int, is_promo: int | None = None) -> dict[str, float]:
    day = series[index]["date"]
    vals = [float(x["units"]) for x in series]
    return {
        "product_id": float(product_id), "store_id": float(store_id),
        "weekday": float(day.weekday()), "month": float(day.month),
        "is_promo": float(series[index].get("is_promo", 0) if is_promo is None else is_promo),
        "lag_1": vals[index - 1], "lag_7": vals[index - 7],
        "rolling_mean_7": _mean(vals[index - 7:index]),
        "rolling_mean_14": _mean(vals[index - 14:index]),
    }


def _training_rows(conn) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    series_map = _series_with_calendar_features(conn)
    observed = sales_data.observed_daily_rows(conn)
    if not observed:
        return [], [], {"history_days": 0, "first_observed_date": None, "last_observed_date": None, "observed_product_store_days": 0, "product_store_series": 0}
    global_start = min(date.fromisoformat(r["sale_date"]) for r in observed)
    global_end = max(date.fromisoformat(r["sale_date"]) for r in observed)
    cutoff = global_end - timedelta(days=TEST_DAYS - 1)
    all_rows: list[dict[str, Any]] = []
    for (pid, sid), series in series_map.items():
        for i in range(14, len(series)):
            feat = _features_for(series, i, pid, sid)
            all_rows.append({
                "date": series[i]["date"], "features": feat,
                "target": float(series[i]["units"]),
                "baseline": max(0.0, float(feat["rolling_mean_7"])),
            })
    train = [r for r in all_rows if r["date"] < cutoff]
    test = [r for r in all_rows if r["date"] >= cutoff]
    summary = {
        "history_days": (global_end - global_start).days + 1,
        "first_observed_date": global_start.isoformat(),
        "last_observed_date": global_end.isoformat(),
        "observed_product_store_days": len(observed),
        "product_store_series": len(series_map),
    }
    return train, test, summary


def _fit_ridge(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Fit standardized ridge regression with batch gradient descent in pure Python."""
    raw_x = [[float(row["features"][key]) for key in FEATURES] for row in rows]
    y = [float(row["target"]) for row in rows]
    n_features = len(FEATURES)
    means = [_mean([x[j] for x in raw_x]) for j in range(n_features)]
    scales = []
    for j, avg in enumerate(means):
        sd = math.sqrt(_mean([(x[j] - avg) ** 2 for x in raw_x]))
        scales.append(sd if sd > 1e-9 else 1.0)
    y_mean = _mean(y)
    y_sd = math.sqrt(_mean([(v - y_mean) ** 2 for v in y]))
    y_scale = y_sd if y_sd > 1e-9 else 1.0
    x_norm = [[(x[j] - means[j]) / scales[j] for j in range(n_features)] for x in raw_x]
    y_norm = [(v - y_mean) / y_scale for v in y]
    weights = [0.0] * n_features
    intercept = 0.0
    lr, reg = 0.025, 0.03
    for _ in range(350):
        grad = [0.0] * n_features
        grad_b = 0.0
        for x, target in zip(x_norm, y_norm):
            error = intercept + sum(w * xv for w, xv in zip(weights, x)) - target
            grad_b += error
            for j, xv in enumerate(x):
                grad[j] += error * xv
        n = max(1, len(x_norm))
        intercept -= lr * grad_b / n
        for j in range(n_features):
            weights[j] -= lr * (grad[j] / n + reg * weights[j])
    return {"features": FEATURES, "feature_means": means, "feature_scales": scales, "target_mean": y_mean, "target_scale": y_scale, "weights": weights, "intercept": intercept}


def _predict(model: dict[str, Any], feature_map: dict[str, float]) -> float:
    x = [(float(feature_map[key]) - model["feature_means"][i]) / (model["feature_scales"][i] or 1.0) for i, key in enumerate(FEATURES)]
    scaled = float(model["intercept"]) + sum(w * v for w, v in zip(model["weights"], x))
    return max(0.0, float(model["target_mean"]) + float(model["target_scale"]) * scaled)


@lru_cache(maxsize=1)
def _load_saved_model() -> dict[str, Any]:
    return json.loads(MODEL_PATH.read_text(encoding="utf-8"))


def _load_metadata() -> dict[str, Any] | None:
    if not META_PATH.exists() or not MODEL_PATH.exists():
        return None
    try:
        return json.loads(META_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _readiness(conn) -> dict[str, Any]:
    train, test, train_summary = _training_rows(conn)
    source_summary = sales_data.data_summary(conn)
    ready = len(train) >= MIN_TRAIN_SAMPLES and len(test) >= MIN_TEST_SAMPLES
    reasons = []
    if source_summary["pos_transactions"] == 0 and source_summary["imported_daily_rows"] == 0:
        reasons.append("No retailer-entered POS sales or imported history yet. Make sales in Store & POS or import your actual historical daily sales CSV.")
    if len(train) < MIN_TRAIN_SAMPLES:
        reasons.append(f"Need at least {MIN_TRAIN_SAMPLES} training examples after the 14-day history features; currently {len(train)}.")
    if len(test) < MIN_TEST_SAMPLES:
        reasons.append(f"Need at least {MIN_TEST_SAMPLES} held-out examples from the most recent {TEST_DAYS} days; currently {len(test)}.")
    return {
        **source_summary,
        **train_summary,
        "training_examples_available": len(train),
        "test_examples_available": len(test),
        "minimum_training_examples": MIN_TRAIN_SAMPLES,
        "minimum_test_examples": MIN_TEST_SAMPLES,
        "test_window_days": TEST_DAYS,
        "ready_to_train": ready,
        "ready_for_forecast": any(len(series) >= 7 for series in sales_data.observed_series_map(conn).values()),
        "readiness_reason": "Sufficient observed sales history is available for a time-based train/test evaluation." if ready else " ".join(reasons),
    }


def get_status(conn) -> dict[str, Any]:
    current_signature = sales_data.data_signature(conn)
    readiness = _readiness(conn)
    meta = _load_metadata()
    if not meta or not str(meta.get("data_origin", "")).startswith("Observed Store & POS transactions"):
        return {
            "trained": False, "stale": False, "model_name": MODEL_NAME,
            "selected_forecaster": "observed_moving_average" if readiness["ready_for_forecast"] else None,
            "data_origin": DATA_ORIGIN, "legacy_synthetic_model_ignored": bool(meta),
            "selection_reason": "Previous synthetic-history model artifacts are not used. Train only after enough retailer-entered or imported sales history is available.",
            **readiness,
        }
    stale = meta.get("data_signature") != current_signature
    output = {**meta, **readiness, "trained": True, "stale": stale, "model_name": MODEL_NAME, "data_origin": DATA_ORIGIN}
    if stale:
        output["selected_forecaster"] = "observed_moving_average" if readiness["ready_for_forecast"] else None
        output["selection_reason"] = "New POS sales or imported history arrived after the last training run. The stored ML model is stale; current observed-data averages are used where enough data exists until you retrain."
    return output


def train_and_evaluate(conn) -> dict[str, Any]:
    train, test, summary = _training_rows(conn)
    source_summary = sales_data.data_summary(conn)
    if source_summary["pos_transactions"] == 0 and source_summary["imported_daily_rows"] == 0:
        raise ValueError("There is no retailer-entered sales history to train on. Make sales in Store & POS or import your actual daily history CSV. VoltPilot will not generate synthetic training history.")
    if len(train) < MIN_TRAIN_SAMPLES or len(test) < MIN_TEST_SAMPLES:
        raise ValueError(
            f"Not enough observed history yet. Available: {len(train)} training examples and {len(test)} held-out examples. "
            f"Need at least {MIN_TRAIN_SAMPLES} training and {MIN_TEST_SAMPLES} test examples after the 14-day lag features. "
            "Import historical sales you actually have or keep recording daily sales; do not invent rows to satisfy the threshold."
        )
    evaluation_model = _fit_ridge(train)
    y_test = [float(r["target"]) for r in test]
    model_pred = [_predict(evaluation_model, r["features"]) for r in test]
    baseline_pred = [max(0.0, float(r["baseline"])) for r in test]
    model_mae, baseline_mae = _mae(y_test, model_pred), _mae(y_test, baseline_pred)
    model_rmse, baseline_rmse = _rmse(y_test, model_pred), _rmse(y_test, baseline_pred)
    use_ml = model_mae < baseline_mae
    final_model = _fit_ridge(train + test)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_PATH.write_text(json.dumps(final_model, indent=2), encoding="utf-8")
    _load_saved_model.cache_clear()
    current_signature = sales_data.data_signature(conn)
    meta = {
        "trained": True, "stale": False, "model_name": MODEL_NAME,
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_origin": DATA_ORIGIN,
        "history_days": summary["history_days"], "first_observed_date": summary["first_observed_date"], "last_observed_date": summary["last_observed_date"],
        "training_samples": len(train), "test_samples": len(test), "features": FEATURES,
        "model_mae": round(model_mae, 4), "baseline_mae": round(baseline_mae, 4),
        "model_rmse": round(model_rmse, 4), "baseline_rmse": round(baseline_rmse, 4),
        "model_beats_baseline": bool(use_ml),
        "selected_forecaster": "ridge_regression" if use_ml else "observed_moving_average",
        "selection_reason": "Ridge regression had lower MAE on held-out observed sales data." if use_ml else "The moving-average baseline performed at least as well on held-out observed sales data, so VoltPilot uses the simpler baseline.",
        "evaluation_window_days": TEST_DAYS,
        "data_signature": current_signature,
        "note": "Evaluation uses only completed Store & POS transactions and retailer-imported daily sales. Historical seeded demo sales and generated synthetic history are excluded.",
        **sales_data.data_summary(conn),
        **summary,
        "ready_to_train": True,
    }
    META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def import_history_csv(conn, csv_text: str) -> dict[str, Any]:
    result = sales_data.import_history_csv(conn, csv_text)
    result["model_stale_after_import"] = True
    return result


def _future_features(series: list[dict[str, Any]], pid: int, sid: int, day: date, promo: int) -> dict[str, float]:
    vals = [float(x["units"]) for x in series]
    return {"product_id": float(pid), "store_id": float(sid), "weekday": float(day.weekday()), "month": float(day.month), "is_promo": float(promo), "lag_1": vals[-1], "lag_7": vals[-7], "rolling_mean_7": _mean(vals[-7:]), "rolling_mean_14": _mean(vals[-14:])}


def predict_all(conn, days_ahead: int = 7) -> dict[str, Any]:
    if days_ahead < 1 or days_ahead > 14:
        raise ValueError("days_ahead must be between 1 and 14.")
    status = get_status(conn)
    rows = conn.execute("""SELECT i.product_id, i.store_id, i.quantity, p.name AS product_name, p.sku, s.name AS store_name
        FROM inventory i JOIN products p ON p.id=i.product_id JOIN stores s ON s.id=i.store_id ORDER BY p.name, s.name""").fetchall()
    series_map = _series_with_calendar_features(conn)
    use_ml = status.get("trained") and not status.get("stale") and status.get("selected_forecaster") == "ridge_regression"
    model = _load_saved_model() if use_ml else None
    items = []
    for row in rows:
        pid, sid = int(row["product_id"]), int(row["store_id"])
        series = series_map.get((pid, sid), [])
        eligible = len(series) >= 7
        learned, baseline = [], []
        working = list(series)
        if eligible:
            for offset in range(1, days_ahead + 1):
                day = working[-1]["date"] + timedelta(days=1)
                promo = int(_active_promo(conn, pid, sid, day))
                feat = _future_features(working, pid, sid, day, promo) if len(working) >= 14 else None
                ml_units = _predict(model, feat) if model is not None and feat is not None else 0.0
                base_units = max(0.0, _mean([float(x["units"]) for x in working[-7:]]))
                learned.append(round(ml_units, 2) if feat is not None else None)
                baseline.append(round(base_units, 2))
                # Always use actual baseline values to extend when the selected model is not valid.
                appended = ml_units if (model is not None and feat is not None) else base_units
                working.append({"date": day, "units": max(0, int(round(appended))), "is_promo": promo})
        selected = learned if use_ml and learned and all(v is not None for v in learned) else baseline
        avg = round(sum(selected) / len(selected), 3) if eligible and selected else None
        items.append({
            "product_id": pid, "store_id": sid, "product_name": row["product_name"], "sku": row["sku"], "store_name": row["store_name"],
            "current_stock": int(row["quantity"]), "forecast_available": bool(eligible),
            "forecast_reason": None if eligible else ("No completed POS sales or imported history for this product/store." if not series else f"Only {len(series)} calendar day(s) of observed sales; at least 7 are needed for the baseline and 14 for the ML model."),
            "forecast_daily_average": avg,
            "forecast_total_units": round(sum(selected), 2) if eligible and selected else None,
            "forecast_stock_cover_days": round(int(row["quantity"]) / avg, 2) if avg is not None and avg > 0 else None,
            "ml_daily_average": round(_mean([v for v in learned if v is not None]), 3) if any(v is not None for v in learned) else None,
            "baseline_daily_average": round(_mean(baseline), 3) if baseline else None,
            "promo_in_window": any(_active_promo(conn, pid, sid, series[-1]["date"] + timedelta(days=d)) for d in range(1, days_ahead + 1)) if series else False,
            "forecast_source": MODEL_NAME if use_ml and eligible and all(v is not None for v in learned) else "Observed 7-day moving-average baseline" if eligible else "Unavailable — insufficient observed history",
        })
    items.sort(key=lambda item: (not item["forecast_available"], item["forecast_stock_cover_days"] is None, item["forecast_stock_cover_days"] if item["forecast_stock_cover_days"] is not None else 9999))
    return {"trained": bool(status.get("trained")), "stale": bool(status.get("stale")), "days_ahead": days_ahead, "selected_forecaster": status.get("selected_forecaster"), "data_origin": DATA_ORIGIN, "note": status.get("note", status.get("selection_reason")), "items": items, "observed_history": sales_data.data_summary(conn)}


def using_current_ml_model(conn) -> bool:
    """Whether the saved ML artifact is trained on the exact current observed dataset."""
    meta = _load_metadata()
    return bool(
        meta and str(meta.get("data_origin", "")).startswith("Observed Store & POS transactions")
        and meta.get("data_signature") == sales_data.data_signature(conn)
        and meta.get("selected_forecaster") == "ridge_regression"
    )


def forecast_daily_demand(conn, product_id: int, store_id: int) -> float | None:
    """Return a forecast only from observed transaction/imported history.

    No seed/demo sales velocity is used to manufacture an ML time series. When
    observed history is too sparse, return None and let the rule-based agent's
    existing fallback label its conventional demo/history calculation.
    """
    series = _series_with_calendar_features(conn).get((int(product_id), int(store_id)), [])
    if not series:
        return None
    status = _load_metadata()
    fresh = bool(
        status and str(status.get("data_origin", "")).startswith("Observed Store & POS transactions")
        and status.get("data_signature") == sales_data.data_signature(conn)
    )
    if fresh and status.get("selected_forecaster") == "ridge_regression" and len(series) >= 14:
        try:
            model = _load_saved_model()
            tomorrow = series[-1]["date"] + timedelta(days=1)
            promo = int(_active_promo(conn, product_id, store_id, tomorrow))
            return round(_predict(model, _future_features(series, product_id, store_id, tomorrow, promo)), 4)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            pass
    # If the model is not selected or has gone stale after a new sale, the live
    # observed moving average adapts immediately and is preferable to stale ML.
    if len(series) >= 7:
        return round(_mean([float(row["units"]) for row in series[-7:]]), 4)
    # A short history is exposed as low-confidence observed pace, never described
    # as a trained forecast.
    return round(_mean([float(row["units"]) for row in series]), 4)
