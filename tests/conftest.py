import pytest

@pytest.fixture(autouse=True)
def disable_background_scheduler(monkeypatch):
    monkeypatch.setenv("DAHAN_DISABLE_SCHEDULER", "1")
    # Deliberate historical-library fixtures; production has no preset Sources.
    monkeypatch.setenv("DAHAN_LEGACY_SOURCES", '["Yoav14ProMax", "Bar\\u2019s iPhone", "iPhoneX Hila"]')
    monkeypatch.setenv("DAHAN_HOST_ALIASES", "dahanoffice,dahanoffice.local")

    # Tests must never inherit a production database path from a launcher.
    for name in ("DAHAN_DATABASE_DIR", "DAHAN_REQUIRE_EXISTING_DATABASE", "DAHAN_BACKUP_DIR"):
        monkeypatch.delenv(name, raising=False)
