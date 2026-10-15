"""Advanced layout migrations and removals operate only on isolated fixtures."""
import json
from pathlib import Path
import pytest
from tests.test_catalogue import client
from tests.test_source_management import files,register,index

def setup(api,core,tmp_path,names=None,layout='collection'):
 root=files(tmp_path/'Photos',names or ['A/a.jpg','B/b.jpg','MobileBackup/Yoav/AA/y.jpg','MobileBackup/Hila/DD/h.jpg','MobileBackup/Bar/GG/b.mov'])
 did,_=register(api,root,interpretation=layout,source_aliases={'':'Photo on FILER'})
 index(did,core)
 return did,root

def plan(api,did,changes):
 response=api.post(f'/api/databases/{did}/advanced-preview',json={'changes':changes})
 assert response.status_code==200,response.text
 return response.json()

def apply(api,did,preview):
 response=api.post(f'/api/databases/{did}/advanced-confirm',json={'token':preview['token'],'confirm':True})
 assert response.status_code==200,response.text
 return response.json()

def child_change(path='MobileBackup',layout='sources'):
 return {'path':path,'kind':'database','alias':'Mobile memories','layout':layout,'source_aliases':{'Yoav':'Yoav','Hila':'Hila','Bar':'Bar'} if layout=='sources' else {'':'Backup collection'}}

def ids(api,**params):
 response=api.get('/api/media',params={**params,'limit':200})
 assert response.status_code==200,response.text
 return {row['id'] for row in response.json()['items']}

def annotations(c):
 return {name:[tuple(r) for r in c.execute('SELECT * FROM '+name+' ORDER BY 1')] for name in ('faces','people','face_rejections','review_approvals','actions','media_overrides','media_original_metadata')}

