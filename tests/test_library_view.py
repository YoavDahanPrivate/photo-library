from tests.test_catalogue import client
import pytest

def pair(core):
    with core.db() as c:
        for identity,name,ext in [('h','Pair.HEIC','.heic'),('j','Pair.JPG','.jpg')]:
            c.execute("INSERT INTO media(id,path,name,extension,phone,album,kind,status,taken,width,height,latitude,longitude) VALUES(?,?,?,?,?,'Recents','photo','ready','2026-10-01',1200,800,32,34)",(identity,str(core.ROOT/name),name,ext,'Yoav14ProMax'))

def test_hide_format_copies_is_optional_and_non_destructive(client):
    api,core=client;pair(core)
    assert api.get('/api/media').json()['total']==5
    result=api.get('/api/media?hide_format_duplicates=true').json()
    assert result['total']==4
    assert 'h' in [m['id'] for m in result['items']] and 'j' not in [m['id'] for m in result['items']]
    assert api.get('/api/map-results?hide_format_duplicates=true').json()['known']==1
    assert api.get('/api/map-results?hide_format_duplicates=true').json()['total']==4
    with core.db() as c:assert c.execute("SELECT count(*) FROM media WHERE status='ready'").fetchone()[0]==5

@pytest.mark.parametrize('column,value',[('phone','Other'),('name','Other.JPG'),('taken','2026-10-02'),('taken',None),('width',100),('height',100),('kind','video'),('extension','.heic')])
def test_only_matching_valid_format_pairs_collapse(client,column,value):
    api,core=client;pair(core)
    with core.db() as c:c.execute('UPDATE media SET '+column+"=? WHERE id='j'",(value,))
    assert api.get('/api/media?hide_format_duplicates=true').json()['total']==5

def test_filter_precedes_format_collapse(client):
    api,core=client;pair(core)
    with core.db() as c:c.execute("INSERT INTO faces(id,media_id,person_id,bbox,embedding) VALUES('jpeg-face','j',1,'[]',?)",(b'0000',))
    result=api.get('/api/media?hide_format_duplicates=true&people=1').json()
    assert 'j' in [m['id'] for m in result['items']]
    assert 'h' not in [m['id'] for m in result['items']]
    assert api.get('/api/media?hide_format_duplicates=true&q=JPG').json()['total']==4

@pytest.mark.parametrize('order',['asc','desc'])
def test_neighbors_follow_entire_filtered_order(client,order):
    api,core=client;pair(core)
    with core.db() as c:
        for n in range(90):c.execute("INSERT INTO media(id,path,name,phone,kind,status,taken) VALUES(?,?,?,'Yoav14ProMax','photo','ready',?)",(f'x{n:03}',f'/x{n}',f'x{n}.jpg',f'2026-08-{n%28+1:02}'))
    query='hide_format_duplicates=true&phones=Yoav14ProMax&order='+order
    all_items=api.get('/api/media?limit=200&'+query).json()['items']
    ids=[m['id'] for m in all_items]
    for i in [0,79,80,len(ids)-1]:
        result=api.get('/api/media/'+ids[i]+'/neighbors?'+query).json()
        assert result['previous']==(ids[i-1] if i else None)
        assert result['next']==(ids[i+1] if i+1<len(ids) else None)
        assert result['position']==i+1 and result['total']==len(ids)
    assert api.get('/api/media/j/neighbors?'+query).json()['total']==0

def test_original_download_disposition(client):
    api,core=client
    path=core.ROOT/core.PHONES[0]/'download.jpg';path.parent.mkdir(parents=True);path.write_bytes(b'original image bytes')
    with core.db() as c:c.execute("UPDATE media SET path=?,name='download.jpg' WHERE id='0'",(str(path),))
    assert api.get('/api/media/0/original').headers['content-disposition'].startswith('inline')
    r=api.get('/api/media/0/original?download=true')
    assert r.status_code==200 and r.content==path.read_bytes()
    assert r.headers['content-disposition'].startswith('attachment')

