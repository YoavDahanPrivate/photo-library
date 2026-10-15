"""Metadata edits and catalogue removal use disposable SQLite and original fixtures."""
import hashlib
import json
import os
import time
from types import SimpleNamespace
import pytest
from PIL import Image
from tests.test_catalogue import client
from tests.test_source_management import register, index


def apply(api, body, params=None):
    p=api.post('/api/metadata/preview',json=body,params=params)
    assert p.status_code==200,p.text
    result=api.post('/api/metadata/confirm',json={'token':p.json()['token'],'confirm':True})
    assert result.status_code==200,result.text
    return p.json(),result.json()


def test_lazy_migration_keeps_all_existing_records_and_annotations(client):
    api,core=client
    with core.db() as c:
        baseline={t:[tuple(r) for r in c.execute('SELECT * FROM '+t+' ORDER BY rowid')] for t in ('media','faces','people','actions')}
    core.init();core.init()
    with core.db() as c:
        assert {t:[tuple(r) for r in c.execute('SELECT * FROM '+t+' ORDER BY rowid')] for t in baseline}==baseline
        assert c.execute('SELECT count(*) FROM media_overrides').fetchone()[0]==0
    assert api.get('/api/media/0').json()['date_source']=='embedded'


def test_fill_missing_preserves_embedded_metadata_and_manual_corrections(client):
    api,core=client
    with core.db() as c:
        c.execute("UPDATE media SET taken=NULL WHERE id='1'")
        c.execute("UPDATE media SET latitude=48.85,longitude=2.35 WHERE id='0'")
    p,result=apply(api,{'date':{'value':'1978','approximate':True},'location':{'label':'Old Paris home'}})
    assert p['matched']==3 and p['changed']==2 and p['skipped']==1
    a=api.get('/api/media/0').json();b=api.get('/api/media/1').json()
    assert a['taken']=='2026-09-06' and a['latitude']==48.85
    assert b['taken']=='1978' and b['date_precision']=='year' and b['date_approximate']
    assert b['latitude'] is None and b['location_label']=='Old Paris home'
    p,_=apply(api,{'date':{'value':'1980'},'location':{'label':'Elsewhere'}})
    assert p['changed']==0


def test_place_without_coordinates_is_searchable_but_not_a_pin(client):
    api,core=client
    apply(api,{'media_ids':['0'],'location':{'label':'Paris'}})
    def ids(expression):return {r['id'] for r in api.get('/api/media',params={'expression':expression}).json()['items']}
    assert ids('Place("Paris")')=={'0'}
    assert ids('Location("unknown")')=={'1','2'}
    assert ids('Location("no_gps")')=={'0','1','2'}
    m=api.get('/api/map-results').json()
    assert m['unlocated']==2 and m['place_only']==1 and m['no_gps']==3 and not m['points']
    p=api.get('/api/media/0').json()
    assert p['location_source']=='manual' and p['location_precision']=='place'


def test_manual_point_and_map_collection_or_filter(client):
    api,_=client
    apply(api,{'media_ids':['0'],'location':{'label':'Paris','latitude':48.85,'longitude':2.35}})
    m=api.get('/api/map-results').json()
    assert m['known']==1 and m['unlocated']==2 and m['points'][0]['latitude']==48.85
    geo={'places':[],'unknown':True,'includes':[{'id':'a','south':48,'north':49,'west':2,'east':3}],'excludes':[]}
    assert api.get('/api/media',params={'geo':json.dumps(geo)}).json()['total']==3
    assert api.get('/api/media/0').json()['location_source']=='manual'


@pytest.mark.parametrize('value,end,expression',[('1978',None,'in 1978'),('1978-06',None,'on 1978-06-15'),('1978','1980','in 1979')])
def test_partial_dates_and_ranges_overlap_search_without_invented_day(client,value,end,expression):
    api,_=client
    date={'value':value,'approximate':True}
    if end:date['end']=end
    apply(api,{'media_ids':['0'],'mode':'replace','date':date})
    assert api.get('/api/media/0').json()['taken']==value
    assert {r['id'] for r in api.get('/api/media',params={'expression':expression}).json()['items']}=={'0'}
    assert api.get('/api/media',params={'start':'1978-06-15','end':'1978-06-15'}).json()['total']==1
    assert api.get('/api/media',params={'expression':'before 1978'}).json()['total']==0


