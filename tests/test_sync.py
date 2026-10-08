import importlib, json, os, time
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pytest
from tests.test_catalogue import client

@pytest.fixture
def service(client):
    _,core=client
    from backend import sync_service as s
    for p in core.PHONES: (core.ROOT/p).mkdir(parents=True)
    return s,core

def stamp(s): return datetime.fromisoformat(s)
def test_calendar_month_end_weekly_off():
    from backend.sync_service import Settings,next_due
    utc=timezone.utc
    assert next_due(Settings(frequency="off"),datetime.now(utc)) is None
    setting=Settings(frequency="monthly",month_day=31,time="03:00",timezone="UTC")
    assert next_due(setting,datetime(2026,2,1,tzinfo=utc))=="2026-02-28T03:00:00+00:00"
    assert next_due(setting,datetime(2028,2,1,tzinfo=utc))=="2028-02-29T03:00:00+00:00"
    assert next_due(Settings(frequency="weekly",weekday=0,timezone="UTC"),datetime(2026,10,5,4,tzinfo=utc))=="2026-10-12T03:00:00+00:00"

def test_hourly_dst_and_exact_boundary():
    from backend.sync_service import Settings,next_due
    s=Settings(frequency="hourly",time="00:15",timezone="UTC")
    assert next_due(s,stamp("2026-10-04T10:15:00+00:00"))=="2026-10-04T11:15:00+00:00"
    daily=Settings(frequency="daily",time="02:30",timezone="America/New_York")
    assert next_due(daily,stamp("2026-03-08T05:00:00+00:00"))=="2026-03-08T07:30:00+00:00"
    fold=Settings(frequency="daily",time="01:30",timezone="America/New_York")
    assert next_due(fold,stamp("2026-11-01T06:00:00+00:00"))=="2026-11-02T06:30:00+00:00"

def test_settings_persist_and_validate(service,client):
    s,core=service; api,_=client
    state=api.get("/api/sync/status").json()
    assert state["settings"]["auto_assign"] is True
    assert state["settings"]["frequency"]=="daily"
    changed={**state["settings"],"frequency":"weekly","weekday":2,"auto_assign":False}
    assert api.put("/api/sync/settings",json=changed).status_code==200
    assert s.load_settings().auto_assign is False
    assert s.status()["settings"]==changed
    for field,value in [("frequency","yearly"),("month_day",32),("time","25:00"),("timezone","Mars/Nowhere")]:
        assert api.put("/api/sync/settings",json={**changed,field:value}).status_code==422

def test_overlap_with_full_scan(service):
    s,_=service
    with s.scan_lock():
        with pytest.raises(Exception) as error: s.start_run()
        assert error.value.status_code==409
    with s.scan_lock(): pass

def test_catchup_once_and_off(service,monkeypatch):
    s,_=service
    calls=[]
    def fake(reason):
        calls.append(reason)
        with s.store() as c:
            setting=s.load_settings()
            c.execute("UPDATE settings SET next_due=?",(s.next_due(setting,s.now()),))
        return {}
    monkeypatch.setattr(s,"start_run",fake)
    with s.store() as c: c.execute("UPDATE settings SET next_due='2020-01-01T00:00:00+00:00'")
    s.tick();s.tick()
    assert calls==["scheduled"]
    s.save_settings(s.Settings(frequency="off"))
    s.tick();assert calls==["scheduled"]

def make_file(core,name="one.jpg",content=b"photo"):
    p=core.ROOT/core.PHONES[0]/name
    p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(content)
    os.utime(p,(time.time()-120,time.time()-120))
    return p

def test_incremental_move_missing_restore_preserves_faces(service):
    s,core=service
    p=make_file(core)
    r=s.reconcile(s.inventory());assert r["added"]==1
    with core.db() as c:
        row=c.execute("SELECT * FROM media WHERE path=?",(str(p),)).fetchone()
        mid=row["id"]
        c.execute("UPDATE media SET status='ready',face_status='ready' WHERE id=?",(mid,))
        c.execute("INSERT INTO faces(id,media_id,person_id,status) VALUES('kept',?,1,'manual')",(mid,))
    assert s.reconcile(s.inventory())["added"]==0
    new=p.with_name("moved.jpg");p.rename(new)
    assert s.reconcile(s.inventory())["moved"]==1
    with core.db() as c:
        assert c.execute("SELECT id FROM media WHERE path=?",(str(new),)).fetchone()[0]==mid
    content=new.read_bytes();new.unlink()
    assert s.reconcile(s.inventory())["missing"]==1
    new.write_bytes(content);os.utime(new,(time.time()-120,time.time()-120))
    assert s.reconcile(s.inventory())["restored"]==1
    with core.db() as c:
        assert tuple(c.execute("SELECT person_id,status FROM faces WHERE id='kept'").fetchone())==(1,"manual")
        assert c.execute("SELECT status FROM media WHERE id=?",(mid,)).fetchone()[0]=="ready"

