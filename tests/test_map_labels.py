from tests.test_catalogue import client
import sqlite3

def test_zoom_levels_and_viewport_limit(client):
    api,core=client
    path=core.DATA/'maps'/'gazetteer.sqlite';path.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(path) as c:
        c.execute('CREATE TABLE cities(id TEXT,name TEXT,lat REAL,lon REAL,feature_code TEXT)')
        c.executemany('INSERT INTO cities VALUES(?,?,?,?,?)',[('a','Capital',40,20,'PPLC'),('b','Regional',41,21,'PPLA'),('c','Local',42,22,'PPL'),('d','Outside',0,0,'PPLC')])
    params=dict(south=35,north=45,west=15,east=25,span=60)
    def names(span):
        return [r['name'] for r in api.get('/api/map/labels',params={**params,'span':span}).json()['cities']]
    assert names(180)==[]
    assert names(60)==['Capital']
    assert names(25)==['Capital','Regional']
    assert names(3)==['Capital','Regional','Local']
    assert api.get('/api/map/labels',params={**params,'south':50}).status_code==422
    with sqlite3.connect(path) as c:
        c.executemany('INSERT INTO cities VALUES(?,?,?,?,?)',[(str(n),'Extra',40,20,'PPL') for n in range(300)])
    assert len(names(3))==180

def test_missing_gazetteer_is_nonfatal(client):
    api,_=client
    response=api.get('/api/map/labels',params=dict(south=0,north=10,west=0,east=10,span=10))
    assert response.status_code==200 and response.json()=={'cities':[]}
