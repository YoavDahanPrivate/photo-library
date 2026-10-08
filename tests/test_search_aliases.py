from tests.test_catalogue import client
from tests.test_search_people import ids


def seed_usa(core):
    with core.db() as c:
        c.execute("INSERT INTO geographic_places VALUES('country:USA','United States of America','country','United States of America',NULL,NULL,'united states')")
        c.execute("INSERT INTO media_places VALUES('0','country:USA',NULL,NULL,'test')")


def test_country_aliases_and_bare_names(client):
    c, core = client
    seed_usa(core)
    for value in ['Place("USA")', 'Place("United States")', 'Place("US")', 'USA', 'United States', '"United States"']:
        assert ids(c, value) == {'0'}
    assert ids(c, 'Maya and United States') == {'0'}
    with core.db() as db:
        db.execute("UPDATE people SET name='Maya Smith' WHERE id=1")
    assert ids(c, 'Maya Smith') == {'0', '1'}
    assert ids(c, 'Maya Smith and USA') == {'0'}
    options=c.get('/api/place-options').json()['options']
    assert 'USA' in options[0]['search_aliases']
    assert 'United States' in options[0]['search_aliases']
    assert c.get('/api/search/validate',params={'expression':'Place("United")'}).status_code == 422


def test_alias_ambiguity_and_map_context(client):
    c, core = client
    seed_usa(core)
    with core.db() as db:
        db.execute("INSERT INTO people(id,name) VALUES(10,'USA')")
    assert c.get('/api/search/validate',params={'expression':'USA'}).status_code == 422
    assert ids(c, 'Place("USA")') == {'0'}
    assert ids(c, 'Person("USA")') == set()
    assert c.get('/api/map-context',params={'expression':'Place("USA") and Maya'}).json()['total'] == 2
