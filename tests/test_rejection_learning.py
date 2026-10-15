import math
import numpy as np
import pytest

from tests.test_catalogue import client
from tests.test_search_people import seed_vectors


def embedding(x, z, extra=0):
    value=np.zeros(128,dtype=np.float32)
    value[0],value[2],value[3]=x,z,extra
    return value/np.linalg.norm(value)


def seed(core):
    seed_vectors(core)
    values={
        'negative':embedding(.8,.6),
        'lookalike':embedding(.78,math.sqrt(1-.78**2)),
        'genuine':embedding(1,0),
        'borderline':embedding(.72,(.74-.8*.72)/.6,math.sqrt(1-.72**2-((.74-.8*.72)/.6)**2)),
    }
    with core.db() as c:
        c.execute("DELETE FROM faces WHERE id='candidate'")
        c.executemany("INSERT INTO faces(id,media_id,embedding) VALUES(?,'2',?)",[(identity,value.tobytes()) for identity,value in values.items()])
    return values


def suggestions(api):
    return {row['face_id']:row for row in api.get('/api/people/suggestions').json()}


def reject(api):
    response=api.post('/api/people/reject-suggestion',json={'face_id':'negative','person_id':1})
    assert response.status_code==200,response.text
    assert response.json()['learning_pending']


def test_rejection_learns_lookalikes_and_personal_separation_without_relabelling(client):
    api,core=client
    seed(core)
    from backend.people_review import reevaluate
    assert reevaluate()['suggestions']==4
    assert all(row['confidence']=='high' for row in suggestions(api).values())
    reject(api)
    # A worker may not automatically consume old high flags for this person.
    assert all(row['confidence']=='lower' for row in suggestions(api).values())
    from backend.automatic_review import selection
    assert selection()==[]
    with core.db() as c:
        before=[tuple(row) for row in c.execute('SELECT * FROM faces ORDER BY id')]
    result=reevaluate()
    assert result['rejection_suppressed']==1
    assert result['rejection_softened']==1
    assert result['rejection_examples']==1
    rows=suggestions(api)
    assert set(rows)=={'genuine','borderline'}
    assert rows['genuine']['confidence']=='high'
    assert rows['borderline']['confidence']=='lower'
    assert rows['borderline']['rejection_score']==pytest.approx(.74,abs=1e-6)
    assert rows['borderline']['rejection_floor']==pytest.approx(.78,abs=1e-6)
    assert rows['borderline']['score_cutoff']==rows['borderline']['rejection_floor']
    assert {row['face_id'] for row in selection()}=={'genuine'}
    with core.db() as c:
        assert [tuple(row) for row in c.execute('SELECT * FROM faces ORDER BY id')]==before
        assert c.execute('SELECT count(*) FROM review_approvals').fetchone()[0]==0


def test_rejection_undo_and_repeat_pass_do_not_reuse_stale_learning(client):
    api,core=client
    seed(core)
    from backend.people_review import reevaluate
    first=reevaluate()
    reject(api)
    learned=reevaluate()
    assert learned['comparisons']==0 and learned['reused_comparisons']==first['comparisons']
    assert 'lookalike' not in suggestions(api)
    assert reevaluate()['rejection_suppressed']==1
    assert api.post('/api/undo',json={}).status_code==200
    restored=reevaluate()
    assert restored['rejection_examples']==0 and restored['comparisons']==0
    assert suggestions(api)['lookalike']['confidence']=='high'
    with core.db() as c:
        assert c.execute('SELECT count(*) FROM face_rejection_evidence').fetchone()[0]==0


def test_later_correct_assignment_overrides_rejection_and_teaches_true_person(client):
    api,core=client
    seed(core)
    from backend.people_review import reevaluate
    reevaluate();reject(api);reevaluate()
    assert api.post('/api/faces/correct',json={'face_ids':['negative'],'action':'move','target':2}).status_code==200
    reevaluate()
    assert suggestions(api)['lookalike']['person_id']==2
    # An explicit reversal wins over the earlier rejection.
    assert api.post('/api/faces/correct',json={'face_ids':['negative'],'action':'move','target':1}).status_code==200
    reevaluate()
    assert suggestions(api)['lookalike']['person_id']==1
    with core.db() as c:
        assert c.execute("SELECT 1 FROM face_rejections WHERE face_id='negative' AND person_id=1").fetchone() is None