def test_trash_pagination_and_full_selection(client):
    api,core=client
    from backend import duplicates as d
    d.init()
    with core.db() as c:
        for n in range(205):
            mid=f't{n:03}'
            c.execute("INSERT INTO media(id,path,name,phone,kind,status) VALUES(?,?,?,'Yoav14ProMax','photo','trashed')",(mid,'/original/'+mid,mid+'.jpg'))
            c.execute("INSERT INTO duplicate_trash(media_id,source,trash,state,created) VALUES(?,?,?,?,?)",(mid,'/original/'+mid,'/trash/'+mid,'attention' if n==204 else 'trashed','2026-10-01'))
    first=api.get('/api/duplicates/trash-page').json();last=api.get('/api/duplicates/trash-page?offset=180').json()
    assert first['total']==205 and len(first['items'])==30
    assert len(last['items'])==25 and last['items'][-1]['media_id']=='t204'
    ids=api.get('/api/duplicates/trash-selection').json()['media_ids']
    assert len(ids)==204 and 't204' not in ids


def test_display_original_photo_preserves_pixels_and_cache(client):
    from PIL import Image
    import io
    api,core=client
    path=core.ROOT/core.PHONES[0]/'full.tiff';path.parent.mkdir(parents=True)
    Image.new('RGB',(2400,1800),'orange').save(path)
    with core.db() as c:c.execute("UPDATE media SET path=?,kind='photo' WHERE id='0'",(str(path),))
    r=api.get('/api/media/0/display-original')
    assert r.status_code==200
    assert Image.open(io.BytesIO(r.content)).size==(2400,1800)
    assert api.get('/api/media/0/display-original').content==r.content
    assert len(list((core.DATA/'display-originals').glob('*.jpg')))==1
    Image.new('RGB',(2600,1900),'green').save(path)
    changed=api.get('/api/media/0/display-original')
    assert Image.open(io.BytesIO(changed.content)).size==(2600,1900)
    assert path.exists()

def test_display_original_errors(client):
    api,core=client
    assert api.get('/api/media/0/display-original').status_code==403
    path=core.ROOT/core.PHONES[0]/'missing.heic'
    with core.db() as c:c.execute("UPDATE media SET path=? WHERE id='0'",(str(path),))
    assert api.get('/api/media/0/display-original').status_code==404
    path.parent.mkdir(parents=True);path.write_bytes(b'bad image')
    assert api.get('/api/media/0/display-original').status_code==422
    assert not list((core.DATA/'display-originals').glob('*.tmp'))
    with core.db() as c:c.execute("UPDATE media SET kind='video' WHERE id='0'")
    assert api.get('/api/media/0/display-original').status_code==400


def test_navigation_buffer_is_bounded_and_matches_filtered_order(client):
    api,core=client;pair(core)
    with core.db() as c:
        for n in range(20):c.execute("INSERT INTO media(id,path,name,phone,kind,status,taken) VALUES(?,?,?,'Yoav14ProMax','photo','ready','2026-08-01')",(f'b{n:02}',f'/b{n}',f'b{n}.jpg'))
    query='hide_format_duplicates=true&phones=Yoav14ProMax'
    ids=[m['id'] for m in api.get('/api/media?limit=200&'+query).json()['items']]
    for position in [0,10,len(ids)-1]:
        result=api.get('/api/media/'+ids[position]+'/neighbors?'+query).json()
        rows=result['window'];assert len(rows)<=7
        assert [r['id'] for r in rows]==ids[max(0,position-3):position+4]
        for row in rows:
            i=ids.index(row['id'])
            assert row['previous']==(ids[i-1] if i else None)
            assert row['next']==(ids[i+1] if i+1<len(ids) else None)
    assert api.get('/api/media/j/neighbors?'+query).json()['window']==[]
