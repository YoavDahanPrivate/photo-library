"""Synthetic directory inventories; no family-library or NAS writes."""
from pathlib import Path
from types import SimpleNamespace
import json
import subprocess
import pytest
from tests.test_catalogue import client
from tests.test_source_management import files


def test_preview_and_confirmation_never_run_full_inventory_or_metadata(client,tmp_path,monkeypatch):
    api,core=client
    from backend import source_management as sm, metadata_support as metadata
    root=files(tmp_path/'Photos',['Family/a.jpg','Travel/Italy/b.jpg'])
    monkeypatch.setattr(sm,'walk',lambda *a,**k:pytest.fail('Full inventory during registration'))
    monkeypatch.setattr(metadata,'file_report',lambda *a,**k:pytest.fail('Metadata read during layout approval'))
    for endpoint in ('analyze','preview'):
        response=api.post('/api/databases/'+endpoint,json={'root':str(root)})
        assert response.status_code==200,response.text
        p=response.json()
        assert p['inspection']['directories']==4
        assert p['inspection']['media_names']==2 and not p['inspection']['sampled']
        assert p['metadata_report'] is None
    response=api.post('/api/databases/register',json={'token':p['token'],'confirm':True})
    assert response.status_code==201,response.text
    with core.db() as c:
        assert c.execute('SELECT count(*) FROM media WHERE database_id=?',(response.json()['id'],)).fetchone()[0]==0


def test_directory_scan_never_stats_or_opens_media(tmp_path,monkeypatch):
    from backend.source_preview import scan
    root=files(tmp_path/'Archive',['1978/Paris/a.jpg','1978/Paris/b.mov','a.jpg'])
    original_stat=Path.stat
    def stat(path,*args,**kwargs):
        if path.suffix.lower() in ('.jpg','.mov'):pytest.fail('Media stat during preview')
        return original_stat(path,*args,**kwargs)
    monkeypatch.setattr(Path,'stat',stat)
    monkeypatch.setattr(Path,'open',lambda *a,**k:pytest.fail('Media opened during preview'))
    result=scan(root)
    assert len(result['files'])==3 and not result['inspection']['truncated']
    assert all(set(f)=={'relative'} for f in result['files'])


def test_huge_directory_reads_only_bounded_entries_and_samples(tmp_path,monkeypatch):
    from backend import source_preview as preview
    root=tmp_path/'Huge';root.mkdir()
    count=[]
    class Entry:
        def __init__(self,i):self.name=f'{i:06}.jpg'
        def is_symlink(self):return False
        def is_junction(self):return False
        def is_dir(self,**kwargs):return False
        def is_file(self,**kwargs):return True
    class Listing:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def __iter__(self):
            for i in range(1000000):count.append(i);yield Entry(i)
    monkeypatch.setattr(preview.os,'scandir',lambda path:Listing())
    result=preview.scan(root,per_directory_limit=32)
    assert len(count)==33
    assert result['inspection']['entries']==32
    assert result['inspection']['media_names']==32
    assert result['inspection']['truncated'] and result['inspection']['sampled']
    assert len(result['files'])==3


def test_sampling_covers_sibling_branches_and_honors_exclusions(tmp_path):
    from backend.source_preview import scan
    root=files(tmp_path/'Backups',['Alice iPhone/DCIM/Deep/a.jpg','Bob Pixel/Camera/b.jpg','Excluded/c.jpg'])
    result=scan(root,['Excluded'])
    names={f['relative'] for f in result['files']}
    assert names=={'Alice iPhone/DCIM/Deep/a.jpg','Bob Pixel/Camera/b.jpg'}
    limited=scan(root,['Excluded'],directory_limit=3)
    assert limited['inspection']['directories']==3 and limited['inspection']['truncated']
    assert limited['inspection']['limits']==['directory limit']


def test_stalled_network_listing_has_hard_timeout(client,tmp_path,monkeypatch):
    from backend import source_preview as preview
    seen=[]
    def run(args,**kwargs):
        seen.append((args,kwargs));raise subprocess.TimeoutExpired('helper',10)
    monkeypatch.setattr(preview.subprocess,'run',run)
    with pytest.raises(RuntimeError,match='10 seconds'):
        preview.inspect(tmp_path)
    args,kwargs=seen[0]
    assert args[-1]=='backend.source_preview' and kwargs['timeout']==10
    assert 'env' not in kwargs and set(json.loads(kwargs['input']))=={'root','exclusions'}


def test_partial_structure_is_flagged_and_unseen_media_uses_approved_layout(client,tmp_path,monkeypatch):
    api,core=client
    from backend import source_preview as preview,source_management as sm
    root=files(tmp_path/'Many albums',[f'Album {i:03}/a.jpg' for i in range(105)])
    p=api.post('/api/databases/preview',json={'root':str(root),'interpretation':'collection','alias':'Archive','source_aliases':{'':'Scans'}}).json()
    assert p['inspection']['truncated'] and p['suggestion']['ambiguous']
    assert p['inspection']['directories']<=96
    response=api.post('/api/databases/register',json={'token':p['token'],'confirm':True})
    assert response.status_code==201,response.text
    inventory=sm.inventory(response.json()['id'])
    assert len(inventory)==105
    assert {entry['phone'] for entry in inventory.values()}=={'Scans'}
    assert len({entry['album'] for entry in inventory.values()})==105


def test_every_discovered_album_is_available_beyond_the_old_30_row_cap(client,tmp_path):
    api,_=client
    root=files(tmp_path/'Albums',[f'Album {i:03}/{j}.jpg' for i in range(45) for j in range(4)])
    p=api.post('/api/databases/preview',json={'root':str(root)}).json()
    assert p['album_count']==45 and not p['inspection']['truncated']
    assert len(p['samples'])==135
    assert {row['album'] for row in p['samples']}=={f'Album {i:03}' for i in range(45)}
    from collections import Counter
    assert set(Counter((row['source_key'],row['album_key']) for row in p['samples']).values())=={3}
