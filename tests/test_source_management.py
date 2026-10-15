"""All paths, catalogue changes and removals in this file use disposable fixtures."""
import hashlib
import json
import os
import time
from pathlib import Path

import pytest
from tests.test_catalogue import client


def files(root, names):
    for name in names:
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(("fixture:" + name).encode())
        os.utime(p, (time.time()-120, time.time()-120))
    return root


def register(api, root, **options):
    p = api.post('/api/databases/preview', json=dict(root=str(root), **options))
    assert p.status_code == 200, p.text
    result = api.post('/api/databases/register', json={'token':p.json()['token'], 'confirm':True})
    assert result.status_code == 201, result.text
    return result.json()['id'], p.json()


def index(did, core):
    from backend import source_management as sm, sync_service as sync
    report = sync.reconcile(sm.inventory(did))
    with core.db() as c:
        c.execute("UPDATE media SET status='ready',face_status='ready' WHERE database_id=?", (did,))
    return report


@pytest.mark.parametrize('names,mode,albums', [
    (['Holiday/a.jpg','Family/b.mov'], 'collection', ['Holiday','Family']),
    (['a.jpg','b.mov'], 'collection', ['Main folder']),
    (['Travel/Italy/Rome/a.jpg','Family/2025/b.jpg'], 'collection', ['Travel › Italy › Rome','Family › 2025']),
    (['Alice iPhone/DCIM/a.jpg','Bob Pixel/Camera/b.mov'], 'sources', ['DCIM','Camera']),
])
def test_predominant_detection(client, tmp_path, names, mode, albums):
    api, _ = client
    root = files(tmp_path/'Photos', names)
    p = api.post('/api/databases/preview', json={'root':str(root)}).json()
    assert p['interpretation'] == mode
    assert p['alias'] == 'Photos'
    assert {r['album'] for r in p['samples']} == set(albums)
    if mode == 'collection':
        assert p['sources'] == [{'key':'', 'alias':'Photos Collection'}]
    assert p['media_count'] == len(names)


def test_mixed_layout_alias_override_and_representative_branches(client, tmp_path):
    api, _ = client
    root = files(tmp_path/'Photos', ['a.jpg','Alice iPhone/DCIM/a.jpg','Travel/a.jpg'])
    p = api.post('/api/databases/preview',json={'root':str(root),'interpretation':'sources','alias':'Archive','source_aliases':{'':'Root collection','Travel':'Trips'}}).json()
    assert p['suggestion']['ambiguous']
    assert {s['source'] for s in p['samples']} == {'Root collection','Alice iPhone','Trips'}
    assert all(s['database']=='Archive' for s in p['samples'])


def test_register_requires_fresh_confirmed_preview_and_prevents_overlap(client, tmp_path):
    api, core = client
    root = files(tmp_path/'Photos', ['a.jpg'])
    p = api.post('/api/databases/preview',json={'root':str(root)}).json()
    assert api.post('/api/databases/register',json={'token':p['token']}).status_code==422
    files(root,['new.jpg'])
    assert api.post('/api/databases/register',json={'token':p['token'],'confirm':True}).status_code==409
    did,p = register(api,root)
    with core.db() as c:
        assert not c.execute('SELECT 1 FROM media WHERE database_id=?',(did,)).fetchone()
    for overlap in (root,root/'child',tmp_path):
        assert api.post('/api/databases/preview',json={'root':str(overlap)}).status_code==409
    assert api.post('/api/databases/register',json={'token':p['token'],'confirm':True}).status_code==409


