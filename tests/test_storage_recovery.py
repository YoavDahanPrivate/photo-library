"""Storage faults are injected only into disposable catalogue fixtures."""
import sqlite3
from contextlib import contextmanager
import pytest
from tests.test_catalogue import client
from tests.test_sync_progress import run
from tests.test_sync import service


def test_api_storage_error_is_actionable_json_and_recovers(client,monkeypatch):
    http,core=client
    from backend import app
    original=app.db
    def offline():raise sqlite3.OperationalError('disk I/O error')
    monkeypatch.setattr(app,'db',offline)
    response=http.get('/api/status')
    assert response.status_code==503
    assert response.headers['retry-after']=='5'
    assert 'drive' in response.json()['detail']
    monkeypatch.setattr(app,'db',original)
    assert http.get('/api/status').status_code==200
    with core.db() as c:assert c.execute('SELECT count(*) FROM media').fetchone()[0]==3


def test_failed_checkpoint_write_releases_lock_and_recovers_state(run,monkeypatch):
    sync,core=run
    original=sync.store
    @contextmanager
    def offline():
        raise sqlite3.OperationalError('disk I/O error')
        yield
    def disconnected():
        monkeypatch.setattr(sync,'store',offline)
        raise sqlite3.OperationalError('disk I/O error')
    monkeypatch.setattr(sync,'inventory',disconnected)
    lock=sync.scan_lock();lock.__enter__()
    sync.execute('progress-run',lock)
    with sync.scan_lock():pass
    assert sync.terminal_runs['progress-run'][0]=='interrupted'
    monkeypatch.setattr(sync,'store',original)
    result=sync.status()['runs'][0]
    assert result['state']=='interrupted'
    assert 'reconnect' in result['error']
    assert not sync.terminal_runs
    with core.db() as c:assert c.execute('SELECT count(*) FROM faces').fetchone()[0]==3


def test_permission_error_is_json_and_frontend_stays_available(client,monkeypatch):
    http,core=client
    from backend import app
    def denied():raise PermissionError(5,'Access is denied',str(core.DATA))
    monkeypatch.setattr(app,'db',denied)
    response=http.get('/api/status')
    assert response.status_code==503
    assert response.headers['retry-after']=='5'
    assert 'database drive' in response.json()['detail']
    assert http.get('/').status_code==200


def test_offline_database_at_boot_serves_shell_and_recovers_existing_annotations(client,tmp_path,monkeypatch):
    import importlib
    from fastapi.testclient import TestClient
    from backend import app,storage_runtime
    http,core=client
    offline=tmp_path/'unavailable-device'
    offline.write_text('a file cannot serve as a database directory')
    monkeypatch.setenv('DAHAN_DATABASE_DIR',str(offline))
    monkeypatch.setenv('DAHAN_REQUIRE_EXISTING_DATABASE','1')
    importlib.reload(app)
    with TestClient(app.app) as recovering:
        assert recovering.get('/').status_code==200
        assert recovering.get('/api/health').json()['storage']=='unavailable'
        response=recovering.get('/api/status')
        assert response.status_code==503 and 'database drive' in response.json()['detail']
        monkeypatch.delenv('DAHAN_DATABASE_DIR')
        monkeypatch.delenv('DAHAN_REQUIRE_EXISTING_DATABASE')
        monkeypatch.setattr(storage_runtime,'_next_retry',0)
        assert recovering.get('/api/health').json()['storage']=='available'
        assert recovering.get('/api/status').status_code==200
    with core.db() as c:
        assert c.execute('SELECT count(*) FROM media').fetchone()[0]==3
        assert c.execute('SELECT count(*) FROM faces').fetchone()[0]==3


def test_database_and_derivative_storage_can_be_separated(client,tmp_path,monkeypatch):
    http,core=client
    from backend import sync_service,network_access
    vault_key=network_access.target('fixture-server')
    catalogue=tmp_path/'database-device'
    catalogue.mkdir()
    with core.db() as source,sqlite3.connect(catalogue/'catalogue.sqlite') as dest:source.backup(dest)
    original_data=core.DATA
    monkeypatch.setenv('DAHAN_DATABASE_DIR',str(catalogue))
    derivatives=tmp_path/'persistent-derivatives';derivatives.mkdir()
    monkeypatch.setattr(core,'DATA',derivatives)
    # Code normally imports DATA once; this represents a fresh startup with it.
    from backend import app
    monkeypatch.setattr(app,'DATA',derivatives)
    with sync_service.store() as c:assert c.execute('SELECT count(*) FROM settings').fetchone()[0]==1
    assert (catalogue/'sync.sqlite').is_file()
    assert not (derivatives/'catalogue.sqlite').exists()
    with core.db() as c:assert c.execute('SELECT count(*) FROM faces').fetchone()[0]==3
    (derivatives/'thumbs').mkdir()
    (derivatives/'thumbs'/'0-small.jpg').write_bytes(b'derived preview fixture')
    assert http.get('/api/media/0/thumbnail?size=small').content==b'derived preview fixture'
    # Credential identity follows database storage, not the moved derivatives.
    monkeypatch.setenv('DAHAN_DATABASE_DIR',str(original_data))
    assert network_access.target('fixture-server')==vault_key


def test_required_database_cannot_be_silently_recreated(client,tmp_path,monkeypatch):
    http,core=client
    folder=tmp_path/'missing-database';folder.mkdir()
    monkeypatch.setenv('DAHAN_DATABASE_DIR',str(folder))
    monkeypatch.setenv('DAHAN_REQUIRE_EXISTING_DATABASE','1')
    with pytest.raises(OSError,match='Expected library database'):core.db()
    assert not (folder/'catalogue.sqlite').exists()
    (folder/'catalogue.sqlite').write_bytes(b'')
    with pytest.raises(OSError,match='Expected library database'):core.db()
    assert (folder/'catalogue.sqlite').stat().st_size==0
