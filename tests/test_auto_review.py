import json
import sqlite3

import numpy as np
import pytest

from test_catalogue import client
from test_people_jobs import fake_worker,wait


def chain(core):
    def vector(angle):
        value=np.zeros(128,np.float32)
        value[0]=np.cos(np.deg2rad(angle));value[1]=np.sin(np.deg2rad(angle))
        return value.tobytes()
    other=np.zeros(128,np.float32);other[2]=1
    lower=np.zeros(128,np.float32);lower[0]=.6;lower[3]=.8
    with core.db() as db:
        db.execute("UPDATE faces SET embedding=?,status='manual' WHERE person_id=1",(vector(0),))
        db.execute("UPDATE faces SET embedding=?,status='manual' WHERE person_id=2",(other.tobytes(),))
        for mid in ('3','4','5','6'):
            db.execute("INSERT INTO media(id,path,name,kind,status) VALUES(?,?,?,'photo','ready')",(mid,'fixture-'+mid+'.jpg',mid+'.jpg'))
        for fid,mid,embedding in [('bridge1','2',vector(30)),('bridge2','3',vector(30)),('later','4',vector(60)),('lower','5',lower.tobytes())]:
            db.execute("INSERT INTO faces(id,media_id,embedding,status) VALUES(?,?,?,'suggested')",(fid,mid,embedding))
            db.execute("INSERT INTO unknown_faces VALUES(?)",(fid,))
    from backend.people_review import reevaluate
    reevaluate()


def start_fake(c,monkeypatch):
    jobs,calls=fake_worker(monkeypatch)
    response=c.post('/api/people/operations/auto-approve')
    assert response.status_code==202,response.text
    return jobs,response.json(),calls


def test_real_worker_repeats_using_new_references_then_stops(client):
    c,core=client
    chain(core)
    before=c.get('/api/people/suggestions').json()
    assert {r['face_id'] for r in before if r['confidence']=='high'}=={'bridge1','bridge2'}
    response=c.post('/api/people/operations/auto-approve')
    assert response.status_code==202,response.text
    state=wait(c,response.json()['id'])
    assert state['state']=='completed',state
    assert state['kind']=='auto-approve'
    assert state['approved_total']==3
    assert state['rounds_completed']==2
    assert state['result']['stop_reason']=='no-high-confidence'
    assert state['review_revision']==4
    assert {r['face_id'] for r in c.get('/api/people/suggestions').json()}=={'lower'}
    with core.db() as db:
        assert db.execute("SELECT count(*) FROM faces WHERE id IN ('bridge1','bridge2','later') AND person_id=1 AND status='manual'").fetchone()[0]==3
        assert db.execute("SELECT person_id FROM faces WHERE id='lower'").fetchone()[0] is None
        assert db.execute('SELECT count(*) FROM review_approvals').fetchone()[0]==3
        actions=db.execute('SELECT description,previous FROM actions ORDER BY id').fetchall()
        assert len(actions)==2
        assert [len(json.loads(a['previous'])['faces']) for a in actions]==[2,1]
    # Each automatic round has the same reversible catalogue changes as Approve all.
    assert c.post('/api/undo').status_code==200
    with core.db() as db:
        assert db.execute("SELECT person_id FROM faces WHERE id='later'").fetchone()[0] is None
        assert db.execute("SELECT person_id FROM faces WHERE id='bridge1'").fetchone()[0]==1
    assert c.post('/api/undo').status_code==200
    with core.db() as db:
        assert db.execute("SELECT count(*) FROM faces WHERE id IN ('bridge1','bridge2','later') AND person_id IS NULL").fetchone()[0]==3
        assert db.execute("SELECT person_id FROM faces WHERE id='a'").fetchone()[0]==1


def test_no_high_confidence_finishes_without_reevaluation(client,monkeypatch):
    c,core=client
    jobs,state,_=start_fake(c,monkeypatch)
    from backend import people_review
    monkeypatch.setattr(people_review,'reevaluate',lambda **kw:pytest.fail('An empty high-confidence queue ends the loop'))
    jobs.work(state['id'])
    result=c.get('/api/people/operations/current').json()
    assert result['state']=='completed'
    assert result['approved_total']==result['rounds_completed']==0


