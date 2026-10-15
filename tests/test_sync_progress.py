"""Long network scan controls and progress, using disposable local originals only."""
import importlib
import os
import time
from pathlib import Path
import pytest
from tests.test_sync import service, make_file
from tests.test_catalogue import client


@pytest.fixture
def run(service,monkeypatch):
    s,core=service
    from backend import incremental_import
    # These tests isolate hash checkpoints and the established durable queue.
    # Real incremental preview publication is covered by test_incremental_import.
    class NoPreviewPublisher:
        def __init__(self,identity):pass
        def process(self,ids):pass
        def close(self):pass
    monkeypatch.setattr(incremental_import,'PreviewPublisher',NoPreviewPublisher)
    with s.store() as c:
        c.execute("INSERT INTO runs VALUES('progress-run',?,NULL,'running','manual','{}',NULL)",(s.now().isoformat(),))
    s.worker_context.run_id='progress-run'
    s.worker_context.pending_progress={}
    s.worker_context.last_progress=0
    s.worker_context.database_id=None
    s.worker_context.global_scheduled=False
    yield s,core
    s.worker_context.run_id=None
    s.worker_context.pending_progress={}
    s.live_progress.clear()


def test_current_file_visible_during_slow_hash_before_next_persisted_update(run,monkeypatch):
    s,core=run
    file=make_file(core,'nested/A/B/movie.mp4')
    original=s.digest_stable
    def slow_hash(path,entry):
        p=s.status()['runs'][0]['progress']
        assert p['phase']=='Checking file contents'
        assert p['current_folder']==str(file.parent)
        assert p['current_file']=='movie.mp4'
        assert p['processed']==0 and p['total']==1
        assert p['updated_at']
        return original(path,entry)
    monkeypatch.setattr(s,'digest_stable',slow_hash)
    assert s.reconcile(s.inventory())['added']==1
    assert s.status()['runs'][0]['progress']['processed']==1


def pause_after_one_hash(s,core,monkeypatch):
    first=make_file(core,'a.jpg')
    second=make_file(core,'b.jpg',b'second photo')
    original=s.digest_stable
    calls=[]
    def stopping_hash(path,entry):
        calls.append(path)
        digest=original(path,entry)
        if len(calls)==1:s.control_run('progress-run','pause')
        return digest
    monkeypatch.setattr(s,'digest_stable',stopping_hash)
    with pytest.raises(s.SyncStopped):s.reconcile(s.inventory())
    assert calls==[str(first)]
    with s.store() as c:
        assert c.execute('SELECT count(*) FROM file_hashes').fetchone()[0]==1
        c.execute("DELETE FROM controls")
    with core.db() as c:
        assert not c.execute('SELECT 1 FROM media WHERE path=?',(str(first),)).fetchone()
        assert c.execute('SELECT count(*) FROM faces').fetchone()[0]==3
    return first,second,original


def test_pause_resume_reuses_completed_hash_after_backend_restart(run,monkeypatch):
    s,core=run
    first,second,original=pause_after_one_hash(s,core,monkeypatch)
    importlib.reload(s)  # No in-memory hash state survives.
    s.worker_context.run_id='progress-run'
    calls=[]
    def resumed_hash(path,entry):
        calls.append(path)
        return original(path,entry)
    monkeypatch.setattr(s,'digest_stable',resumed_hash)
    assert s.reconcile(s.inventory())['added']==2
    assert calls==[str(second)]
    assert s.status()['runs'][0]['progress']['hashes_reused']==1
    assert first.read_bytes()==b'photo'


def test_changed_file_does_not_reuse_saved_hash(run,monkeypatch):
    s,core=run
    first,second,original=pause_after_one_hash(s,core,monkeypatch)
    first.write_bytes(b'changed original in isolated fixture')
    os.utime(first,(time.time()-60,time.time()-60))
    calls=[]
    def hash_again(path,entry):
        calls.append(path)
        return original(path,entry)
    monkeypatch.setattr(s,'digest_stable',hash_again)
    assert s.reconcile(s.inventory())['added']==2
    assert calls==[str(first),str(second)]
    assert s.status()['runs'][0]['progress']['hashes_reused']==0