@pytest.mark.parametrize('body',[
 {'date':{'value':'1978-02-30'}},{'date':{'value':'0000'}}, {'date':{'value':'1980','end':'1979'}},
 {'location':{'latitude':10}},{'location':{'latitude':100,'longitude':10}},
 {'location':{'label':'   '}},{'restore':'both','date':{'value':'1978'}},{}
])
def test_invalid_edits_are_atomic(client,body):
    api,core=client
    assert api.post('/api/metadata/preview',json=body).status_code==422
    with core.db() as c:
        assert not c.execute('SELECT 1 FROM media_overrides').fetchone()
        assert c.execute('SELECT taken FROM media WHERE id="0"').fetchone()[0]=='2026-09-06'


def test_preview_confirm_replay_expiry_and_conflicts(client):
    api,core=client
    body={'media_ids':['0'],'mode':'replace','date':{'value':'1978'}}
    p=api.post('/api/metadata/preview',json=body).json()
    assert api.post('/api/metadata/confirm',json={'token':p['token']}).status_code==422
    apply(api,{**body,'date':{'value':'1980'}})
    assert api.post('/api/metadata/confirm',json={'token':p['token'],'confirm':True}).status_code==409
    p=api.post('/api/metadata/preview',json=body).json()
    assert api.post('/api/metadata/confirm',json={'token':p['token'],'confirm':True}).status_code==200
    assert api.post('/api/metadata/confirm',json={'token':p['token'],'confirm':True}).status_code==409
    p=api.post('/api/metadata/preview',json=body).json()
    with core.db() as c:c.execute("UPDATE metadata_previews SET created='2020-01-01T00:00:00+00:00'")
    assert api.post('/api/metadata/confirm',json={'token':p['token'],'confirm':True}).status_code==409


def test_stale_bulk_preview_detects_place_enrichment_and_hidden_media(client):
    api,core=client
    p=api.post('/api/metadata/preview',json={'media_ids':['0'],'location':{'label':'Paris'}}).json()
    with core.db() as c:
        c.execute("INSERT INTO geographic_places VALUES('x','Test','country','Test',NULL,NULL,'test')")
        c.execute("INSERT INTO media_places VALUES('0','x',NULL,NULL,'test')")
    assert api.post('/api/metadata/confirm',json={'token':p['token'],'confirm':True}).status_code==409
    assert api.post('/api/metadata/preview',json={'media_ids':['0','absent'],'date':{'value':'1978'}}).status_code==409


def test_scope_bulk_edit_respects_current_people_filters(client):
    api,_=client
    p,_=apply(api,{'date':{'value':'1978'},'mode':'replace'},params={'people':[1,2]})
    assert p['changed']==1 and p['samples'][0]['id']=='0'
    assert api.get('/api/media/1').json()['taken']=='2026-09-06'


def test_saved_place_selection_does_not_copy_city_center_to_image(client):
    api,core=client
    with core.db() as c:
        c.execute("INSERT INTO geographic_places VALUES('country:FRA','France','country','France',NULL,NULL,'france')")
        c.execute("INSERT INTO geographic_places VALUES('city:Paris','Paris','city','France',48.85,2.35,'paris')")
    apply(api,{'media_ids':['0'],'location':{'place_id':'city:Paris'}})
    assert api.get('/api/media/0').json()['latitude'] is None
    assert api.get('/api/media',params={'expression':'Place("France")'}).json()['total']==1


def test_undo_restore_and_rescan_preserve_separate_embedded_metadata(client):
    api,core=client
    from backend import metadata_support as ms
    p,r=apply(api,{'media_ids':['0'],'mode':'replace','date':{'value':'1978'},'location':{'label':'Paris'}})
    with core.db() as c:
        ms.record_embedded(c,'0',{'taken':'1985-07-15','latitude':32,'longitude':34},SimpleNamespace(st_mtime=1234,st_birthtime=1200))
    d=api.get('/api/media/0').json()
    assert d['taken']=='1978' and d['embedded_taken']=='1985-07-15' and d['latitude'] is None and d['file_created']==1200
    assert api.post('/api/metadata/undo/'+str(r['action_id']),json={}).status_code==200
    d=api.get('/api/media/0').json()
    assert d['taken']=='1985-07-15' and d['latitude']==32 and d['date_source']=='embedded'
    p,r=apply(api,{'media_ids':['0'],'mode':'replace','date':{'value':'1990'}})
    apply(api,{'media_ids':['0'],'restore':'date'})
    assert api.get('/api/media/0').json()['taken']=='1985-07-15'
    assert api.post('/api/undo',json={}).status_code==200
    assert api.get('/api/media/0').json()['taken']=='1990'


