"""Keep tests isolated even when application modules were imported during collection."""

import pytest


@pytest.fixture(autouse=True)
def isolate_database_per_test(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("VOLTPILOT_DB", str(tmp_path / "voltpilot-test.sqlite3"))
