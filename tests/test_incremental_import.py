"""Actual previews from disposable photos, with synchronous worker transport."""
import os
import time
from pathlib import Path
import pytest
from PIL import Image
from tests.test_catalogue import client
from tests.test_source_management import register,index


def photos(root,count):
    root.mkdir(parents=True,exist_ok=True)
    for i in range(count):
        p=root/f'img-{i:04}.jpg'
        Image.new('RGB',(80,60),(i%255,20,30)).save(p)
        os.utime(p,(time.time()-120,time.time()-120))
    return root


@pytest.fixture
def importing(client,tmp_path,monkeypatch):
    api,core=client
    from backend import sync_service as sync,incremental_import,full_scan
    root=photos(tmp_path/'new-database',105)
    photos(root/'Late'/'A'/'B',2)
    did,_=register(api,root,interpretation='collection')
    with sync.store() as c:c.execute("INSERT INTO runs VALUES('stream-test',?,NULL,'running','manual',?,NULL)",(sync.now().isoformat(),__import__('json').dumps({'database_id':did})))
    sync.worker_context.run_id='stream-test'
    sync.worker_context.database_id=did
    sync.worker_context.global_scheduled=False
    sync.worker_context.pending_progress={}
    sync.worker_context.last_progress=0
    sync.worker_context.preview_publisher=None
    sync.report_progress(force=True,phase='Reading source folders',total=None)
    class Result:
        def __init__(self,result):self.result=result
        def get(self,timeout):return self.result
    class Pool:
        def __init__(self,*args,**kw):pass
        def apply_async(self,fn,args):return Result(fn(*args))
        def terminate(self):pass
        def join(self):pass
    class Context:
        def Pool(self,*args,**kw):return Pool(*args,**kw)
    monkeypatch.setattr(incremental_import.mp,'get_context',lambda *args:Context())
    class NoRecognition:
        def process(self,*args):pytest.fail('Faces must not delay publishing previews')
    monkeypatch.setattr(full_scan,'recognizer',NoRecognition())
    yield api,core,sync,root,did
    publisher=getattr(sync.worker_context,'preview_publisher',None)
    if publisher:publisher.close()
    sync.worker_context.preview_publisher=None
    sync.worker_context.run_id=None
    sync.worker_context.database_id=None
    sync.worker_context.pending_progress={}
    sync.live_progress.clear()


def test_first_import_visible_before_later_directories_and_without_faces(importing,monkeypatch):
    api,core,sync,root,did=importing
    from backend import source_management as sm
    from backend.discovery_checkpoint import DiscoveryCheckpoint
    listing=DiscoveryCheckpoint.list_directory;observed=[]
    def monitored(directory,*args):
        if directory!=root:
            visible=api.get('/api/media',params={'database_ids':did}).json()
            assert visible['total']>=105
            assert (core.DATA/'thumbs'/f"{visible['items'][0]['id']}-small.jpg").is_file()
            with core.db() as c:
                assert not c.execute('SELECT 1 FROM media WHERE database_id=? AND face_status=\'ready\'',(did,)).fetchone()
            observed.append(directory)
        return listing(directory,*args)
    monkeypatch.setattr(DiscoveryCheckpoint,'list_directory',staticmethod(monitored))
    files=sync.inventory()
    assert len(files)==107 and observed
    assert api.get('/api/media',params={'database_ids':did}).json()['total']==107
    with core.db() as c:assert c.execute('SELECT count(*) FROM faces').fetchone()[0]==3
    assert sync.status_progress('stream-test')['live_added']==107


def test_pause_resume_first_import_keeps_visible_ids_and_manual_annotations(importing,monkeypatch):
    api,core,sync,root,did=importing
    from backend import incremental_import
    original=incremental_import.PreviewPublisher.process
    def pause_batch(self,ids):
        original(self,ids)
        sync.control_run('stream-test','pause')
    monkeypatch.setattr(incremental_import.PreviewPublisher,'process',pause_batch)
    with pytest.raises(sync.SyncStopped):sync.inventory()
    visible=api.get('/api/media',params={'database_ids':did}).json()
    assert visible['total']==50
    preserved={row['id'] for row in visible['items']}
    annotated=visible['items'][0]['id']
    with core.db() as c:c.execute("INSERT INTO faces(id,media_id,person_id,status) VALUES('during-import',?,1,'manual')",(annotated,))
    with sync.store() as c:c.execute('DELETE FROM controls')
    monkeypatch.setattr(incremental_import.PreviewPublisher,'process',original)
    files=sync.inventory()
    assert sync.reconcile(files)['missing']==0
    visible=api.get('/api/media',params={'database_ids':did,'limit':200}).json()
    assert visible['total']==107
    assert preserved.issubset({row['id'] for row in visible['items']})
    with core.db() as c:assert tuple(c.execute("SELECT media_id,person_id,status FROM faces WHERE id='during-import'").fetchone())==(annotated,1,'manual')


