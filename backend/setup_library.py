"""Explicit first-time catalogue creation; normal production startup never creates one."""
import json
import os
from . import core


def initialize():
    directory = core.database_dir()
    paths = [directory / name for name in ("catalogue.sqlite", "sync.sqlite")]
    existing = [path.is_file() and path.stat().st_size > 0 for path in paths]
    if any(path.exists() for path in paths) and not all(existing):
        raise OSError("Incomplete existing database pair: restore both databases; setup will not replace them")
    # This explicit installer is the sole exception to the existing-database guard.
    # Never relax that guard for an established or partially missing installation.
    previous = os.environ.get("DAHAN_REQUIRE_EXISTING_DATABASE")
    os.environ["DAHAN_REQUIRE_EXISTING_DATABASE"] = "1" if all(existing) else "0"
    try:
        core.DATA.mkdir(parents=True, exist_ok=True)
        directory.mkdir(parents=True, exist_ok=True)
        core.init()
        from .sync_service import store
        with store():
            pass
        with core.db() as connection:
            count = connection.execute("SELECT count(*) FROM library_databases").fetchone()[0]
        return {"runtime": str(core.DATA), "databases": str(directory), "registered_databases": count, "created": not any(existing)}
    finally:
        if previous is None:
            os.environ.pop("DAHAN_REQUIRE_EXISTING_DATABASE", None)
        else:
            os.environ["DAHAN_REQUIRE_EXISTING_DATABASE"] = previous


if __name__ == "__main__":
    print(json.dumps(initialize()))
