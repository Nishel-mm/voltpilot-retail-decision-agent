import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = Path(os.environ.get("VOLTPILOT_DB", DATA_DIR / "voltpilot.db"))

FRONTEND_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

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
