import hashlib,json,os,time
from pathlib import Path
import pytest
from PIL import Image
from tests.test_sync import service,make_file
from tests.test_catalogue import client

def run_row(s,identity="checkpoint",progress=None):
    with s.store() as c:
        c.execute("INSERT INTO runs VALUES(?,?,NULL,'running','manual',?,NULL)",(identity,s.now().isoformat(),json.dumps(progress or {})))

def test_preview_is_browsable_before_recognition(client,monkeypatch):
    api,core=client
    from backend import full_scan,indexer
    monkeypatch.setattr(indexer,"DATA",core.DATA)
    path=core.ROOT/core.PHONES[0]/"early.jpg";path.parent.mkdir(parents=True)
    Image.new("RGB",(80,60),"green").save(path);os.utime(path,(time.time()-90,)*2)
    st=path.stat()
    for folder in ("thumbs","frames","faces"): (core.DATA/folder).mkdir()
    with core.db() as c:
        c.execute("INSERT INTO media(id,path,name,phone,kind,bytes,mtime) VALUES('early',?,?,?,'photo',?,?)",(str(path),path.name,core.PHONES[0],st.st_size,st.st_mtime))
    monkeypatch.setattr(full_scan,"recognizer",None)
    monkeypatch.setattr(full_scan,"locations",None)
    assert full_scan.process_one("early",True)["ok"]
    assert api.get("/api/media/early/thumbnail").status_code==200
    assert any(r["id"]=="early" for r in api.get("/api/media").json()["items"])
    with core.db() as c:
        r=c.execute("SELECT status,face_status FROM media WHERE id='early'").fetchone()
        assert tuple(r)==("ready","pending")

def test_pause_resume_durable_queue_and_preview_priority(service,monkeypatch):
    s,core=service
    from backend import full_scan,indexer
    import multiprocessing
    for name in ("one.jpg","two.jpg"): make_file(core,name)
    s.reconcile(s.inventory())
    models=core.DATA/"models";models.mkdir()
    monkeypatch.setattr(indexer,"MODELS",models)
    (core.DATA/"maps").mkdir()
    for path in [models/"yunet.onnx",models/"sface.onnx",core.DATA/"maps"/"countries.geojson",core.DATA/"maps"/"gazetteer.sqlite"]:path.touch()
    run_row(s,progress={"reconciled":True})
    calls=[]
    def process(mid,preview):
        calls.append((mid,preview))
        with core.db() as c:
            c.execute("UPDATE media SET status='ready' WHERE id=?",(mid,))
            if not preview:c.execute("UPDATE media SET face_status='ready' WHERE id=?",(mid,))
        if len(calls)==1:s.control_run("checkpoint","pause")
        return {"id":mid,"ok":True}
    class Result:
        def __init__(self,args):self.args=args
        def get(self,timeout):return process(*self.args)
    class Pool:
        def apply_async(self,fn,args):return Result(args)
        def terminate(self):pass
        def join(self):pass
    class Context:
        def Pool(self,*args,**kw):return Pool()
    monkeypatch.setattr(multiprocessing,"get_context",lambda _:Context())
    s.save_settings(s.Settings(auto_assign=False))
    lock=s.scan_lock();lock.__enter__();s.execute("checkpoint",lock)
    assert s.status()["runs"][0]["state"]=="paused",s.status()["runs"][0]["error"]
    with s.store() as c:assert c.execute("SELECT count(*) FROM work WHERE done=1").fetchone()[0]==1
    jobs=[]
    class Thread:
        def __init__(self,target,args,**kw):jobs.append((target,args))
        def start(self):pass
    monkeypatch.setattr(s.threading,"Thread",Thread)
    assert s.control_run("checkpoint","resume")["id"]=="checkpoint"
    jobs[0][0](*jobs[0][1])
    assert s.status()["runs"][0]["state"]=="completed"
    assert len(calls)==4
    assert [preview for _,preview in calls]==[True,True,False,False]
    assert len(set(calls))==4

def test_cancel_persists_and_blocks_scheduled_restart(service):
    s,core=service;run_row(s)
    s.control_run("checkpoint","cancel")
    lock=s.scan_lock();lock.__enter__();s.execute("checkpoint",lock)
    assert s.status()["runs"][0]["state"]=="cancelled"
    with s.store() as c:c.execute("UPDATE settings SET next_due='2020-01-01T00:00:00+00:00'")
    assert s.start_run("scheduled")["state"]=="not_due"
    with s.scan_lock():pass