def test_visibility_sync_independent_alias_ids_and_scope(client, tmp_path):
    api,core=client
    did,_=register(api,files(tmp_path/'Photos',['Holiday/a.jpg']))
    other,_=register(api,files(tmp_path/'Other',['b.jpg']))
    index(did,core); index(other,core)
    with core.db() as c:
        before=dict(c.execute('SELECT * FROM media WHERE database_id=?',(did,)).fetchone())
        c.execute("INSERT INTO faces(id,media_id,person_id,status) VALUES('registered-face',?,1,'manual')",(before['id'],))
    assert api.patch('/api/databases/'+did,json={'visible':False}).status_code==200
    assert api.get('/api/media/'+before['id']).status_code==404
    assert before['id'] not in {r['id'] for r in api.get('/api/media').json()['items']}
    # Hiding doesn't stop inventory, and syncing one root doesn't mark another missing.
    assert index(did,core)['missing']==0
    assert api.patch('/api/databases/'+did,json={'visible':True,'alias':'Renamed'}).status_code==200
    assert api.patch(f'/api/databases/{did}/sources/{before["source_id"]}',json={'alias':'Family'}).status_code==200
    with core.db() as c:
        after=dict(c.execute('SELECT * FROM media WHERE id=?',(before['id'],)).fetchone())
        assert (after['id'],after['source_id'],after['album_id'])==(before['id'],before['source_id'],before['album_id'])
        assert after['phone']=='Family'
        assert c.execute("SELECT status FROM faces WHERE id='registered-face'").fetchone()[0]=='manual'
    assert api.patch('/api/databases/'+did,json={'sync_enabled':False}).status_code==200
    assert api.get('/api/media/'+before['id']).status_code==200
    from backend import source_management as sm
    assert not sm.inventory(did)
    assert api.post('/api/databases/'+did+'/sync',json={}).status_code==409


def test_exclusions_and_paused_source_do_not_mark_missing(client, tmp_path):
    api,core=client
    root=files(tmp_path/'Backups',['Alice iPhone/DCIM/a.jpg','Bob Pixel/Camera/b.jpg'])
    did,_=register(api,root)
    index(did,core)
    p=api.post(f'/api/databases/{did}/layout-preview',json={'root':str(root),'interpretation':'sources','exclusions':['Alice iPhone/DCIM']}).json()
    assert api.post(f'/api/databases/{did}/layout-confirm',json={'token':p['token'],'confirm':True}).status_code==200
    assert index(did,core)['missing']==0
    with core.db() as c:
        assert {r[0] for r in c.execute('SELECT status FROM media WHERE database_id=?',(did,))}=={'ready'}
        sid=c.execute("SELECT id FROM library_sources WHERE database_id=? AND relative_path='Bob Pixel'",(did,)).fetchone()[0]
    api.patch(f'/api/databases/{did}/sources/{sid}',json={'sync_enabled':False})
    (root/'Bob Pixel/Camera/b.jpg').unlink()
    assert index(did,core)['missing']==0


def test_unavailable_root_is_atomic(client,tmp_path):
    api,core=client
    root=files(tmp_path/'Photos',['a.jpg']);did,_=register(api,root);index(did,core)
    root.rename(tmp_path/'Offline')
    from backend import source_management as sm
    with pytest.raises(RuntimeError,match='unavailable'):
        sm.inventory(did)
    with core.db() as c:
        assert c.execute('SELECT status FROM media WHERE database_id=?',(did,)).fetchone()[0]=='ready'
    assert next(d for d in api.get('/api/databases').json() if d['id']==did)['availability']=='unavailable'


def test_legacy_migration_preserves_all_annotations_and_is_idempotent(client):
    _,core=client
    p=files(core.ROOT,[core.PHONES[0]+'/Album/Deep/a.jpg'])/core.PHONES[0]/'Album/Deep/a.jpg'
    with core.db() as c:
        c.execute('UPDATE media SET path=?,phone=?,album=? WHERE id=\'0\'',(str(p),core.PHONES[0],'Album'))
        c.execute("INSERT INTO review_approvals(face_id,person_id) VALUES('a',1)")
        c.execute("INSERT INTO face_rejections VALUES('b',1)")
        c.execute("INSERT INTO actions(description,previous) VALUES('fixture correction','{}')")
        before={t:[tuple(r) for r in c.execute('SELECT * FROM '+t)] for t in ('faces','people','actions','review_approvals','face_rejections')}
        c.execute("DELETE FROM library_meta WHERE key='legacy_migrated'")
        c.execute('DELETE FROM library_albums');c.execute('DELETE FROM library_sources');c.execute('DELETE FROM library_databases')
    core.init()
    with core.db() as c:
        migrated=dict(c.execute("SELECT * FROM media WHERE id='0'").fetchone())
        assert migrated['album']=='Album'
        assert migrated['database_id'] and migrated['source_id'] and migrated['album_id']
        assert migrated['relative_path']==core.PHONES[0]+'/Album/Deep/a.jpg'
        for t,rows in before.items():
            assert [tuple(r) for r in c.execute('SELECT * FROM '+t)]==rows
    core.init()
    with core.db() as c:
        assert c.execute('SELECT count(*) FROM library_databases').fetchone()[0]==1
        assert c.execute("SELECT source_id FROM media WHERE id='0'").fetchone()[0]==migrated['source_id']


