"""Read-only hierarchy responses, using disposable catalogues and originals."""
import pytest
from tests.test_catalogue import client
from tests.test_source_management import files,register,index

@pytest.mark.parametrize('layout,relative,source_path,album_path',[
 ('collection','Holiday/A/B/C/photo.jpg','','Holiday/A/B/C'),
 ('sources','Phone folder/Holiday/A/B/C/photo.jpg','Phone folder','Holiday/A/B/C'),
 ('sources','Phone folder/photo.jpg','Phone folder','.'),
 ('single_album','A/B/C/photo.jpg','','.'),
 ('collection','photo.jpg','','.'),
])
def test_detail_exposes_physical_hierarchy_without_reassignment(client,tmp_path,layout,relative,source_path,album_path):
 api,core=client
 root=files(tmp_path/'Photos',[relative])
 did,_=register(api,root,interpretation=layout,source_aliases={source_path:'Source nickname'})
 index(did,core)
 with core.db() as c:
  before=[tuple(r) for r in c.execute('SELECT * FROM media WHERE database_id=?',(did,))]
  mid=c.execute('SELECT id FROM media WHERE database_id=?',(did,)).fetchone()[0]
  faces=[tuple(r) for r in c.execute('SELECT * FROM faces')]
 result=api.get('/api/media/'+mid)
 assert result.status_code==200,result.text
 detail=result.json()
 assert detail['source_relative_path']==source_path
 assert detail['album_relative_path']==album_path
 assert detail['relative_path']==relative
 assert detail['phone']=='Source nickname'
 assert 'path' not in detail
 with core.db() as c:
  assert [tuple(r) for r in c.execute('SELECT * FROM media WHERE database_id=?',(did,))]==before
  assert [tuple(r) for r in c.execute('SELECT * FROM faces')]==faces

def test_folder_preview_keeps_raw_keys_with_source_alias(client,tmp_path):
 api,_=client
 root=files(tmp_path/'Photos',['Phone folder/Holiday/A/B/C/photo.jpg'])
 result=api.post('/api/databases/analyze',json={'root':str(root),'interpretation':'sources','source_aliases':{'Phone folder':'Source nickname'}})
 assert result.status_code==200,result.text
 preview=result.json()
 folder=next(f for f in preview['folder_tree'] if f['relative']=='Phone folder/Holiday/A/B/C')
 assert folder['source']=='Source nickname'
 assert folder['source_key']=='Phone folder'
 assert folder['album_key']=='Holiday/A/B/C'

def test_old_unassigned_detail_still_reads_without_hierarchy(client):
 api,_=client
 result=api.get('/api/media/0')
 assert result.status_code==200,result.text
 assert result.json()['album']=='Recents'
