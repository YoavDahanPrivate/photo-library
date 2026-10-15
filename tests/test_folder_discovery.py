"""Complete preview and recursive catalogue inclusion on disposable trees."""
import time
from pathlib import Path
import pytest
from tests.test_catalogue import client
from tests.test_source_management import files,register,index


def wait_job(api,key):
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        response=api.get('/api/databases/folder-discovery/'+key)
        assert response.status_code==200,response.text
        result=response.json()
        if result['state']!='running':return result
        time.sleep(.05)
    pytest.fail('Isolated discovery did not complete')


def test_complete_discovery_has_no_folder_entry_or_depth_cap(client,tmp_path):
    api,core=client
    deep='/'.join(f'D{i:02}' for i in range(22))
    names=[f'Album {i:03}/a.jpg' for i in range(125)]+[f'Crowded/{i:04}.jpg' for i in range(700)]+[f'subfolder/{deep}/clip.mp4']
    root=files(tmp_path/'Complete archive',names)
    response=api.post('/api/databases/folder-discovery',json={'root':str(root),'interpretation':'collection','alias':'Archive','source_aliases':{'':'Scans'}})
    assert response.status_code==200,response.text
    result=wait_job(api,response.json()['id'])
    assert result['state']=='complete',result
    p=result['preview'];info=p['inspection']
    assert info['kind']=='directory_tree' and not info['truncated']
    assert info['media_names']==len(names) and info['directories']>125
    assert len(p['folder_tree'])==info['directories']
    assert any(f['relative']=='subfolder/'+deep and f['direct_media']==1 for f in p['folder_tree'])
    assert any(f['relative']=='subfolder' and f['direct_media']==0 and f['role']=='Container folder' for f in p['folder_tree'])
    assert any(row['album']=='Album 124' for row in p['samples'])
    registered=api.post('/api/databases/register',json={'token':p['token'],'confirm':True})
    assert registered.status_code==201,registered.text
    did=registered.json()['id'];index(did,core)
    with core.db() as c:
        assert c.execute('SELECT count(*) FROM media WHERE database_id=?',(did,)).fetchone()[0]==len(names)
        nested=c.execute('SELECT album,phone FROM media WHERE database_id=? AND relative_path=?',(did,'subfolder/'+deep+'/clip.mp4')).fetchone()
        assert nested['phone']=='Scans' and nested['album']==' › '.join(['subfolder']+deep.split('/'))


@pytest.mark.parametrize('layout,album',[('collection','subfolder › A › B'),('sources','A › B'),('single_album','Main folder')])
def test_images_and_videos_at_every_depth_belong_to_database(client,tmp_path,layout,album):
    api,core=client
    names=['root.jpg','subfolder/A/B/img.jpg','subfolder/A/B/Deeper/movie.mp4']
    root=files(tmp_path/'Recursive',names)
    did,_=register(api,root,interpretation=layout)
    index(did,core)
    with core.db() as c:
        rows=[dict(row) for row in c.execute('SELECT relative_path,kind,album FROM media WHERE database_id=?',(did,))]
    assert {row['relative_path'] for row in rows}==set(names)
    assert next(row for row in rows if row['relative_path']=='subfolder/A/B/img.jpg')['album']==album
    assert next(row for row in rows if row['relative_path'].endswith('.mp4'))['kind']=='video'
    if layout=='single_album':assert {row['album'] for row in rows}=={'Main folder'}


def test_complete_directory_discovery_reads_no_media_content_or_stats(tmp_path,monkeypatch):
    from backend.source_preview import discover
    root=files(tmp_path/'Archive',['Container/A/B/a.jpg','Container/A/B/movie.mp4','Skip/sub/a.jpg'])
    (root/'Empty').mkdir()
    original_stat=Path.stat
    def stat(path,*args,**kwargs):
        if path.suffix in ('.jpg','.mp4'):pytest.fail('Media stat in folder discovery')
        return original_stat(path,*args,**kwargs)
    monkeypatch.setattr(Path,'stat',stat)
    monkeypatch.setattr(Path,'open',lambda *a,**k:pytest.fail('Media file opened'))
    progress=[];result=discover(root,['Skip'],progress.append)
    assert result['inspection']['media_names']==2
    assert {f['relative'] for f in result['folder_tree']}=={'.','Container','Container/A','Container/A/B','Empty'}
    assert progress[-1]['current']=='Finished'
    assert not result['inspection']['truncated']


def test_unreadable_subfolder_is_visible_and_never_claimed_complete(tmp_path,monkeypatch):
    from backend import source_preview as preview
    root=files(tmp_path/'Archive',['Readable/a.jpg','Denied/A/b.jpg'])
    original=preview.os.scandir
    def scan(path):
        if Path(path)==root/'Denied':raise PermissionError('isolated fixture')
        return original(path)
    monkeypatch.setattr(preview.os,'scandir',scan)
    result=preview.discover(root)
    assert result['inspection']['truncated']
    assert any(f['relative']=='Denied' and f['readable'] is False for f in result['folder_tree'])


def test_discovery_cancel_and_failed_root_are_reported(client,tmp_path,monkeypatch):
    api,_=client
    from backend import source_discovery as discovery
    def wait(job,body):
        job['cancel'].wait(2)
        job['state']='cancelled';job['finished']=time.monotonic()
    with monkeypatch.context() as patch:
        patch.setattr(discovery,'worker',wait)
        root=tmp_path/'Cancel';root.mkdir()
        started=api.post('/api/databases/folder-discovery',json={'root':str(root)}).json()
        assert api.post('/api/databases/folder-discovery/'+started['id']+'/cancel',json={}).status_code==200
        assert wait_job(api,started['id'])['state']=='cancelled'
    response=api.post('/api/databases/folder-discovery',json={'root':str(tmp_path/'Missing')})
    assert wait_job(api,response.json()['id'])['state']=='failed'