def test_layout_migration_requires_preview_and_preserves_media_faces_history(client,tmp_path):
    api,core=client
    root=files(tmp_path/'Photos',['Travel/Italy/Rome/a.jpg'])
    did,_=register(api,root);index(did,core)
    with core.db() as c:
        m=dict(c.execute('SELECT * FROM media WHERE database_id=?',(did,)).fetchone())
        c.execute("INSERT INTO faces(id,media_id,person_id,status,embedding) VALUES('migration-face',?,1,'manual',?)",(m['id'],b'preserved'))
        c.execute("INSERT INTO face_rejections VALUES('migration-face',2)")
        before=[tuple(r) for r in c.execute('SELECT * FROM faces ORDER BY id')]
    p=api.post(f'/api/databases/{did}/layout-preview',json={'root':str(root),'interpretation':'sources'}).json()
    assert p['samples'][0]['source']=='Travel' and p['samples'][0]['album']=='Italy › Rome'
    assert api.post(f'/api/databases/{did}/layout-confirm',json={'token':p['token'],'confirm':True}).status_code==200
    with core.db() as c:
        after=dict(c.execute('SELECT * FROM media WHERE id=?',(m['id'],)).fetchone())
        assert after['source_id']!=m['source_id'] and after['album']=='Italy › Rome'
        assert [tuple(r) for r in c.execute('SELECT * FROM faces ORDER BY id')]==before
        assert c.execute("SELECT 1 FROM face_rejections WHERE face_id='migration-face'").fetchone()
    # It remains this interpretation during future scans.
    index(did,core)
    assert api.post(f'/api/databases/{did}/layout-confirm',json={'token':p['token'],'confirm':True}).status_code==409


def test_reconnect_verifies_content_and_preserves_identity(client,tmp_path):
    api,core=client
    root=files(tmp_path/'Photos',['Album/a.jpg']);did,_=register(api,root);index(did,core)
    with core.db() as c:
        before=dict(c.execute('SELECT * FROM media WHERE database_id=?',(did,)).fetchone())
        c.execute("INSERT INTO faces(id,media_id,person_id,status) VALUES('reconnect-face',?,1,'manual')",(before['id'],))
    moved=tmp_path/'Moved';root.rename(moved)
    p=api.post(f'/api/databases/{did}/reconnect-preview',json={'root':str(moved)})
    assert p.status_code==200,p.text
    assert api.post(f'/api/databases/{did}/reconnect-confirm',json={'token':p.json()['token'],'confirm':True}).status_code==200
    with core.db() as c:
        after=dict(c.execute('SELECT * FROM media WHERE database_id=?',(did,)).fetchone())
        for k in ('id','source_id','album_id','database_id','relative_path'):
            assert after[k]==before[k]
        assert Path(after['path'])==moved/'Album/a.jpg'
        assert core.original(after)==moved/'Album/a.jpg'
        assert c.execute("SELECT person_id FROM faces WHERE id='reconnect-face'").fetchone()[0]==1


def test_reconnect_rejects_different_content_and_stale_files(client,tmp_path):
    api,core=client
    root=files(tmp_path/'Photos',['a.jpg']);did,_=register(api,root);index(did,core)
    wrong=files(tmp_path/'Wrong',['a.jpg']);(wrong/'a.jpg').write_bytes(b'fixture:b.jpg')
    assert api.post(f'/api/databases/{did}/reconnect-preview',json={'root':str(wrong)}).status_code==409
    moved=tmp_path/'Moved';root.rename(moved)
    p=api.post(f'/api/databases/{did}/reconnect-preview',json={'root':str(moved)}).json()
    (moved/'a.jpg').write_bytes(b'changed')
    assert api.post(f'/api/databases/{did}/reconnect-confirm',json={'token':p['token'],'confirm':True}).status_code==409
    with core.db() as c:
        assert c.execute('SELECT root FROM library_databases WHERE id=?',(did,)).fetchone()[0]==str(root)


