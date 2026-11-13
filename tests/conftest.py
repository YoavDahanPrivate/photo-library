from pathlib import Path
import sys

# The portable runtime may also list its installed app; always test this checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

@pytest.fixture(autouse=True)
def disable_background_scheduler(monkeypatch):
    monkeypatch.setenv("DAHAN_DISABLE_SCHEDULER", "1")
    # Deliberate historical-library fixtures; production has no preset Sources.
    monkeypatch.setenv("DAHAN_LEGACY_SOURCES", '["Yoav14ProMax", "Bar\\u2019s iPhone", "iPhoneX Hila"]')
    monkeypatch.setenv("DAHAN_HOST_ALIASES", "dahanoffice,dahanoffice.local")

    # Tests must never inherit a production database path from a launcher.
    for name in ("DAHAN_DATABASE_DIR", "DAHAN_REQUIRE_EXISTING_DATABASE", "DAHAN_BACKUP_DIR", "DAHAN_CACHE_PACKS"):
        monkeypatch.delenv(name, raising=False)


_seed_hashes = {}

@pytest.fixture(autouse=True)
def reuse_disposable_account_seed_hashes(monkeypatch):
    # Hundreds of fresh catalogue fixtures seed the same six bootstrap accounts.
    # Reuse only those fixture seed hashes; ordinary password hashing (and its
    # random salts) remains the real implementation for authentication tests.
    from backend import account_auth, user_profiles
    original = account_auth.hash_password
    seeds = {name + "1919" for name in user_profiles.NAMES}
    def hash_password(password):
        if password not in seeds:
            return original(password)
        if password not in _seed_hashes:
            _seed_hashes[password] = original(password)
        return _seed_hashes[password]
    monkeypatch.setattr(account_auth, "hash_password", hash_password)
