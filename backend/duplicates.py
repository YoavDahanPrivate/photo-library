"""Exact duplicate review and reversible, journalled moves to source-local trash."""
import hashlib, json, os, threading, uuid
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from . import core, sync_service as sync

router=APIRouter(prefix="/api/duplicates",tags=["Library tools"])

def init():
    with core.db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS duplicate_jobs(id TEXT PRIMARY KEY,kind TEXT,state TEXT,progress TEXT,error TEXT,created TEXT);
        CREATE TABLE IF NOT EXISTS duplicate_groups(id TEXT PRIMARY KEY,job_id TEXT,keeper TEXT,members TEXT,taken TEXT,sha TEXT);
        CREATE TABLE IF NOT EXISTS duplicate_rules(group_id TEXT PRIMARY KEY,mode TEXT);
        CREATE TABLE IF NOT EXISTS duplicate_trash(media_id TEXT PRIMARY KEY,keeper TEXT,source TEXT,trash TEXT,sha TEXT,taken TEXT,previous_status TEXT,state TEXT,error TEXT,created TEXT);
        """)

def job_update(identity,**values):
    with core.db() as c:
        row=c.execute("SELECT progress FROM duplicate_jobs WHERE id=?",(identity,)).fetchone()
        progress=json.loads(row[0] or "{}");progress.update(values.pop("progress",{}))
        values["progress"]=json.dumps(progress)
        c.execute("UPDATE duplicate_jobs SET "+",".join(k+"=?" for k in values)+" WHERE id=?",[*values.values(),identity])

def exact_hash(row):
    path=core.original(row)
    if not path.is_file() or path.is_symlink(): raise ValueError("Source file is unavailable")
    before=path.stat()
    if (before.st_size,before.st_mtime)!=(row["bytes"],row["mtime"]): raise ValueError("Source changed; sync it before duplicate cleanup")
    h=hashlib.sha256()
    with path.open("rb") as f:
        while block:=f.read(4*1024*1024): h.update(block)
    after=path.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns): raise ValueError("Source changed while checking")
    return h.hexdigest()

def recover():
    # Called only under scan_lock. Finish catalogue bookkeeping after an interrupted atomic move.
    init()
    with core.db() as c:
        for r in c.execute("SELECT * FROM duplicate_trash WHERE state IN ('moving','restoring')").fetchall():
            source=Path(r["source"]); trash=Path(r["trash"])
            if trash.is_file() and not source.exists():
                c.execute("UPDATE media SET status='trashed' WHERE id=?",(r["media_id"],))
                c.execute("UPDATE duplicate_trash SET state='trashed',error=NULL WHERE media_id=?",(r["media_id"],))
            elif source.is_file() and not trash.exists():
                state="restored" if r["state"]=="restoring" else "failed"
                if state=="restored": c.execute("UPDATE media SET status=?,error=NULL WHERE id=?",(r["previous_status"],r["media_id"]))
                c.execute("UPDATE duplicate_trash SET state=?,error=? WHERE media_id=?",(state,None if state=="restored" else "Move was interrupted before completion",r["media_id"]))
            else:
                c.execute("UPDATE duplicate_trash SET state='attention',error='Source/trash conflict; no file overwritten' WHERE media_id=?",(r["media_id"],))
        c.execute("UPDATE duplicate_jobs SET state='interrupted',error='Backend stopped; completed file moves are saved. Review trash or run detection again.' WHERE state='running'")

MEDIA_FIELDS="m.id,m.path,m.phone,m.album,m.name,m.kind,m.bytes,m.mtime,m.sha,m.taken,m.width,m.height,m.extension"
def format_key(row):
    if row["kind"]!="photo" or (row["extension"] or "").lower() not in (".heic",".jpg",".jpeg") or not row["taken"] or not row["width"] or not row["height"]: return None
    return (row["phone"],Path(row["name"]).stem.casefold(),row["taken"],row["width"],row["height"])

def detect_formats(job_id,keep_format):
    with core.db() as c:
        rows=[dict(r) for r in c.execute("SELECT "+MEDIA_FIELDS+" FROM media m WHERE status='ready' AND taken IS NOT NULL AND kind='photo'")]
    grouped={}
    for row in rows:
        key=format_key(row)
        if key: grouped.setdefault(key,[]).append(row)
    candidates=[members for members in grouped.values() if any(r["extension"].lower()==".heic" for r in members) and any(r["extension"].lower() in (".jpg",".jpeg") for r in members)]
    count=extras=checked=0;errors=[];total=sum(len(g) for g in candidates)
    job_update(job_id,progress=dict(total=total,checked=0,mode="heic_jpeg",keep_format=keep_format))
    for members in candidates:
        valid=[]
        for row in members:
            try:
                path=core.original(row);st=path.stat()
                if not row["sha"] or (st.st_size,st.st_mtime)!=(row["bytes"],row["mtime"]):
                    raise ValueError("Source changed or hash unavailable; sync this file first")
                valid.append(row)
            except (OSError,ValueError) as e: errors.append(dict(name=row["name"],error=str(e)))
            checked+=1
        if any(r["extension"].lower()==".heic" for r in valid) and any(r["extension"].lower() in (".jpg",".jpeg") for r in valid):
            def preferred(r):
                return r["extension"].lower()==".heic" if keep_format=="heic" else r["extension"].lower() in (".jpg",".jpeg")
            valid.sort(key=lambda r:(not preferred(r),r["path"].casefold()))
            identity=uuid.uuid4().hex
            with core.db() as c:
                c.execute("INSERT INTO duplicate_groups VALUES(?,?,?,?,?,NULL)",(identity,job_id,valid[0]["id"],json.dumps(valid),valid[0]["taken"]))
                c.execute("INSERT INTO duplicate_rules VALUES(?,'heic_jpeg')",(identity,))
            count+=1;extras+=len(valid)-1
        if checked%100< len(members) or checked==total:
            job_update(job_id,progress=dict(checked=checked,total=total,groups=count,extra_copies=extras,errors=errors[:50],error_count=len(errors)))
    job_update(job_id,progress=dict(checked=checked,total=total,groups=count,extra_copies=extras,errors=errors[:50],error_count=len(errors)),state="completed_with_issues" if errors else "completed")

def detect(job_id,mode="exact",keep_format="heic"):
    if mode=="heic_jpeg": return detect_formats(job_id,keep_format)
    job_update(job_id,progress=dict(mode="exact"))
    with core.db() as c:
        rows=[dict(r) for r in c.execute("SELECT "+MEDIA_FIELDS+""" FROM media m JOIN
          (SELECT taken,bytes FROM media WHERE status='ready' AND taken IS NOT NULL AND taken!=''
           GROUP BY taken,bytes HAVING count(*)>1) candidates ON m.taken=candidates.taken AND m.bytes=candidates.bytes
          WHERE m.status='ready' ORDER BY m.taken,m.path""")]
    grouped={}; errors=[]
    for i,row in enumerate(rows):
        try:
            digest=exact_hash(row)
            grouped.setdefault((row["taken"],digest),[]).append(row)
        except (OSError,ValueError) as e: errors.append({"name":row["name"],"error":str(e)})
        job_update(job_id,progress=dict(checked=i+1,total=len(rows),errors=errors[:50],error_count=len(errors)))
    count=0
    with core.db() as c:
        for (taken,digest),members in grouped.items():
            if len(members)<2: continue
            # Keep the copy with the most manually reviewed identities, then stable path order.
            reviewed={r["id"]:c.execute("SELECT count(*) FROM faces WHERE media_id=? AND status='manual'",(r["id"],)).fetchone()[0] for r in members}
            members.sort(key=lambda r:(-reviewed[r["id"]],r["path"].casefold()))
            summary=[{k:r[k] for k in ("id","name","path","phone","album","bytes","taken")} for r in members]
            c.execute("INSERT INTO duplicate_groups VALUES(?,?,?,?,?,?)",(uuid.uuid4().hex,job_id,members[0]["id"],json.dumps(summary),taken,digest))
            count+=1
    job_update(job_id,progress=dict(groups=count),state="completed_with_issues" if errors else "completed")

def validated_trash_path(row,identity):
    source=core.original(row)
    phone_root=(core.ROOT/row["phone"]).resolve()
    if row["phone"] not in core.PHONES or not source.is_relative_to(phone_root): raise ValueError("Invalid source phone")
    target=phone_root/".dtrash"/"dahan-duplicates"/identity/row["name"]
    if not target.resolve().is_relative_to(phone_root): raise ValueError("Trash folder resolves outside source phone")
    # Do not follow a junction/symlink in a trash ancestor.
    for p in (phone_root/".dtrash",phone_root/".dtrash"/"dahan-duplicates",target.parent):
        if p.is_symlink() or p.is_junction(): raise ValueError("Trash folder must not be a link")
    return source,target

def move_one(mid,group):
    with core.db() as c:
        row=c.execute("SELECT * FROM media WHERE id=?",(mid,)).fetchone()
        keep=c.execute("SELECT * FROM media WHERE id=?",(group["keeper"],)).fetchone()
    if not row or not keep or row["status"]!="ready" or keep["status"]!="ready": raise ValueError("A reviewed copy is no longer available; run detection again")
    if mid==keep["id"] or row["taken"]!=group["taken"] or keep["taken"]!=group["taken"]: raise ValueError("Capture dates no longer match")
    digest=exact_hash(row); kept_digest=exact_hash(keep)
    if group.get("mode","exact")=="heic_jpeg":
        snapshots=group["members"] if isinstance(group["members"],list) else json.loads(group["members"])
        snapshots={r["id"]:r for r in snapshots}
        previous=snapshots.get(mid);kept_previous=snapshots.get(keep["id"])
        if not previous or not kept_previous: raise ValueError("Missing review evidence; run detection again")
        if not format_key(row) or format_key(row)!=format_key(keep) or format_key(row)!=format_key(previous) or format_key(keep)!=format_key(kept_previous):
            raise ValueError("Metadata changed since review; nothing moved")
        if digest!=previous["sha"] or kept_digest!=kept_previous["sha"]:
            raise ValueError("Files changed since review; nothing moved")
    elif digest!=group["sha"] or kept_digest!=group["sha"]:
        raise ValueError("Files changed since review; nothing moved")
    source,target=validated_trash_path(row,uuid.uuid4().hex)
    target.parent.mkdir(parents=True,exist_ok=False)
    with core.db() as c:
        c.execute("INSERT OR REPLACE INTO duplicate_trash VALUES(?,?,?,?,?,?,?,'moving',NULL,?)",(mid,keep["id"],str(source),str(target),digest,row["taken"],row["status"],sync.now().isoformat()))
    # Same-volume, atomic rename. Target has a new random parent and cannot overwrite an existing file.
    os.rename(source,target)
    with core.db() as c:
        c.execute("UPDATE media SET status='trashed' WHERE id=?",(mid,))
        c.execute("UPDATE duplicate_trash SET state='trashed' WHERE media_id=?",(mid,))

def restore_one(mid):
    with core.db() as c: r=c.execute("SELECT * FROM duplicate_trash WHERE media_id=? AND state='trashed'",(mid,)).fetchone()
    if not r: raise ValueError("This copy is not in recoverable trash")
    source=Path(r["source"]);trash=Path(r["trash"])
    with core.db() as c: row=c.execute("SELECT * FROM media WHERE id=?",(mid,)).fetchone()
    if not row or str(core.original(row))!=str(source.resolve()): raise ValueError("Original path changed")
    expected_root=(core.ROOT/row["phone"]/".dtrash"/"dahan-duplicates").resolve()
    if not trash.resolve().is_relative_to(expected_root) or trash.is_symlink(): raise ValueError("Invalid trash path")
    if source.exists(): raise ValueError("Original path is occupied; no file overwritten")
    with trash.open("rb") as f:
        if hashlib.file_digest(f,"sha256").hexdigest()!=r["sha"]: raise ValueError("Trash file changed; restore requires review")
    source.parent.mkdir(parents=True,exist_ok=True)
    with core.db() as c: c.execute("UPDATE duplicate_trash SET state='restoring' WHERE media_id=?",(mid,))
    os.rename(trash,source)
    with core.db() as c:
        c.execute("UPDATE media SET status=? WHERE id=?",(r["previous_status"],mid))
        c.execute("UPDATE duplicate_trash SET state='restored',error=NULL WHERE media_id=?",(mid,))

class Selection(BaseModel):
    job_id:str
    media_ids:list[str]=Field(min_length=1,max_length=100000)

class RestoreSelection(BaseModel):
    media_ids:list[str]=Field(min_length=1,max_length=100000)

def operate(job_id,kind,plans):
    errors=[]; completed=0
    for i,(mid,group) in enumerate(plans):
        try:
            if kind=="remove": move_one(mid,group)
            else: restore_one(mid)
            completed+=1
        except (OSError,ValueError) as e:
            errors.append(dict(id=mid,error=str(e)))
        job_update(job_id,progress=dict(processed=i+1,total=len(plans),completed=completed,errors=errors[:50],error_count=len(errors)))
    job_update(job_id,state="completed_with_issues" if errors else "completed")

def launch(kind,plans=None,mode="exact",keep_format="heic"):
    lock=sync.scan_lock()
    try: lock.__enter__()
    except RuntimeError: raise HTTPException(409,"Sync or another library operation is active. Pause sync before duplicate cleanup.")
    identity=uuid.uuid4().hex
    try:
        recover()
        with core.db() as c:
            c.execute("INSERT INTO duplicate_jobs VALUES(?,?,'running',?,NULL,?)",(identity,kind,json.dumps(dict(mode=mode,keep_format=keep_format)) if kind=="detect" else "{}",sync.now().isoformat()))
        def worker():
            try:
                if kind=="detect": detect(identity,mode,keep_format)
                else: operate(identity,kind,plans)
            except Exception as e: job_update(identity,state="failed",error=str(e)[:2000])
            finally: lock.__exit__(None,None,None)
        threading.Thread(target=worker,daemon=True,name="duplicate-cleanup").start()
    except Exception:
        lock.__exit__(None,None,None);raise
    return {"id":identity,"state":"running"}

class DetectionRequest(BaseModel):
    mode:Literal["exact","heic_jpeg"]="exact"
    keep_format:Literal["heic","jpeg"]="heic"

@router.post("/detect",status_code=202)
def start_detection(body:DetectionRequest=DetectionRequest()):
    return launch("detect",mode=body.mode,keep_format=body.keep_format)

@router.post("/remove",status_code=202)
def remove(body:Selection):
    init()
    with core.db() as c:
        job=c.execute("SELECT * FROM duplicate_jobs WHERE id=? AND kind='detect'",(body.job_id,)).fetchone()
        if not job or job["state"] not in ("completed","completed_with_issues"): raise HTTPException(409,"Wait for duplicate detection to finish")
        groups=[dict(r) for r in c.execute("SELECT * FROM duplicate_groups WHERE job_id=?",(body.job_id,))]
    with core.db() as c:
        for group in groups:
            rule=c.execute("SELECT mode FROM duplicate_rules WHERE group_id=?",(group["id"],)).fetchone()
            group["mode"]=rule[0] if rule else "exact"
    candidates={m["id"]:g for g in groups for m in json.loads(g["members"]) if m["id"]!=g["keeper"]}
    selected=list(dict.fromkeys(body.media_ids))
    if any(mid not in candidates for mid in selected): raise HTTPException(422,"Only reviewed extra copies may be removed; keep one copy per group")
    return launch("remove",[(mid,candidates[mid]) for mid in selected])

@router.post("/restore",status_code=202)
def restore(body:RestoreSelection): return launch("restore",[(mid,None) for mid in dict.fromkeys(body.media_ids)])

@router.get("/status")
def status():
    init()
    with core.db() as c:
        jobs=[{**dict(r),"progress":json.loads(r["progress"])} for r in c.execute("SELECT * FROM duplicate_jobs ORDER BY created DESC LIMIT 10")]
        trash=c.execute("SELECT count(*) FROM duplicate_trash WHERE state='trashed'").fetchone()[0]
        reviews=[{**dict(r),"progress":json.loads(r["progress"])} for r in c.execute("SELECT * FROM duplicate_jobs WHERE kind='detect' AND state IN ('completed','completed_with_issues') ORDER BY created DESC LIMIT 20")]
    return {"jobs":jobs,"reviews":reviews,"trash_count":trash,"running":any(j["state"]=="running" for j in jobs)}

@router.get("/groups")
def groups(job_id:str,offset:int=0,limit:int=30):
    init();offset=max(0,offset);limit=max(1,min(100,limit))
    with core.db() as c:
        total=c.execute("SELECT count(*) FROM duplicate_groups WHERE job_id=?",(job_id,)).fetchone()[0]
        rows=[{**dict(r),"members":json.loads(r["members"])} for r in c.execute("SELECT * FROM duplicate_groups WHERE job_id=? ORDER BY id LIMIT ? OFFSET ?",(job_id,limit,offset))]
        for group in rows:
            rule=c.execute("SELECT mode FROM duplicate_rules WHERE group_id=?",(group["id"],)).fetchone()
            group["mode"]=rule[0] if rule else "exact"
            for m in group["members"]:
                current=c.execute("SELECT status FROM media WHERE id=?",(m["id"],)).fetchone()
                m["available"]=bool(current and current[0]=="ready")
    return {"groups":rows,"total":total}

@router.get("/trash")
def trash():
    init()
    with core.db() as c:
        return [dict(r) for r in c.execute("SELECT t.*,m.name FROM duplicate_trash t JOIN media m ON m.id=t.media_id WHERE t.state IN ('trashed','attention','moving','restoring') ORDER BY t.created DESC LIMIT 200")]


@router.get("/selection")
def selection(job_id:str):
    """All eligible extra copies in this completed review, across every page."""
    init()
    with core.db() as c:
        job=c.execute("SELECT state FROM duplicate_jobs WHERE id=? AND kind='detect'",(job_id,)).fetchone()
        if not job or job[0] not in ("completed","completed_with_issues"):
            raise HTTPException(409,"Choose a completed duplicate check")
        available={r[0] for r in c.execute("SELECT id FROM media WHERE status='ready'")}
        ids=[]; extra_total=0
        for r in c.execute("SELECT keeper,members FROM duplicate_groups WHERE job_id=?",(job_id,)):
            extras=[m["id"] for m in json.loads(r["members"]) if m["id"]!=r["keeper"]]
            extra_total+=len(extras)
            if r["keeper"] in available: ids.extend(mid for mid in extras if mid in available)
    return {"media_ids":list(dict.fromkeys(ids)),"extra_total":extra_total}


@router.get("/trash-page")
def trash_page(offset:int=0,limit:int=30):
    init();offset=max(0,offset);limit=max(1,min(100,limit))
    with core.db() as c:
        where="t.state IN ('trashed','attention','moving','restoring')"
        total=c.execute("SELECT count(*) FROM duplicate_trash t WHERE "+where).fetchone()[0]
        items=[dict(r) for r in c.execute("SELECT t.*,m.name,m.phone,m.kind FROM duplicate_trash t JOIN media m ON m.id=t.media_id WHERE "+where+" ORDER BY t.created DESC,t.media_id LIMIT ? OFFSET ?",(limit,offset))]
    return {"items":items,"total":total}

@router.get("/trash-selection")
def trash_selection():
    init()
    with core.db() as c:
        ids=[r[0] for r in c.execute("SELECT media_id FROM duplicate_trash WHERE state='trashed' ORDER BY created,media_id")]
    return {"media_ids":ids}