def test_removal_requires_two_confirmations_preserves_files_and_other_database(client,tmp_path):
    api,core=client
    root=files(tmp_path/'Photos',['a.jpg']);did,_=register(api,root);index(did,core)
    other,_=register(api,files(tmp_path/'Other',['b.jpg']));index(other,core)
    with core.db() as c:
        mid=c.execute('SELECT id FROM media WHERE database_id=?',(did,)).fetchone()[0]
        c.execute("INSERT INTO faces(id,media_id,person_id,status) VALUES('remove-face',?,1,'manual')",(mid,))
        for table in ('unknown_faces','high_confidence_faces'):
            c.execute('INSERT INTO '+table+" VALUES('remove-face')")
        c.execute("INSERT INTO face_rejections VALUES('remove-face',2)")
        c.execute("INSERT INTO review_approvals(face_id,person_id) VALUES('remove-face',1)")
        c.execute("INSERT INTO face_suggestions VALUES('remove-face',2,.9,.2)")
        c.execute('INSERT INTO actions(description,previous) VALUES(?,?)',('fixture',json.dumps({'faces':[{'id':'remove-face'}]})))
    content=(root/'a.jpg').read_bytes()
    p=api.post(f'/api/databases/{did}/removal-preview',json={}).json()
    assert p['media']==1 and p['faces']==1
    assert api.post(f'/api/databases/{did}/removal-final-confirm',json={'token':p['token'],'confirm':True,'typed_alias':'Photos'}).status_code==422
    first=api.post(f'/api/databases/{did}/removal-first-confirm',json={'token':p['token'],'confirm':True}).json()
    assert api.post(f'/api/databases/{did}/removal-first-confirm',json={'token':p['token'],'confirm':True}).status_code==409
    assert api.post(f'/api/databases/{did}/removal-final-confirm',json={'token':first['token'],'confirm':True,'typed_alias':'wrong'}).status_code==422
    r=api.post(f'/api/databases/{did}/removal-final-confirm',json={'token':first['token'],'confirm':True,'typed_alias':'Photos'})
    assert r.status_code==200,r.text
    assert (root/'a.jpg').read_bytes()==content
    with core.db() as c:
        assert not c.execute('SELECT 1 FROM media WHERE database_id=?',(did,)).fetchone()
        assert not c.execute("SELECT 1 FROM faces WHERE id='remove-face'").fetchone()
        assert c.execute('SELECT count(*) FROM media WHERE database_id=?',(other,)).fetchone()[0]==1
        assert c.execute("PRAGMA foreign_key_check").fetchall()==[]
    core.init()
    assert did not in {d['id'] for d in api.get('/api/databases').json()}


def test_changed_removal_preview_and_active_operation_are_rejected(client,tmp_path):
    api,core=client
    root=files(tmp_path/'Photos',['a.jpg']);did,_=register(api,root);index(did,core)
    p=api.post(f'/api/databases/{did}/removal-preview',json={}).json()
    first=api.post(f'/api/databases/{did}/removal-first-confirm',json={'token':p['token'],'confirm':True}).json()
    with core.db() as c:
        c.execute("UPDATE media SET status='error' WHERE database_id=?",(did,))
    assert api.post(f'/api/databases/{did}/removal-final-confirm',json={'token':first['token'],'confirm':True,'typed_alias':'Photos'}).status_code==409
    from backend import sync_service
    with sync_service.scan_lock():
        assert api.patch('/api/databases/'+did,json={'visible':False}).status_code==409