def test_unavailable_later_folder_preserves_published_previews_and_family(importing,monkeypatch):
    api,core,sync,root,did=importing
    from backend import source_management as sm
    from backend.discovery_checkpoint import DiscoveryCheckpoint
    listing=DiscoveryCheckpoint.list_directory
    def unavailable(directory,*args):
        if directory!=root:raise OSError('Disconnected isolated network fixture')
        return listing(directory,*args)
    monkeypatch.setattr(DiscoveryCheckpoint,'list_directory',staticmethod(unavailable))
    with pytest.raises(OSError):sync.inventory()
    assert api.get('/api/media',params={'database_ids':did}).json()['total']==105
    with core.db() as c:
        assert not c.execute("SELECT 1 FROM media WHERE status='missing'").fetchone()
        assert c.execute('SELECT count(*) FROM faces').fetchone()[0]==3


def test_existing_database_move_waits_for_inventory_and_preserves_face_identity(importing):
    api,core,sync,root,did=importing
    from backend import source_management as sm
    # Establish an existing catalogue without invoking incremental publication.
    sync.reconcile(sm.inventory(did))
    with core.db() as c:
        row=c.execute('SELECT id,path FROM media WHERE database_id=? ORDER BY path LIMIT 1',(did,)).fetchone()
        mid,path=row['id'],Path(row['path'])
        c.execute("UPDATE media SET status='ready',face_status='ready' WHERE database_id=?",(did,))
        c.execute("INSERT INTO faces(id,media_id,person_id,status) VALUES('moved-manual',?,2,'manual')",(mid,))
    moved=path.with_name('moved.jpg');path.rename(moved)
    before=api.get('/api/media',params={'database_ids':did}).json()['total']
    files=sync.inventory()
    assert api.get('/api/media',params={'database_ids':did}).json()['total']==before
    assert sync.reconcile(files)['moved']==1
    with core.db() as c:
        assert c.execute('SELECT id FROM media WHERE path=?',(str(moved),)).fetchone()[0]==mid
        assert tuple(c.execute("SELECT media_id,person_id,status FROM faces WHERE id='moved-manual'").fetchone())==(mid,2,'manual')


def test_existing_database_publishes_new_batch_before_remaining_hashes(importing,monkeypatch):
    api,core,sync,root,did=importing
    from backend import source_management as sm
    sync.reconcile(sm.inventory(did))
    with core.db() as c:c.execute("UPDATE media SET status='ready' WHERE database_id=?",(did,))
    photos(root/'New',55)
    files=sync.inventory()
    assert api.get('/api/media',params={'database_ids':did}).json()['total']==107
    original=sync.digest_stable;seen=[]
    def digest(path,entry):
        if path.endswith('img-0054.jpg') and '/New/' in path.replace('\\','/'):
            assert api.get('/api/media',params={'database_ids':did}).json()['total']>=157
            seen.append(path)
        return original(path,entry)
    monkeypatch.setattr(sync,'digest_stable',digest)
    report=sync.reconcile(files)
    assert report['added']==55 and seen
    assert api.get('/api/media',params={'database_ids':did}).json()['total']==162


def test_video_preview_is_published_without_recognition(importing,monkeypatch):
    api,core,sync,root,did=importing
    from backend import indexer
    clip=root/'Late'/'A'/'B'/'clip.mp4'
    clip.write_bytes(b'disposable video transport fixture')
    os.utime(clip,(time.time()-120,time.time()-120))
    def decoded_video(path):
        assert path==clip
        return [(i,Image.new('RGB',(80,60),'blue')) for i in range(3)],dict(taken=None,latitude=None,longitude=None,metadata={},duration=2,width=80,height=60)
    monkeypatch.setattr(indexer,'video',decoded_video)
    sync.inventory()
    videos=api.get('/api/media',params={'database_ids':did,'kind':'video'}).json()
    assert videos['total']==1
    mid=videos['items'][0]['id']
    assert (core.DATA/'thumbs'/f'{mid}-small.jpg').is_file()
    assert all((core.DATA/'frames'/f'{mid}-{i}.jpg').is_file() for i in range(3))
    with core.db() as c:
        row=c.execute('SELECT status,face_status,sha FROM media WHERE id=?',(mid,)).fetchone()
        assert (row['status'],row['face_status'])==('ready','pending')
        assert len(row['sha'])==64
    assert clip.read_bytes()==b'disposable video transport fixture'