def test_inventory_can_pause_inside_one_large_directory_and_reports_unknown_total(run,monkeypatch):
    s,core=run
    from backend import source_management as sm
    for n in range(5):make_file(core,f'{n}.jpg')
    observed=[]
    def progress(**kw):
        observed.append(kw)
        if kw.get('media_delta')==1:s.control_run('progress-run','pause')
    with pytest.raises(s.SyncStopped):
        sm.walk(core.ROOT/core.PHONES[0],control=s.check_control,progress=progress)
    assert sum(p.get('media_delta',0) for p in observed)==1
    assert any(p.get('current_file')=='0.jpg' for p in observed)


def test_inventory_live_folder_counts_all_nested_media(run):
    s,core=run
    from backend import source_management as sm
    make_file(core,'A/B/img.jpg');make_file(core,'A/B/video.mp4')
    s.report_progress(force=True,phase='Reading source folders',total=None)
    files=s.inventory()
    p=s.status()['runs'][0]['progress']
    assert len(files)==2
    assert p['media_found']==2 and p['folders_checked']>=4
    assert p['total'] is None
    assert Path(p['current_folder']).is_relative_to(core.ROOT)


def test_paused_execute_persists_progress_and_releases_lock(run,monkeypatch):
    s,core=run
    make_file(core)
    s.control_run('progress-run','pause')
    lock=s.scan_lock();lock.__enter__()
    s.execute('progress-run',lock)
    assert s.status()['runs'][0]['state']=='paused'
    assert s.status_progress('progress-run')['phase']=='Paused at checkpoint'
    with s.scan_lock():pass


def test_completed_execute_cleans_hash_checkpoint_and_stale_paths(run,monkeypatch):
    s,core=run
    make_file(core)
    s.save_settings(s.Settings(frequency='off',auto_assign=False))
    monkeypatch.setattr(s,'process_pending',lambda identity:0)
    from backend import full_scan
    monkeypatch.setattr(full_scan,'assign_new_faces',lambda **kw:0)
    lock=s.scan_lock();lock.__enter__()
    s.execute('progress-run',lock)
    result=s.status()['runs'][0]
    assert result['state']=='completed'
    assert result['progress']['current_file']==''
    assert result['progress']['total'] is None
    with s.store() as c:assert c.execute('SELECT count(*) FROM file_hashes').fetchone()[0]==0


def test_preview_queue_reports_current_file_and_resume_skips_completed_work(run,monkeypatch):
    s,core=run
    import multiprocessing
    first=make_file(core,'preview-a.jpg');second=make_file(core,'preview-b.jpg')
    s.reconcile(s.inventory())
    with core.db() as c:
        c.execute("UPDATE media SET face_status='ready'")
        ids={r['path']:r['id'] for r in c.execute('SELECT id,path FROM media')}
    processed=[]
    class Result:
        def __init__(self,mid):self.mid=mid
        def get(self,timeout):
            p=s.status()['runs'][0]['progress']
            assert p['phase']=='Publishing previews'
            assert p['current_file']==('preview-a.jpg' if self.mid==ids[str(first)] else 'preview-b.jpg')
            processed.append(self.mid)
            with core.db() as c:c.execute("UPDATE media SET status='ready' WHERE id=?",(self.mid,))
            if len(processed)==1:s.control_run('progress-run','pause')
            return dict(id=self.mid,ok=True)
    class Pool:
        def __init__(self,*args,**kwargs):pass
        def apply_async(self,fn,args):return Result(args[0])
        def terminate(self):pass
        def join(self):pass
    class Context:
        def Pool(self,*args,**kwargs):return Pool(*args,**kwargs)
    monkeypatch.setattr(multiprocessing,'get_context',lambda *args:Context())
    with pytest.raises(s.SyncStopped):s.process_pending('progress-run')
    assert len(processed)==1
    with s.store() as c:
        assert c.execute('SELECT count(*) FROM work WHERE done=1').fetchone()[0]==1
        c.execute('DELETE FROM controls')
    assert s.process_pending('progress-run')==0
    assert len(processed)==2
    assert set(processed)=={ids[str(first)],ids[str(second)]}