def test_schedules_validation_and_targeted_dispatch(client,tmp_path,monkeypatch):
    api,core=client
    did,_=register(api,files(tmp_path/'Photos',['a.jpg']))
    from backend import sync_service as sync
    assert api.patch('/api/databases/'+did,json={'schedule':{'frequency':'yearly'}}).status_code==422
    assert api.patch('/api/databases/'+did,json={'schedule':{'frequency':'weekly','weekday':2,'timezone':'UTC'}}).status_code==200
    with core.db() as c:
        c.execute("UPDATE library_databases SET next_due='2020-01-01T00:00:00+00:00' WHERE id=?",(did,))
    calls=[]
    monkeypatch.setattr(sync,'start_run',lambda reason='manual',**kw:calls.append((reason,kw)) or {'state':'running'})
    sync.tick()
    assert calls==[('scheduled',{'database_id':did})]
    assert api.post('/api/databases/'+did+'/sync',json={}).status_code==202
    assert calls[-1]==('manual',{'database_id':did})


@pytest.mark.parametrize('exclusion',['../outside','A/../../B','C:/Photos'])
def test_invalid_exclusions(client,tmp_path,exclusion):
    api,_=client
    assert api.post('/api/databases/preview',json={'root':str(tmp_path/'Photos'),'exclusions':[exclusion]}).status_code==422


def test_global_scheduled_inventory_excludes_custom_schedules(client,tmp_path):
    api,core=client
    first,_=register(api,files(tmp_path/'Photos',['a.jpg']))
    second,_=register(api,files(tmp_path/'Other',['b.jpg']))
    api.patch('/api/databases/'+second,json={'schedule':{'frequency':'off'}})
    for phone in core.PHONES:
        (core.ROOT/phone).mkdir(parents=True)
    from backend import source_management as sm
    inventory=sm.inventory(global_scheduled=True)
    assert {e['database_id'] for e in inventory.values()}=={first}


def test_targeted_recognition_scope_leaves_other_sources_unchanged(client,tmp_path):
    import numpy as np
    api,core=client
    first,_=register(api,files(tmp_path/'Photos',['a.jpg']))
    second,_=register(api,files(tmp_path/'Other',['b.jpg']))
    index(first,core);index(second,core)
    vector=np.zeros(128,np.float32);vector[0]=1
    with core.db() as c:
        c.execute("UPDATE faces SET embedding=?,status='manual' WHERE id IN ('a','c')",(vector.tobytes(),))
        for did,fid in ((first,'target'),(second,'other-target')):
            mid=c.execute('SELECT id FROM media WHERE database_id=?',(did,)).fetchone()[0]
            c.execute("INSERT INTO faces(id,media_id,embedding,status) VALUES(?,?,?,'suggested')",(fid,mid,vector.tobytes()))
    from backend import sync_service as sync
    sync.worker_context.run_id='fixture-run'
    sync.worker_context.database_id=first
    # check_control reads an empty isolated store; no live run is started.
    try:
        assert sync.auto_assign_until_stable()['assigned']==1
    finally:
        sync.worker_context.run_id=None
        sync.worker_context.database_id=None
    with core.db() as c:
        assert c.execute("SELECT status FROM faces WHERE id='target'").fetchone()[0]=='auto-sync'
        assert c.execute("SELECT person_id FROM faces WHERE id='other-target'").fetchone()[0] is None