def test_stop_after_commit_preserves_counts_and_skips_next_matching(client,monkeypatch):
    c,core=client
    chain(core)
    jobs,state,_=start_fake(c,monkeypatch)
    from backend import automatic_review,people_review
    apply=automatic_review.apply_batch
    def stop_after_commit(*args,**kwargs):
        result=apply(*args,**kwargs)
        (jobs.folder()/(state['id']+'.cancel')).touch()
        return result
    monkeypatch.setattr(automatic_review,'apply_batch',stop_after_commit)
    monkeypatch.setattr(people_review,'reevaluate',lambda **kw:pytest.fail('Stop must prevent the next matching pass'))
    jobs.work(state['id'])
    result=c.get('/api/people/operations/current').json()
    assert result['state']=='cancelled',result
    assert result['approved_total']==2 and result['rounds_completed']==1
    with core.db() as db:
        assert db.execute("SELECT count(*) FROM faces WHERE id LIKE 'bridge%' AND person_id=1").fetchone()[0]==2
        assert db.execute("SELECT person_id FROM faces WHERE id='later'").fetchone()[0] is None
        assert db.execute('SELECT count(*) FROM actions').fetchone()[0]==1


def test_stop_before_commit_rolls_back_whole_batch(client,monkeypatch):
    c,core=client
    chain(core)
    jobs,state,_=start_fake(c,monkeypatch)
    from backend import automatic_review
    apply=automatic_review.apply_batch
    def interrupt(body,**kwargs):
        check=kwargs['before_commit'];calls=0
        def stop():
            nonlocal calls
            calls+=1
            if calls==2:(jobs.folder()/(state['id']+'.cancel')).touch()
            check()
        return apply(body,**{**kwargs,'before_commit':stop})
    monkeypatch.setattr(automatic_review,'apply_batch',interrupt)
    jobs.work(state['id'])
    result=c.get('/api/people/operations/current').json()
    assert result['state']=='cancelled',result
    assert result['approved_total']==0
    with core.db() as db:
        assert db.execute("SELECT count(*) FROM faces WHERE id LIKE 'bridge%' AND person_id IS NULL").fetchone()[0]==2
        assert db.execute('SELECT count(*) FROM actions').fetchone()[0]==0
        assert db.execute('SELECT count(*) FROM face_suggestions').fetchone()[0]==3


def test_stop_between_batches_preserves_partial_round(client,monkeypatch):
    c,core=client
    chain(core)
    jobs,state,_=start_fake(c,monkeypatch)
    from backend import automatic_review
    monkeypatch.setattr(automatic_review,'BATCH_SIZE',1)
    apply=automatic_review.apply_batch
    def stop(*args,**kwargs):
        result=apply(*args,**kwargs)
        (jobs.folder()/(state['id']+'.cancel')).touch()
        return result
    monkeypatch.setattr(automatic_review,'apply_batch',stop)
    jobs.work(state['id'])
    result=c.get('/api/people/operations/current').json()
    assert result['state']=='cancelled'
    assert result['approved_total']==1 and result['rounds_completed']==0
    assert result['round_approved']==1 and result['round_total']==2
    with core.db() as db:
        assert db.execute('SELECT count(*) FROM review_approvals').fetchone()[0]==1


def test_downgraded_match_cannot_be_auto_approved(client,monkeypatch):
    c,core=client
    chain(core)
    jobs,state,_=start_fake(c,monkeypatch)
    from backend import automatic_review
    apply=automatic_review.apply_batch
    def downgrade(body,**kwargs):
        with core.db() as db:db.execute("DELETE FROM high_confidence_faces WHERE face_id='bridge1'")
        return apply(body,**kwargs)
    monkeypatch.setattr(automatic_review,'apply_batch',downgrade)
    jobs.work(state['id'])
    result=c.get('/api/people/operations/current').json()
    assert result['state']=='failed'
    assert result['approved_total']==0
    with core.db() as db:assert db.execute('SELECT count(*) FROM actions').fetchone()[0]==0


def test_hidden_rejected_and_dismissed_are_never_selected(client):
    c,core=client
    chain(core)
    with core.db() as db:
        db.execute("INSERT INTO library_databases(id,root,alias,layout,visible) VALUES('hidden','Z:/fixture','Hidden','single',0)")
        db.execute("UPDATE media SET database_id='hidden' WHERE id='6'")
        for fid,mid,status in [('hidden','6','suggested'),('rejected','2','suggested'),('dismissed','2','dismissed')]:
            db.execute("INSERT INTO faces(id,media_id,status) VALUES(?,?,?)",(fid,mid,status))
            db.execute("INSERT INTO face_suggestions VALUES(?,1,.99,.5)",(fid,))
            db.execute("INSERT INTO high_confidence_faces VALUES(?)",(fid,))
        db.execute("INSERT INTO face_rejections VALUES('rejected',1)")
    from backend.automatic_review import selection
    assert {row['face_id'] for row in selection()}=={'bridge1','bridge2'}


