"""Persistent calendar scheduler and incremental, read-only-source synchronization."""
import calendar, hashlib, json, os, sqlite3, threading, time, uuid
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
    timezone: str = "Asia/Jerusalem"
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

@contextmanager
def store():
    core.DATA.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(core.DATA/"sync.sqlite",timeout=30)
    c.row_factory=sqlite3.Row
    try:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1),value TEXT,next_due TEXT);
        CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,started TEXT,finished TEXT,state TEXT,reason TEXT,progress TEXT,error TEXT);
        CREATE TABLE IF NOT EXISTS controls(run_id TEXT PRIMARY KEY,request TEXT);
        CREATE TABLE IF NOT EXISTS work(run_id TEXT,media_id TEXT,stage TEXT,done INTEGER DEFAULT 0,error TEXT,PRIMARY KEY(run_id,media_id,stage));
        """)
        if not c.execute("SELECT 1 FROM settings").fetchone():
            s=Settings()
            c.execute("INSERT OR IGNORE INTO settings VALUES(1,?,?)",(s.model_dump_json(),next_due(s,now())))
        c.commit()
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
        return {"settings":json.loads(s["value"]),"next_due":s["next_due"],"runs":runs,"running":any(r["state"] in ("running","pausing","cancelling") for r in runs)}

@router.put("/settings")
def save_settings(body:Settings):
    with store() as c: c.execute("UPDATE settings SET value=?,next_due=? WHERE id=1",(body.model_dump_json(),next_due(body,now())))
    return status()

@contextmanager
def scan_lock():
    import msvcrt
    core.DATA.mkdir(parents=True,exist_ok=True)
    f=(core.DATA/"full-scan.lock").open("a+b")
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
    from .indexer import IMAGES,VIDEOS
    result={}
    for phone in core.PHONES:
        base=core.ROOT/phone
        if not base.is_dir() or base.is_symlink() or base.is_junction(): raise RuntimeError("Source unavailable: "+str(base))
        def failed(e): raise e
        for folder,dirs,names in os.walk(base,followlinks=False,onerror=failed):
            check_control()
            dirs[:]=[n for n in dirs if n not in (".dtrash","PhotoPrismStorage","$RECYCLE.BIN") and not Path(folder,n).is_symlink() and not Path(folder,n).is_junction()]
            for name in names:
                p=Path(folder,name)
                if p.suffix.lower() not in IMAGES|VIDEOS or p.is_symlink(): continue
                stat=p.stat()
                relative=p.relative_to(base)
                result[str(p)]=dict(path=str(p),phone=phone,album=relative.parts[0] if len(relative.parts)>1 else "(Phone root)",
                                   name=name,extension=p.suffix.lower(),kind="video" if p.suffix.lower() in VIDEOS else "photo",
                                   bytes=stat.st_size,mtime=stat.st_mtime)
        if not base.is_dir(): raise RuntimeError("Source disconnected during inventory: "+str(base))
    return result

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
        rows={r["path"]:dict(r) for r in c.execute("SELECT * FROM media WHERE status!='superseded'")}
    absent=[r for p,r in rows.items() if p not in files]
    by_hash={}
    for r in absent:
        if r["sha"] and r["status"]!="trashed": by_hash.setdefault((r["bytes"],r["sha"]),[]).append(r)
    fresh={}; changes={}; deferred=0
    for path,entry in files.items():
        check_control()
        old=rows.get(path)
        if old and old["status"]!="trashed" and (old["bytes"],old["mtime"])==(entry["bytes"],entry["mtime"]): continue
        if time.time()-entry["mtime"]<30: deferred+=1; continue
        digest=digest_stable(path,entry)
        (changes if old else fresh)[path]=digest
    if any(not (core.ROOT/p).is_dir() for p in core.PHONES): raise RuntimeError("Source disconnected; catalogue not reconciled")
    report=dict(added=0,changed=0,moved=0,missing=0,restored=0,deferred=deferred)
    claimed=set()
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
        for path,entry in files.items():
            old=rows.get(path)
            if old:
                if path not in changes:
                    if (old["bytes"],old["mtime"])==(entry["bytes"],entry["mtime"]): restore(old)
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
                matches=[r for r in by_hash.get((entry["bytes"],digest),[]) if r["id"] not in claimed]
                if len(matches)==1:
                    old=matches[0]; claimed.add(old["id"])
                    c.execute("UPDATE media SET path=?,phone=?,album=?,name=?,mtime=? WHERE id=?",(path,entry["phone"],entry["album"],entry["name"],entry["mtime"],old["id"]))
                    restore(old); report["moved"]+=1
                else: add(entry,digest); report["added"]+=1
        for row in absent:
            if row["id"] in claimed or row["status"] in ("missing","trashed"): continue
            c.execute("INSERT OR IGNORE INTO sync_missing VALUES(?,?)",(row["id"],row["status"]))
            c.execute("UPDATE media SET status='missing' WHERE id=?",(row["id"],))
            report["missing"]+=1
    return report

def auto_assign_until_stable(progress=lambda **kw:None):
    from .people_review import reevaluate
    assigned=0; passes=0
    while True:
        check_control()
        if not load_settings().auto_assign: return dict(assigned=assigned,passes=passes,stopped_by_setting=True)
        reevaluate()
        passes+=1; previous=[]
        if not load_settings().auto_assign: return dict(assigned=assigned,passes=passes,stopped_by_setting=True)
        with core.db() as c:
            c.execute("BEGIN IMMEDIATE")
            rows=c.execute("""SELECT f.id,f.person_id,f.status,s.person_id target FROM face_suggestions s
                JOIN high_confidence_faces h ON h.face_id=s.face_id JOIN faces f ON f.id=s.face_id
                JOIN media m ON m.id=f.media_id LEFT JOIN people p ON p.id=f.person_id
                WHERE m.status='ready' AND f.status NOT IN ('manual','dismissed','auto-sync')
                AND trim(coalesce(p.name,''))='' AND NOT EXISTS(SELECT 1 FROM face_rejections r WHERE r.face_id=f.id AND r.person_id=s.person_id)""").fetchall()
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
            ids=[r[0] for r in c.execute("SELECT id FROM media WHERE "+sql)]
        with store() as c:
            c.executemany("INSERT OR IGNORE INTO work(run_id,media_id,stage) VALUES(?,?,?)",[(run_id,mid,stage) for mid in ids])
            todo=[r[0] for r in c.execute("SELECT media_id FROM work WHERE run_id=? AND stage=? AND done=0 ORDER BY rowid",(run_id,stage))]
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
                update_run(run_id,phase="Publishing previews" if stage=="preview" else "Recognizing faces and locations",processed=completed+index,total=completed+len(todo))
                try: result=pool.apply_async(full_scan.process_one,(mid,stage=="preview")).get(timeout=240)
                except Exception as e:
                    pool.terminate(); pool.join(); pool=None
                    result=dict(id=mid,ok=False,error=str(e) or "Decoder timed out")
                if not result["ok"]: full_scan.record_error(result)
                with store() as c:
                    c.execute("UPDATE work SET done=1,error=? WHERE run_id=? AND media_id=? AND stage=?",(result.get("error"),run_id,mid,stage))
                update_run(run_id,processed=completed+index+1)
            update_run(run_id,processed=completed+len(todo),total=completed+len(todo))
        finally:
            if pool: pool.terminate(); pool.join()
    with store() as c:
        errors=c.execute("SELECT count(*) FROM work WHERE run_id=? AND error IS NOT NULL",(run_id,)).fetchone()[0]
    update_run(run_id,errors=errors)
    return errors

def execute(run_id,lock_context):
    worker_context.run_id=run_id
    try:
        import shutil
        if shutil.disk_usage(core.DATA).free<10*1024**3: raise RuntimeError("Less than 10 GiB free on the data SSD")
        check_control(run_id)
        with store() as c:
            progress=json.loads(c.execute("SELECT progress FROM runs WHERE id=?",(run_id,)).fetchone()[0])
        if not progress.get("reconciled"):
            update_run(run_id,phase="Reading source folders")
            files=inventory()
            update_run(run_id,phase="Reconciling files",inventory=len(files))
            report=reconcile(files); update_run(run_id,**report,reconciled=True)
        errors=process_pending(run_id)
        check_control(run_id)
        if load_settings().auto_assign:
            update_run(run_id,phase="Matching faces")
            prior=status_progress(run_id)
            auto_assign_until_stable(lambda **kw:update_run(run_id,assigned=prior.get("assigned",0)+kw["assigned"],passes=prior.get("passes",0)+kw["passes"]))
        from .full_scan import assign_new_faces
        update_run(run_id,phase="Grouping unnamed faces")
        while True:
            check_control(run_id)
            if not assign_new_faces(allow_named=False): break
        check_control(run_id)
        update_run(run_id,phase="Finished")
        with store() as c:
            c.execute("UPDATE runs SET state=?,finished=? WHERE id=?",("completed_with_issues" if errors or status_progress(run_id).get("deferred") else "completed",now().isoformat(),run_id))
    except SyncStopped as e:
        state="paused" if e.request=="pause" else "cancelled"
        update_run(run_id,phase="Paused at checkpoint" if state=="paused" else "Cancelled; progress saved")
        with store() as c:
            c.execute("UPDATE runs SET state=?,finished=? WHERE id=?",(state,now().isoformat(),run_id))
    except Exception as e:
        with store() as c: c.execute("UPDATE runs SET state='failed',finished=?,error=? WHERE id=?",(now().isoformat(),str(e)[:2000],run_id))
    finally:
        worker_context.run_id=None
        try:
            with store() as c:
                row=c.execute("SELECT * FROM settings WHERE id=1").fetchone()
                if row["next_due"] and datetime.fromisoformat(row["next_due"])<=now():
                    c.execute("UPDATE settings SET next_due=? WHERE id=1",(next_due(Settings.model_validate_json(row["value"]),now()),))
        finally: lock_context.__exit__(None,None,None)

def status_progress(run_id):
    with store() as c: return json.loads(c.execute("SELECT progress FROM runs WHERE id=?",(run_id,)).fetchone()[0] or "{}")

def start_run(reason="manual",resume_id=None):
    lock=scan_lock()
    try: lock.__enter__()
    except RuntimeError as e: raise HTTPException(409,str(e))
    identity=resume_id or uuid.uuid4().hex
    try:
        with store() as c:
            # Respect a user's paused/cancelled run: scheduled work waits for an explicit resume or new sync.
            if reason == "scheduled":
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
                c.execute("UPDATE runs SET state='running',finished=NULL,error=NULL WHERE id=?",(resume_id,))
            else:
                c.execute("INSERT INTO runs VALUES(?,?,NULL,'running',?,'{}',NULL)",(identity,now().isoformat(),reason))
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
    with store() as c: row=c.execute("SELECT * FROM settings WHERE id=1").fetchone()
    if row["next_due"] and datetime.fromisoformat(row["next_due"])<=instant:
        try: return start_run("scheduled")
        except HTTPException as e:
            if e.status_code!=409: raise

stop_event=threading.Event()
scheduler=None
def start_scheduler():
    global scheduler
    if os.environ.get("DAHAN_DISABLE_SCHEDULER")=="1" or scheduler and scheduler.is_alive(): return
    stop_event.clear()
    try:
        with scan_lock(),store() as c:
            c.execute("UPDATE runs SET state='interrupted',finished=?,error='Backend restarted; resume this run from its checkpoint' WHERE state IN ('running','pausing','cancelling')",(now().isoformat(),))
    except RuntimeError: pass
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