def test_undo_refuses_newer_override_and_preserves_unrelated_faces(client):
    api,core=client
    _,a=apply(api,{'media_ids':['0'],'mode':'replace','date':{'value':'1978'}})
    _,b=apply(api,{'media_ids':['0'],'mode':'replace','date':{'value':'1980'}})
    assert api.post('/api/metadata/undo/'+str(a['action_id']),json={}).status_code==409
    assert api.post('/api/metadata/undo/'+str(b['action_id']),json={}).status_code==200
    assert api.post('/api/metadata/undo/'+str(a['action_id']),json={}).status_code==200
    with core.db() as c:assert c.execute('SELECT person_id FROM faces WHERE id="a"').fetchone()[0]==1


def test_header_report_tagless_embedded_and_year_suggestions(client,tmp_path):
    api,_=client
    root=tmp_path/'Archive'
    (root/'1978'/'Paris').mkdir(parents=True)
    Image.new('RGB',(20,20)).save(root/'1978'/'Paris'/'scan.jpg')
    exif=Image.Exif();exif[306]='1985:06:15 10:30:00'
    Image.new('RGB',(20,20)).save(root/'dated.jpg',exif=exif)
    p=api.post('/api/databases/preview',json={'root':str(root)}).json()
    assert p['metadata_report'] is None  # Metadata is deferred until indexing.
    from backend.metadata_support import file_report
    report=file_report(root,[{'relative':'dated.jpg','mtime':(root/'dated.jpg').stat().st_mtime},{'relative':'1978/Paris/scan.jpg','mtime':(root/'1978/Paris/scan.jpg').stat().st_mtime}])
    assert report['inspected']==2 and not report['sampled']
    assert report['counts']=={'capture_date':1,'gps':0,'file_date_only':1,'no_metadata':1,'unreadable':0}
    assert any(e['suggested_year']=='1978' for e in report['examples'])


def test_sample_report_labels_counts_as_sample(client,tmp_path):
    _,_=client
    from backend.metadata_support import file_report
    root=tmp_path/'sample';root.mkdir()
    files=[]
    for i in range(6):
        p=root/f'{i}.jpg';Image.new('RGB',(10,10)).save(p)
        files.append({'relative':p.name,'mtime':p.stat().st_mtime})
    report=file_report(root,files,limit=3)
    assert report['sampled'] and report['inspected']==3 and report['total_files']==6


def test_index_worker_reapplies_overrides_without_changing_originals(client,tmp_path):
    api,core=client
    from backend import full_scan
    root=tmp_path/'ScannedArchive';root.mkdir()
    path=root/'scan.jpg';Image.new('RGB',(30,20)).save(path);os.utime(path,(time.time()-120,time.time()-120))
    did,_=register(api,root);index(did,core)
    with core.db() as c:
        mid=c.execute('SELECT id FROM media WHERE database_id=?',(did,)).fetchone()[0]
        c.execute('UPDATE media SET taken=NULL WHERE id=?',(mid,))
    apply(api,{'media_ids':[mid],'date':{'value':'1978'},'location':{'label':'Paris'}})
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    with core.db() as c:c.execute("UPDATE media SET status='pending' WHERE id=?",(mid,))
    (core.DATA/'thumbs').mkdir(exist_ok=True)
    result=full_scan.process_one(mid,preview_only=True)
    assert result['ok'],result
    d=api.get('/api/media/'+mid).json()
    assert d['taken']=='1978' and d['location_label']=='Paris' and d['embedded_taken'] is None
    assert hashlib.sha256(path.read_bytes()).hexdigest()==digest