def test_duplicate_start_and_other_operation_conflict(client,monkeypatch):
    c,core=client
    jobs,state,calls=start_fake(c,monkeypatch)
    assert c.post('/api/people/operations/auto-approve').json()['id']==state['id']
    assert len(calls)==1
    assert c.post('/api/people/operations/reevaluate').status_code==409
    assert c.post('/api/people/operations/'+state['id']+'/cancel').json()['stop_requested']
    assert c.get('/api/people/operations/current').json()['stop_requested']
    jobs.work(state['id'])
    assert c.get('/api/people/operations/current').json()['state']=='cancelled'


def test_storage_error_after_approval_retains_saved_round(client,monkeypatch):
    c,core=client
    chain(core)
    jobs,state,_=start_fake(c,monkeypatch)
    from backend import people_review
    def fail(**kw):raise sqlite3.OperationalError('disk I/O error')
    monkeypatch.setattr(people_review,'reevaluate',fail)
    jobs.work(state['id'])
    result=c.get('/api/people/operations/current').json()
    assert result['state']=='failed'
    assert result['approved_total']==2
    with core.db() as db:
        assert db.execute('SELECT count(*) FROM review_approvals').fetchone()[0]==2
        assert db.execute("SELECT person_id FROM faces WHERE id='later'").fetchone()[0] is None


def test_sync_matching_honors_stop_mid_pass(client,monkeypatch):
    c,core=client
    from backend import sync_service as sync,people_review
    def stop(*args):raise sync.SyncStopped('cancel')
    checked=[]
    def matching(progress):
        monkeypatch.setattr(sync,'check_control',stop)
        progress('Comparing faces',1,100,'comparisons')
        checked.append('should not finish')
    monkeypatch.setattr(people_review,'reevaluate',matching)
    with pytest.raises(sync.SyncStopped):sync.auto_assign_until_stable()
    assert not checked


def test_sync_matching_reports_progress_and_stops_before_saving(client,monkeypatch):
    c,core=client
    from backend import sync_service as sync,people_review
    with sync.store() as db:
        db.execute("INSERT INTO runs VALUES('face-progress',?,NULL,'running','manual','{}',NULL)",(sync.now().isoformat(),))
    sync.worker_context.run_id='face-progress'
    sync.worker_context.pending_progress={}
    sync.worker_context.last_progress=0
    def matching(progress):
        progress('Comparing faces',25,100,'comparisons')
        live=sync.status()['runs'][0]['progress']
        assert live['processed']==25 and live['total']==100
        assert live['phase']=='Matching faces: Comparing faces'
        assert live['unit']=='comparisons'
        sync.control_run('face-progress','cancel')
        progress('Saving suggestions')
        pytest.fail('Stop must prevent publishing these matches')
    monkeypatch.setattr(people_review,'reevaluate',matching)
    try:
        with pytest.raises(sync.SyncStopped):sync.auto_assign_until_stable()
    finally:
        sync.worker_context.run_id=None
        sync.worker_context.pending_progress={}
        sync.live_progress.pop('face-progress',None)


def test_windows_progress_read_retries_transient_file_lock(client,monkeypatch):
    c,core=client
    jobs,state,_=start_fake(c,monkeypatch)
    from pathlib import Path
    original=Path.read_text
    calls=0
    def busy(path,*args,**kwargs):
        nonlocal calls
        if path==jobs.job_path(state['id']):
            calls+=1
            if calls==1:raise PermissionError('Fixture atomic replace in progress')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'read_text',busy)
    response=c.get('/api/people/operations/'+state['id'])
    assert response.status_code==200,response.text
    assert response.json()['state']=='queued'
    assert calls==2


def test_progress_access_failure_does_not_report_disconnected_catalogue(client,monkeypatch):
    c,core=client
    jobs,state,_=start_fake(c,monkeypatch)
    from pathlib import Path
    original=Path.read_text
    def busy(path,*args,**kwargs):
        if path==jobs.job_path(state['id']):raise PermissionError('Fixture locked progress')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'read_text',busy)
    response=c.get('/api/people/operations/'+state['id'])
    assert response.status_code==503
    assert 'progress is temporarily unavailable' in response.json()['detail']
    assert c.get('/api/health').json()['storage']=='available'
