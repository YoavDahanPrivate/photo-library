"""Portrait metadata and schema changes use disposable catalogues only."""
import json
import sqlite3
import pytest
from tests.test_catalogue import client


@pytest.fixture
def portraits(client):
    api,core=client
    folder=core.DATA/'faces';folder.mkdir(parents=True,exist_ok=True)
    for identity in ('a','b','c'):
        (folder/(identity+'.jpg')).write_bytes(b'isolated face crop')
    return api,core


def person(api,identity=1):
    return next(row for row in api.get('/api/people').json() if row['id']==identity)


def test_default_choose_persists_everywhere_and_does_not_change_recognition(portraits):
    api,core=portraits
    assert person(api)['cover']=='a'
    with core.db() as c:
        faces=[tuple(r) for r in c.execute('SELECT * FROM faces ORDER BY id')]
        c.execute("INSERT INTO face_suggestions VALUES('a',2,.95,.2)")
        c.execute("INSERT INTO face_rejections VALUES('c',2)")
        before_revision=c.execute('SELECT revision FROM catalogue_clock').fetchone()[0]
    chosen=api.post('/api/people/1/portrait',json={'face_id':'c'})
    assert chosen.status_code==200,chosen.text
    assert chosen.json()['cover']=='c' and chosen.json()['portrait_custom']
    assert chosen.json()['automatic_cover']=='a'
    assert person(api)['cover']=='c' and person(api)['count']==2
    assert next(row for row in api.get('/api/people-name-records').json() if row['id']==1)['cover']=='c'
    core.init()  # Startup migration is idempotent and does not reset a choice.
    assert person(api)['cover']=='c'
    with core.db() as c:
        assert faces==[tuple(r) for r in c.execute('SELECT * FROM faces ORDER BY id')]
        assert tuple(c.execute('SELECT * FROM face_suggestions').fetchone())==('a',2,.95,.2)
        assert tuple(c.execute('SELECT * FROM face_rejections').fetchone())==('c',2)
        assert c.execute('SELECT revision FROM catalogue_clock').fetchone()[0]>before_revision
    assert (core.DATA/'faces/c.jpg').read_bytes()==b'isolated face crop'


def test_reset_undo_and_noop_are_metadata_only(portraits):
    api,core=portraits
    assert api.post('/api/people/1/portrait',json={'face_id':'c'}).status_code==200
    with core.db() as c:
        actions=c.execute('SELECT count(*) FROM actions').fetchone()[0]
    assert api.post('/api/people/1/portrait',json={'face_id':'c'}).status_code==200
    with core.db() as c:
        assert c.execute('SELECT count(*) FROM actions').fetchone()[0]==actions
    response=api.post('/api/people/1/portrait',json={'face_id':None})
    assert response.json()['cover']=='a' and not response.json()['portrait_custom']
    assert api.post('/api/undo',json={}).status_code==200
    assert person(api)['cover']=='c'
    assert api.post('/api/undo',json={}).status_code==200
    assert person(api)['cover']=='a' and not person(api)['portrait_custom']


@pytest.mark.parametrize('face,code',[('b',409),('missing',409),('',422),('x'*241,422)])
def test_reject_another_person_missing_or_malformed_face(portraits,face,code):
    api,core=portraits
    assert api.post('/api/people/1/portrait',json={'face_id':face}).status_code==code
    with core.db() as c:
        assert not c.execute('SELECT * FROM person_portraits').fetchall()
        assert not c.execute('SELECT * FROM actions').fetchall()


def test_special_buckets_missing_people_and_explicit_reset_validation(portraits):
    api,_=portraits
    for identity in (-1,0):
        assert api.get(f'/api/people/{identity}/portrait').status_code==422
        assert api.post(f'/api/people/{identity}/portrait',json={'face_id':'a'}).status_code==422
    assert api.get('/api/people/100/portrait').status_code==404
    assert api.post('/api/people/100/portrait',json={'face_id':'a'}).status_code==404
    assert api.post('/api/people/1/portrait',json={}).status_code==422


def test_missing_crop_cannot_be_saved(portraits):
    api,core=portraits
    (core.DATA/'faces/c.jpg').unlink()
    candidates=api.get('/api/people/1/portrait').json()['items']
    assert next(row for row in candidates if row['id']=='c')['available'] is False
    assert api.post('/api/people/1/portrait',json={'face_id':'c'}).status_code==409


@pytest.mark.parametrize('change',[
    "UPDATE faces SET status='dismissed' WHERE id='c'",
    "UPDATE faces SET person_id=2 WHERE id='c'",
    "INSERT INTO unknown_faces VALUES('c')",
    "UPDATE media SET status='missing' WHERE id='1'",
    "UPDATE media SET status='trashed' WHERE id='1'",
])
def test_invalid_saved_face_falls_back_without_reassigning_faces(portraits,change):
    api,core=portraits
    assert api.post('/api/people/1/portrait',json={'face_id':'c'}).status_code==200
    with core.db() as c:c.execute(change)
    assert person(api)['cover']=='a' and not person(api)['portrait_custom']
    choices=api.get('/api/people/1/portrait').json()
    assert 'c' not in {row['id'] for row in choices['items']}
    assert api.post('/api/people/1/portrait',json={'face_id':'c'}).status_code==409