def test_layout_reconnect_removal_preserve_or_delete_annotations_only(client,tmp_path):
    api,core=client
    root=tmp_path/'Photos';(root/'Trips').mkdir(parents=True)
    path=root/'Trips'/'scan.jpg';Image.new('RGB',(20,20)).save(path);os.utime(path,(time.time()-120,time.time()-120))
    did,_=register(api,root);index(did,core)
    with core.db() as c:mid=c.execute('SELECT id FROM media WHERE database_id=?',(did,)).fetchone()[0]
    apply(api,{'media_ids':[mid],'mode':'replace','date':{'value':'1978'},'location':{'label':'Paris'}})
    p=api.post(f'/api/databases/{did}/layout-preview',json={'root':str(root),'interpretation':'single_album'}).json()
    assert api.post(f'/api/databases/{did}/layout-confirm',json={'token':p['token'],'confirm':True}).status_code==200
    moved=tmp_path/'Moved';root.rename(moved)
    p=api.post(f'/api/databases/{did}/reconnect-preview',json={'root':str(moved)}).json()
    assert api.post(f'/api/databases/{did}/reconnect-confirm',json={'token':p['token'],'confirm':True}).status_code==200
    assert api.get('/api/media/'+mid).json()['taken']=='1978'
    path=moved/'Trips'/'scan.jpg';digest=hashlib.sha256(path.read_bytes()).hexdigest()
    pending=api.post('/api/metadata/preview',json={'media_ids':[mid],'mode':'replace','date':{'value':'1980'}}).json()
    p=api.post(f'/api/databases/{did}/removal-preview').json()
    second=api.post(f'/api/databases/{did}/removal-first-confirm',json={'token':p['token'],'confirm':True}).json()
    assert api.post(f'/api/databases/{did}/removal-final-confirm',json={'token':second['token'],'confirm':True,'typed_alias':'Photos'}).status_code==200
    assert api.post('/api/metadata/confirm',json={'token':pending['token'],'confirm':True}).status_code==409
    with core.db() as c:
        assert not c.execute('SELECT 1 FROM metadata_previews WHERE id=?',(pending['token'],)).fetchone()
        assert not c.execute('SELECT 1 FROM media_overrides WHERE media_id=?',(mid,)).fetchone()
        assert not c.execute('SELECT 1 FROM media_original_metadata WHERE media_id=?',(mid,)).fetchone()
        assert not c.execute("SELECT 1 FROM actions WHERE previous LIKE ?",('%'+mid+'%',)).fetchone()
    assert hashlib.sha256(path.read_bytes()).hexdigest()==digest


def test_file_sort_is_explicit_and_does_not_assign_capture_dates(client):
    api,core=client
    with core.db() as c:
        c.execute('UPDATE media SET taken=NULL,mtime=1000 WHERE id="0"')
        c.execute('UPDATE media SET mtime=3000 WHERE id="1"')
        c.execute('UPDATE media SET mtime=2000 WHERE id="2"')
    rows=api.get('/api/media',params={'sort_by':'file','order':'desc'}).json()['items']
    assert [r['id'] for r in rows]==['1','2','0']
    assert rows[2]['taken'] is None and rows[2]['date_source']=='unknown'
    assert api.get('/api/media/2/neighbors',params={'sort_by':'file'}).json()['previous']=='1'


def test_metadata_confirmation_works_during_isolated_scan_lock(client):
    api,_=client
    from backend.sync_service import scan_lock
    with scan_lock():
        _,r=apply(api,{'media_ids':['0'],'mode':'replace','date':{'value':'1978'}})
    assert r['changed']==1


def test_stale_worker_geography_does_not_overwrite_manual_point(client,monkeypatch):
    api,core=client
    from backend import full_scan
    with core.db() as c:c.execute("UPDATE media SET latitude=32,longitude=34,face_status='ready' WHERE id='0'")
    class Locations:
        def resolve(self,lat,lon):
            assert (lat,lon)==(32,34)
            apply(api,{'media_ids':['0'],'mode':'replace','location':{'latitude':40,'longitude':10}})
            return None,'wrong-place',0,[('wrong-place','Wrong city','city','',32,34,'wrong city')]
    monkeypatch.setattr(full_scan,'locations',Locations())
    assert full_scan.process_one('0')['ok']
    d=api.get('/api/media/0').json()
    assert d['latitude']==40 and d['city'] is None and d['location_source']=='manual'
    p=api.get('/api/map-results').json()['points'][0]
    assert p['latitude']==40 and p['manual_count']==1


def test_metadata_edit_invalidates_catalogue_removal_preview(client,tmp_path):
    api,core=client
    root=tmp_path/'Other';root.mkdir();Image.new('RGB',(10,10)).save(root/'a.jpg')
    os.utime(root/'a.jpg',(time.time()-120,time.time()-120))
    did,_=register(api,root);index(did,core)
    with core.db() as c:mid=c.execute('SELECT id FROM media WHERE database_id=?',(did,)).fetchone()[0]
    p=api.post(f'/api/databases/{did}/removal-preview').json()
    second=api.post(f'/api/databases/{did}/removal-first-confirm',json={'token':p['token'],'confirm':True}).json()
    apply(api,{'media_ids':[mid],'mode':'replace','date':{'value':'1978'}})
    assert api.post(f'/api/databases/{did}/removal-final-confirm',json={'token':second['token'],'confirm':True,'typed_alias':'Other'}).status_code==409
    assert (root/'a.jpg').is_file() and api.get('/api/media/'+mid).json()['taken']=='1978'
