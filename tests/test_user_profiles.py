from tests.test_catalogue import client
from fastapi.testclient import TestClient


def signed_in(fixture, identity):
    previous, core = fixture
    # Test data only: account-lifecycle tests separately cover mandatory changes.
    with core.db() as database:
        database.execute('UPDATE account_passwords SET must_change=0 WHERE profile_id=?', (identity,))
    http = TestClient(previous.app, base_url='https://localhost', headers={'Origin':'http://localhost'})
    response = http.post('/api/auth/login', json={'username':identity,'password':identity.capitalize()+'1919'})
    assert response.status_code == 200, response.text
    return http, core

def test_profiles_restore_isolate_and_validate(client):
    c, _ = signed_in(client, "yoav")
    assert [p['name'] for p in c.get('/api/profiles').json()] == ['Yoav','Hila','Bar','Rotem','Guy','Drora','Guest']
    yoav=c.post('/api/profiles/yoav/select').json()
    assert yoav['last_login_at'] and yoav['source_ids'] is None
    prefs={'theme':'white','source_ids':['source-1'],'source_names':['My phone']}
    assert c.put('/api/profiles/yoav/preferences',json=prefs).status_code==200
    assert c.post('/api/profiles/hila/select').status_code == 403
    hila, _ = signed_in(client, 'hila')
    assert hila.post('/api/profiles/hila/select').json()['theme']=='sage'
    restored=c.post('/api/profiles/yoav/select').json()
    assert all(restored[k]==v for k,v in prefs.items())
    assert c.put('/api/profiles/yoav/preferences',json={**prefs,'theme':'bad'}).status_code==422
    assert c.post('/api/profiles/nobody/select').status_code==403
    assert c.put('/api/profiles/yoav/preferences',json={**prefs,'source_ids':[],'source_names':[]}).status_code==200
    assert c.post('/api/profiles/yoav/select').json()['source_ids']==[]

def test_history_distinguishes_searches_and_requested_downloads(client):
    c, core = signed_in(client, "bar")
    c.post('/api/profiles/bar/select')
    assert c.post('/api/profiles/bar/searches',json={'expression':'Includes("Maya")','source_names':['Yoav14ProMax']}).status_code==200
    thumbs=core.DATA/'thumbs';thumbs.mkdir(exist_ok=True)
    (thumbs/'0-small.jpg').write_bytes(b'\xff\xd8test')
    assert c.get('/api/media/0/thumbnail?size=small').status_code==200
    assert c.get('/api/media/0/thumbnail?size=small&activity=download&profile_id=bar').status_code==200
    rows=c.get('/api/profiles/bar/activity').json()
    assert [r['kind'] for r in rows]==['download_requested','search','login']
    assert rows[0]['details']['media_id']=='0'
    assert rows[1]['details']['expression']=='Includes("Maya")'
    assert c.get('/api/profiles/guest/activity').status_code == 403


def test_people_preferences_default_restore_validation_and_account_isolation(client):
    yoav, _ = signed_in(client, 'yoav')
    assert yoav.get('/api/auth/me').json()['people_browse'] is None
    prefs={'known':True,'unknown':False,'sort':'name','directions':{'name':'desc','count':'asc'},'action':'edit'}
    assert yoav.put('/api/profiles/yoav/people-preferences',json=prefs).status_code==200
    # Existing theme/source saves must not overwrite People choices.
    yoav.put('/api/profiles/yoav/preferences',json={'theme':'plum','source_ids':[],'source_names':[]})
    another_device, _ = signed_in(client, 'yoav')
    assert another_device.get('/api/auth/me').json()['people_browse']==prefs
    hila, _ = signed_in(client, 'hila')
    assert hila.get('/api/auth/me').json()['people_browse'] is None
    assert hila.put('/api/profiles/yoav/people-preferences',json=prefs).status_code==403
    assert yoav.put('/api/profiles/yoav/people-preferences',json={**prefs,'sort':'invalid'}).status_code==422
    assert yoav.put('/api/profiles/yoav/people-preferences',json={**prefs,'known':False,'unknown':False}).status_code==422
    assert yoav.put('/api/profiles/yoav/people-preferences',json={}).json()['people_browse']['sort']=='count'


def test_people_action_defaults_and_validation(client):
    c, _ = signed_in(client, 'yoav')
    defaults = c.put('/api/profiles/yoav/people-preferences', json={}).json()['people_browse']
    assert defaults['known'] is True
    assert defaults['unknown'] is False
    assert defaults['action'] == 'search'
    assert 'selection' not in defaults
    assert c.put('/api/profiles/yoav/people-preferences', json={'action':'delete'}).status_code == 422
    # Existing preferences without the new keys retain their visibility choices.
    old = c.put('/api/profiles/yoav/people-preferences', json={'known':False,'unknown':True}).json()['people_browse']
    assert old['known'] is False and old['unknown'] is True
    assert old['action'] == 'search' and 'selection' not in old


def test_selection_is_not_saved_and_old_setting_is_removed(client):
    import json
    from backend import user_profiles
    c, core = signed_in(client, 'yoav')
    result = c.put('/api/profiles/yoav/people-preferences', json={'selection':True,'action':'edit'}).json()['people_browse']
    assert 'selection' not in result
    with core.db() as db:
        db.execute("UPDATE user_people_preferences SET preferences=? WHERE profile_id='yoav'", (json.dumps({**result,'selection':True}),))
        user_profiles.migrate(db)
        stored = json.loads(db.execute("SELECT preferences FROM user_people_preferences WHERE profile_id='yoav'").fetchone()[0])
    assert stored == result
