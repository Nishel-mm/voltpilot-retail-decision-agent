# VoltPilot

Decision agent for **VoltKart Electronics** (Cypher 2026 — Festival Rush).

VoltPilot is not a static dashboard. A FastAPI backend calculates stock cover, ranks issues, compares transfer vs purchase vs wait, and executes **simulated** operations only after a manager approves them.

## What to tell judges

1. **Transfer before purchase** — the agent looks at other stores before recommending a new PO.
2. **What-if consequences** — transferring stock shows whether the source store would go short.
3. **Evidence before action** — every recommendation lists data, assumptions, alternatives, and a human approval gate.

This is **rule-based**. There is no LLM and no fake machine-learning model.

Product names such as AirBeat TWS, PulseFit Smartwatch, and SlimCell Power Bank were taken from [volttkart.shop](https://volttkart.shop/). The NovaVision 55-inch Smart TV scenario comes from the hackathon brief, not the public shop. Transfer time, transfer cost, and promo demand uplift were **not** given in the brief; they are labelled assumptions.

## Run locally

Terminal 1 — backend:

```powershell
cd C:\Users\Nishel\voltpilot\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Terminal 2 — frontend:

```powershell
cd C:\Users\Nishel\voltpilot\frontend
npm install
npm run dev
```

Open http://localhost:5173

## Tests

```powershell
cd C:\Users\Nishel\voltpilot\backend
.\.venv\Scripts\Activate.ps1
python -m pytest tests -q
```

## Demo path (5 minutes)

1. Command Center → open the Critical TV issue.
2. Show Mumbai cover vs Bengaluru surplus vs Apex (7-day cheap) vs Swift (2-day +5%).
3. Approve the transfer. Inventory moves immediately. Ledger records it.
4. Try Approve again — duplicate execution is blocked.
5. Reset demo, reject the same item — inventory does not change.
6. Open the healthy SilentClick mouse issue — recommended action is **do nothing**.

## Architecture

- `backend/app/seed.py` — reproducible 9 Oct 2026 snapshot.
- `backend/app/services/metrics.py` — velocity, cover, surplus math.
- `backend/app/services/engine.py` — issue detection, option comparison, radar score.
- `backend/app/services/executor.py` — approve / reject with SQLite transactions.
- `frontend/src` — React UI that only displays API results.

Radar score: `(severity_weight + urgency + financial_index) × confidence`.