def test_pause_hash_inventory_and_invalid_controls(service,client):
    s,core=service;api,_=client
    run_row(s);s.control_run("checkpoint","pause")
    s.worker_context.run_id="checkpoint"
    try:
        with pytest.raises(s.SyncStopped):s.inventory()
    finally:s.worker_context.run_id=None
    assert api.post("/api/sync/runs/missing/pause").status_code==404
    with s.store() as c:c.execute("UPDATE runs SET state='completed'")
    assert api.post("/api/sync/runs/checkpoint/resume").status_code==409

def duplicates_fixture(s,core):
    from backend import duplicates as d
    for name,contents in [("one.jpg",b"identical"),("two.jpg",b"identical"),("three.jpg",b"identical"),("different.jpg",b"different"),("undated.jpg",b"identical")]:
        make_file(core,name,contents)
    s.reconcile(s.inventory())
    with core.db() as c:
        c.execute("UPDATE media SET status='ready',face_status='ready',taken='2026-01-01T12:30:00' WHERE name IN ('one.jpg','two.jpg','three.jpg','different.jpg')")
        c.execute("UPDATE media SET status='ready',taken=NULL WHERE name='undated.jpg'")
    d.init()
    with core.db() as c:c.execute("INSERT INTO duplicate_jobs VALUES('review','detect','running','{}',NULL,?)",(s.now().isoformat(),))
    d.detect("review")
    group=d.groups("review")["groups"][0]
    return d,group

def test_exact_duplicates_exclude_similar_metadata_and_missing_dates(service):
    s,core=service;d,g=duplicates_fixture(s,core)
    assert d.groups("review")["total"]==1
    assert {m["name"] for m in g["members"]}=={"one.jpg","two.jpg","three.jpg"}
    assert g["sha"]==hashlib.sha256(b"identical").hexdigest()

def test_review_selection_rejects_keeper_and_only_moves_checked(service,monkeypatch):
    s,core=service;d,g=duplicates_fixture(s,core)
    with pytest.raises(Exception) as e:d.remove(d.Selection(job_id="review",media_ids=[g["keeper"]]))
    assert e.value.status_code==422
    extra=next(m for m in g["members"] if m["id"]!=g["keeper"])
    calls=[]
    monkeypatch.setattr(d,"launch",lambda kind,plans:calls.append(plans) or {})
    d.remove(d.Selection(job_id="review",media_ids=[extra["id"]]))
    assert [mid for mid,_ in calls[0]]==[extra["id"]]

def test_recoverable_removal_restore_and_sync_exclusion(service,client):
    s,core=service;api,_=client;d,g=duplicates_fixture(s,core)
    extra=next(m for m in g["members"] if m["id"]!=g["keeper"])
    source=Path(extra["path"]);original=source.read_bytes()
    with core.db() as c:c.execute("INSERT INTO faces(id,media_id,person_id,status) VALUES('reviewed',?,1,'manual')",(extra["id"],))
    d.move_one(extra["id"],g)
    assert not source.exists()
    trash=d.trash()[0];assert Path(trash["trash"]).read_bytes()==original
    assert extra["id"] not in {r["id"] for r in api.get("/api/media").json()["items"]}
    assert s.reconcile(s.inventory())["missing"]==0
    with core.db() as c:assert c.execute("SELECT status FROM media WHERE id=?",(extra["id"],)).fetchone()[0]=="trashed"
    d.restore_one(extra["id"])
    assert source.read_bytes()==original
    assert extra["id"] in {r["id"] for r in api.get("/api/media").json()["items"]}
    with core.db() as c:assert tuple(c.execute("SELECT person_id,status FROM faces WHERE id='reviewed'").fetchone())==(1,"manual")

def test_changed_files_fail_revalidation_and_restore_never_overwrites(service):
    s,core=service;d,g=duplicates_fixture(s,core)
    extra=next(m for m in g["members"] if m["id"]!=g["keeper"])
    source=Path(extra["path"]);st=source.stat()
    source.write_bytes(b"not equal");os.utime(source,ns=(st.st_atime_ns,st.st_mtime_ns))
    with pytest.raises(ValueError,match="changed"):d.move_one(extra["id"],g)
    assert source.read_bytes()==b"not equal"
    source.write_bytes(b"identical");os.utime(source,ns=(st.st_atime_ns,st.st_mtime_ns))
    d.move_one(extra["id"],g)
    source.write_bytes(b"new upload")
    with pytest.raises(ValueError,match="occupied"):d.restore_one(extra["id"])
    assert source.read_bytes()==b"new upload"

