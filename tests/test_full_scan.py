import json
import numpy as np
from PIL import Image
from tests.test_catalogue import client


def test_discovery_additive_resume_and_changed_sources(client):
    _, core = client
    from backend import full_scan

    for phone in core.PHONES:
        (core.ROOT / phone / "Album").mkdir(parents=True)
    image = core.ROOT / core.PHONES[0] / "Album" / "new.jpg"
    Image.new("RGB", (80, 60)).save(image)
    excluded = core.ROOT / core.PHONES[0] / ".dtrash"
    excluded.mkdir()
    (excluded / "ignore.jpg").write_bytes(b"not a photo")
    before = None
    with core.db() as c:
        before = [
            tuple(r)
            for r in c.execute("SELECT id,person_id,status FROM faces ORDER BY id")
        ]
    report = full_scan.discover({})
    assert report["added"] == 1
    assert full_scan.discover({})["added"] == 0
    image.write_bytes(b"changed")
    assert full_scan.discover({})["changed_sources"] == [str(image)]
    with core.db() as c:
        assert [
            tuple(r)
            for r in c.execute("SELECT id,person_id,status FROM faces ORDER BY id")
        ] == before


def test_process_photo_and_resume_without_redecoding(client, monkeypatch):
    _, core = client
    from backend import full_scan, indexer

    monkeypatch.setattr(indexer, "DATA", core.DATA)
    phone = core.PHONES[0]
    (core.ROOT / phone).mkdir(parents=True)
    path = core.ROOT / phone / "new.jpg"
    Image.new("RGB", (200, 100), "red").save(path)
    import os, time

    os.utime(path, (time.time() - 100, time.time() - 100))
    stat = path.stat()
    for folder in ("thumbs", "frames", "faces"):
        (core.DATA / folder).mkdir()
    with core.db() as c:
        c.execute(
            "INSERT INTO media(id,path,phone,name,kind,bytes,mtime) VALUES('new',?,?,?,'photo',?,?)",
            (str(path), phone, path.name, stat.st_size, stat.st_mtime),
        )

    class Recognizer:
        def process(self, *args):
            pass

    class Locations:
        def resolve(self, *args):
            return None

    monkeypatch.setattr(full_scan, "recognizer", Recognizer())
    monkeypatch.setattr(full_scan, "locations", Locations())
    assert full_scan.process_one("new")["ok"]
    assert (core.DATA / "thumbs" / "new-large.jpg").is_file()
    monkeypatch.setattr(
        indexer,
        "photo",
        lambda p: (_ for _ in ()).throw(AssertionError("Decoded ready photo again")),
    )
    assert full_scan.process_one("new")["ok"]


def test_new_clustering_does_not_rewrite_manual_faces(client):
    _, core = client
    from backend import full_scan

    v = np.zeros(128, dtype=np.float32)
    v[0] = 1
    with core.db() as c:
        c.execute(
            "UPDATE faces SET embedding=?,status='manual' WHERE person_id=1",
            (v.tobytes(),),
        )
        c.execute(
            "INSERT INTO faces(id,media_id,embedding) VALUES('fresh','2',?)",
            (v.tobytes(),),
        )
        c.execute(
            "INSERT INTO faces(id,media_id,embedding,status) VALUES('unassigned','2',?,'manual')",
            (v.tobytes(),),
        )
    assert full_scan.assign_new_faces() == 1
    with core.db() as c:
        assert (
            c.execute("SELECT person_id FROM faces WHERE id='fresh'").fetchone()[0] == 1
        )
        assert (
            c.execute("SELECT person_id FROM faces WHERE id='unassigned'").fetchone()[0]
            is None
        )
        assert (
            c.execute("SELECT status FROM faces WHERE id='a'").fetchone()[0] == "manual"
        )
    assert full_scan.assign_new_faces() == 0


def test_record_error_keeps_browsable_media(client):
    _, core = client
    from backend import full_scan

    full_scan.record_error({"id": "0", "error": "face stage failed"})
    with core.db() as c:
        r = c.execute(
            "SELECT status,face_status,error FROM media WHERE id='0'"
        ).fetchone()
        assert r["status"] == "ready" and r["face_status"] == "error"
        assert r["error"] == "face stage failed"


def test_checkpoint_state_transitions_and_windows_retry(client,monkeypatch):
    _,core=client
    from backend import full_scan
    from pathlib import Path
    real=Path.replace
    attempts=[]
    def transient(self,target):
        attempts.append(1)
        if len(attempts)<3: raise PermissionError('sharing conflict')
        return real(self,target)
    monkeypatch.setattr(Path,'replace',transient)
    monkeypatch.setattr(full_scan.time,'sleep',lambda seconds:None)
    progress={'state':'running'}
    assert full_scan.checkpoint(progress,state='paused') is True
    assert len(attempts)==3
    assert json.loads((core.DATA/'scan-state.json').read_text())['state']=='paused'
    assert full_scan.checkpoint(progress,state='completed') is True
    assert full_scan.checkpoint(progress,state='stopped',error='test') is True


def test_checkpoint_persistent_sharing_conflict_is_not_fatal(client,monkeypatch):
    _,core=client
    from backend import full_scan
    from pathlib import Path
    def denied(self,target):raise PermissionError('sharing conflict')
    monkeypatch.setattr(Path,'replace',denied)
    monkeypatch.setattr(full_scan.time,'sleep',lambda seconds:None)
    assert full_scan.checkpoint({},state='running') is False