def test_child_database_preserves_identity_annotations_and_disjoint_inventory(client,tmp_path):
 api,core=client;did,root=setup(api,core,tmp_path)
 with core.db() as c:
  before={r['id']:dict(r) for r in c.execute('SELECT * FROM media WHERE database_id=?',(did,))}
  target=next(r['id'] for r in before.values() if 'Yoav' in r['relative_path'])
  c.execute("INSERT INTO faces(id,media_id,person_id,bbox,embedding,status) VALUES('advanced-face',?,1,'[1,2,3,4]',?,'manual')",(target,b'preserve exact embedding'))
  c.execute("INSERT INTO review_approvals(face_id,person_id) VALUES('advanced-face',1)")
  c.execute("INSERT INTO face_rejections VALUES('advanced-face',2)")
  c.execute('INSERT INTO media_overrides VALUES(?,?,?)',(target,json.dumps({'location':{'label':'Family memory'}}),'fixture'))
  before_annotations=annotations(c)
 original_bytes={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
 preview=plan(api,did,[child_change()]);assert preview['affected_media']==3
 with core.db() as c:assert c.execute('SELECT count(*) FROM library_databases WHERE parent_id=?',(did,)).fetchone()[0]==0
 result=apply(api,did,preview);cid=result['new_database_ids'][0]
 with core.db() as c:
  child=dict(c.execute('SELECT * FROM library_databases WHERE id=?',(cid,)).fetchone())
  assert child['parent_id']==did and child['parent_path']=='MobileBackup'
  assert json.loads(child['schedule'])['frequency']=='off'
  after={r['id']:dict(r) for r in c.execute('SELECT * FROM media WHERE id IN ('+','.join('?' for _ in before)+')',list(before))}
  for mid,row in before.items():
   assert after[mid]['path']==row['path'] and after[mid]['sha']==row['sha'] and after[mid]['face_status']==row['face_status']
   assert after[mid]['database_id']==(cid if row['relative_path'].startswith('MobileBackup/') else did)
  assert annotations(c)==before_annotations
 assert {str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}==original_bytes
 from backend import source_management as sm
 parent_files=sm.inventory(did);child_files=sm.inventory(cid)
 assert not set(parent_files)&set(child_files)
 assert len(parent_files)==2 and len(child_files)==3
 assert len(ids(api,database_ids=did))==2
 assert ids(api,database_ids=did,include_child_databases='true')==set(before)
 assert ids(api,database_ids='does-not-exist',include_child_databases='true')==set()
 assert api.post('/api/databases/'+did+'/removal-preview').status_code==409
 assert api.post('/api/databases/preview',json={'root':str(root/'MobileBackup'),'interpretation':'sources'}).status_code==409

def test_source_override_resolves_all_depths_and_pause_controls(client,tmp_path):
 api,core=client;did,root=setup(api,core,tmp_path)
 preview=plan(api,did,[{'path':'MobileBackup/Yoav','kind':'source','alias':'Yoav memories','layout':'collection'}]);apply(api,did,preview)
 from backend import source_management as sm
 files(root,['MobileBackup/Yoav/AA/Deep/C/new.mp4'])
 inventory=sm.inventory(did)
 record=inventory[str(root/'MobileBackup/Yoav/AA/Deep/C/new.mp4')]
 assert record['phone']=='Yoav memories' and record['album']=='AA › Deep › C'
 assert api.patch(f'/api/databases/{did}/sources/{record["source_id"]}',json={'sync_enabled':False}).status_code==200
 assert not any('/Yoav/' in Path(p).as_posix() for p in sm.inventory(did))

def test_linked_sources_cross_databases_respect_visibility_and_never_duplicate(client,tmp_path):
 api,core=client;did,_=setup(api,core,tmp_path)
 other=files(tmp_path/'Other',['Camera/a.jpg']);other_did,_=register(api,other,interpretation='collection');index(other_did,core)
 with core.db() as c:
  first=c.execute('SELECT source_id FROM media WHERE database_id=?',(did,)).fetchone()[0]
  second=c.execute('SELECT source_id FROM media WHERE database_id=?',(other_did,)).fetchone()[0]
 response=api.post('/api/linked-sources',json={'alias':'All memories','source_ids':[first,second,first]})
 assert response.status_code==201,response.text
 gid=response.json()['id'];assert len(ids(api,linked_source_ids=gid))==6
 assert len(api.get('/api/linked-sources').json()[0]['members'])==2
 assert api.patch(f'/api/databases/{other_did}/sources/{second}',json={'visible':False}).status_code==200
 assert len(ids(api,linked_source_ids=gid))==5
 assert api.put('/api/linked-sources/'+gid,json={'alias':'Hidden collection','source_ids':[first,second],'visible':False}).status_code==200
 assert ids(api,linked_source_ids=gid)==set()
 assert api.delete('/api/linked-sources/'+gid).status_code==200
 with core.db() as c:assert c.execute('SELECT count(*) FROM media WHERE database_id IN (?,?)',(did,other_did)).fetchone()[0]==6

def test_linked_source_follows_narrower_split_but_rejects_broader_merge(client,tmp_path):
 api,core=client;did,_=setup(api,core,tmp_path)
 with core.db() as c:sid=c.execute('SELECT source_id FROM media WHERE database_id=?',(did,)).fetchone()[0]
 gid=api.post('/api/linked-sources',json={'alias':'Whole collection','source_ids':[sid]}).json()['id'];before=ids(api,linked_source_ids=gid)
 apply(api,did,plan(api,did,[{'path':'MobileBackup/Yoav','kind':'source','alias':'Yoav','layout':'collection'}]))
 assert ids(api,linked_source_ids=gid)==before
 with core.db() as c:yoav=c.execute('SELECT source_id FROM library_source_rules WHERE database_id=?',(did,)).fetchone()[0]
 solo=api.post('/api/linked-sources',json={'alias':'Only Yoav','source_ids':[yoav]}).json()['id']
 response=api.post('/api/databases/'+did+'/advanced-preview',json={'changes':[{'path':'MobileBackup/Yoav','kind':'inherit'}]})
 assert response.status_code==409 and 'broaden' in response.text
 api.delete('/api/linked-sources/'+solo);api.delete('/api/linked-sources/'+gid)
 apply(api,did,plan(api,did,[{'path':'MobileBackup/Yoav','kind':'inherit'}]))
 with core.db() as c:assert c.execute('SELECT count(*) FROM library_source_rules WHERE database_id=?',(did,)).fetchone()[0]==0

def test_stale_plan_rejected_and_confirmation_required(client,tmp_path):
 api,core=client;did,_=setup(api,core,tmp_path)
 preview=plan(api,did,[child_change()])
 assert api.post('/api/databases/'+did+'/advanced-confirm',json={'token':preview['token'],'confirm':False}).status_code==422
 assert api.patch('/api/databases/'+did,json={'alias':'Changed name'}).status_code==200
 assert api.post('/api/databases/'+did+'/advanced-confirm',json={'token':preview['token'],'confirm':True}).status_code==409
 with core.db() as c:assert c.execute('SELECT count(*) FROM library_databases WHERE parent_id=?',(did,)).fetchone()[0]==0

@pytest.mark.parametrize('path',['../outside','A/../B','/absolute','C:/outside','A//B'])
def test_path_escape_rejected(client,tmp_path,path):
 api,core=client;did,_=setup(api,core,tmp_path)
 assert api.post('/api/databases/'+did+'/advanced-preview',json={'changes':[{'path':path,'kind':'source'}]}).status_code==422

def test_child_visibility_independent_from_parent_and_unavailable_root_guard(client,tmp_path):
 api,core=client;did,root=setup(api,core,tmp_path);cid=apply(api,did,plan(api,did,[child_change()]))['new_database_ids'][0]
 api.patch('/api/databases/'+did,json={'visible':False})
 assert len(ids(api,database_ids=cid))==3
 (root/'MobileBackup').rename(root/'Unavailable backup')
 assert api.post('/api/databases/'+did+'/advanced-preview',json={'changes':[{'path':'Missing','kind':'database'}]}).status_code==409
 with core.db() as c:assert c.execute('SELECT count(*) FROM media WHERE database_id=?',(cid,)).fetchone()[0]==3

def test_child_sources_keep_physical_ids_and_group_links(client,tmp_path):
 api,core=client;did,_=setup(api,core,tmp_path)
 apply(api,did,plan(api,did,[{'path':'MobileBackup/Yoav','kind':'source','alias':'Yoav archive'}]))
 with core.db() as c:sid=c.execute('SELECT source_id FROM library_source_rules WHERE database_id=?',(did,)).fetchone()[0]
 gid=api.post('/api/linked-sources',json={'alias':'Yoav across libraries','source_ids':[sid]}).json()['id'];before=ids(api,linked_source_ids=gid)
 cid=apply(api,did,plan(api,did,[child_change()]))['new_database_ids'][0]
 with core.db() as c:
  source=c.execute('SELECT * FROM library_sources WHERE id=?',(sid,)).fetchone()
  assert source['database_id']==cid and source['relative_path']=='Yoav'
 assert ids(api,linked_source_ids=gid)==before

def test_different_visibility_cannot_be_merged_silently(client,tmp_path):
 api,core=client;did,_=setup(api,core,tmp_path)
 apply(api,did,plan(api,did,[{'path':'MobileBackup/Yoav','kind':'source','alias':'Private Yoav'}]))
 with core.db() as c:sid=c.execute('SELECT source_id FROM library_source_rules WHERE database_id=?',(did,)).fetchone()[0]
 api.patch(f'/api/databases/{did}/sources/{sid}',json={'visible':False})
 response=api.post('/api/databases/'+did+'/advanced-preview',json={'changes':[{'path':'MobileBackup/Yoav','kind':'inherit'}]})
 assert response.status_code==409 and 'different visibility' in response.text


def test_reconnect_parent_moves_child_roots_and_keeps_group_ids(client,tmp_path):
 api,core=client;did,root=setup(api,core,tmp_path);cid=apply(api,did,plan(api,did,[child_change()]))['new_database_ids'][0]
 with core.db() as c:
  source_ids=[r[0] for r in c.execute('SELECT id FROM library_sources WHERE database_id IN (?,?)',(did,cid))]
  before_ids={r[0] for r in c.execute('SELECT id FROM media WHERE database_id IN (?,?)',(did,cid))}
  before_annotations=annotations(c)
 gid=api.post('/api/linked-sources',json={'alias':'Family after reconnect','source_ids':source_ids}).json()['id']
 moved=tmp_path/'Moved Photos';root.rename(moved)
 response=api.post('/api/databases/'+did+'/reconnect-preview',json={'root':str(moved)})
 assert response.status_code==200,response.text
 assert response.json()['database_count']==2
 result=api.post('/api/databases/'+did+'/reconnect-confirm',json={'token':response.json()['token'],'confirm':True})
 assert result.status_code==200,result.text
 with core.db() as c:
  assert c.execute('SELECT root FROM library_databases WHERE id=?',(cid,)).fetchone()[0]==str(moved/'MobileBackup')
  assert annotations(c)==before_annotations
  assert {r[0] for r in c.execute('SELECT id FROM media WHERE database_id IN (?,?)',(did,cid))}==before_ids
 assert ids(api,linked_source_ids=gid)==before_ids

def test_child_removal_only_removes_child_records_and_keeps_parent_originals(client,tmp_path):
 api,core=client;did,root=setup(api,core,tmp_path);cid=apply(api,did,plan(api,did,[child_change()]))['new_database_ids'][0]
 parent_ids=ids(api,database_ids=did)
 with core.db() as c:
  child_sources=[r[0] for r in c.execute('SELECT id FROM library_sources WHERE database_id=?',(cid,))]
 gid=api.post('/api/linked-sources',json={'alias':'Child links','source_ids':child_sources}).json()['id']
 preview=api.post('/api/databases/'+cid+'/removal-preview');assert preview.status_code==200,preview.text
 first=api.post('/api/databases/'+cid+'/removal-first-confirm',json={'token':preview.json()['token'],'confirm':True});assert first.status_code==200
 result=api.post('/api/databases/'+cid+'/removal-final-confirm',json={'token':first.json()['token'],'confirm':True,'typed_alias':'Mobile memories'})
 assert result.status_code==200,result.text
 assert ids(api,database_ids=did)==parent_ids
 assert len(list(root.rglob('*.jpg')))==4 and len(list(root.rglob('*.mov')))==1
 assert ids(api,linked_source_ids=gid)==set()

def test_child_policies_keep_future_sources_paused_and_hidden(client,tmp_path):
 api,core=client;did,root=setup(api,core,tmp_path)
 with core.db() as c:parent_source=c.execute('SELECT source_id FROM media WHERE database_id=?',(did,)).fetchone()[0]
 api.patch(f'/api/databases/{did}/sources/{parent_source}',json={'visible':False,'sync_enabled':False})
 cid=apply(api,did,plan(api,did,[child_change()]))['new_database_ids'][0]
 files(root,['MobileBackup/New phone/Camera/new.jpg'])
 from backend import source_management as sm
 assert not sm.inventory(cid)
 with core.db() as c:
  future=c.execute('SELECT * FROM library_sources WHERE database_id=? AND relative_path=?',(cid,'New phone')).fetchone()
  assert future and future['visible']==0 and future['sync_enabled']==0

def test_target_linked_source_cannot_silently_absorb_unlinked_sources(client,tmp_path):
 api,core=client;did,root=setup(api,core,tmp_path,names=['root.jpg','A/a.jpg','B/b.jpg'],layout='sources')
 with core.db() as c:sid=c.execute("SELECT id FROM library_sources WHERE database_id=? AND relative_path=''",(did,)).fetchone()[0]
 gid=api.post('/api/linked-sources',json={'alias':'Root files only','source_ids':[sid]}).json()['id'];before=ids(api,linked_source_ids=gid)
 response=api.post('/api/databases/'+did+'/advanced-preview',json={'changes':[{'path':'.','kind':'default','layout':'collection','alias':'Photos'}]})
 assert response.status_code==409 and 'broaden' in response.text
 assert ids(api,linked_source_ids=gid)==before

def test_unindexed_directory_samples_do_not_create_media_before_sync(client,tmp_path):
 api,core=client;did,root=setup(api,core,tmp_path);files(root,['New archive/Yoav/Album/new.jpg'])
 with core.db() as c:before=c.execute('SELECT count(*) FROM media').fetchone()[0]
 response=api.post('/api/databases/'+did+'/advanced-preview',json={'changes':[{'path':'New archive','kind':'database','layout':'sources'}],'representative_files':['New archive/Yoav/Album/new.jpg']})
 assert response.status_code==200,response.text
 assert response.json()['affected_media']==0 and response.json()['samples'][0]['source']=='Yoav'
 apply(api,did,response.json())
 with core.db() as c:assert c.execute('SELECT count(*) FROM media').fetchone()[0]==before
