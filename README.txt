VoltPilot — Late PO decision-routing fix

Purpose
- Treat an open purchase order as late when its expected_at date has passed the fixed DEMO_TODAY, even if the PO status still says "ordered" or "in_transit".
- Ensure the decision engine includes an expedite_po option for a late PO when it generates a stockout/promotion recommendation.
- Let Goal 07 match the relevant pending decision by exact PO number in the title/evidence/options. This sends Review agent recommendations to /decision/:id rather than a generic fallback when a matching executable decision exists.

Files included
- backend/app/services/engine.py
- backend/tests/test_late_po_decision_routing.py
- frontend/src/utils/recommendationRouting.js

Apply
1. Back up these files.
2. Extract this ZIP into C:\Users\Nishel\voltpilot and replace only included files.
3. Restart the backend (Python engine changed): Ctrl+C, then run:
   cd C:\Users\Nishel\voltpilot\backend
   .\.venv\Scripts\Activate.ps1
   python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
4. Keep/restart Vite only if the UI does not hot reload.
5. Test GET http://127.0.0.1:8000/api/recommendations?refresh=true, then Command Center > Goal 07 > Review agent recommendations. A pending matching decision should open the Decision page directly.

No DB, package files, Vite config, virtual environment, or frontend App.jsx is included. No migrations required.

Business safety: approval and simulated execution remain handled by the existing decision page and backend. This patch does not mark incoming goods as on-hand inventory.
