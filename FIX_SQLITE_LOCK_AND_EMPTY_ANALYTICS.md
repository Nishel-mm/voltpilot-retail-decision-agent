# VoltPilot test-lock and empty-analytics fix

## Apply
Extract this ZIP into the root of your existing VoltPilot repository (`C:\Users\Nishel\voltpilot`) and allow the listed files to replace the matching files. It does **not** include or replace any `.db` file, `.env` file, connection string, frontend build, or `node_modules`.

## What this fixes
- Makes each pytest test use its own SQLite database, rather than tests colliding on a single file after imports.
- Aligns the explicit test-seed sales dates with the application's current India business date, so the expected 14-day test velocity does not drift as calendar days pass.
- Makes normal startup default to stores, the 13-product catalogue and opening stock only. It does not automatically create sales history, POS transactions, suppliers, supplier offers, promotions, purchase orders or recommendations.
- Leaves legacy synthetic fixture seeding available only with `VOLTPILOT_AUTO_SEED_DEMO=true` in local development; demo reset is disabled unless `VOLTPILOT_ALLOW_DEMO_RESET=true` is explicitly set.
- Makes the late-PO unit test create its required fixture explicitly, instead of depending on synthetic data being installed at app startup.

## Validation
The prepared source snapshot for this patch completed `python -m pytest -q` with **20 passed**. The user's previous local output reported 23 tests, so the remaining local-only tests should be evaluated after applying this patch; no deployment is required for that check.

Do not delete your existing database. Do not push or deploy until the local test result is reviewed.
