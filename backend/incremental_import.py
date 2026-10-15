"""Publish verified previews before discovery/checking and recognition finish."""
import multiprocessing as mp
import shutil
import time
import uuid
from pathlib import Path
from . import core

BATCH_SIZE=50


def first_import(database,run_id):
    """Early discovery publication is only safe for a previously empty root.

    Existing catalogues wait for a complete inventory so moves retain their IDs.
    A durable marker allows an interrupted first import to continue publishing.
    Root/layout revisions invalidate the marker after a deliberate migration.
    """
    # Legacy catalogues can still contain unassigned historical records.
    if database['layout']=='legacy':return False
    from . import sync_service as sync
    with sync.store() as c:
        row=c.execute('SELECT root,revision FROM streaming_roots WHERE run_id=? AND database_id=?',(run_id,database['id'])).fetchone()
    if row:
        return (row['root'],row['revision'])==(database['root'],database['revision'])
    with core.db() as c:
        if c.execute('SELECT 1 FROM media WHERE database_id=? LIMIT 1',(database['id'],)).fetchone():return False
    with sync.store() as c:
        c.execute('INSERT OR IGNORE INTO streaming_roots VALUES(?,?,?,?)',(run_id,database['id'],database['root'],database['revision']))
    return True


def publish(entries,run_id,publisher,digests=None):
    """Commit additions, keeping every existing identity/annotation unchanged."""
    added=0; ids=[]; paths=[]
    with core.db() as c:
        for path,entry in entries.items():
            if time.time()-entry['mtime']<30:continue
            row=c.execute('SELECT * FROM media WHERE path=?',(path,)).fetchone()
            if row is None:
                mid=uuid.uuid4().hex[:24];cols=list(entry)
                c.execute('INSERT INTO media(id,'+','.join(cols)+',sha) VALUES('+','.join('?' for _ in range(len(cols)+2))+')',[mid,*entry.values(),(digests or {}).get(path)])
                added+=1
                row=c.execute('SELECT * FROM media WHERE id=?',(mid,)).fetchone()
            if row['status'] in ('pending','error') and (row['bytes'],row['mtime'])==(entry['bytes'],entry['mtime']):ids.append(row['id'])
            paths.append(path)
    from . import sync_service as sync
    if added:
        previous=sync.status_progress(run_id).get('live_added',0)
        sync.report_progress(force=True,live_added=previous+added)
    publisher.process(ids)
    with core.db() as c:
        return added,{path:dict(c.execute('SELECT * FROM media WHERE path=?',(path,)).fetchone()) for path in paths}


class PreviewPublisher:
    def __init__(self,run_id):
        self.run_id=run_id
        self.pool=None

    def process(self,ids):
        from . import sync_service as sync,full_scan
        if not ids:return
        sync.check_control(self.run_id)
        for directory in ('thumbs','frames','faces','previews'):(core.DATA/directory).mkdir(exist_ok=True)
        with sync.store() as c:
            c.executemany('INSERT OR IGNORE INTO work(run_id,media_id,stage) VALUES(?,?,\'preview\')',[(self.run_id,mid) for mid in ids])
            todo=[mid for mid in ids if not c.execute("SELECT done FROM work WHERE run_id=? AND media_id=? AND stage='preview'",(self.run_id,mid)).fetchone()[0]]
            completed=c.execute("SELECT count(*) FROM work WHERE run_id=? AND stage='preview' AND done=1",(self.run_id,)).fetchone()[0]
        if not todo:return
        previous=sync.status_progress(self.run_id)
        for index,mid in enumerate(todo):
            sync.check_control(self.run_id)
            if shutil.disk_usage(core.DATA).free<10*1024**3:raise RuntimeError('Less than 10 GiB free on the data SSD')
            with core.db() as c:row=c.execute('SELECT path FROM media WHERE id=?',(mid,)).fetchone()
            if self.pool is None:self.pool=mp.get_context('spawn').Pool(1,initializer=full_scan.prepare_preview_worker,maxtasksperchild=150)
            sync.report_progress(force=True,phase='Publishing previews',processed=completed+index,total=completed+len(todo),preview_total_growing=True,current_folder=str(Path(row['path']).parent),current_file=Path(row['path']).name)
            try:result=self.pool.apply_async(full_scan.process_one,(mid,True)).get(timeout=240)
            except Exception as error:
                self.close()
                result=dict(id=mid,ok=False,error=str(error) or 'Decoder timed out')
            if not result['ok']:full_scan.record_error(result)
            with sync.store() as c:c.execute("UPDATE work SET done=1,error=? WHERE run_id=? AND media_id=? AND stage='preview'",(result.get('error'),self.run_id,mid))
            sync.report_progress(force=True,previews_published=completed+index+1,processed=completed+index+1)
        sync.report_progress(force=True,phase=previous.get('phase','Reading source folders'),processed=previous.get('processed',0),total=previous.get('total'),preview_total_growing=False,current_folder=previous.get('current_folder',''),current_file=previous.get('current_file',''))

    def close(self):
        if self.pool:
            self.pool.terminate();self.pool.join();self.pool=None
