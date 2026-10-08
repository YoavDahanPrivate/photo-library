from tests.test_catalogue import client


def test_shell_and_release_are_not_cached(client):
    c, _ = client
    for path in ('/', '/index.html', '/version.json', '/manifest.webmanifest', '/?app-release=test'):
        response = c.get(path)
        assert response.headers['cache-control'] == 'no-store, max-age=0'
    assert c.get('/brand/dahan-black-v2.svg').headers['cache-control'] == 'no-cache'
    assert c.get('/api/status').status_code == 200
