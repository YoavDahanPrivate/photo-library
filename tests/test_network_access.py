"""Synthetic shares/credentials only; never connect to a real protected share."""
import contextlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import subprocess
import uuid

import pytest
from tests.test_catalogue import client
from tests.test_connected_databases import local_client
from tests.test_source_management import files, register, index


@pytest.fixture
def access_fixture(client, monkeypatch):
    api, core = client
    from backend import network_access as access
    secrets, connections = {}, []
    access._connections.clear(); access._failures.clear()
    monkeypatch.setattr(access, 'read_secret', lambda server: secrets.get(server))
    monkeypatch.setattr(access, 'write_secret', lambda server, username, password: secrets.update({server: (username, password)}))
    monkeypatch.setattr(access, 'delete_secret', lambda server: secrets.pop(server, None))
    monkeypatch.setattr(access, 'connect_share', lambda share, username, password: connections.append((share, username, password)))
    # Patch just the directory check in the authentication helper. Other tests
    # continue using real disposable filesystem inventories.
    real_scandir = os.scandir
    monkeypatch.setattr(access.os, 'scandir', lambda p: contextlib.nullcontext(iter([])) if str(p).startswith('\\\\') else real_scandir(p))
    return local_client(api), core, access, secrets, connections


@pytest.mark.parametrize('endpoint', ['status', 'connect', 'forget', 'use-existing'])
def test_remote_credentials_are_rejected_before_reading_body(client, monkeypatch, endpoint):
    api, _ = client
    from backend import network_access as access
    monkeypatch.setattr(access, 'read_secret', lambda server: pytest.fail('Remote request accessed vault'))
    remote = local_client(api, address='192.0.2.50')
    assert remote.post('/api/databases/access/'+endpoint, json={'password':'synthetic-secret'}).status_code == 403
    assert remote.get('/api/databases/access/capabilities').json()['available'] is False
    local = local_client(api)
    assert local.post('/api/databases/access/'+endpoint, headers={'X-Forwarded-For':'127.0.0.1'}, json={}).status_code == 403


def test_password_validation_never_echoes_inputs(access_fixture):
    api, _, _, secrets, connections = access_fixture
    secret = 'synthetic-secret'
    for body in ({'password':secret}, {'root':'relative', 'username':'test', 'password':secret},
                 {'root':r'\\server\share', 'username':'test', 'password':secret*300}):
        result = api.post('/api/databases/access/connect', json=body)
        assert result.status_code == 422
        assert secret not in result.text
    assert not secrets and not connections


def test_connect_remember_status_and_forget_do_not_touch_catalogue(access_fixture):
    api, core, _, secrets, connections = access_fixture
    with core.db() as c:
        before = [tuple(r) for r in c.execute('SELECT * FROM library_databases')]
    result = api.post('/api/databases/access/connect', json={'root':r'\\nas\photos\Family', 'username':'NAS\\reader', 'password':'synthetic-secret', 'remember':True})
    assert result.status_code == 200, result.text
    assert result.json()['saved'] is True and 'synthetic-secret' not in result.text
    assert connections == [(r'\\nas\photos', 'NAS\\reader', 'synthetic-secret')]
    status = api.post('/api/databases/access/status', json={'root':r'\\NAS\other-share\Trips'}).json()
    assert status == {'server':'nas', 'saved':True, 'username':'NAS\\reader'}
    assert api.post('/api/databases/access/forget', json={'root':r'\\nas\photos'}).json()['forgotten'] is True
    assert not secrets
    with core.db() as c:
        assert [tuple(r) for r in c.execute('SELECT * FROM library_databases')] == before


def test_test_only_does_not_save_or_forget_existing_credentials(access_fixture):
    api, _, _, secrets, _ = access_fixture
    secrets['nas'] = ('old-reader', 'old-synthetic-password')
    result = api.post('/api/databases/access/connect', json={'root':r'\\nas\photos', 'username':'temporary-reader', 'password':'temporary-synthetic-password', 'remember':False})
    assert result.status_code == 200 and result.json()['saved'] is False
    assert secrets['nas'] == ('old-reader', 'old-synthetic-password')