def test_move_recovery_after_backend_interruption(service,monkeypatch):
    s,core=service;d,g=duplicates_fixture(s,core)
    extra=next(m for m in g["members"] if m["id"]!=g["keeper"])
    rename=d.os.rename
    def interrupted(source,target):
        rename(source,target)
        raise OSError("Simulated crash after atomic move")
    monkeypatch.setattr(d.os,"rename",interrupted)
    with pytest.raises(OSError):d.move_one(extra["id"],g)
    d.recover()
    with core.db() as c:
        assert c.execute("SELECT status FROM media WHERE id=?",(extra["id"],)).fetchone()[0]=="trashed"
        assert c.execute("SELECT state FROM duplicate_trash WHERE media_id=?",(extra["id"],)).fetchone()[0]=="trashed"
    monkeypatch.setattr(d.os,"rename",rename)
    d.restore_one(extra["id"])
    assert Path(extra["path"]).exists()

def test_cleanup_conflicts_with_sync_without_blocking_library(service,client):
    s,core=service;api,_=client
    from backend import duplicates as d
    with s.scan_lock():
        assert api.post("/api/duplicates/detect").status_code==409
        assert api.get("/api/media").status_code==200
    # A catalogue writer does not block read-only browsing in WAL mode.
    with core.db() as c:
        c.execute("BEGIN IMMEDIATE")
        c.execute("UPDATE media SET name='pending write' WHERE id='0'")
        assert api.get("/api/media").status_code==200
        c.rollback()

def test_revision_changes_on_enrichment_and_duplicate_removal(service,client):
    s,core=service;api,_=client
    before=api.get("/api/status").json()["revision"]
    with core.db() as c:c.execute("UPDATE faces SET status='manual' WHERE id='a'")
    assert api.get("/api/status").json()["revision"]>before

def test_resumed_older_run_is_current_and_pause_holds_schedule(service,monkeypatch):
    s,core=service
    with s.store() as c:
        c.execute("INSERT INTO runs VALUES('older','2026-01-01','2026-01-01','paused','manual','{}',NULL)")
        c.execute("INSERT INTO runs VALUES('newer','2026-02-01','2026-02-01','completed','manual','{}',NULL)")
    jobs=[]
    class Thread:
        def __init__(self,target,args,**kw):jobs.append((target,args))
        def start(self):pass
    monkeypatch.setattr(s.threading,'Thread',Thread)
    s.control_run('older','resume')
    assert s.status()['runs'][0]['id']=='older'
    s.control_run('older','pause')
    jobs[0][0](*jobs[0][1])
    assert s.status()['runs'][0]['state']=='paused'
    with s.store() as c:c.execute("UPDATE settings SET next_due='2020-01-01T00:00:00+00:00'")
    assert s.start_run('scheduled')['state']=='not_due'

def test_select_all_spans_pages_and_excludes_retained_unavailable_copies(service,client):
    s,core=service;api,_=client
    from backend import duplicates as d
    d.init()
    with core.db() as c:
        c.execute("INSERT INTO duplicate_jobs VALUES('many','detect','completed','{}',NULL,?)",(s.now().isoformat(),))
        for i in range(35):
            members=[]
            for role in ('keep','extra'):
                mid=f'{role}-{i}'
                c.execute("INSERT INTO media(id,path,status) VALUES(?,?,'ready')",(mid,mid))
                members.append(dict(id=mid,name=mid))
            c.execute("INSERT INTO duplicate_groups VALUES(?,?,?,?,?,?)",(f'g{i:02}','many',f'keep-{i}',json.dumps(members),'2026-10-05','sha'))
    assert len(api.get('/api/duplicates/groups',params={'job_id':'many'}).json()['groups'])==30
    selected=api.get('/api/duplicates/selection',params={'job_id':'many'}).json()
    assert len(selected['media_ids'])==35 and selected['extra_total']==35
    assert 'extra-34' in selected['media_ids']
    assert not any(mid.startswith('keep') for mid in selected['media_ids'])
    with core.db() as c:
        c.execute("UPDATE media SET status='trashed' WHERE id IN ('keep-1','extra-2')")
    selected=d.selection('many')
    assert len(selected['media_ids'])==33
    assert 'extra-1' not in selected['media_ids'] and 'extra-2' not in selected['media_ids']
    assert api.get('/api/duplicates/selection',params={'job_id':'absent'}).status_code==409

