from tests.test_catalogue import client


def test_https_alias_origins(client):
    c, _ = client
    for origin in ('https://dahanoffice', 'https://dahanoffice:443'):
        assert c.post('/api/status', headers={'host': 'dahanoffice', 'origin': origin}).status_code == 405
    for origin in ('https://untrusted.invalid', 'https://dahanoffice.evil.invalid', 'https://dahanoffice:444'):
        assert c.post('/api/status', headers={'host': 'dahanoffice', 'origin': origin}).status_code == 403
    assert c.get('/api/health', headers={'host': 'untrusted.invalid'}).status_code == 403
