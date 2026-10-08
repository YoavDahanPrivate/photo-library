from tests.test_catalogue import client
from tests.test_search_people import ids

def test_empty_duplicate_search_and_clear_undo(client):
    c,core=client
    with core.db() as db:
        db.execute("INSERT INTO people(id,name) VALUES(12,'Maya')")
    assert ids(c,'Includes("Maya")')=={'0','1'}
    records=c.get('/api/people-name-records').json()
    assert len([r for r in records if r['conflict']])==2
    assert c.post('/api/people/1/clear-unused-name').status_code==409
    assert c.post('/api/people/12/clear-unused-name').status_code==200
    assert not any(r['conflict'] for r in c.get('/api/people-name-records').json())
    assert c.post('/api/undo').status_code==200
    assert len([r for r in c.get('/api/people-name-records').json() if r['conflict']])==2

def test_media_shortcuts(client):
    c,core=client
    with core.db() as db:
        db.execute("UPDATE media SET kind='video' WHERE id='2'")
    for phrase in ['photos','images','only photos','only images','photos only','images only','MediaType("photo")']:
        assert ids(c,phrase)=={'0','1'}
    for phrase in ['videos','only videos','videos only','MediaType("video")']:
        assert ids(c,phrase)=={'2'}
    assert ids(c,'photos and Maya')=={'0','1'}
    assert c.get('/api/search/validate',params={'expression':'only videos and after 2025'}).json()['expression']=='MediaType("video") and after 2025'
