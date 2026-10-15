import pytest
from fastapi import HTTPException
from test_catalogue import client
from test_search_people import seed_vectors


def test_display_rename_preserves_queue_flags_and_annotations(client):
    c, core = client
    seed_vectors(core)
    assert c.post('/api/people/reevaluate').json()['suggestions'] == 1
    before = c.get('/api/people/suggestions').json()[0]
    assert before['confidence'] == 'high'
    assert c.post('/api/people/1/name', json={'name': 'Renamed Maya'}).status_code == 200
    after = c.get('/api/people/suggestions').json()[0]
    assert after['face_id'] == before['face_id']
    assert after['person_id'] == before['person_id']
    assert after['confidence'] == 'high'
    assert after['name'] == 'Renamed Maya'
    with core.db() as db:
        assert db.execute("SELECT person_id FROM faces WHERE id='candidate'").fetchone()[0] is None


def test_naming_group_removes_only_its_candidates_and_demotes_old_flags(client):
    c, core = client
    seed_vectors(core)
    assert c.post('/api/people/reevaluate').json()['suggestions'] == 1
    with core.db() as db:
        db.execute('INSERT INTO people(id) VALUES(3)')
        db.execute("INSERT INTO faces(id,media_id,person_id,status) VALUES('own','2',3,'manual')")
        db.execute("INSERT INTO face_suggestions VALUES('own',1,.9,.2)")
        db.execute("INSERT INTO high_confidence_faces VALUES('own')")
    assert c.post('/api/people/3/name', json={'name': 'New person'}).status_code == 200
    rows = c.get('/api/people/suggestions').json()
    assert [row['face_id'] for row in rows] == ['candidate']
    assert rows[0]['confidence'] == 'lower'
    with core.db() as db:
        assert db.execute("SELECT count(*) FROM face_suggestions WHERE face_id='own'").fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM high_confidence_faces').fetchone()[0] == 0
        assert db.execute("SELECT person_id FROM faces WHERE id='own'").fetchone()[0] == 3


def test_worker_retries_changed_snapshot_and_publishes_current_references(client, monkeypatch):
    c, core = client
    seed_vectors(core)
    from backend.people_review import reevaluate_current
    phases = []
    changed = False
    def progress(phase, *args):
        nonlocal changed
        phases.append(phase)
        if phase == 'Saving suggestions' and not changed:
            changed = True
            assert c.post('/api/people/1/name', json={'name': 'Updated name'}).status_code == 200
    result = reevaluate_current(progress)
    assert result['suggestions'] == 1
    assert sum('retry' in phase for phase in phases) == 1
    assert c.get('/api/people/suggestions').json()[0]['name'] == 'Updated name'


def test_persistent_changes_are_bounded_and_preserve_last_committed_queue(client):
    c, core = client
    seed_vectors(core)
    from backend.people_review import reevaluate, reevaluate_current
    reevaluate()
    before = c.get('/api/people/suggestions').json()
    retries = []
    def progress(phase, *args):
        if 'retry' in phase:
            retries.append(phase)
        if phase == 'Saving suggestions':
            with core.db() as db:
                db.execute("INSERT INTO actions(description,previous) VALUES('fixture changed','{}')")
    with pytest.raises(HTTPException) as error:
        reevaluate_current(progress)
    assert error.value.status_code == 409
    assert len(retries) == 2
    assert c.get('/api/people/suggestions').json() == before


@pytest.mark.parametrize('status,detail', [(409, 'Another failure'), (503, 'Storage unavailable')])
def test_retry_does_not_swallow_unrelated_errors(monkeypatch, status, detail):
    from backend import people_review
    calls = []
    def fail(**kwargs):
        calls.append(1)
        raise HTTPException(status, detail)
    monkeypatch.setattr(people_review, 'reevaluate', fail)
    with pytest.raises(HTTPException) as error:
        people_review.reevaluate_current()
    assert error.value.status_code == status
    assert calls == [1]
