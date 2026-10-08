import pytest

@pytest.fixture(autouse=True)
def disable_background_scheduler(monkeypatch):
    monkeypatch.setenv("DAHAN_DISABLE_SCHEDULER", "1")
