import pytest
from test_catalogue import client
from test_bulk_review import seed


def test_5000_rejections_one_transaction_preserve_faces_and_scoped_undo(client, monkeypatch):
    api, core = client
    body = seed(core)
    from backend import bulk_review
    with core.db() as db:
        db.execute("INSERT INTO people(id,name) VALUES(4,'Other')")
        db.execute("INSERT INTO faces(id,media_id,person_id,status) VALUES('neighbour','1',3,'suggested'),('other','1',3,'suggested')")
        db.execute("INSERT INTO face_suggestions VALUES('neighbour',1,.9,.3),('other',4,.9,.3)")
        db.execute("INSERT INTO high_confidence_faces VALUES('neighbour'),('other')")
        before = [tuple(row) for row in db.execute('SELECT * FROM faces ORDER BY id')]
    original, traces = bulk_review.db, []
    def traced():
        db = original()
        db.set_trace_callback(traces.append)
        return db
    monkeypatch.setattr(bulk_review, 'db', traced)
    result = api.post('/api/people/reject-suggestions', json=body)
    assert result.status_code == 200, result.text
    assert result.json()['rejected'] == 5000
    assert result.json()['confidence_invalidated_for'] == [1, 2]
    assert sum(sql == 'COMMIT' for sql in traces) == 1
    assert not any('embedding' in sql for sql in traces)
    with core.db() as db:
        assert [tuple(row) for row in db.execute('SELECT * FROM faces ORDER BY id')] == before
        assert db.execute('SELECT count(*) FROM face_rejections').fetchone()[0] == 5001
        assert db.execute('SELECT count(*) FROM face_suggestions').fetchone()[0] == 2
        assert [row[0] for row in db.execute('SELECT face_id FROM high_confidence_faces')] == ['other']
        assert db.execute('SELECT count(*) FROM unknown_faces').fetchone()[0] == 5000
        assert db.execute('SELECT count(*) FROM review_approvals').fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM actions').fetchone()[0] == 1
        db.execute("INSERT INTO face_rejections VALUES('other',2)")
    assert api.post('/api/undo').status_code == 200
    with core.db() as db:
        assert [tuple(row) for row in db.execute('SELECT * FROM faces ORDER BY id')] == before
        assert db.execute('SELECT count(*) FROM face_suggestions').fetchone()[0] == 5002
        assert db.execute('SELECT count(*) FROM high_confidence_faces').fetchone()[0] == 5001
        assert db.execute('SELECT count(*) FROM face_rejections').fetchone()[0] == 2
        assert db.execute("SELECT 1 FROM face_rejections WHERE face_id='other' AND person_id=2").fetchone()
    assert api.post('/api/people/reject-suggestions', json=body).status_code == 200


@pytest.mark.parametrize('change', ['target', 'assigned', 'source', 'dismissed', 'hidden', 'pending', 'rejected', 'removed'])
def test_stale_rejection_batch_is_atomic(client, change):
    api, core = client
    body = seed(core, 2)
    with core.db() as db:
        if change == 'target': db.execute("UPDATE face_suggestions SET person_id=1 WHERE face_id='batch-1'")
        elif change == 'assigned': db.execute("UPDATE faces SET person_id=1,status='manual' WHERE id='batch-1'")
        elif change == 'source': db.execute("UPDATE faces SET person_id=NULL WHERE id='batch-1'")
        elif change == 'dismissed': db.execute("UPDATE faces SET status='dismissed' WHERE id='batch-1'")
        elif change == 'pending': db.execute("UPDATE media SET status='pending' WHERE id='0'")
        elif change == 'rejected': db.execute("INSERT INTO face_rejections VALUES('batch-1',2)")
        elif change == 'removed': db.execute("DELETE FROM face_suggestions WHERE face_id='batch-1'")
        elif change == 'hidden':
            db.execute("INSERT INTO library_databases(id,root,alias,layout,visible) VALUES('hidden','Z:/hidden','Hidden','single',0)")
            db.execute("UPDATE media SET database_id='hidden' WHERE id='0'")
        before = [tuple(row) for row in db.execute('SELECT * FROM face_rejections ORDER BY face_id,person_id')]
    result = api.post('/api/people/reject-suggestions', json=body)
    assert result.status_code == 409, result.text
    with core.db() as db:
        assert db.execute('SELECT count(*) FROM actions').fetchone()[0] == 0
        assert [tuple(row) for row in db.execute('SELECT * FROM face_rejections ORDER BY face_id,person_id')] == before


def test_duplicate_and_empty_rejection_selection_are_rejected(client):
    api, core = client
    body = seed(core, 1)
    assert api.post('/api/people/reject-suggestions', json={'matches': []}).status_code == 422
    assert api.post('/api/people/reject-suggestions', json={'matches': body['matches'] * 2}).status_code == 422
    with core.db() as db:
        assert db.execute('SELECT count(*) FROM actions').fetchone()[0] == 0
