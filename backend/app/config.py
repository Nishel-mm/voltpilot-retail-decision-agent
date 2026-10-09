import os
from pathlib import Path
from datetime import datetime, date
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = Path(os.environ.get("VOLTPILOT_DB", DATA_DIR / "voltpilot.db"))
# Set DATABASE_URL only on the deployed service to use hosted PostgreSQL.
# Local development keeps SQLite unless DATABASE_URL is explicitly configured.
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_POSTGRES = DATABASE_URL.lower().startswith(("postgres://", "postgresql://"))
# Safe-by-default: starter catalogue is allowed, synthetic business history is opt-in only.
AUTO_SEED_DEMO = os.environ.get("VOLTPILOT_AUTO_SEED_DEMO", "false").strip().lower() in {"1", "true", "yes"}
ALLOW_DEMO_RESET = os.environ.get("VOLTPILOT_ALLOW_DEMO_RESET", "false").strip().lower() in {"1", "true", "yes"}
BUSINESS_TIMEZONE = os.environ.get("VOLTPILOT_TIMEZONE", "Asia/Kolkata")
BUSINESS_DATE_OVERRIDE = os.environ.get("VOLTPILOT_BUSINESS_DATE", "").strip()

def business_date() -> date:
    """Return the configured business date (India by default); tests can override it."""
    if BUSINESS_DATE_OVERRIDE:
        return date.fromisoformat(BUSINESS_DATE_OVERRIDE)
    try:
        return datetime.now(ZoneInfo(BUSINESS_TIMEZONE)).date()
    except Exception:
        return datetime.now().date()

# Local development origins plus comma-separated production origins.
# Example: FRONTEND_ORIGINS=https://voltpilot-retail-web-nishel.onrender.com
_CONFIGURED_FRONTEND_ORIGINS = [
    origin.strip().rstrip("/")
    for origin in os.environ.get("FRONTEND_ORIGINS", "").split(",")
    if origin.strip()
]
FRONTEND_ORIGINS = list(dict.fromkeys([
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    *_CONFIGURED_FRONTEND_ORIGINS,
]))

# Demo clock. Seed data and promo windows are built around this date.
DEMO_TODAY = "2026-10-09"
# These are CONFIGURABLE ASSUMPTIONS, not facts from VoltKart.
# The UI must label them as assumptions.
DEFAULT_ASSUMPTIONS = {
    "transfer_days": {
        "value": "1",
        "description": "Days to move stock between stores. Not supplied by the challenge; used for what-if timing.",
    },
    "transfer_cost_per_unit": {
        "value": "150",
        "description": "Estimated INR cost to transfer one unit between stores (packaging + logistics).",
    },
    "promo_demand_uplift": {
        "value": "0.40",
        "description": "Extra demand during a promotion as a fraction of baseline velocity (0.40 = +40%).",
    },
    "min_safe_cover_days": {
        "value": "7",
        "description": "Minimum days of stock a source store should keep after a transfer.",
    },
    "velocity_lookback_days": {
        "value": "14",
        "description": "Number of past days used to compute average daily sales velocity.",
    },
    "ageing_days_threshold": {
        "value": "90",
        "description": "Days on hand after which slow stock is treated as ageing / markdown risk.",
    },
    "horizon_days": {
        "value": "10",
        "description": "Planning window for stockout and transfer quantity calculations.",
    },
    "margin_on_lost_sale": {
        "value": "0.22",
        "description": "Assumed profit share of selling price used to estimate stockout impact.",
    },
}