def test_changed_content_archives_corrections_not_original(service):
    s,core=service;p=make_file(core)
    s.reconcile(s.inventory())
    with core.db() as c:
        mid=c.execute("SELECT id FROM media WHERE path=?",(str(p),)).fetchone()[0]
        c.execute("INSERT INTO faces(id,media_id,person_id,status) VALUES('kept',?,1,'manual')",(mid,))
    p.write_bytes(b"replacement");os.utime(p,(time.time()-120,time.time()-120))
    assert s.reconcile(s.inventory())["changed"]==1
    assert p.read_bytes()==b"replacement"
    with core.db() as c:
        assert c.execute("SELECT status FROM media WHERE id=?",(mid,)).fetchone()[0]=="superseded"
        assert c.execute("SELECT person_id FROM faces WHERE id='kept'").fetchone()[0]==1
        assert c.execute("SELECT id FROM media WHERE path=?",(str(p),)).fetchone()[0]!=mid

def test_offline_root_does_not_mark_missing(service):
    s,core=service
    (core.ROOT/core.PHONES[1]).rmdir()
    with core.db() as c: before=[tuple(r) for r in c.execute("SELECT id,status FROM media")]
    with pytest.raises(RuntimeError,match="Source unavailable"):s.inventory()
    with core.db() as c: assert [tuple(r) for r in c.execute("SELECT id,status FROM media")]==before

def test_recent_copy_deferred_and_excluded_dirs(service):
    s,core=service
    p=make_file(core);os.utime(p,None)
    make_file(core,".dtrash/skip.jpg")
    assert len(s.inventory())==1
    r=s.reconcile(s.inventory())
    assert r["deferred"]==1 and r["added"]==0

def test_hash_change_race_is_not_reconciled(service,monkeypatch):
    s,core=service;p=make_file(core);files=s.inventory()
    p.write_bytes(b"changed during scan")
    with pytest.raises(RuntimeError):s.reconcile(files)
    with core.db() as c:assert not c.execute("SELECT 1 FROM media WHERE path=?",(str(p),)).fetchone()

def test_automatic_fixed_point_and_undo(service):
    s,core=service
    v=np.zeros(128,np.float32);v[0]=1
    with core.db() as c:
        c.execute("UPDATE faces SET embedding=?,status='manual' WHERE id IN ('a','c')",(v.tobytes(),))
        c.execute("INSERT INTO faces(id,media_id,embedding,status) VALUES('candidate','2',?,'suggested')",(v.tobytes(),))
        c.execute("INSERT INTO faces(id,media_id,embedding,status) VALUES('manual-unknown','2',?,'manual')",(v.tobytes(),))
    result=s.auto_assign_until_stable()
    assert result=={"assigned":1,"passes":2}
    assert s.auto_assign_until_stable()["assigned"]==0
    review=s.automatic_assignments()
    assert review["faces"][0]["id"]=="candidate"
    assert s.undo_assignments(review["actions"][0]["id"])["restored"]==1
    assert s.auto_assign_until_stable()["assigned"]==0
    with core.db() as c:
        assert c.execute("SELECT person_id FROM faces WHERE id='manual-unknown'").fetchone()[0] is None
        assert c.execute("SELECT 1 FROM face_rejections WHERE face_id='candidate' AND person_id=1").fetchone()

def test_auto_disabled_never_changes_assignments(service,monkeypatch):
    s,core=service
    s.save_settings(s.Settings(auto_assign=False))
    from backend import people_review
    monkeypatch.setattr(people_review,"reevaluate",lambda:pytest.fail("Disabled checkbox must skip matching"))
    assert s.auto_assign_until_stable()["assigned"]==0

