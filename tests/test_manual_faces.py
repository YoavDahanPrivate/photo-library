import json
import pytest
from PIL import Image
from tests.test_catalogue import client


@pytest.fixture
def photo(client, monkeypatch):
    c, core = client
    from backend import manual_faces

    monkeypatch.setattr(manual_faces, "signature", lambda crop: None)
    (core.DATA / "thumbs").mkdir()
    Image.new("RGB", (400, 200), "gray").save(core.DATA / "thumbs" / "2-large.jpg")
    return c, core


def box(**changes):
    return dict(x=0.1, y=0.1, width=0.2, height=0.4, person_id=1, **changes)


def test_manual_search_crop_and_undo(photo):
    c, core = photo
    r = c.post("/api/media/2/manual-face", json=box())
    assert r.status_code == 200, r.text
    assert r.json()["recognition_ready"] is False
    fid = r.json()["id"]
    assert (core.DATA / "faces" / f"{fid}.jpg").is_file()
    data = c.get("/api/media/2").json()
    assert data["people_names"] == ["Maya"]
    assert data["faces"][0]["bbox_width"] == 400
    assert (
        c.get("/api/media", params={"expression": 'Only "Maya"'}).json()["total"] == 2
    )
    assert c.post("/api/undo").status_code == 200
    assert c.get("/api/media/2").json()["faces"] == []


def test_overlap_reassign_redraw_remove(photo):
    c, core = photo
    first = c.post("/api/media/2/manual-face", json=box()).json()["id"]
    assert c.post("/api/media/2/manual-face", json=box()).status_code == 409
    moved = box(replaces=first)
    moved["person_id"] = 2
    moved["x"] = 0.5
    second = c.post("/api/media/2/manual-face", json=moved)
    assert second.status_code == 200, second.text
    assert c.get("/api/media/2").json()["people_names"] == ["Daniel"]
    c.post("/api/undo")
    assert c.get("/api/media/2").json()["faces"][0]["id"] == first
    c.post(
        "/api/faces/correct", json={"face_ids": [first], "action": "move", "target": 2}
    )
    assert c.get("/api/media/2").json()["people_names"] == ["Daniel"]
    c.post("/api/faces/correct", json={"face_ids": [first], "action": "dismiss"})
    assert c.get("/api/media/2").json()["faces"] == []
    c.post("/api/undo")
    assert c.get("/api/media/2").json()["people_names"] == ["Daniel"]


def test_new_name_and_signature(photo, monkeypatch):
    c, core = photo
    from backend import manual_faces
    import numpy as np

    v = np.zeros(128, dtype=np.float32)
    v[0] = 1
    monkeypatch.setattr(manual_faces, "signature", lambda crop: v.tobytes())
    body = box()
    body["person_id"] = None
    body["name"] = "New Relative"
    result = c.post("/api/media/2/manual-face", json=body)
    assert result.status_code == 200 and result.json()["recognition_ready"]
    assert c.get("/api/media/2").json()["people_names"] == ["New Relative"]
    c.post("/api/undo")
    assert c.post("/api/media/2/manual-face", json=body).status_code == 200


@pytest.mark.parametrize(
    "changes",
    [
        {"x": -0.1},
        {"width": 0},
        {"x": 0.9, "width": 0.4},
        {"person_id": None},
        {"name": "Other"},
        {"width": 0.001},
        {"replaces": "missing"},
        {"person_id": 999},
    ],
)
def test_invalid_regions_atomic(photo, changes):
    c, core = photo
    body = box()
    body.update(changes)
    assert c.post("/api/media/2/manual-face", json=body).status_code in (404, 409, 422)
    assert c.get("/api/media/2").json()["faces"] == []


def test_video_and_missing_preview(photo):
    c, core = photo
    assert c.post("/api/media/absent/manual-face", json=box()).status_code == 404
    assert c.post("/api/media/1/manual-face", json=box()).status_code == 409
    with core.db() as db:
        db.execute("UPDATE media SET kind='video' WHERE id='2'")
    assert c.post("/api/media/2/manual-face", json=box()).status_code == 422


def test_later_clustering_ignores_manual_without_signature(photo):
    c, core = photo
    import numpy as np
    from backend import indexer

    with core.db() as db:
        db.execute("DELETE FROM faces")
    assert c.post("/api/media/2/manual-face", json=box()).status_code == 200
    with core.db() as db:
        v = np.zeros(128, dtype=np.float32)
        v[0] = 1
        db.execute(
            "INSERT INTO faces(id,media_id,embedding,status) VALUES('later','1',?,'suggested')",
            (v.tobytes(),),
        )
    indexer.cluster()
    with core.db() as db:
        assert (
            db.execute("SELECT person_id FROM faces WHERE id='later'").fetchone()[0]
            is not None
        )