def test_removal_prunes_queues_and_preserves_surviving_undo_entries(client,tmp_path):
    api,core=client
    did,_=register(api,files(tmp_path/'Photos',['a.jpg']));index(did,core)
    with core.db() as c:
        mid=c.execute('SELECT id FROM media WHERE database_id=?',(did,)).fetchone()[0]
        c.execute("INSERT INTO faces(id,media_id,person_id,status) VALUES('delete-me',?,1,'manual')",(mid,))
        aid=c.execute('INSERT INTO actions(description,previous) VALUES(?,?)',('mixed batch',json.dumps({'faces':[{'id':'delete-me','person_id':None},{'id':'a','person_id':2}]}))).lastrowid
    from backend import sync_service as sync
    with sync.store() as c:
        c.execute("INSERT INTO runs VALUES('old-target','2020',NULL,'paused','manual',?,NULL)",(json.dumps({'database_id':did}),))
        c.execute("INSERT INTO work VALUES('old-target',?,'preview',0,NULL)",(mid,))
        c.execute("INSERT INTO file_hashes VALUES('old-target',?,1,0,'fixture-sha')",(str(tmp_path/'Photos'/'a.jpg'),))
        c.execute("INSERT INTO streaming_roots VALUES('old-target',?,?,1)",(did,str(tmp_path/'Photos')))
    p=api.post(f'/api/databases/{did}/removal-preview',json={}).json()
    first=api.post(f'/api/databases/{did}/removal-first-confirm',json={'token':p['token'],'confirm':True}).json()
    assert api.post(f'/api/databases/{did}/removal-final-confirm',json={'token':first['token'],'confirm':True,'typed_alias':'Photos'}).status_code==200
    with core.db() as c:
        assert json.loads(c.execute('SELECT previous FROM actions WHERE id=?',(aid,)).fetchone()[0])=={'faces':[{'id':'a','person_id':2}]}
    with sync.store() as c:
        assert not c.execute('SELECT 1 FROM work WHERE media_id=?',(mid,)).fetchone()
        assert c.execute("SELECT state FROM runs WHERE id='old-target'").fetchone()[0]=='cancelled'
        assert not c.execute("SELECT 1 FROM file_hashes WHERE run_id='old-target'").fetchone()
        assert not c.execute("SELECT 1 FROM streaming_roots WHERE database_id=?",(did,)).fetchone()
    assert api.post('/api/sync/runs/old-target/resume',json={}).status_code==404


def test_migration_keeps_archived_version_ownership(client):
    _,core=client
    phone=core.PHONES[0]
    path=core.ROOT/phone/'Album'/'old.jpg'
    with core.db() as c:
        c.execute("UPDATE media SET path='archived://0',phone=?,status='superseded' WHERE id='0'",(phone,))
        c.execute('CREATE TABLE sync_versions(old_id TEXT PRIMARY KEY,new_id TEXT,source_path TEXT,created TEXT)')
        c.execute("INSERT INTO sync_versions VALUES('0','1',?,'2020')",(str(path),))
        c.execute("DELETE FROM library_meta WHERE key='legacy_migrated'")
        c.execute('DELETE FROM library_albums');c.execute('DELETE FROM library_sources');c.execute('DELETE FROM library_databases')
    core.init()
    with core.db() as c:
        m=dict(c.execute("SELECT * FROM media WHERE id='0'").fetchone())
        assert m['path']=='archived://0' and m['database_id'] and m['source_id']
        assert m['relative_path']==phone+'/Album/old.jpg'
        assert c.execute("SELECT person_id FROM faces WHERE id='a'").fetchone()[0]==1


def test_migration_snapshot_exists(client):
    _,core=client
    assert (core.DATA/'catalogue-before-source-management.sqlite').is_file()


def test_hidden_source_is_removed_from_people_and_library(client,tmp_path):
    api,core=client
    did,_=register(api,files(tmp_path/'Photos',['a.jpg']));index(did,core)
    with core.db() as c:
        m=dict(c.execute('SELECT * FROM media WHERE database_id=?',(did,)).fetchone())
        c.execute("INSERT INTO people(id,name) VALUES(8,'Fixture Person')")
        c.execute("INSERT INTO faces(id,media_id,person_id,status) VALUES('hide-face',?,8,'manual')",(m['id'],))
    assert any(p['id']==8 for p in api.get('/api/people').json())
    assert api.patch(f'/api/databases/{did}/sources/{m["source_id"]}',json={'visible':False}).status_code==200
    assert api.get('/api/media/'+m['id']).status_code==404
    assert api.get('/api/faces/hide-face/thumbnail').status_code==404
    assert not any(p['id']==8 for p in api.get('/api/people').json())


def test_stable_hierarchy_filters_distinguish_identical_aliases(client,tmp_path):
    api,core=client
    first,_=register(api,files(tmp_path/'Photos',['Album/a.jpg']),source_aliases={'':'Family'})
    second,_=register(api,files(tmp_path/'Other',['Album/b.jpg']),source_aliases={'':'Family'})
    index(first,core);index(second,core)
    sources=api.get('/api/sources').json()
    families=[s for s in sources if s['phone']=='Family']
    assert len(families)==2
    assert len({s['source_id'] for s in families})==2
    for did in (first,second):
        result=api.get('/api/media',params={'database_ids':did}).json()
        assert result['total']==1 and result['items'][0]['database_id']==did
    chosen=families[0]
    for key in ('source_id','album_id'):
        result=api.get('/api/media',params={key+'s':chosen[key]}).json()
        assert result['total']==1
        assert result['items'][0][key]==chosen[key]


