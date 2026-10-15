"""Persistent calendar scheduler and incremental, read-only-source synchronization."""
import calendar, hashlib, json, os, sqlite3, threading, time, uuid, logging
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from . import core

router = APIRouter(prefix="/api/sync", tags=["Sync"])
UTC = timezone.utc

class Settings(BaseModel):
    frequency: Literal["off","hourly","daily","weekly","monthly"] = "daily"
    time: str = "03:00"
    weekday: int = Field(default=6, ge=0, le=6)
    month_day: int = Field(default=1, ge=1, le=31)
    timezone: str = "UTC"
    auto_assign: bool = True

    @field_validator("time")
    @classmethod
    def check_time(cls,v):
        try:
            if datetime.strptime(v,"%H:%M").strftime("%H:%M") != v: raise ValueError()
        except ValueError: raise ValueError("Use HH:MM in 24-hour time")
        return v

    @field_validator("timezone")
    @classmethod
    def check_zone(cls,v):
        try: ZoneInfo(v)
        except (ZoneInfoNotFoundError,ValueError): raise ValueError("Unknown timezone")
        return v

def now(): return datetime.now(UTC)

def next_due(s, after):
    if s.frequency == "off": return None
    zone = ZoneInfo(s.timezone)
    local = after.astimezone(zone)
    hour, minute = map(int,s.time.split(":"))
    # fold=0 runs repeated wall-clock times once; gaps advance by the DST gap.
    for offset in range(370):
        day = local.date()+timedelta(days=offset)
        if s.frequency=="weekly" and day.weekday()!=s.weekday: continue
        if s.frequency=="monthly" and day.day!=min(s.month_day,calendar.monthrange(day.year,day.month)[1]): continue
        for h in (range(24) if s.frequency=="hourly" else [hour]):
            candidate=datetime(day.year,day.month,day.day,h,minute,tzinfo=zone,fold=0).astimezone(UTC)
            if candidate>after: return candidate.isoformat()
    raise ValueError("No schedule occurrence found")

# Retain terminal state in memory if the checkpoint drive disappears. A fresh
# connection writes it back once storage returns; startup also recovers stale runs.
terminal_runs={}
terminal_runs_lock=threading.Lock()

