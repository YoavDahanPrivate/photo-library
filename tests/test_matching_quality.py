import json
import numpy as np
import pytest

from tests.test_catalogue import client
from tests.test_search_people import seed_vectors


def test_cache_reuses_comparisons_and_recomputes_changed_references(client):
    _,core=client
    seed_vectors(core)
    from backend.people_review import reevaluate
    first=reevaluate()
    assert first['comparisons']>0 and first['reused_comparisons']==0
    second=reevaluate()
    assert second['comparisons']==0 and second['reused_comparisons']==first['comparisons']
    with core.db() as c:
        saved=[tuple(row) for row in c.execute('SELECT * FROM face_suggestions')]
        c.execute("UPDATE faces SET embedding=? WHERE id='b'", (np.eye(128,dtype=np.float32)[2].tobytes(),))
    changed=reevaluate()
    assert changed['comparisons']>0 and changed['reused_comparisons']>0
    with core.db() as c:
        assert [tuple(row) for row in c.execute('SELECT * FROM face_suggestions')]==saved
        assert c.execute('SELECT support FROM face_match_evidence').fetchone()[0]==2


def test_cache_invalidation_on_changed_candidate_and_corrupt_cache(client):
    _,core=client
    seed_vectors(core)
    from backend.people_review import reevaluate
    reevaluate()
    with core.db() as c:
        c.execute("UPDATE faces SET embedding=? WHERE id='candidate'", (np.eye(128,dtype=np.float32)[10].tobytes(),))
    changed=reevaluate()
    assert changed['comparisons']>0 and changed['suggestions']==0
    (core.DATA/'face-matching'/'comparisons.npz').write_bytes(b'interrupted cache write')
    assert reevaluate()['suggestions']==0


def test_removing_references_cannot_keep_cached_high_confidence(client):
    _,core=client
    seed_vectors(core)
    from backend.people_review import reevaluate
    assert reevaluate()['suggestions']==1
    with core.db() as c:
        c.execute("UPDATE faces SET status='dismissed' WHERE id IN ('a','c')")
    assert reevaluate()['suggestions']==0


def test_calibration_requires_separate_validation_and_rejects_false_matches():
    from backend.face_calibration import propose
    tuning=[dict(actual=1,predicted=1,score=.65,margin=.1,support=2) for _ in range(40)]
    validation=[dict(actual=1,predicted=1,score=.65,margin=.1,support=2) for _ in range(40)]
    negative=[dict(actual=2,predicted=2,score=.8,margin=.3,support=2) for _ in range(120)]
    good=propose(tuning+negative,validation+negative,1)
    assert good['eligible'] and good['validation']['correct']==40
    assert good['baseline']['correct']==0 and good['proposed']['score']<=.65
    # No second threshold search is allowed after seeing validation mistakes.
    bad=propose(tuning+negative,validation+negative+[dict(actual=None,predicted=1,score=.69,margin=.11,support=2)],1)
    assert not bad['eligible'] and bad['validation']['mistakes']==1
    assert not propose(tuning,validation,1)['eligible']


def test_analysis_never_assigns_faces_or_enables_rules_and_can_stop(client):
    api,core=client
    seed_vectors(core)
    from backend.face_calibration import analyze
    with core.db() as c:
        before=[tuple(row) for row in c.execute('SELECT * FROM faces')]
    report=analyze()
    assert report['eligible_people']==0
    current=api.get('/api/people/calibration').json()
    assert current['active_id'] is None and current['report']['id']==report['profile_id']
    assert 'anchors' not in current['report']
    assert api.post('/api/people/calibration/apply',json={'profile_id':report['profile_id'],'confirm':True}).status_code==409
    with core.db() as c:
        assert [tuple(row) for row in c.execute('SELECT * FROM faces')]==before
    def stopped(*args):raise RuntimeError('Stop fixture')
    with pytest.raises(RuntimeError,match='Stop fixture'):analyze(progress=stopped)
    assert api.get('/api/people/calibration').json()['report']['id']==report['profile_id']


def test_profile_needs_confirmation_rejects_stale_report_and_preserves_annotations(client):
    api,core=client
    seed_vectors(core)
    from backend.face_calibration import revision,token
    from backend.people_review import reevaluate
    with core.db() as c:
        row=dict(c.execute("SELECT * FROM faces WHERE id='a'").fetchone())
        report=dict(people=[dict(person_id=1,eligible=True,proposed=dict(score=.6,margin=.08,support=2))],anchors={'a':token(row)},eligible_people=1)
        c.execute('INSERT INTO face_match_profiles(id,report,revision) VALUES(?,?,?)',('fixture',json.dumps(report),revision(c)))
    assert api.post('/api/people/calibration/apply',json={'profile_id':'fixture'}).status_code==422
    assert api.post('/api/people/calibration/apply',json={'profile_id':'fixture','confirm':True}).status_code==200
    assert api.get('/api/people/calibration').json()['active_id']=='fixture'
    assert reevaluate()['profile_warning'] is None
    with core.db() as c:
        c.execute("UPDATE faces SET person_id=2 WHERE id='a'")
        c.execute("INSERT INTO actions(description,previous) VALUES('correction','{}')")
    assert reevaluate()['profile_warning']
    assert api.post('/api/people/calibration/apply',json={'profile_id':'fixture','confirm':True}).status_code==409
    assert api.post('/api/people/calibration/reset',json={}).status_code==200
    assert api.get('/api/people/calibration').json()['active_id'] is None


def test_calibration_worker_has_progress_and_does_not_approve(client):
    api,core=client
    seed_vectors(core)
    from tests.test_people_jobs import wait
    result=api.post('/api/people/operations/calibrate')
    assert result.status_code==202
    state=wait(api,result.json()['id'])
    assert state['state']=='completed' and state['kind']=='calibrate'
    assert 'profile_id' in state['result']
    with core.db() as c:
        assert c.execute('SELECT count(*) FROM review_approvals').fetchone()[0]==0


def test_profile_change_during_matching_cannot_publish_old_high_flags(client):
    _,core=client
    seed_vectors(core)
    from backend.people_review import reevaluate
    from fastapi import HTTPException
    changed=False
    def progress(phase,*args):
        nonlocal changed
        if phase=='Comparing faces' and not changed:
            changed=True
            with core.db() as c:
                c.execute("INSERT INTO face_match_profiles(id,report,revision,active) VALUES('changed','{}','[]',1)")
    with pytest.raises(HTTPException,match='409'):
        reevaluate(progress=progress)
    with core.db() as c:
        assert c.execute('SELECT count(*) FROM face_suggestions').fetchone()[0]==0


def test_partial_cache_metadata_falls_back_to_exact_recomputation(client):
    _,core=client
    seed_vectors(core)
    from backend.people_review import reevaluate
    from backend.face_match_cache import VERSION
    assert reevaluate()['suggestions']==1
    path=core.DATA/'face-matching'/'comparisons.npz'
    np.savez_compressed(path,metadata=np.asarray(json.dumps(dict(version=VERSION))),best=np.zeros((1,1)),support=np.zeros((1,1)))
    result=reevaluate()
    assert result['comparisons']>0 and result['suggestions']==1
