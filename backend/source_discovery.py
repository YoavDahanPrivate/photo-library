"""Complete directory discovery in a cancellable, isolated helper process."""
import atexit
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
from fastapi import APIRouter,HTTPException
from . import source_management as sm

class DiscoveryRequest(sm.Layout):
    database_id:str|None=None

router=APIRouter(prefix='/api/databases/folder-discovery',tags=['Folder discovery'])
_jobs={};_lock=threading.RLock()


def stop(job):
    job['cancel'].set()
    process=job.get('process')
    if process and process.poll() is None:process.kill()


def cancel_all():
    with _lock:
        for job in _jobs.values():stop(job)
atexit.register(cancel_all)


def worker(job,body):
    process=None
    try:
        from .network_access import ensure_access
        ensure_access(body.root)
        if job['cancel'].is_set():return
        process=subprocess.Popen([sys.executable,'-B','-m','backend.source_preview','--discover'],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            text=True,encoding='utf-8',creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0,
            cwd=Path(__file__).resolve().parents[1])
        with _lock:job['process']=process;job['last_progress']=time.monotonic()
        import os
        process.stdin.write(json.dumps({'root':body.root,'exclusions':body.exclusions,'parent_pid':os.getpid()}));process.stdin.close()
        def monitor():
            while process.poll() is None:
                if job['cancel'].wait(.25):
                    if process.poll() is None:process.kill()
                    return
                if time.monotonic()-job['last_progress']>30:
                    with _lock:job['error']='A folder listing stopped responding for 30 seconds. Check network access and retry.'
                    if process.poll() is None:process.kill()
                    return
        threading.Thread(target=monitor,daemon=True).start()
        result=None
        for line in process.stdout:
            message=json.loads(line)
            with _lock:
                job['last_progress']=time.monotonic()
                if message.get('progress'):job['progress']=message['progress']
            if 'result' in message:result=message['result']
            if message.get('error'):raise RuntimeError(message['error'])
        process.wait()
        if job['cancel'].is_set():return
        if not result:raise RuntimeError(job.get('error') or 'Folder discovery could not complete. Retry after checking folder access.')
        preview=sm.build_preview(body,did=body.database_id,structure_override=result,persist=body.database_id is None)
        with _lock:job.update(state='complete',preview=preview)
    except (OSError,ValueError,RuntimeError,HTTPException) as error:
        with _lock:
            if not job['cancel'].is_set():job.update(state='failed',error=job.get('error') or str(getattr(error,'detail',error)))
    except Exception:
        with _lock:
            if not job['cancel'].is_set():job.update(state='failed',error='Folder discovery could not complete. Check backend diagnostics and retry.')
    finally:
        if process:
            if process.poll() is None:process.kill()
            process.wait()
            process.stdout.close();process.stderr.close()
        with _lock:
            if job['cancel'].is_set():job['state']='cancelled'
            job['finished']=time.monotonic()


@router.post('')
def start(body:DiscoveryRequest):
    root=Path(body.root).expanduser()
    if not root.is_absolute():raise HTTPException(422,'Choose an absolute server folder path')
    with sm.core.db() as c:
        if body.database_id and Path(sm.get_database(c,body.database_id)['root'])!=root:
            raise HTTPException(422,'Folder discovery must use the selected Database root')
        sm.validate_overlap(c,Path(__import__('os').path.abspath(root)),body.database_id)
    with _lock:
        for key,old in list(_jobs.items()):
            if old.get('finished',float('inf'))<time.monotonic()-3600:del _jobs[key]
        if sum(j['state']=='running' for j in _jobs.values())>=2:
            raise HTTPException(409,'Two folder discoveries are already running. Cancel one before starting another.')
        key=uuid.uuid4().hex
        job=dict(state='running',cancel=threading.Event(),progress=dict(directories=0,entries=0,media_names=0,current='Connecting'),error=None)
        _jobs[key]=job
        threading.Thread(target=worker,args=(job,body),daemon=True).start()
    return {'id':key,'state':'running'}


@router.get('/{key}')
def status(key:str):
    with _lock:
        job=_jobs.get(key)
        if not job:raise HTTPException(404,'Folder discovery expired; start again')
        return {k:job.get(k) for k in ('state','progress','error','preview')}


@router.post('/{key}/cancel')
def cancel(key:str):
    with _lock:
        job=_jobs.get(key)
        if not job:raise HTTPException(404,'Folder discovery not found')
        if job['state']=='running':stop(job);job['state']='cancelled'
    return {'cancelled':True}
