import json
import sqlite3
import time

import pytest

from test_catalogue import client
from test_search_people import seed_vectors


def wait(c, identity):
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        response=c.get('/api/people/operations/'+identity)
        assert response.status_code==200, response.text
        state=response.json()
        if state['state'] not in ('queued','running'):
            return state
        time.sleep(.05)
    pytest.fail('Worker did not finish')


def fake_worker(monkeypatch):
    from backend import people_jobs
    calls=[]
    class Process:
        def __init__(self,*args,**kwargs): calls.append((args,kwargs))
        def poll(self): return None
    monkeypatch.setattr(people_jobs.subprocess,'Popen',Process)
    return people_jobs,calls


def test_real_worker_and_reloadable_status(client):
    c,core=client
    seed_vectors(core)
    started=c.post('/api/people/operations/reevaluate')
    assert started.status_code==202,started.text
    identity=started.json()['id']
    assert c.get('/api/status').status_code==200
    state=wait(c,identity)
    assert state['state']=='completed',state
    assert state['result']['suggestions']==1
    assert state['result']['assigned']==0
    assert c.get('/api/people/operations/current').json()['id']==identity
    with core.db() as db:
        assert db.execute("SELECT person_id FROM faces WHERE id='candidate'").fetchone()[0] is None
    assert c.get('/api/people/suggestions').json()[0]['confidence']=='high'


def test_progress_counts_real_comparisons_and_preserves_algorithm(client):
    c,core=client
    seed_vectors(core)
    from backend.people_review import reevaluate
    progress=[]
    result=reevaluate(progress=lambda *values:progress.append(values))
    scoring=[p for p in progress if p[0]=='Comparing faces']
    assert scoring[0][1]==0
    assert scoring[-1][1]==scoring[-1][2]>0
    assert [p[1] for p in scoring]==sorted(p[1] for p in scoring)
    assert progress[-1][0]=='Saving suggestions'
    assert result['suggestions']==1


def test_duplicate_start_and_cancel_preserve_queue(client,monkeypatch):
    c,core=client
    seed_vectors(core)
    from backend.people_review import reevaluate
    reevaluate()
    before=c.get('/api/people/suggestions').json()
    jobs,calls=fake_worker(monkeypatch)
    first=c.post('/api/people/operations/reevaluate').json()
    assert c.post('/api/people/operations/reevaluate').json()['id']==first['id']
    assert len(calls)==1
    assert c.post('/api/people/operations/'+first['id']+'/cancel').status_code==200
    jobs.work(first['id'])
    assert c.get('/api/people/operations/current').json()['state']=='cancelled'
    assert c.get('/api/people/suggestions').json()==before


def test_storage_failure_is_visible_and_does_not_clear_suggestions(client,monkeypatch):
    c,core=client
    seed_vectors(core)
    from backend import people_review
    people_review.reevaluate()
    before=c.get('/api/people/suggestions').json()
    jobs,_=fake_worker(monkeypatch)
    state=c.post('/api/people/operations/reevaluate').json()
    def broken(**kwargs): raise sqlite3.OperationalError('disk I/O error')
    monkeypatch.setattr(people_review,'reevaluate',broken)
    jobs.work(state['id'])
    state=c.get('/api/people/operations/current').json()
    assert state['state']=='failed'
    assert 'drive' in state['error']
    assert c.get('/api/people/suggestions').json()==before


def test_worker_exit_and_status_when_catalogue_offline(client,monkeypatch):
    c,core=client
    from backend import people_jobs as jobs,storage_runtime
    identity='f'*32
    state=dict(id=identity,state='running',pid=999999999,started_at=time.time(),updated_at=time.time(),phase='Comparing faces')
    jobs.write(jobs.job_path(identity),state)
    jobs.write(jobs.folder()/'current.json',{'id':identity})
    monkeypatch.setattr(jobs,'process_alive',lambda pid:False)
    monkeypatch.setattr(storage_runtime,'initialize',lambda *args,**kwargs:False)
    response=c.get('/api/people/operations/current')
    assert response.status_code==200,response.text
    assert response.json()['state']=='interrupted'
    assert c.get('/api/status').status_code==503
    assert c.get('/api/people/operations/not-a-job').status_code==404


def test_cancel_during_matching_keeps_existing_suggestions(client):
    c,core=client
    seed_vectors(core)
    from backend.people_jobs import Cancelled
    from backend.people_review import reevaluate
    reevaluate()
    before=c.get('/api/people/suggestions').json()
    def cancel(phase,*args):
        if phase=='Saving suggestions': raise Cancelled()
    with pytest.raises(Cancelled): reevaluate(progress=cancel)
    assert c.get('/api/people/suggestions').json()==before


def test_concurrent_correction_prevents_stale_publish(client):
    c,core=client
    seed_vectors(core)
    from fastapi import HTTPException
    from backend.people_review import reevaluate
    def correct(phase,*args):
        if phase=='Saving suggestions':
            with core.db() as db:
                db.execute("UPDATE faces SET person_id=2,status='manual' WHERE id='candidate'")
                db.execute("INSERT INTO actions(description,previous) VALUES('fixture correction','{}')")
    with pytest.raises(HTTPException) as error: reevaluate(progress=correct)
    assert error.value.status_code==409
    with core.db() as db:
        assert db.execute("SELECT person_id FROM faces WHERE id='candidate'").fetchone()[0]==2
        assert db.execute('SELECT count(*) FROM face_suggestions').fetchone()[0]==0


def test_progress_after_server_restart_does_not_signal_worker(client):
    import subprocess
    import sys
    c,core=client
    from backend import people_jobs as jobs
    process=subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)'])
    try:
        identity='e'*32
        state=dict(id=identity,state='running',pid=process.pid,started_at=time.time(),updated_at=time.time(),phase='Comparing faces')
        jobs.write(jobs.job_path(identity),state)
        assert jobs.process_alive(process.pid)
        assert c.get('/api/people/operations/'+identity).json()['state']=='running'
        assert process.poll() is None
    finally:
        process.terminate()
        process.wait(timeout=10)
