from tests.test_catalogue import client


def test_home_names_and_origins(client):
    c, _ = client
    for name in ('dahanoffice', 'dahanoffice.local'):
        for suffix in ('', ':80'):
            headers = {'host': name + suffix, 'origin': 'http://' + name + suffix}
            assert c.get('/api/status', headers=headers).status_code == 200
            # POST to a GET-only endpoint exercises origin checks without changing data.
            assert c.post('/api/status', headers=headers).status_code == 405
    assert c.get('/api/status', headers={'host': 'untrusted.invalid'}).status_code == 403
    assert c.post('/api/status', headers={'host': 'dahanoffice', 'origin': 'http://untrusted.invalid'}).status_code == 403