def test_bulk_selection_supports_more_than_five_thousand_copies():
    from backend.duplicates import Selection
    selected=Selection(job_id='large-review',media_ids=[str(i) for i in range(6000)])
    assert len(selected.media_ids)==6000

def format_fixture(s,core,keep="heic"):
    from backend import duplicates as d
    make_file(core,"IMG_1234.HEIC",b"heic-original-content")
    make_file(core,"IMG_1234.JPG",b"jpeg-converted-content")
    make_file(core,"IMG_9999.JPG",b"different-name")
    s.reconcile(s.inventory())
    with core.db() as c:
        c.execute("UPDATE media SET status='ready',face_status='ready',taken='2026-10-01T09:30:00',width=4032,height=3024 WHERE name IN ('IMG_1234.HEIC','IMG_1234.JPG','IMG_9999.JPG')")
    d.init()
    with core.db() as c:c.execute("INSERT INTO duplicate_jobs VALUES('format','detect','running','{}',NULL,?)",(s.now().isoformat(),))
    d.detect("format","heic_jpeg",keep)
    return d,d.groups("format")["groups"][0]

def test_metadata_format_review_and_recoverable_removal(service):
    s,core=service;d,g=format_fixture(s,core)
    assert g["mode"]=="heic_jpeg"
    assert len(g["members"])==2
    kept=next(m for m in g["members"] if m["id"]==g["keeper"])
    assert kept["extension"]==".heic"
    extra=next(m for m in g["members"] if m["id"]!=g["keeper"])
    before=Path(extra["path"]).read_bytes()
    d.move_one(extra["id"],g)
    assert Path(kept["path"]).is_file() and not Path(extra["path"]).exists()
    d.restore_one(extra["id"])
    assert Path(extra["path"]).read_bytes()==before

def test_format_preference_can_keep_jpeg(service):
    s,core=service;d,g=format_fixture(s,core,"jpeg")
    assert next(m for m in g["members"] if m["id"]==g["keeper"])["extension"]==".jpg"
    assert d.selection("format")["media_ids"]==[m["id"] for m in g["members"] if m["extension"]==".heic"]

def test_format_candidate_revalidates_files_and_metadata(service):
    s,core=service;d,g=format_fixture(s,core)
    extra=next(m for m in g["members"] if m["id"]!=g["keeper"])
    path=Path(extra["path"]);st=path.stat()
    path.write_bytes(b"x"*st.st_size);os.utime(path,ns=(st.st_atime_ns,st.st_mtime_ns))
    with pytest.raises(ValueError,match="changed"): d.move_one(extra["id"],g)
    assert path.is_file()
    with core.db() as c:c.execute("UPDATE media SET width=4000 WHERE id=?",(extra["id"],))
    with pytest.raises(ValueError,match="Metadata changed"):d.move_one(extra["id"],g)

def test_format_matching_requires_every_metadata_key():
    from backend.duplicates import format_key
    row=dict(kind="photo",extension=".heic",taken="2026-10-01T09:30:00",width=4032,height=3024,phone="A",name="IMG_1234.HEIC")
    jpeg={**row,"extension":".jpg","name":"img_1234.JPG"}
    assert format_key(row)==format_key(jpeg)
    for key,value in [('phone','B'),('name','IMG_5678.JPG'),('taken','2026-10-01T09:30:01'),('width',4000),('height',3000)]:
        assert format_key(row)!=format_key({**jpeg,key:value})
    for key,value in [('taken',None),('width',None),('extension','.png'),('kind','video')]:
        assert format_key({**jpeg,key:value}) is None

def test_format_review_does_not_change_exact_match_rule(service):
    s,core=service;d,g=format_fixture(s,core)
    with core.db() as c:c.execute("INSERT INTO duplicate_jobs VALUES('exact-again','detect','running','{}',NULL,?)",(s.now().isoformat(),))
    d.detect("exact-again")
    assert d.groups("exact-again")["total"]==0

def test_review_survives_more_than_ten_other_jobs(service,client):
    s,core=service;api,_=client;d,g=format_fixture(s,core)
    with core.db() as c:
        for i in range(11):c.execute("INSERT INTO duplicate_jobs VALUES(?,'restore','completed','{}',NULL,'2099-01-01')",(str(i),))
    state=d.status()
    assert not any(j['id']=='format' for j in state['jobs'])
    assert any(j['id']=='format' for j in state['reviews'])
    assert api.post('/api/duplicates/detect',json={'mode':'visual_similarity'}).status_code==422
