import json
import time

import pytest

from test_catalogue import client


def seed(core, count=5000):
    with core.db() as db:
        db.execute("INSERT INTO people(id) VALUES(3)")
        db.executemany("INSERT INTO faces(id,media_id,person_id,status,embedding) VALUES(?,'0',3,'suggested',?)",
                       [(f'batch-{i}', b'x' * 512) for i in range(count)])
        db.executemany("INSERT INTO face_suggestions VALUES(?,?,0.9,0.3)",
                       [(f'batch-{i}', 1 + i % 2) for i in range(count)])
        db.executemany("INSERT INTO unknown_faces VALUES(?)", [(f'batch-{i}',) for i in range(count)])
        db.executemany("INSERT INTO high_confidence_faces VALUES(?)", [(f'batch-{i}',) for i in range(count)])
        db.execute("INSERT INTO face_rejections VALUES('batch-0',2)")
        db.execute("INSERT INTO review_approvals(face_id,person_id,created) VALUES('batch-0',2,'2020-01-01')")
    return {'matches': [{'face_id': f'batch-{i}', 'person_id': 1 + i % 2, 'source_person_id': 3} for i in range(count)]}


def test_5000_assignments_one_transaction_and_undo(client, monkeypatch):
    c, core = client
    body = seed(core)
    from backend import bulk_review, people_review
    original = bulk_review.db
    traces = []
    def traced_db():
        db = original()
        db.set_trace_callback(traces.append)
        return db
    monkeypatch.setattr(bulk_review, 'db', traced_db)
    monkeypatch.setattr(people_review, 'vector', lambda _: pytest.fail('Approval must not evaluate embeddings'))
    started = time.perf_counter()
    result = c.post('/api/people/approve-suggestions', json=body)
    elapsed = time.perf_counter() - started
    assert result.status_code == 200, result.text
    assert result.json()['approved'] == 5000
    assert sum(sql == 'COMMIT' for sql in traces) == 1
    assert not any('embedding' in sql for sql in traces)
    print(f'5000 approvals: {elapsed:.3f}s; one transaction, no embedding reads')
    with core.db() as db:
        assert db.execute("SELECT count(*) FROM faces WHERE status='manual'").fetchone()[0] == 5000
        assert db.execute('SELECT count(*) FROM face_suggestions').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM high_confidence_faces').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM unknown_faces').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM review_approvals').fetchone()[0] == 5000
        assert db.execute('SELECT count(*) FROM actions').fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM face_rejections WHERE person_id=3').fetchone()[0] == 5000
        # Scanner work after approval must survive undo.
        db.execute("INSERT INTO faces(id,media_id) VALUES('unrelated','1')")
        db.execute("INSERT INTO unknown_faces VALUES('unrelated')")
        db.execute("INSERT INTO face_rejections VALUES('unrelated',2)")
        db.execute("INSERT INTO face_suggestions VALUES('unrelated',1,0.8,0.2)")
    started = time.perf_counter()
    assert c.post('/api/undo').status_code == 200
    print(f'5000 undo: {time.perf_counter()-started:.3f}s')
    with core.db() as db:
        assert db.execute("SELECT count(*) FROM faces WHERE person_id=3 AND status='suggested'").fetchone()[0] == 5000
        assert db.execute('SELECT count(*) FROM unknown_faces').fetchone()[0] == 5001
        assert db.execute('SELECT count(*) FROM face_suggestions').fetchone()[0] == 5001
        assert db.execute('SELECT count(*) FROM high_confidence_faces').fetchone()[0] == 5000
        assert db.execute('SELECT count(*) FROM face_rejections').fetchone()[0] == 2
        assert tuple(db.execute('SELECT person_id,created FROM review_approvals').fetchone()) == (2, '2020-01-01')
    # Undo restores exactly the reviewed suggestions, so reapproval is possible.
    assert c.post('/api/people/approve-suggestions', json=body).status_code == 200


@pytest.mark.parametrize('change', ['target', 'assigned', 'dismissed', 'hidden', 'pending', 'rejected', 'removed'])
def test_stale_batch_is_atomic(client, change):
    c, core = client
    body = seed(core, 2)
    with core.db() as db:
        if change == 'target': db.execute("UPDATE face_suggestions SET person_id=1 WHERE face_id='batch-1'")
        elif change == 'assigned': db.execute("UPDATE faces SET person_id=1,status='manual' WHERE id='batch-1'")
        elif change == 'dismissed': db.execute("UPDATE faces SET status='dismissed' WHERE id='batch-1'")
        elif change == 'pending': db.execute("UPDATE media SET status='pending' WHERE id='0'")
        elif change == 'rejected': db.execute("INSERT INTO face_rejections VALUES('batch-1',2)")
        elif change == 'removed': db.execute("DELETE FROM face_suggestions WHERE face_id='batch-1'")
        elif change == 'hidden':
            db.execute("INSERT INTO library_databases(id,root,alias,layout,visible) VALUES('hidden','Z:/hidden','Hidden','single',0)")
            db.execute("UPDATE media SET database_id='hidden' WHERE id='0'")
    result = c.post('/api/people/approve-suggestions', json=body)
    assert result.status_code == 409, result.text
    with core.db() as db:
        assert db.execute("SELECT person_id FROM faces WHERE id='batch-0'").fetchone()[0] == 3
        assert db.execute('SELECT count(*) FROM actions').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM unknown_faces').fetchone()[0] == 2


def test_duplicate_and_retry_do_not_duplicate_actions(client):
    c, core = client
    body = seed(core, 2)
    assert c.post('/api/people/approve-suggestions', json={'matches': [body['matches'][0]] * 2}).status_code == 422
    assert c.post('/api/people/approve-suggestions', json=body).status_code == 200
    assert c.post('/api/people/approve-suggestions', json=body).status_code == 409
    with core.db() as db:
        assert db.execute('SELECT count(*) FROM actions').fetchone()[0] == 1


def test_write_failure_rolls_back_entire_batch(client):
    c, core = client
    body = seed(core, 2)
    with core.db() as db:
        db.execute("CREATE TRIGGER fail_batch BEFORE UPDATE ON faces WHEN NEW.id='batch-1' BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
    c.raise_server_exceptions = False
    assert c.post('/api/people/approve-suggestions', json=body).status_code >= 500
    with core.db() as db:
        assert db.execute("SELECT count(*) FROM faces WHERE person_id=3").fetchone()[0] == 2
        assert db.execute('SELECT count(*) FROM actions').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM face_suggestions').fetchone()[0] == 2
        assert db.execute('SELECT count(*) FROM unknown_faces').fetchone()[0] == 2
        assert db.execute('SELECT count(*) FROM high_confidence_faces').fetchone()[0] == 2
