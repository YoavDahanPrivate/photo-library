import importlib
from pathlib import Path
import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("DAHAN_LAN_ADDRESS", raising=False)
    monkeypatch.setenv("DAHAN_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("DAHAN_SOURCE", str(tmp_path / "originals"))
    from backend import core

    importlib.reload(core)
    from backend import app

    importlib.reload(app)
    from fastapi.testclient import TestClient

    with core.db() as c:
        for i, (phone, album) in enumerate(
            [
                ("Yoav14ProMax", "Recents"),
                ("Bar\u2019s iPhone", "Recents"),
                ("Yoav14ProMax", "AI"),
            ]
        ):
            c.execute(
                "INSERT INTO media(id,path,phone,album,name,kind,status,width,height,taken) VALUES(?,?,?,?,?,'photo','ready',800,1200,'2026-09-06')",
                (str(i), str(tmp_path / f"{i}.jpg"), phone, album, f"{i}.jpg"),
            )
        c.execute("INSERT INTO people(id,name) VALUES(1,'Maya'),(2,'Daniel')")
        for fid, mid, pid in [("a", "0", 1), ("b", "0", 2), ("c", "1", 1)]:
            c.execute(
                "INSERT INTO faces(id,media_id,person_id,bbox,embedding) VALUES(?,?,?,?,?)",
                (fid, mid, pid, "[]", b"0000"),
            )
    return TestClient(app.app), core


def test_source_pairs(client):
    c, _ = client
    assert [
        m["id"]
        for m in c.get(
            "/api/media", params={"albums": "Yoav14ProMax\x1fRecents"}
        ).json()["items"]
    ] == ["0"]
    assert (
        c.get("/api/media", params={"phones": "Bar\u2019s iPhone"}).json()["total"] == 1
    )


def test_match_all_people(client):
    c, _ = client
    assert (
        c.get("/api/media", params=[("people", 1), ("people", 2)]).json()["total"] == 1
    )
    assert c.get("/api/media", params={"orientation": "landscape"}).json()["total"] == 0


def test_face_corrections_and_undo(client):
    c, s = client
    result = c.post(
        "/api/faces/correct",
        json={"face_ids": ["a"], "action": "split", "name": "Other"},
    ).json()
    assert result["person_id"] not in (1, 2)
    assert c.post("/api/undo", json={}).status_code == 200
    with s.db() as db:
        assert db.execute("SELECT person_id FROM faces WHERE id='a'").fetchone()[0] == 1
    assert (
        c.post(
            "/api/faces/correct", json={"face_ids": ["a"], "action": "unknown"}
        ).status_code
        == 200
    )
    with s.db() as db:
        row = db.execute("SELECT person_id,status FROM faces WHERE id='a'").fetchone()
        assert row["person_id"] is None and row["status"] == "manual"
    assert c.post("/api/undo", json={}).status_code == 200


def test_invalid_correction_atomic(client):
    c, s = client
    assert (
        c.post(
            "/api/faces/correct",
            json={"face_ids": ["a", "missing"], "action": "dismiss"},
        ).status_code
        == 404
    )
    with s.db() as db:
        assert (
            db.execute("SELECT status FROM faces WHERE id='a'").fetchone()[0]
            == "suggested"
        )


def test_unassigned_queue_and_reassignment(client):
    c, s = client
    assert (
        c.post(
            "/api/faces/correct", json={"face_ids": ["a"], "action": "unknown"}
        ).status_code
        == 200
    )
    queue = [p for p in c.get("/api/people").json() if p["id"] == 0]
    assert len(queue) == 1 and queue[0]["count"] == 1
    assert c.get("/api/faces", params={"unknown": True}).json()[0]["id"] == "a"
    assert (
        c.post(
            "/api/faces/correct",
            json={"face_ids": ["a"], "action": "move", "target": 2},
        ).status_code
        == 200
    )
    with s.db() as db:
        assert db.execute("SELECT person_id FROM faces WHERE id='a'").fetchone()[0] == 2


def test_rename_and_undo(client):
    c, _ = client
    assert c.post("/api/people/1/name", json={"name": "Revised"}).status_code == 200
    assert (
        next(p for p in c.get("/api/people").json() if p["id"] == 1)["name"]
        == "Revised"
    )
    assert c.post("/api/undo", json={}).status_code == 200
    assert (
        next(p for p in c.get("/api/people").json() if p["id"] == 1)["name"] == "Maya"
    )


def test_dismiss_and_restore(client):
    c, _ = client
    assert (
        c.post(
            "/api/faces/correct", json={"face_ids": ["a"], "action": "dismiss"}
        ).status_code
        == 200
    )
    assert not any(f["id"] == "a" for f in c.get("/api/faces").json())
    assert c.post("/api/undo", json={}).status_code == 200
    assert any(f["id"] == "a" for f in c.get("/api/faces").json())


def test_source_boundary(client):
    c, _ = client
    assert c.get("/api/media/0/original").status_code == 403
    assert c.get("/api/media/missing").status_code == 404


def test_cross_origin(client):
    c, _ = client
    assert (
        c.post(
            "/api/undo", json={}, headers={"origin": "https://example.com"}
        ).status_code
        == 403
    )


def test_sample_formats():
    from backend.indexer import choose

    files = [Path(f"/phone/Recents/{i}.jpg") for i in range(100)] + [
        Path("/phone/AI/one.heic"),
        Path("/phone/Recents/movie.mov"),
    ]
    selected = choose(files, 10)
    assert len(selected) == 10 and len(set(selected)) == 10
    assert {p.suffix for p in selected} == {".jpg", ".heic", ".mov"}
    assert selected == choose(files, 10)


def test_lan_opt_in(client, monkeypatch):
    c, _ = client
    from backend import app
    address = "10.100.102.52"
    headers = {"host": f"{address}:8765", "origin": f"http://{address}:8765"}
    assert c.get("/api/status", headers=headers).status_code == 403
    monkeypatch.setenv("DAHAN_LAN_ADDRESS", address)
    importlib.reload(app)
    from fastapi.testclient import TestClient
    with TestClient(app.app) as lan:
        assert lan.get("/api/status", headers=headers).status_code == 200
        assert lan.post("/api/people/1/name", json={"name": "LAN test"}, headers=headers).status_code == 200
        assert lan.post("/api/undo", json={}, headers={**headers, "origin": "http://evil.example"}).status_code == 403
        assert lan.get("/api/status", headers={"host": "evil.example:8765"}).status_code == 403