def test_reassignment_undo_restores_valid_selected_portrait(portraits):
    api,_=portraits
    api.post('/api/people/1/portrait',json={'face_id':'c'})
    assert api.post('/api/faces/correct',json={'face_ids':['c'],'action':'move','target':2}).status_code==200
    assert person(api)['cover']=='a'
    assert api.post('/api/undo',json={}).status_code==200
    assert person(api)['cover']=='c'


def test_deleted_face_clears_selection_foreign_keys_and_undo_stays_safe(portraits):
    api,core=portraits
    api.post('/api/people/1/portrait',json={'face_id':'a'})
    api.post('/api/people/1/portrait',json={'face_id':'c'})
    with core.db() as c:c.execute("DELETE FROM faces WHERE id='a'")
    assert api.post('/api/undo',json={}).status_code==200
    assert person(api)['cover']=='c' and not person(api)['portrait_custom']
    with core.db() as c:
        c.execute("DELETE FROM faces WHERE id='c'")
        assert c.execute('PRAGMA foreign_key_check').fetchall()==[]


def test_candidate_paging_reaches_every_face_and_video_frame(portraits):
    api,core=portraits
    with core.db() as c:
        c.execute("UPDATE media SET kind='video' WHERE id='1'")
        c.executemany("INSERT INTO faces(id,media_id,person_id,timestamp,status) VALUES(?,'1',1,?,'manual')",
                      [(f'frame-{i:03}',i+.5) for i in range(73)])
    seen=[]
    for offset in (0,30,60):
        result=api.get('/api/people/1/portrait',params={'offset':offset}).json()
        assert result['total']==75 and len(result['items'])==(30 if offset<60 else 15)
        seen.extend(row['id'] for row in result['items'])
        assert any(row['kind']=='video' for row in result['items'])
    assert len(set(seen))==75
    for query in ('?offset=-1','?limit=0','?limit=101'):
        assert api.get('/api/people/1/portrait'+query).status_code==422


def test_schema_upgrade_preserves_existing_annotations(portraits):
    api,core=portraits
    with core.db() as c:
        c.execute('DROP TABLE person_portraits')
        c.execute("INSERT INTO face_rejections VALUES('a',2)")
        c.execute("INSERT INTO review_approvals(face_id,person_id) VALUES('a',1)")
        faces=[tuple(r) for r in c.execute('SELECT * FROM faces ORDER BY id')]
    core.init()
    with core.db() as c:
        assert faces==[tuple(r) for r in c.execute('SELECT * FROM faces ORDER BY id')]
        assert tuple(c.execute('SELECT * FROM face_rejections').fetchone())==('a',2)
        assert c.execute('SELECT count(*) FROM review_approvals').fetchone()[0]==1
        assert c.execute('SELECT count(*) FROM person_portraits').fetchone()[0]==0
        assert c.execute('PRAGMA foreign_key_check').fetchall()==[]
    assert person(api)['cover']=='a'


def test_hidden_sources_and_database_removal_keep_portraits_safe(portraits,tmp_path):
    from tests.test_source_management import files,register,index
    api,core=portraits
    root=files(tmp_path/'Portrait source',['portrait.jpg'])
    did,_=register(api,root);index(did,core)
    with core.db() as c:
        media=c.execute('SELECT id,source_id FROM media WHERE database_id=?',(did,)).fetchone()
        c.execute("INSERT INTO faces(id,media_id,person_id,status) VALUES('chosen-registered',?,1,'manual')",(media['id'],))
        sid=media['source_id']
    (core.DATA/'faces/chosen-registered.jpg').write_bytes(b'isolated crop')
    assert api.post('/api/people/1/portrait',json={'face_id':'chosen-registered'}).status_code==200
    assert api.patch(f'/api/databases/{did}/sources/{sid}',json={'visible':False}).status_code==200
    assert person(api)['cover']=='a'
    assert 'chosen-registered' not in {r['id'] for r in api.get('/api/people/1/portrait').json()['items']}
    assert api.post('/api/people/1/portrait',json={'face_id':'chosen-registered'}).status_code==409
    assert api.patch(f'/api/databases/{did}/sources/{sid}',json={'visible':True}).status_code==200
    assert person(api)['cover']=='chosen-registered'
    assert api.patch(f'/api/databases/{did}',json={'visible':False}).status_code==200
    records=api.get('/api/people-name-records').json()
    assert next(r for r in records if r['id']==1)['cover']=='a'
    assert api.patch(f'/api/databases/{did}',json={'visible':True}).status_code==200
    preview=api.post(f'/api/databases/{did}/removal-preview',json={}).json()
    first=api.post(f'/api/databases/{did}/removal-first-confirm',json={'token':preview['token'],'confirm':True}).json()
    response=api.post(f'/api/databases/{did}/removal-final-confirm',json={'token':first['token'],'confirm':True,'typed_alias':'Portrait source'})
    assert response.status_code==200,response.text
    assert (root/'portrait.jpg').read_bytes()==b'fixture:portrait.jpg'
    assert person(api)['cover']=='a'
    with core.db() as c:
        assert c.execute('PRAGMA foreign_key_check').fetchall()==[]