def test_rejected_lookalikes_cannot_reappear_as_group_hint(client):
    api,core=client
    seed(core)
    with core.db() as c:
        c.execute('INSERT INTO people(id) VALUES(3)')
        c.execute("UPDATE faces SET person_id=3 WHERE id='lookalike'")
    assert api.get('/api/people/3/match').json()['match']['person_id']==1
    from backend.people_review import reevaluate
    reevaluate();reject(api)
    assert api.get('/api/people/3/match').json()['match'] is None


def test_conflicting_rejection_never_blacklists_positive_neighbourhood(client):
    api,core=client
    seed_vectors(core)
    with core.db() as c:
        c.execute("INSERT INTO faces(id,media_id,embedding) SELECT 'copy','2',embedding FROM faces WHERE id='candidate'")
    from backend.people_review import reevaluate
    reevaluate()
    assert api.post('/api/people/reject-suggestion',json={'face_id':'candidate','person_id':1}).status_code==200
    result=reevaluate()
    assert result['rejection_conflicts']==1 and result['rejection_examples']==0
    assert 'candidate' not in suggestions(api)
    assert suggestions(api)['copy']['confidence']=='high'


def test_learning_is_scoped_to_rejected_person_and_unavailable_examples_are_ignored(client):
    api,core=client
    seed(core)
    with core.db() as c:
        c.execute("INSERT INTO faces(id,media_id,person_id,status,embedding) SELECT 'daniel-reference','1',2,'manual',embedding FROM faces WHERE id='b'")
        c.execute("INSERT INTO faces(id,media_id,embedding) VALUES('other','2',?)",(np.eye(128,dtype=np.float32)[1].tobytes(),))
    from backend.people_review import reevaluate
    reevaluate();reject(api)
    assert suggestions(api)['other']['confidence']=='high'
    reevaluate()
    assert suggestions(api)['other']['person_id']==2
    assert suggestions(api)['other']['confidence']=='high'
    with core.db() as c:c.execute("UPDATE faces SET status='dismissed' WHERE id='negative'")
    assert reevaluate()['rejection_examples']==0
    assert 'lookalike' in suggestions(api)


@pytest.mark.parametrize('phase',['Learning from rejected faces','Checking rejected lookalikes'])
def test_stop_during_learning_preserves_last_queue_and_evidence(client,phase):
    api,core=client
    seed(core)
    from backend.people_review import reevaluate
    reevaluate();reject(api);reevaluate()
    with core.db() as c:
        before={name:[tuple(row) for row in c.execute('SELECT * FROM '+name+' ORDER BY face_id')] for name in ('face_suggestions','face_match_evidence','face_rejection_evidence')}
    def stop(current,*args):
        if current==phase:raise RuntimeError('Stop fixture')
    with pytest.raises(RuntimeError,match='Stop fixture'):reevaluate(progress=stop)
    with core.db() as c:
        for name,rows in before.items():assert [tuple(row) for row in c.execute('SELECT * FROM '+name+' ORDER BY face_id')]==rows


def test_new_feedback_during_learning_cannot_publish_stale_suggestions(client):
    api,core=client
    seed(core)
    from backend.people_review import reevaluate
    from fastapi import HTTPException
    reevaluate();reject(api)
    changed=False
    def progress(phase,*args):
        nonlocal changed
        if phase=='Checking rejected lookalikes' and not changed:
            changed=True
            assert api.post('/api/people/reject-suggestion',json={'face_id':'borderline','person_id':1}).status_code==200
    with pytest.raises(HTTPException,match='409'):reevaluate(progress=progress)
    assert 'borderline' not in suggestions(api)
    assert 'lookalike' in suggestions(api) # Previous queue is retained, with high flags invalidated.


def test_migration_is_additive_and_only_demotes_legacy_high_flags_once(client):
    _,core=client
    seed(core)
    from backend.people_review import reevaluate
    from backend.face_calibration import migrate
    reevaluate()
    with core.db() as c:
        before=[tuple(row) for row in c.execute('SELECT * FROM faces ORDER BY id')]
        c.execute('DROP TABLE face_rejection_evidence')
        migrate(c)
        assert c.execute('SELECT count(*) FROM high_confidence_faces').fetchone()[0]==0
        assert c.execute('SELECT count(*) FROM face_suggestions').fetchone()[0]==4
        assert [tuple(row) for row in c.execute('SELECT * FROM faces ORDER BY id')]==before
        c.execute("INSERT INTO high_confidence_faces VALUES('genuine')")
        migrate(c)
        assert c.execute('SELECT count(*) FROM high_confidence_faces').fetchone()[0]==1