def test_failed_connection_and_unreadable_folder_never_save(access_fixture, monkeypatch):
    api, _, access, secrets, _ = access_fixture
    def denied(*args): raise RuntimeError('Access denied')
    monkeypatch.setattr(access, 'connect_share', denied)
    body = {'root':r'\\nas\photos', 'username':'reader', 'password':'synthetic-secret', 'remember':True}
    assert api.post('/api/databases/access/connect', json=body).status_code == 409
    assert not secrets
    monkeypatch.setattr(access, 'connect_share', lambda *args: None)
    monkeypatch.setattr(access.os, 'scandir', lambda *args: (_ for _ in ()).throw(PermissionError('unreadable')))
    result = api.post('/api/databases/access/connect', json=body)
    assert result.status_code == 409 and 'synthetic-secret' not in result.text
    assert not secrets


def test_saved_access_reused_after_restart_and_for_another_share(access_fixture):
    _, _, access, secrets, connections = access_fixture
    secrets['nas'] = ('reader', 'synthetic-secret')
    access.ensure_access(r'\\NAS\photos\Family')
    access.ensure_access(r'\\nas\photos\Other-folder')
    assert len(connections) == 1
    access.ensure_access(r'\\nas\videos\Trips')
    assert len(connections) == 2
    access._connections.clear()  # New backend process has no connection cache.
    access.ensure_access(r'\\nas\photos\Family')
    assert len(connections) == 3


def test_network_failures_back_off_without_losing_records(client, tmp_path, monkeypatch):
    api, core = client
    root = files(tmp_path/'Offline fixture', ['Family/a.jpg'])
    did, _ = register(api, root); index(did, core)
    from backend import network_access as access, source_management as sm
    def unavailable(root): raise RuntimeError('Saved network login needs updating')
    monkeypatch.setattr(access, 'ensure_access', unavailable)
    with pytest.raises(RuntimeError): sm.inventory(did)
    database = next(d for d in api.get('/api/databases').json() if d['id'] == did)
    assert database['availability'] == 'unavailable'
    with core.db() as c:
        assert c.execute('SELECT status FROM media WHERE database_id=?', (did,)).fetchone()[0] == 'ready'


def test_helper_does_not_put_password_in_command_or_environment(client, monkeypatch):
    from backend import network_access as access
    seen = []
    def run(args, **kwargs):
        seen.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps({'code':1219}))
    monkeypatch.setattr(access.subprocess, 'run', run)
    with pytest.raises(RuntimeError, match='different credentials'):
        access.connect_share(r'\\nas\photos', 'reader', 'synthetic-secret')
    args, kwargs = seen[0]
    assert all('synthetic-secret' not in arg for arg in args)
    assert 'env' not in kwargs
    assert kwargs['timeout'] == 20
    assert json.loads(kwargs['input'])['password'] == 'synthetic-secret'


def test_helper_timeout_has_safe_error(client, monkeypatch):
    from backend import network_access as access
    def timeout(*args, **kwargs): raise subprocess.TimeoutExpired('helper', 20)
    monkeypatch.setattr(access.subprocess, 'run', timeout)
    with pytest.raises(RuntimeError, match='timed out'):
        access.connect_share(r'\\nas\photos', 'reader', 'synthetic-secret')


def test_automatic_bad_password_is_not_retried_on_each_ui_poll(access_fixture, monkeypatch):
    _, _, access, secrets, _ = access_fixture
    secrets['nas'] = ('reader', 'synthetic-secret')
    attempts = []
    def denied(*args):
        attempts.append(1)
        raise RuntimeError('Access denied')
    monkeypatch.setattr(access, 'connect_share', denied)
    for _ in range(3):
        with pytest.raises(RuntimeError, match='Access denied'):
            access.ensure_access(r'\\nas\photos')
    assert len(attempts) == 1


@pytest.mark.parametrize('suffix', ['original', 'display-original'])
def test_unavailable_original_has_recoverable_response(client, tmp_path, monkeypatch, suffix):
    api, core = client
    root = files(tmp_path/'Network original fixture', ['Family/a.jpg'])
    did, _ = register(api, root); index(did, core)
    with core.db() as c:
        mid = c.execute('SELECT id FROM media WHERE database_id=?', (did,)).fetchone()[0]
    from backend import network_access as access
    def unavailable(root): raise RuntimeError('Network access unavailable')
    monkeypatch.setattr(access, 'ensure_access', unavailable)
    assert api.get(f'/api/media/{mid}/{suffix}').status_code == 503


@pytest.mark.parametrize('value', [r'\\?\C:\secret', r'\\.\device', r'\\server', r'\\server\share\..\other', r'\\server\share\bad:name'])
def test_unsafe_network_paths_rejected(value):
    from backend import network_access as access
    with pytest.raises(ValueError): access.scope(value)


