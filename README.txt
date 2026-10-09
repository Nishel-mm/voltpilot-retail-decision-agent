VoltPilot API test fix

What this fixes
- The two remaining failures were from tests/test_api.py using a module-level TestClient without entering its context, so FastAPI startup never initialized the schema for that test database.
- The old dashboard test expected seeded recommendations, which conflicts with the required empty-analytics startup behaviour.

Install
1. Extract this ZIP into C:\Users\Nishel\voltpilot.
2. Allow it to replace backend\tests\test_api.py only.
3. From PowerShell, run:
   cd C:\Users\Nishel\voltpilot\backend
   python -m pytest -q

Validation
The patched project snapshot available for verification passed: 23 passed.
The test-only patch does not alter application code, your database, or live deployment settings.