def test_auto_predictions_not_trusted_references(service):
    s,core=service
    v=np.zeros(128,np.float32);v[0]=1
    with core.db() as c:
        c.execute("UPDATE faces SET embedding=?,status='auto-sync' WHERE id IN ('a','c')",(v.tobytes(),))
        c.execute("INSERT INTO faces(id,media_id,embedding,status) VALUES('candidate','2',?,'suggested')",(v.tobytes(),))
    assert s.auto_assign_until_stable()["assigned"]==0

def test_manual_correction_after_auto_survives_batch_undo(service):
    s,core=service
    with core.db() as c:
        c.execute("UPDATE faces SET status='manual',person_id=2 WHERE id='a'")
        action=c.execute("INSERT INTO actions(description,previous) VALUES(?,?)",("Automatic sync face assignments",json.dumps({"faces":[{"id":"a","person_id":None,"status":"suggested","target":1}],"auto_sync":True}))).lastrowid
    assert s.undo_assignments(action)["restored"]==0
    with core.db() as c: assert c.execute("SELECT person_id FROM faces WHERE id='a'").fetchone()[0]==2

def test_failed_run_records_error_and_releases_lock(service,monkeypatch):
    s,core=service
    monkeypatch.setattr(s,"inventory",lambda:(_ for _ in ()).throw(RuntimeError("Drive offline")))
    lock=s.scan_lock();lock.__enter__()
    with s.store() as c:c.execute("INSERT INTO runs VALUES('test',?,NULL,'running','manual','{}',NULL)",(s.now().isoformat(),))
    s.execute("test",lock)
    assert s.status()["runs"][0]["state"]=="failed"
    assert s.status()["runs"][0]["error"]=="Drive offline"
    with s.scan_lock():pass

def test_unnamed_grouping_never_assigns_a_name_when_disabled(service):
    s,core=service
    from backend import full_scan
    v=np.zeros(128,np.float32);v[0]=1
    with core.db() as c:
        c.execute("UPDATE faces SET embedding=?,status='manual' WHERE id IN ('a','c')",(v.tobytes(),))
        c.execute("INSERT INTO faces(id,media_id,embedding,status) VALUES('new-unknown','2',?,'suggested')",(v.tobytes(),))
    assert full_scan.assign_new_faces(allow_named=False)==1
    with core.db() as c:
        row=c.execute("SELECT p.name FROM faces f JOIN people p ON p.id=f.person_id WHERE f.id='new-unknown'").fetchone()
        assert row and row[0] is None

def test_soft_deleted_and_replaced_media_hidden_from_people(service,client):
    _,core=service;api,_=client
    with core.db() as c:c.execute("UPDATE media SET status='superseded' WHERE id='0'")
    assert api.get('/api/faces',params={'person':2}).json()==[]
    assert not any(p['id']==2 for p in api.get('/api/people').json())

def test_manual_now_works_when_schedule_is_off(service,monkeypatch):
    s,core=service
    s.save_settings(s.Settings(frequency='off',auto_assign=False))
    jobs=[]
    class DeferredThread:
        def __init__(self,target,args,**kw):jobs.append((target,args))
        def start(self):pass
    monkeypatch.setattr(s.threading,'Thread',DeferredThread)
    monkeypatch.setattr(s,'process_pending',lambda run_id:0)
    result=s.start_run()
    assert result['state']=='running'
    with pytest.raises(Exception) as error:s.start_run()
    assert error.value.status_code==409
    target,args=jobs[0];target(*args)
    assert s.status()['runs'][0]['state']=='completed'
    assert s.status()['next_due'] is None

def test_stale_scheduled_request_does_not_start_second_run(service):
    s,_=service
    assert s.start_run('scheduled')['state']=='not_due'
    assert not s.status()['runs']

def test_move_between_phones_preserves_media_id(service):
    s,core=service;p=make_file(core)
    s.reconcile(s.inventory())
    with core.db() as c:mid=c.execute('SELECT id FROM media WHERE path=?',(str(p),)).fetchone()[0]
    other=core.ROOT/core.PHONES[1]/p.name;p.rename(other)
    assert s.reconcile(s.inventory())['moved']==1
    with core.db() as c:assert c.execute('SELECT phone FROM media WHERE id=?',(mid,)).fetchone()[0]==core.PHONES[1]

def test_pending_processing_checks_offline_models_before_spawning(service):
    s,core=service
    with s.store() as c: c.execute("INSERT INTO runs VALUES('not-started',?,NULL,'running','manual','{}',NULL)",(s.now().isoformat(),))
    with pytest.raises(RuntimeError,match='Required offline model/reference missing'):
        s.process_pending('not-started')
