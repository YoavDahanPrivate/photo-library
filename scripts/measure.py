"""Read-only measurements for the disposable prototype."""

import json
import statistics
import time
from pathlib import Path
import httpx
from backend.core import DATA, db, original


def size_of(path):
    return (
        sum(
            p.stat().st_size
            for p in path.rglob("*")
            if p.is_file() and not p.is_symlink()
        )
        if path.exists()
        else 0
    )


with db() as connection:
    records = connection.execute("SELECT * FROM media").fetchall()
    changed = []
    for row in records:
        info = original(row).stat()
        if info.st_size != row["bytes"] or abs(info.st_mtime - row["mtime"]) > 0.001:
            changed.append(row["id"])
    counts = [
        dict(row)
        for row in connection.execute(
            "SELECT phone,kind,extension,count(*) count FROM media GROUP BY phone,kind,extension"
        )
    ]
    unknown_dates = connection.execute(
        "SELECT count(*) FROM media WHERE taken IS NULL"
    ).fetchone()[0]
    gps_count = connection.execute(
        "SELECT count(*) FROM media WHERE latitude IS NOT NULL"
    ).fetchone()[0]
    active_test_edits = connection.execute(
        "SELECT count(*) FROM actions WHERE undone=0"
    ).fetchone()[0]

times = []
with httpx.Client(base_url="http://127.0.0.1:8765", timeout=20) as client:
    for _ in range(20):
        started = time.perf_counter()
        response = client.get(
            "/api/media", params={"phones": "Yoav14ProMax", "limit": 80}
        )
        response.raise_for_status()
        assert response.json()["total"] == 200
        times.append((time.perf_counter() - started) * 1000)

report = {
    "sample_files": len(records),
    "source_bytes": sum(row["bytes"] for row in records),
    "source_fingerprint_changes": changed,
    "active_test_edits": active_test_edits,
    "unknown_capture_dates": unknown_dates,
    "with_gps": gps_count,
    "formats": counts,
    "generated_bytes": {
        name: size_of(DATA / name) for name in ("thumbs", "frames", "faces", "previews")
    },
    "database_bytes": (DATA / "catalogue.sqlite").stat().st_size,
    "model_bytes": size_of(DATA.parent / "models"),
    "api_query_ms": {
        "median": round(statistics.median(times), 2),
        "p95": round(sorted(times)[18], 2),
        "iterations": 20,
    },
}
(DATA / "verification-report.json").write_text(
    json.dumps(report, indent=2), encoding="utf-8"
)
print(json.dumps(report, indent=2))
