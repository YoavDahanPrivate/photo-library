from tests.test_catalogue import client
import pytest

@pytest.mark.parametrize('expression, expected', [
    ('Includes("Maya") and Area("30,35,30,40")', 2),
    ('Includes("Maya") and not Area("30,35,30,40")', 2),
    ('Includes("Maya") and (Area("30,35,30,40") or Area("40,50,0,10"))', 2),
    ('not (Area("30,35,30,40") or Includes("Daniel"))', 2),
    ('Area("30,35,30,40")', 3),
    ('not Location("unknown")', 3),
    ('Includes("Maya") and Phone("Yoav14ProMax") and date = 2026 and Area("30,35,30,40")', 1),
])
def test_context_removes_geography_but_preserves_other_filters(client, expression, expected):
    api, core = client
    with core.db() as c:
        c.execute("UPDATE media SET latitude=32,longitude=34 WHERE id='0'")
        c.execute("UPDATE media SET latitude=48,longitude=2 WHERE id='1'")
    context = api.get('/api/map-context',params={'expression':expression})
    assert context.status_code == 200
    assert context.json()['total'] == expected
    assert api.get('/api/map-results',params={'expression':'Includes("Maya") and Area("30,35,30,40")'}).json()['total'] == 1
    assert api.get('/api/media',params={'expression':'Includes("Maya") and Area("30,35,30,40")'}).json()['total'] == 1

def test_context_legacy_bounds_and_empty_results(client):
    api, core = client
    with core.db() as c:
        c.execute("UPDATE media SET latitude=32,longitude=34")
    query={'people':1,'location':'bounds','south':-10,'north':0,'west':-10,'east':0}
    assert api.get('/api/map-results',params=query).json()['total'] == 0
    assert api.get('/api/map-context',params=query).json()['total'] == 2
    assert api.get('/api/map-context',params={'expression':'Area("invalid")'}).status_code == 422


def test_map_cache_invalidates_on_catalogue_changes(client):
    api, core = client
    from backend.map_results import _cache
    _cache.clear()
    first = api.get('/api/map-results').json()
    assert api.get('/api/map-context').json() == first
    assert len(_cache) == 1
    with core.db() as c:
        c.execute("UPDATE media SET latitude=32,longitude=34 WHERE id='0'")
    changed = api.get('/api/map-results').json()
    assert changed['known'] == 1 and changed['unknown'] == 2
    assert first['known'] == 0
    with core.db() as c:
        c.execute("UPDATE media SET status='trashed' WHERE id='0'")
    assert api.get('/api/map-results').json()['total'] == 2

def test_map_cache_is_bounded_and_preserves_unknown_totals(client):
    api, core = client
    from backend.map_results import _cache
    _cache.clear()
    with core.db() as c:
        c.execute("UPDATE media SET latitude=999,longitude=1 WHERE id='0'")
    for n in range(10):
        api.get('/api/map-results',params={'q':str(n)})
    assert len(_cache) <= 6
    result = api.get('/api/map-results').json()
    assert result['total'] == 3 and result['unknown'] == 3 and result['points'] == []


def test_map_transport_compression_preserves_response(client):
    api, _ = client
    compressed=api.get('/api/map-results',headers={'accept-encoding':'gzip'})
    plain=api.get('/api/map-results',headers={'accept-encoding':'gzip;q=0'})
    assert compressed.headers['content-encoding']=='gzip'
    assert 'content-encoding' not in plain.headers
    assert compressed.json()==plain.json()
