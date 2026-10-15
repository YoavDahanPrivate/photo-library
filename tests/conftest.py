import pytest

@pytest.fixture(autouse=True)
def disable_background_scheduler(monkeypatch):
    monkeypatch.setenv("DAHAN_DISABLE_SCHEDULER", "1")

    # Tests must never inherit a production database path from a launcher.
    for name in ("DAHAN_DATABASE_DIR", "DAHAN_REQUIRE_EXISTING_DATABASE", "DAHAN_BACKUP_DIR"):
        monkeypatch.delenv(name, raising=False)
