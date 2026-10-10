# VoltPilot performance patch — batched PostgreSQL reads

This patch reduces backend/database round trips without changing the seven risk-area rules or creating business history.

## Files included
- `backend/app/services/metrics.py`: adds one-query `sales_velocity_map`.
- `backend/app/main.py`: uses batched velocity for `/api/inventory`.
- `backend/app/services/risk_areas.py`: batches sales velocity, supplier offers, active promotion lookups, weekend sales reads, status counts, and activity timestamps; replaces a repeated inventory scan for late purchase orders with a dictionary lookup.
- `backend/tests/test_performance_batch_queries.py`: guards against reintroducing per-inventory-row database calls.

No production database schema/data is reset or seeded by this patch. Existing product, inventory, sales, supplier, promotion and purchase-order data are read as before.

## Apply
Extract this ZIP into the repository root (`C:\Users\Nishel\voltpilot`) and allow the listed files to replace their existing versions. Then run the backend test suite and frontend build before committing/deploying.