def test_root_replaced_by_junction_is_unavailable(client,tmp_path,monkeypatch):
    api,core=client
    root=files(tmp_path/'Photos',['a.jpg']);did,_=register(api,root);index(did,core)
    real=Path.is_junction
    monkeypatch.setattr(Path,'is_junction',lambda p: p==root or real(p))
    from backend import source_management as sm
    with pytest.raises(RuntimeError,match='unavailable'):
        sm.inventory(did)
    with core.db() as c:
        row=c.execute('SELECT * FROM media WHERE database_id=?',(did,)).fetchone()
        assert row['status']=='ready'
        with pytest.raises(ValueError,match='links'):
            core.original(row)
    assert next(d for d in api.get('/api/databases').json() if d['id']==did)['availability']=='unavailable'


def test_management_hierarchy_lists_album_counts_and_stable_media_covers(client,tmp_path):
    api,core=client
    did,_=register(api,files(tmp_path/'Photos',['Family/a.jpg','Family/b.mov','Travel/Italy/Rome/c.jpg']))
    index(did,core)
    d=next(d for d in api.get('/api/databases').json() if d['id']==did)
    assert d['source_count']==1 and d['album_count']==2 and d['media_count']==3
    source=d['sources'][0]
    assert source['album_count']==2 and source['media_count']==3
    albums={a['alias']:a for a in source['albums']}
    assert albums['Family']['photos']==1 and albums['Family']['videos']==1
    assert albums['Travel › Italy › Rome']['media_count']==1
    for album in albums.values():
        result=api.get('/api/media',params={'album_ids':album['id']}).json()
        assert result['total']==album['media_count']
        assert album['cover'] in {m['id'] for m in result['items']}
    api.patch(f'/api/databases/{did}/sources/{source["id"]}',json={'alias':'New source alias'})
    after=next(d for d in api.get('/api/databases').json() if d['id']==did)['sources'][0]
    assert after['id']==source['id'] and after['albums']==source['albums']


@pytest.mark.parametrize('mode,expected', [
    ('sources', {('Root photos', 'Main folder'), ('Alex', 'Camera'), ('Alex', 'Trips › Rome'), ('Sam', 'Camera')}),
    ('collection', {('Root photos', 'Main folder'), ('Root photos', 'Alex › Camera'), ('Root photos', 'Alex › Trips › Rome'), ('Root photos', 'Sam › Camera')}),
    ('single_album', {('Root photos', 'Main folder')}),
])
def test_three_folder_roles_match_preview_index_and_future_scans(client, tmp_path, mode, expected):
    api, core = client
    root = files(tmp_path/'Role fixture', ['root.jpg', 'Alex/Camera/a.jpg', 'Alex/Trips/Rome/b.jpg', 'Sam/Camera/c.mov'])
    did, preview = register(api, root, interpretation=mode, source_aliases={'': 'Root photos'})
    assert {(s['source'], s['album']) for s in preview['samples']} == expected
    index(did, core)
    with core.db() as c:
        before = {r['relative_path']: (r['id'], r['source_id'], r['album_id']) for r in c.execute('SELECT * FROM media WHERE database_id=?', (did,))}
        assert {(r['phone'], r['album']) for r in c.execute('SELECT * FROM media WHERE database_id=?', (did,))} == expected
    files(root, ['Alex/Trips/Rome/Deeper/new.jpg'])
    index(did, core)
    with core.db() as c:
        current = {r['relative_path']: (r['id'], r['source_id'], r['album_id']) for r in c.execute('SELECT * FROM media WHERE database_id=?', (did,))}
        assert all(current[k] == ids for k, ids in before.items())
        assert len(current) == 5
        if mode == 'single_album':
            assert len({ids[1:] for ids in current.values()}) == 1