@contextmanager
def store():
    path=core.database_path("sync.sqlite")
    path.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(path,timeout=30)
    c.row_factory=sqlite3.Row
    try:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1),value TEXT,next_due TEXT);
        CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,started TEXT,finished TEXT,state TEXT,reason TEXT,progress TEXT,error TEXT);
        CREATE TABLE IF NOT EXISTS controls(run_id TEXT PRIMARY KEY,request TEXT);
        CREATE TABLE IF NOT EXISTS streaming_roots(run_id TEXT,database_id TEXT,root TEXT,revision INTEGER,PRIMARY KEY(run_id,database_id));
        CREATE TABLE IF NOT EXISTS file_hashes(run_id TEXT,path TEXT,bytes INTEGER,mtime REAL,sha TEXT,PRIMARY KEY(run_id,path));
        CREATE TABLE IF NOT EXISTS work(run_id TEXT,media_id TEXT,stage TEXT,done INTEGER DEFAULT 0,error TEXT,PRIMARY KEY(run_id,media_id,stage));
        """)
        from .discovery_checkpoint import SCHEMA
        c.executescript(SCHEMA)
        if not c.execute("SELECT 1 FROM settings").fetchone():
            s=Settings()
            c.execute("INSERT OR IGNORE INTO settings VALUES(1,?,?)",(s.model_dump_json(),next_due(s,now())))
        with terminal_runs_lock: pending=dict(terminal_runs)
        for identity,(state,finished,error) in pending.items():
            c.execute("UPDATE runs SET state=?,finished=?,error=? WHERE id=?",(state,finished,error,identity))
        c.commit()
        with terminal_runs_lock:
            for identity,value in pending.items():
                if terminal_runs.get(identity)==value:terminal_runs.pop(identity,None)
        yield c
        c.commit()
    finally: c.close()

def load_settings():
    with store() as c: return Settings.model_validate_json(c.execute("SELECT value FROM settings WHERE id=1").fetchone()[0])

@router.get("/status")
def status():
    with store() as c:
        s=c.execute("SELECT * FROM settings WHERE id=1").fetchone()
        runs=[{**dict(r),"progress":json.loads(r["progress"] or "{}")} for r in c.execute("SELECT * FROM runs ORDER BY (state IN ('running','pausing','cancelling')) DESC,coalesce(finished,started) DESC LIMIT 15")]
        with live_progress_lock:
            for run in runs: run["progress"].update(live_progress.get(run["id"],{}))
        return {"settings":json.loads(s["value"]),"next_due":s["next_due"],"runs":runs,"running":any(r["state"] in ("running","pausing","cancelling") for r in runs)}

@router.put("/settings")
def save_settings(body:Settings):
    with store() as c: c.execute("UPDATE settings SET value=?,next_due=? WHERE id=1",(body.model_dump_json(),next_due(body,now())))
    return status()

@contextmanager
def scan_lock():
    import msvcrt
    directory=core.database_dir()
    directory.mkdir(parents=True,exist_ok=True)
    f=(directory/"full-scan.lock").open("a+b")
    try:
        if f.tell()==0: f.write(b"0"); f.flush()
        f.seek(0)
        try: msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        except OSError: raise RuntimeError("A sync or full-library scan is already running")
        yield
    finally: f.close()

def update_run(identity,**values):
    with store() as c:
        p=json.loads(c.execute("SELECT progress FROM runs WHERE id=?",(identity,)).fetchone()[0] or "{}")
        p.update(values)
        c.execute("UPDATE runs SET progress=? WHERE id=?",(json.dumps(p),identity))

worker_context=threading.local()
live_progress={}
live_progress_lock=threading.Lock()

def report_progress(force=False, **values):
    """Publish at most once a second, with immediate phase/checkpoint updates."""
    identity=getattr(worker_context,"run_id",None)
    if not identity: return
    pending=getattr(worker_context,"pending_progress",{})
    pending.update(values)
    with live_progress_lock:
        live_progress.setdefault(identity,{}).update(values,updated_at=now().isoformat())
    worker_context.pending_progress=pending
    instant=time.monotonic()
    if force or instant-getattr(worker_context,"last_progress",0)>=1:
        update_run(identity,**pending,updated_at=now().isoformat())
        worker_context.pending_progress={}
        worker_context.last_progress=instant

def file_progress(path, **values):
    report_progress(current_folder=str(Path(path).parent),current_file=Path(path).name,**values)

class SyncStopped(Exception):
    def __init__(self, request): self.request=request

def check_control(run_id=None):
    identity=run_id or getattr(worker_context,"run_id",None)
    if not identity: return
    with store() as c:
        row=c.execute("SELECT request FROM controls WHERE run_id=?",(identity,)).fetchone()
    if row and row[0]: raise SyncStopped(row[0])

@router.post("/runs/{run_id}/{action}",status_code=202)
def control_run(run_id:str,action:Literal["pause","cancel","resume"]):
    if action=="resume": return start_run("resume",run_id)
    with store() as c:
        row=c.execute("SELECT state FROM runs WHERE id=?",(run_id,)).fetchone()
        if not row: raise HTTPException(404,"Sync run not found")
        if row[0] not in ("running","pausing","cancelling"): raise HTTPException(409,"This run is not active")
        c.execute("INSERT OR REPLACE INTO controls VALUES(?,?)",(run_id,action))
        c.execute("UPDATE runs SET state=? WHERE id=?",("pausing" if action=="pause" else "cancelling",run_id))
    return {"id":run_id,"state":"pausing" if action=="pause" else "cancelling"}


def inventory():
    from .source_management import inventory as registered_inventory
    identity=getattr(worker_context,"run_id",None)
    allowed={}
    def discovered(database,batch):
        from .incremental_import import first_import,publish
        if database['id'] not in allowed:allowed[database['id']]=first_import(database,identity)
        if allowed[database['id']]:publish(batch,identity,preview_publisher())
    from .discovery_checkpoint import DiscoveryCheckpoint
    checkpoint = DiscoveryCheckpoint(identity) if identity else None
    files = registered_inventory(getattr(worker_context,"database_id",None),check_control,getattr(worker_context,"global_scheduled",False),progress=report_progress,on_batch=discovered if identity else None,checkpoint=checkpoint)
    report_progress(force=True)
    return files

def preview_publisher():
    publisher=getattr(worker_context,"preview_publisher",None)
    if publisher is None:
        from .incremental_import import PreviewPublisher
        publisher=PreviewPublisher(worker_context.run_id)
        worker_context.preview_publisher=publisher
    return publisher


def digest_stable(path,expected):
    p=Path(path); before=p.stat()
    if (before.st_size,before.st_mtime)!=(expected["bytes"],expected["mtime"]): raise RuntimeError("Source changed during inventory: "+path)
    h=hashlib.sha256()
    with p.open("rb") as f:
        while chunk:=f.read(4*1024*1024):
            check_control()
            h.update(chunk)
    digest=h.hexdigest()
    after=p.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns): raise RuntimeError("Source changed while hashing: "+path)
    return digest

def reconcile(files):
    with core.db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS sync_missing(media_id TEXT PRIMARY KEY,previous_status TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS sync_versions(old_id TEXT PRIMARY KEY,new_id TEXT,source_path TEXT,created TEXT)")
        from .source_management import Inventory, excluded
        if isinstance(files, Inventory):
            rows={r["path"]:dict(r) for r in c.execute("SELECT * FROM media WHERE status!='superseded'")
                  if r["source_id"] in files.scopes and not excluded(r["relative_path"] or "", json.loads(c.execute("SELECT exclusions FROM library_databases WHERE id=?", (r["database_id"],)).fetchone()[0]))}
        else:
            rows={r["path"]:dict(r) for r in c.execute("SELECT * FROM media WHERE status!='superseded'")}
    absent=[r for p,r in rows.items() if p not in files]
    by_hash={}
    for r in absent:
        if r["sha"] and r["status"]!="trashed": by_hash.setdefault((r.get("database_id"),r["bytes"],r["sha"]),[]).append(r)
    fresh={}; changes={}; deferred=0
    identity=getattr(worker_context,"run_id",None)
    cached={}
    if identity:
        with store() as c:
            cached={r["path"]:dict(r) for r in c.execute("SELECT * FROM file_hashes WHERE run_id=?",(identity,))}
    pending=[]; last_flush=time.monotonic(); reused=0
    early={}; early_added=0; last_publish=time.monotonic()
    potential_moves={(key[0],key[1]) for key in by_hash}
    def publish_early():
        nonlocal early_added,last_publish
        if early:
            from .incremental_import import publish
            added,published=publish(early,identity,preview_publisher(),fresh)
            early_added+=added;rows.update(published)
            for path in published:fresh.pop(path,None)
            early.clear()
        last_publish=time.monotonic()
    def flush_hashes():
        nonlocal last_flush
        if pending:
            with store() as c:
                c.executemany("INSERT OR REPLACE INTO file_hashes VALUES(?,?,?,?,?)",pending)
            pending.clear()
        last_flush=time.monotonic()
    report_progress(force=True,phase="Checking file contents",processed=0,total=len(files),current_folder="",current_file="",hashes_reused=0)
    try:
        for index,(path,entry) in enumerate(files.items()):
            file_progress(path,processed=index)
            check_control()
            old=rows.get(path)
            if old and old["status"]!="trashed" and (old["bytes"],old["mtime"])==(entry["bytes"],entry["mtime"]):
                pass
            elif time.time()-entry["mtime"]<30:
                deferred+=1
            else:
                # A saved inventory is a discovery snapshot. Validate just the
                # file requiring content checks, not every completed folder.
                p=Path(path)
                if p.is_symlink() or p.is_junction():
                    raise RuntimeError("Source must not traverse links: "+path)
                st=p.stat()
                if (st.st_size,st.st_mtime)!=(entry["bytes"],entry["mtime"]):
                    if not getattr(files,"resumed",False):
                        raise RuntimeError("Source changed during inventory: "+path)
                    entry.update(bytes=st.st_size,mtime=st.st_mtime)
                if time.time()-entry["mtime"]<30:
                    deferred+=1
                    report_progress(processed=index+1,hashes_reused=reused)
                    continue
                saved=cached.get(path)
                if saved and (saved["bytes"],saved["mtime"])==(entry["bytes"],entry["mtime"]):
                    digest=saved["sha"]; reused+=1
                else:
                    digest=digest_stable(path,entry)
                    if identity:
                        pending.append((identity,path,entry["bytes"],entry["mtime"],digest))
                (changes if old else fresh)[path]=digest
                if identity and old is None and (entry.get("database_id"),entry["bytes"]) not in potential_moves:
                    early[path]=entry
            if early and (len(early)>=50 or time.monotonic()-last_publish>=5):publish_early()
            report_progress(processed=index+1,hashes_reused=reused)
            if len(pending)>=64 or time.monotonic()-last_flush>=1: flush_hashes()
    finally:
        # Retain only finished hashes, including when pause arrives mid-file.
        flush_hashes()
        report_progress(force=True)
    check_control()
    publish_early()
    from .source_management import verify_available
    verify_available(files)
    report=dict(added=early_added,changed=0,moved=0,missing=0,restored=0,deferred=deferred)
    claimed=set()
    report_progress(force=True,phase="Updating catalogue",processed=0,total=len(files),current_folder="",current_file="")
    with core.db() as c:
        c.execute("BEGIN IMMEDIATE")
        def restore(row):
            previous=c.execute("SELECT previous_status FROM sync_missing WHERE media_id=?",(row["id"],)).fetchone()
            if previous:
                c.execute("UPDATE media SET status=? WHERE id=?",(previous[0],row["id"]))
                c.execute("DELETE FROM sync_missing WHERE media_id=?",(row["id"],))
                report["restored"]+=1
        def add(entry,digest):
            mid=uuid.uuid4().hex[:24]; cols=list(entry)
            c.execute("INSERT INTO media(id,"+",".join(cols)+",sha) VALUES("+",".join("?" for _ in range(len(cols)+2))+")",[mid,*entry.values(),digest])
            return mid
        for index,(path,entry) in enumerate(files.items()):
            file_progress(path,processed=index)
            old=rows.get(path)
            if old:
                if path not in changes:
                    if (old["bytes"],old["mtime"])==(entry["bytes"],entry["mtime"]):
                        restore(old)
                        if "source_id" in entry:
                            c.execute("UPDATE media SET database_id=?,source_id=?,album_id=?,relative_path=?,phone=?,album=? WHERE id=?", (entry["database_id"],entry["source_id"],entry["album_id"],entry["relative_path"],entry["phone"],entry["album"],old["id"]))
                    continue
                digest=changes[path]
                if digest==old["sha"] and old["status"]!="trashed":
                    c.execute("UPDATE media SET bytes=?,mtime=? WHERE id=?",(entry["bytes"],entry["mtime"],old["id"]))
                    restore(old)
                else:
                    # Preserve old detections/corrections on an archived version, never reuse wrong face geometry.
                    c.execute("UPDATE media SET path=?,status='superseded' WHERE id=?",("archived://"+old["id"],old["id"]))
                    new_id=add(entry,digest)
                    c.execute("INSERT INTO sync_versions VALUES(?,?,?,?)",(old["id"],new_id,path,now().isoformat()))
                    c.execute("DELETE FROM sync_missing WHERE media_id=?",(old["id"],))
                    report["changed"]+=1
            elif path in fresh:
                digest=fresh[path]
                matches=[r for r in by_hash.get((entry.get("database_id"),entry["bytes"],digest),[]) if r["id"] not in claimed]
                if len(matches)==1:
                    old=matches[0]; claimed.add(old["id"])
                    c.execute("UPDATE media SET path=?,phone=?,album=?,name=?,mtime=? WHERE id=?",(path,entry["phone"],entry["album"],entry["name"],entry["mtime"],old["id"]))
                    if "source_id" in entry:
                        c.execute("UPDATE media SET database_id=?,source_id=?,album_id=?,relative_path=? WHERE id=?", (entry["database_id"],entry["source_id"],entry["album_id"],entry["relative_path"],old["id"]))
                    restore(old); report["moved"]+=1
                else: add(entry,digest); report["added"]+=1
        for row in absent:
            if row["id"] in claimed or row["status"] in ("missing","trashed"): continue
            c.execute("INSERT OR IGNORE INTO sync_missing VALUES(?,?)",(row["id"],row["status"]))
            c.execute("UPDATE media SET status='missing' WHERE id=?",(row["id"],))
            report["missing"]+=1
    report_progress(force=True,processed=len(files),current_folder="",current_file="")
    return report

def run_scope(alias="m"):
    did=getattr(worker_context,"database_id",None)
    if not getattr(worker_context,"run_id",None): return "1",[]
    sql=f"({alias}.source_id IS NULL OR {alias}.source_id IN (SELECT id FROM library_sources WHERE sync_enabled=1 AND active=1 AND database_id IN (SELECT id FROM library_databases WHERE sync_enabled=1)))"
    args=[]
    if did: sql+=f" AND {alias}.database_id=?"; args.append(did)
    if getattr(worker_context,"global_scheduled",False): sql+=f" AND {alias}.database_id IN (SELECT id FROM library_databases WHERE schedule IS NULL)"
    return sql,args

def auto_assign_until_stable(progress=lambda **kw:None):
    from .people_review import reevaluate
    assigned=0; passes=0
    identity=getattr(worker_context,"run_id",None)
    reporting=False
    if identity:
        with store() as c:
            reporting=c.execute("SELECT 1 FROM runs WHERE id=?",(identity,)).fetchone() is not None
    last_control=0.0
    def matching_progress(phase,processed=None,total=None,unit=None):
        nonlocal last_control
        instant=time.monotonic()
        if instant-last_control>=.25 or phase=='Saving suggestions':
            check_control(); last_control=instant
            if reporting: report_progress(phase='Matching faces: '+phase,processed=processed,total=total,unit=unit,current_folder='',current_file='')
    while True:
        check_control()
        if not load_settings().auto_assign: return dict(assigned=assigned,passes=passes,stopped_by_setting=True)
        reevaluate(progress=matching_progress)
        check_control()
        passes+=1; previous=[]
        if not load_settings().auto_assign: return dict(assigned=assigned,passes=passes,stopped_by_setting=True)
        with core.db() as c:
            c.execute("BEGIN IMMEDIATE")
            scope,args=run_scope()
            rows=c.execute("""SELECT f.id,f.person_id,f.status,s.person_id target FROM face_suggestions s
                JOIN high_confidence_faces h ON h.face_id=s.face_id JOIN faces f ON f.id=s.face_id
                JOIN media m ON m.id=f.media_id LEFT JOIN people p ON p.id=f.person_id
                WHERE m.status='ready' AND f.status NOT IN ('manual','dismissed','auto-sync')
                AND trim(coalesce(p.name,''))='' AND NOT EXISTS(SELECT 1 FROM face_rejections r WHERE r.face_id=f.id AND r.person_id=s.person_id) AND """+scope,args).fetchall()
            for r in rows:
                previous.append(dict(id=r["id"],person_id=r["person_id"],status=r["status"],target=r["target"],unknown=bool(c.execute("SELECT 1 FROM unknown_faces WHERE face_id=?",(r["id"],)).fetchone())))
                c.execute("DELETE FROM unknown_faces WHERE face_id=?",(r["id"],))
                c.execute("UPDATE faces SET person_id=?,status='auto-sync' WHERE id=?",(r["target"],r["id"]))
                c.execute("DELETE FROM face_suggestions WHERE face_id=?",(r["id"],))
                c.execute("DELETE FROM high_confidence_faces WHERE face_id=?",(r["id"],))
            if previous:
                c.execute("INSERT INTO actions(description,previous) VALUES(?,?)",("Automatic sync face assignments",json.dumps({"faces":previous,"auto_sync":True})))
        assigned+=len(previous); progress(assigned=assigned,passes=passes)
        if not previous: return dict(assigned=assigned,passes=passes)

def process_pending(run_id):
    import multiprocessing as mp
    import shutil
    from . import full_scan
    for folder in ("thumbs","frames","faces","previews"): (core.DATA/folder).mkdir(exist_ok=True)
    # Durable per-file queues: previews for all files are published before enrichment.
    for stage in ("preview","enrichment"):
        check_control(run_id)
        with core.db() as c:
            sql="status IN ('pending','error')" if stage=="preview" else "status='ready' AND face_status!='ready'"
            did=getattr(worker_context,"database_id",None)
            scope=" AND ((source_id IS NULL AND NOT EXISTS(SELECT 1 FROM media registered WHERE registered.source_id IS NOT NULL)) OR source_id IN (SELECT id FROM library_sources WHERE sync_enabled=1 AND active=1 AND database_id IN (SELECT id FROM library_databases WHERE sync_enabled=1)))"
            if did: scope+=" AND database_id=?"
            if getattr(worker_context,"global_scheduled",False): scope+=" AND database_id IN (SELECT id FROM library_databases WHERE schedule IS NULL)"
            media=[r for r in c.execute("SELECT id,path FROM media WHERE ("+sql+")"+scope,(did,) if did else ())]
        paths={r["id"]:r["path"] for r in media}
        ids=list(paths)
        with store() as c:
            c.executemany("INSERT OR IGNORE INTO work(run_id,media_id,stage) VALUES(?,?,?)",[(run_id,mid,stage) for mid in ids])
            eligible=set(ids)
            todo=[r[0] for r in c.execute("SELECT media_id FROM work WHERE run_id=? AND stage=? AND done=0 ORDER BY rowid",(run_id,stage)) if r[0] in eligible]
            completed=c.execute("SELECT count(*) FROM work WHERE run_id=? AND stage=? AND done=1",(run_id,stage)).fetchone()[0]
        if todo and stage=="enrichment":
            from .indexer import MODELS
            for path in (MODELS/"yunet.onnx",MODELS/"sface.onnx",core.DATA/"maps"/"countries.geojson",core.DATA/"maps"/"gazetteer.sqlite"):
                if not path.is_file(): raise RuntimeError("Required offline model/reference missing: "+str(path))
        pool=None
        try:
            for index,mid in enumerate(todo):
                check_control(run_id)
                if shutil.disk_usage(core.DATA).free<10*1024**3: raise RuntimeError("Less than 10 GiB free on the data SSD")
                if pool is None:
                    initializer=full_scan.prepare_preview_worker if stage=="preview" else full_scan.prepare_worker
                    pool=mp.get_context("spawn").Pool(1,initializer=initializer,maxtasksperchild=150)
                report_progress(force=True,phase="Publishing previews" if stage=="preview" else "Recognizing faces and locations",processed=completed+index,total=completed+len(todo),current_folder=str(Path(paths[mid]).parent),current_file=Path(paths[mid]).name)
                try: result=pool.apply_async(full_scan.process_one,(mid,stage=="preview")).get(timeout=240)
                except Exception as e:
                    pool.terminate(); pool.join(); pool=None
                    result=dict(id=mid,ok=False,error=str(e) or "Decoder timed out")
                if not result["ok"]: full_scan.record_error(result)
                with store() as c:
                    c.execute("UPDATE work SET done=1,error=? WHERE run_id=? AND media_id=? AND stage=?",(result.get("error"),run_id,mid,stage))
                report_progress(force=True,processed=completed+index+1)
            report_progress(force=True,processed=completed+len(todo),total=completed+len(todo),current_folder="",current_file="")
        finally:
            if pool: pool.terminate(); pool.join()
    with store() as c:
        errors=c.execute("SELECT count(*) FROM work WHERE run_id=? AND error IS NOT NULL",(run_id,)).fetchone()[0]
    update_run(run_id,errors=errors)
    return errors

def execute(run_id,lock_context):
    worker_context.run_id=run_id
    worker_context.pending_progress={}
    worker_context.last_progress=0
    worker_context.database_id=None
    worker_context.global_scheduled=False
    try:
        saved=status_progress(run_id)
        worker_context.database_id=saved.get("database_id")
        worker_context.global_scheduled=saved.get("global_scheduled",False)
        import shutil
        if shutil.disk_usage(core.DATA).free<10*1024**3: raise RuntimeError("Less than 10 GiB free on the data SSD")
        check_control(run_id)
        with store() as c:
            progress=json.loads(c.execute("SELECT progress FROM runs WHERE id=?",(run_id,)).fetchone()[0])
        from .discovery_checkpoint import DiscoveryCheckpoint
        from .source_management import inventory_roots
        discovery = DiscoveryCheckpoint(run_id)
        if progress.get("reconciled") and not discovery.valid_for(inventory_roots(worker_context.database_id, worker_context.global_scheduled)):
            progress["reconciled"] = False
            update_run(run_id,reconciled=False)
        report_progress(force=True,checkpoint_version=2)
        if not progress.get("reconciled"):
            report_progress(force=True,phase="Reading source folders",processed=0,total=None,folders_checked=0,media_found=0,current_folder="",current_file="")
            files=inventory()
            update_run(run_id,phase="Reconciling files",inventory=len(files))
            already_added=status_progress(run_id).get('live_added',0)
            report=reconcile(files)
            report['added']+=already_added
            update_run(run_id,**report,reconciled=True)
            with store() as c: c.execute("DELETE FROM file_hashes WHERE run_id=?",(run_id,))
        publisher=getattr(worker_context,"preview_publisher",None)
        if publisher:publisher.close()
        errors=process_pending(run_id)
        check_control(run_id)
        if load_settings().auto_assign:
            report_progress(force=True,phase="Matching faces",processed=None,total=None,current_folder="",current_file="")
            prior=status_progress(run_id)
            auto_assign_until_stable(lambda **kw:update_run(run_id,assigned=prior.get("assigned",0)+kw["assigned"],passes=prior.get("passes",0)+kw["passes"]))
        from .full_scan import assign_new_faces
        report_progress(force=True,phase="Grouping unnamed faces",processed=None,total=None,current_folder="",current_file="")
        while True:
            check_control(run_id)
            if not assign_new_faces(allow_named=False): break
        check_control(run_id)
        report_progress(force=True,phase="Finished",current_folder="",current_file="")
        with store() as c:
            c.execute("UPDATE runs SET state=?,finished=? WHERE id=?",("completed_with_issues" if errors or status_progress(run_id).get("deferred") else "completed",now().isoformat(),run_id))
        discovery.discard()
    except SyncStopped as e:
        state="paused" if e.request=="pause" else "cancelled"
        try:
            from .discovery_checkpoint import DiscoveryCheckpoint
            DiscoveryCheckpoint(run_id).mark_paused()
            report_progress(force=True,phase="Paused at checkpoint" if state=="paused" else "Cancelled; progress saved")
            with store() as c:
                c.execute("UPDATE runs SET state=?,finished=? WHERE id=?",(state,now().isoformat(),run_id))
        except (sqlite3.Error,OSError):
            with terminal_runs_lock:terminal_runs[run_id]=(state,now().isoformat(),"Storage disconnected while stopping; saved checkpoints retained")
            logging.getLogger(__name__).exception("Stop request retained until storage returns")
    except Exception as e:
        logging.getLogger(__name__).exception("Sync stopped; saved checkpoints retained")
        try:
            report_progress(force=True)
            with store() as c:c.execute("UPDATE runs SET state='failed',finished=?,error=? WHERE id=?",(now().isoformat(),str(e)[:2000],run_id))
        except (sqlite3.Error,OSError):
            with terminal_runs_lock:terminal_runs[run_id]=("interrupted",now().isoformat(),"Storage disconnected during sync; reconnect the data drive and resume the saved checkpoint")
            logging.getLogger(__name__).exception("Could not save stopped sync state; recovery is pending")
    finally:
        publisher=getattr(worker_context,"preview_publisher",None)
        if publisher:
            try:publisher.close()
            except Exception:logging.getLogger(__name__).exception("Preview worker cleanup failed")
        worker_context.preview_publisher=None
        with live_progress_lock: live_progress.pop(run_id,None)
        worker_context.pending_progress={}
        worker_context.run_id=None
        worker_context.database_id=None
        worker_context.global_scheduled=False
        try:
            with store() as c:
                row=c.execute("SELECT * FROM settings WHERE id=1").fetchone()
                if row["next_due"] and datetime.fromisoformat(row["next_due"])<=now():
                    c.execute("UPDATE settings SET next_due=? WHERE id=1",(next_due(Settings.model_validate_json(row["value"]),now()),))
        except (sqlite3.Error,OSError):
            logging.getLogger(__name__).exception("Storage unavailable during sync cleanup")
        finally: lock_context.__exit__(None,None,None)

def status_progress(run_id):
    with store() as c: return json.loads(c.execute("SELECT progress FROM runs WHERE id=?",(run_id,)).fetchone()[0] or "{}")

def start_run(reason="manual",resume_id=None,database_id=None):
    lock=scan_lock()
    try: lock.__enter__()
    except RuntimeError as e: raise HTTPException(409,str(e))
    identity=resume_id or uuid.uuid4().hex
    try:
        with store() as c:
            # Respect a user's paused/cancelled run: scheduled work waits for an explicit resume or new sync.
            if reason == "scheduled" and not database_id:
                due=c.execute("SELECT next_due FROM settings WHERE id=1").fetchone()[0]
                latest=c.execute("SELECT state FROM runs ORDER BY coalesce(finished,started) DESC LIMIT 1").fetchone()
                if due is None or datetime.fromisoformat(due)>now() or (latest and latest[0] in ("paused","cancelled","interrupted")):
                    lock.__exit__(None,None,None)
                    return {"state":"not_due"}
            c.execute("UPDATE runs SET state='interrupted',finished=?,error='Backend stopped; resume this run from its checkpoint' WHERE state IN ('running','pausing','cancelling')",(now().isoformat(),))
            if resume_id:
                row=c.execute("SELECT state FROM runs WHERE id=?",(resume_id,)).fetchone()
                if not row: raise HTTPException(404,"Sync run not found")
                if row[0] not in ("paused","cancelled","interrupted","failed"): raise HTTPException(409,"This run cannot be resumed")
                saved=json.loads(c.execute("SELECT progress FROM runs WHERE id=?",(resume_id,)).fetchone()[0] or "{}")
                if saved.get("database_id"):
                    from .source_management import get_database
                    with core.db() as catalogue:
                        d=get_database(catalogue,saved["database_id"])
                    if not d["sync_enabled"]: raise HTTPException(409,"Resume database syncing before resuming this run")
                c.execute("UPDATE runs SET state='running',finished=NULL,error=NULL WHERE id=?",(resume_id,))
            else:
                c.execute("INSERT INTO runs VALUES(?,?,NULL,'running',?,'{}',NULL)",(identity,now().isoformat(),reason))
            if reason=="scheduled" and not database_id:
                c.execute("UPDATE runs SET progress=? WHERE id=?",(json.dumps({"global_scheduled":True}),identity))
            if database_id:
                c.execute("UPDATE runs SET progress=? WHERE id=?", (json.dumps({"database_id":database_id}),identity))
            c.execute("DELETE FROM controls WHERE run_id=?",(identity,))
            setting=Settings.model_validate_json(c.execute("SELECT value FROM settings WHERE id=1").fetchone()[0])
            c.execute("UPDATE settings SET next_due=? WHERE id=1",(next_due(setting,now()),))
        threading.Thread(target=execute,args=(identity,lock),daemon=True,name="photo-sync").start()
    except Exception:
        lock.__exit__(None,None,None); raise
    return {"id":identity,"state":"running"}

@router.post("/now",status_code=202)
def sync_now(): return start_run()

def tick(instant=None):
    instant=instant or now()
    with core.db() as c:
        due=[dict(r) for r in c.execute("SELECT * FROM library_databases WHERE sync_enabled=1 AND schedule IS NOT NULL AND next_due IS NOT NULL ORDER BY next_due") if datetime.fromisoformat(r["next_due"])<=instant]
    for d in due:
        with store() as c:
            previous=c.execute("SELECT state FROM runs WHERE json_extract(progress,'$.database_id')=? ORDER BY coalesce(finished,started) DESC LIMIT 1",(d["id"],)).fetchone()
        if previous and previous[0] in ("paused","cancelled","interrupted"): continue
        try:
            result=start_run("scheduled",database_id=d["id"])
        except HTTPException as e:
            if e.status_code!=409: raise
            return
        with core.db() as c:
            c.execute("UPDATE library_databases SET next_due=? WHERE id=?",(next_due(Settings.model_validate_json(d["schedule"]),instant),d["id"]))
        return result
    with store() as c: row=c.execute("SELECT * FROM settings WHERE id=1").fetchone()
    with core.db() as c:
        global_roots=c.execute("SELECT 1 FROM library_databases WHERE sync_enabled=1 AND schedule IS NULL LIMIT 1").fetchone()
    if global_roots and row["next_due"] and datetime.fromisoformat(row["next_due"])<=instant:
        try: return start_run("scheduled")
        except HTTPException as e:
            if e.status_code!=409: raise

stop_event=threading.Event()
scheduler=None
def recover_interrupted_runs():
    try:
        with scan_lock(),store() as c:
            c.execute("UPDATE runs SET state='interrupted',finished=?,error='Backend restarted or database reconnected; resume this run from its checkpoint' WHERE state IN ('running','pausing','cancelling')",(now().isoformat(),))
    except RuntimeError: pass
    except (OSError,sqlite3.Error):
        logging.getLogger(__name__).exception("Database storage unavailable during scan recovery")


def start_scheduler():
    global scheduler
    if scheduler and scheduler.is_alive(): return
    recover_interrupted_runs()
    if os.environ.get("DAHAN_DISABLE_SCHEDULER")=="1": return
    stop_event.clear()
    def loop():
        while not stop_event.is_set():
            try: tick()
            except Exception:
                import logging
                logging.getLogger(__name__).exception("Scheduler check failed")
            stop_event.wait(30)
    scheduler=threading.Thread(target=loop,daemon=True,name="photo-sync-scheduler"); scheduler.start()

def stop_scheduler():
    stop_event.set()
    if scheduler: scheduler.join(timeout=2)

@router.get("/assignments")
def automatic_assignments():
    with core.db() as c:
        rows=c.execute("""SELECT f.id,f.media_id,f.person_id,p.name FROM faces f JOIN people p ON p.id=f.person_id
            JOIN media m ON m.id=f.media_id WHERE f.status='auto-sync' AND m.status='ready' ORDER BY f.id LIMIT 100""").fetchall()
        actions=[]
        for r in c.execute("SELECT id,description,created,previous FROM actions WHERE undone=0 AND description='Automatic sync face assignments' ORDER BY id DESC LIMIT 10"):
            payload=json.loads(r["previous"])
            actions.append({"id":r["id"],"created":r["created"],"count":len(payload.get("faces",[]))})
        return {"faces":[dict(r) for r in rows],"actions":actions}

@router.post("/assignments/{action_id}/undo")
def undo_assignments(action_id:int):
    with core.db() as c:
        c.execute("BEGIN IMMEDIATE")
        action=c.execute("SELECT * FROM actions WHERE id=? AND undone=0 AND description='Automatic sync face assignments'",(action_id,)).fetchone()
        if action is None: raise HTTPException(404,"Automatic assignment batch not found or already undone")
        count=0
        for old in json.loads(action["previous"]).get("faces",[]):
            row=c.execute("SELECT person_id,status FROM faces WHERE id=?",(old["id"],)).fetchone()
            if row and row["status"]=="auto-sync" and row["person_id"]==old["target"]:
                c.execute("UPDATE faces SET person_id=?,status=? WHERE id=?",(old["person_id"],old["status"],old["id"]))
                c.execute("INSERT OR IGNORE INTO face_rejections VALUES(?,?)",(old["id"],old["target"]))
                if old.get("unknown"): c.execute("INSERT OR IGNORE INTO unknown_faces VALUES(?)",(old["id"],))
                count+=1
        c.execute("UPDATE actions SET undone=1 WHERE id=?",(action_id,))
        c.execute("DELETE FROM face_suggestions")
        c.execute("DELETE FROM high_confidence_faces")
    return {"restored":count}

@router.get("/errors")
def media_errors():
    with core.db() as c:
        return [dict(r) for r in c.execute("SELECT id,name,error FROM media WHERE status NOT IN ('missing','superseded') AND error IS NOT NULL ORDER BY name LIMIT 50")]