@pytest.mark.skipif(os.name != 'nt', reason='Windows vault only')
def test_real_windows_vault_roundtrip_uses_unique_disposable_target(client):
    _, core = client
    from backend import network_access as access
    server = 'dahan-fixture-'+uuid.uuid4().hex+'.invalid'
    secret = 'synthetic-'+uuid.uuid4().hex+'-שלום'
    try:
        access.write_secret(server, 'fixture-reader', secret)
        assert access.read_secret(server) == ('fixture-reader', secret)
    finally:
        access.delete_secret(server)
    assert access.read_secret(server) is None
    with core.db() as c:
        assert secret not in '\n'.join(c.iterdump())


@pytest.mark.parametrize('readable', [True, False])
def test_conflicting_credentials_reuse_only_readable_windows_access(access_fixture, monkeypatch, readable):
    api, _, access, secrets, _ = access_fixture
    secrets['nas'] = ('previous-reader', 'previous-secret')
    def conflict(*args): raise access.CredentialConflict('Different credentials; submitted credentials were not saved')
    monkeypatch.setattr(access, 'connect_share', conflict)
    checked = []
    monkeypatch.setattr(access, 'existing_folder_readable', lambda root: checked.append(root) or readable)
    result = api.post('/api/databases/access/connect', json={'root':r'\\nas\photos\Family', 'username':'new-reader', 'password':'new-synthetic-secret', 'remember':True})
    assert checked == [r'\\nas\photos\Family']
    assert secrets == {'nas':('previous-reader','previous-secret')}
    assert 'new-synthetic-secret' not in result.text
    if readable:
        assert result.status_code == 200
        assert result.json()['used_existing'] is True
        assert result.json()['credentials_verified'] is False
        assert result.json()['saved'] is False
        assert result.json()['username'] == ''
        assert access._connections
    else:
        assert result.status_code == 409
        assert result.json()['detail']['code'] == 'credential_conflict'
        assert not access._connections


@pytest.mark.parametrize('readable', [True, False])
def test_current_windows_access_needs_no_password_or_vault(access_fixture, monkeypatch, readable):
    api, _, access, _, connections = access_fixture
    monkeypatch.setattr(access, 'read_secret', lambda *args: pytest.fail('Unexpected vault read'))
    monkeypatch.setattr(access, 'write_secret', lambda *args: pytest.fail('Unexpected vault write'))
    monkeypatch.setattr(access, 'existing_folder_readable', lambda root: readable)
    result = api.post('/api/databases/access/use-existing', json={'root':r'\\nas\photos'})
    assert result.status_code == (200 if readable else 409)
    assert not connections
    if readable:
        assert result.json()['used_existing'] is True and result.json()['saved'] is False


def test_saved_account_conflict_does_not_block_readable_folder_after_restart(access_fixture, monkeypatch):
    _, _, access, secrets, _ = access_fixture
    secrets['nas'] = ('reader', 'synthetic-secret')
    attempts = []
    def conflict(*args):
        attempts.append(1)
        raise access.CredentialConflict('different credentials')
    monkeypatch.setattr(access, 'connect_share', conflict)
    monkeypatch.setattr(access, 'existing_folder_readable', lambda root: True)
    for _ in range(2): access.ensure_access(r'\\nas\photos\Family')
    assert len(attempts) == 1 and not access._failures
    access._connections.clear()
    access.ensure_access(r'\\nas\photos\Family')
    assert len(attempts) == 2
    assert secrets['nas'] == ('reader','synthetic-secret')


@pytest.mark.parametrize('response', ['readable', 'unreadable', 'timeout', 'malformed'])
def test_windows_readability_helper_is_bounded_and_contains_no_credentials(client, monkeypatch, response):
    from backend import network_access as access
    calls = []
    def run(args, **kwargs):
        calls.append((args,kwargs))
        if response == 'timeout': raise subprocess.TimeoutExpired('helper',20)
        return SimpleNamespace(returncode=0, stdout='invalid' if response == 'malformed' else json.dumps({'readable':response == 'readable'}))
    monkeypatch.setattr(access.subprocess, 'run', run)
    assert access.existing_folder_readable(r'\\nas\photos') is (response == 'readable')
    args, kwargs = calls[0]
    assert args[-1] == '--check-existing'
    assert kwargs['timeout'] == 20 and 'env' not in kwargs
    assert json.loads(kwargs['input']) == {'root':r'\\nas\photos'}