def test_single_album_migration_merges_nested_groups_without_losing_annotations(client, tmp_path):
    api, core = client
    root = files(tmp_path/'Role migration', ['Alex/Camera/a.jpg', 'Sam/Trips/Rome/b.jpg'])
    did, _ = register(api, root, interpretation='sources')
    index(did, core)
    with core.db() as c:
        media_ids = {r[0] for r in c.execute('SELECT id FROM media WHERE database_id=?', (did,))}
        mid = sorted(media_ids)[0]
        c.execute("INSERT INTO faces(id,media_id,person_id,status,embedding) VALUES('role-face',?,1,'manual',?)", (mid, b'role-preserved'))
        c.execute("INSERT INTO face_rejections VALUES('role-face',2)")
        before_faces = [tuple(r) for r in c.execute('SELECT * FROM faces ORDER BY id')]
        before_rejections = [tuple(r) for r in c.execute('SELECT * FROM face_rejections ORDER BY face_id,person_id')]
    preview = api.post(f'/api/databases/{did}/layout-preview', json={'root': str(root), 'interpretation': 'single_album'}).json()
    assert preview['album_count'] == 1 and len(preview['sources']) == 1
    assert api.post(f'/api/databases/{did}/layout-confirm', json={'token': preview['token'], 'confirm': True}).status_code == 200
    index(did, core)
    with core.db() as c:
        rows = c.execute('SELECT * FROM media WHERE database_id=?', (did,)).fetchall()
        assert {r['id'] for r in rows} == media_ids
        assert len({(r['source_id'], r['album_id']) for r in rows}) == 1
        assert [tuple(r) for r in c.execute('SELECT * FROM faces ORDER BY id')] == before_faces
        assert [tuple(r) for r in c.execute('SELECT * FROM face_rejections ORDER BY face_id,person_id')] == before_rejections


@pytest.mark.parametrize('mode', ['sources', 'collection', 'single_album'])
def test_database_and_source_aliases_are_independent_in_every_layout(client, tmp_path, mode):
    api, core = client
    root = files(tmp_path/'Alias roles', ['root.jpg', 'Alex/Camera/a.jpg', 'Sam/DCIM/b.mov'])
    aliases = {'': 'Shared photos', 'Alex': 'Alex phone', 'Sam': 'Sam phone'}
    did, preview = register(api, root, interpretation=mode, alias='Family archive', source_aliases=aliases)
    assert {s['database'] for s in preview['samples']} == {'Family archive'}
    expected_aliases = set(aliases.values()) if mode == 'sources' else {'Shared photos'}
    assert {s['source'] for s in preview['samples']} == expected_aliases
    index(did, core)
    database = next(d for d in api.get('/api/databases').json() if d['id'] == did)
    assert database['alias'] == 'Family archive'
    assert {s['alias'] for s in database['sources']} == expected_aliases
    sources = {s['id']: s['alias'] for s in database['sources']}
    with core.db() as c:
        before = {r['id']: (r['source_id'], r['album_id']) for r in c.execute('SELECT * FROM media WHERE database_id=?', (did,))}
    assert api.patch('/api/databases/'+did, json={'alias': 'Renamed database'}).status_code == 200
    database = next(d for d in api.get('/api/databases').json() if d['id'] == did)
    assert {s['id']: s['alias'] for s in database['sources']} == sources
    sid = next(iter(sources))
    assert api.patch(f'/api/databases/{did}/sources/{sid}', json={'alias': 'Selected source'}).status_code == 200
    index(did, core)
    database = next(d for d in api.get('/api/databases').json() if d['id'] == did)
    assert database['alias'] == 'Renamed database'
    assert {s['id']: s['alias'] for s in database['sources']} == {**sources, sid: 'Selected source'}
    with core.db() as c:
        rows = c.execute('SELECT * FROM media WHERE database_id=?', (did,)).fetchall()
        assert {r['id']: (r['source_id'], r['album_id']) for r in rows} == before
        assert all(r['phone'] == ('Selected source' if r['source_id'] == sid else sources[r['source_id']]) for r in rows)
