"""Fresh-install and upgrade checks never read an installed household catalogue."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.request import urlopen

import pytest

REPO = Path(__file__).resolve().parents[1]


def clean_environment(tmp_path):
    env = {key: value for key, value in os.environ.items() if not key.startswith("DAHAN_")}
    env.update(LOCALAPPDATA=str(tmp_path / "AppData"), DAHAN_DISABLE_SCHEDULER="1", PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    return env


def python(code, env, cwd=REPO):
    result = subprocess.run([sys.executable, "-B", "-c", code], env=env, cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_empty_first_run_registers_and_indexes_owner_folder_then_reopens(tmp_path):
    env = clean_environment(tmp_path)
    env["FIXTURE_ORIGINALS"] = str(tmp_path / "My Pictures")
    python('''
import os, time
from pathlib import Path
from backend import core
assert core.ROOT is None and core.PHONES == ()
assert core.DATA == Path(os.environ['LOCALAPPDATA'])/'DahanPhotoLibrary'/'runtime'
from backend.setup_library import initialize
assert initialize()['registered_databases'] == 0
from backend.app import app
from fastapi.testclient import TestClient
from PIL import Image
with TestClient(app) as api:
    assert api.get('/api/databases').json() == []
    assert api.get('/api/status', headers={'host':'dahanoffice'}).status_code == 403
    assert api.get('/api/sources').json() == []
    assert api.get('/api/media').json()['total'] == 0
    root = Path(os.environ['FIXTURE_ORIGINALS'])
    file = root/'Travel'/'Summer'/'new.jpg'
    file.parent.mkdir(parents=True)
    Image.new('RGB', (40, 30), 'blue').save(file)
    os.utime(file, (time.time()-120, time.time()-120))
    preview = api.post('/api/databases/preview', json={'root':str(root),'interpretation':'collection'})
    assert preview.status_code == 200, preview.text
    assert preview.json()['alias'] == 'My Pictures'
    result = api.post('/api/databases/register', json={'token':preview.json()['token'],'confirm':True})
    assert result.status_code == 201, result.text
    did = result.json()['id']
    from backend import source_management as sm, sync_service as sync, full_scan
    sync.reconcile(sm.inventory(did))
    with core.db() as c:
        row = c.execute('SELECT * FROM media').fetchone()
        assert row['relative_path'] == 'Travel/Summer/new.jpg'
        mid = row['id']
    for name in ('thumbs','frames','faces','previews'):
        (core.DATA/name).mkdir(exist_ok=True)
    full_scan.prepare_preview_worker()
    report = full_scan.process_one(mid, preview_only=True)
    assert report['ok'], report
    assert api.get('/api/media').json()['total'] == 1
    assert api.get('/api/media/'+mid+'/thumbnail?size=large').status_code == 200
    with core.db() as c:
        c.execute("INSERT INTO people(id,name) VALUES(99,'Owner annotation')")
    (core.DATA/'fixture-identities.json').write_text(__import__('json').dumps([did,mid]),encoding='utf-8')
''', env)
    env["DAHAN_REQUIRE_EXISTING_DATABASE"] = "1"
    python('''
import json
from backend import core
from backend.setup_library import initialize
assert initialize()['created'] is False
did,mid=json.loads((core.DATA/'fixture-identities.json').read_text(encoding='utf-8'))
with core.db() as c:
    assert c.execute('SELECT id FROM library_databases').fetchone()[0] == did
    assert c.execute('SELECT id FROM media').fetchone()[0] == mid
    assert c.execute('SELECT name FROM people WHERE id=99').fetchone()[0] == 'Owner annotation'
assert core.ROOT is None
''', env)


def test_setup_refuses_partial_existing_storage(tmp_path):
    env = clean_environment(tmp_path)
    database = tmp_path / 'catalogues'
    database.mkdir()
    saved = database/'catalogue.sqlite'
    saved.write_bytes(b'original catalogue must not be replaced')
    env['DAHAN_DATABASE_DIR'] = str(database)
    python('''
from backend.setup_library import initialize
try: initialize()
except OSError as error: assert 'restore both' in str(error)
else: raise AssertionError('Accepted a partial database pair')
''',env)
    assert saved.read_bytes() == b'original catalogue must not be replaced'
    assert not (database/'sync.sqlite').exists()


def test_legacy_sources_are_inferred_from_catalogue_without_preset_names(tmp_path):
    env = clean_environment(tmp_path)
    env['DAHAN_SOURCE'] = str(tmp_path/'Family Archive')
    python('''
from backend import core
core.init()
assert core.PHONES == ()
with core.db() as c:
    c.execute("INSERT INTO media(id,path,phone,album,name,kind) VALUES('kept',?,'Camera Alpha','Trip','one.jpg','photo')", (str(core.ROOT/'Camera Alpha'/'Trip'/'one.jpg'),))
    c.execute("INSERT INTO people VALUES(1,'Existing person')")
    c.execute("INSERT INTO faces(id,media_id,person_id,status) VALUES('kept-face','kept',1,'manual')")
    c.execute("DELETE FROM library_meta WHERE key='legacy_migrated'")
    c.execute('DELETE FROM library_sources')
    c.execute('DELETE FROM library_databases')
core.init()
with core.db() as c:
    assert [r[0] for r in c.execute('SELECT alias FROM library_sources')] == ['Camera Alpha']
    row = c.execute("SELECT * FROM media WHERE id='kept'").fetchone()
    assert row['source_id'] and row['relative_path'] == 'Camera Alpha/Trip/one.jpg'
    assert tuple(c.execute("SELECT media_id,person_id,status FROM faces WHERE id='kept-face'").fetchone()) == ('kept',1,'manual')
''', env)


@pytest.mark.skipif(os.name != 'nt', reason='Windows installer and production launcher')
def test_windows_install_and_launch_using_only_saved_local_configuration(tmp_path):
    env = clean_environment(tmp_path)
    clone = tmp_path/'Fresh checkout'
    clone.mkdir()
    shutil.copytree(REPO/'backend', clone/'backend', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(REPO/'scripts', clone/'scripts')
    shutil.copy2(REPO/'start-production.ps1', clone/'start-production.ps1')
    (clone/'frontend'/'dist').mkdir(parents=True)
    (clone/'frontend'/'dist'/'index.html').write_text('<p>Clean install</p>', encoding='utf-8')
    command = ['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File']
    install = subprocess.run(command+[str(clone/'scripts'/'install.ps1'),'-PythonPath',sys.executable,'-SkipDependencies','-SkipModels','-SkipMaps'], cwd=clone, env=env, capture_output=True, text=True, encoding='utf-8', timeout=60)
    assert install.returncode == 0, install.stdout + install.stderr
    configuration = json.loads((clone/'dahan-config.json').read_text(encoding='utf-8-sig'))
    assert 'DAHAN_SOURCE' not in configuration['env']
    assert configuration['env']['DAHAN_DATA'] == str(tmp_path/'AppData'/'DahanPhotoLibrary'/'runtime')
    assert configuration['env']['DAHAN_DATABASE_DIR'] == configuration['env']['DAHAN_DATA']
    import socket
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        port = sock.getsockname()[1]
    process = subprocess.Popen(command+[str(clone/'start-production.ps1'),'-Port',str(port),'-SingleRun'], cwd=clone, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic()+35
        while True:
            assert process.poll() is None, 'Isolated production launcher exited'
            try:
                with urlopen(f'http://127.0.0.1:{port}/api/databases',timeout=2) as response:
                    assert json.load(response) == []
                break
            except OSError:
                if time.monotonic() > deadline: raise
                time.sleep(.2)
        with urlopen(f'http://127.0.0.1:{port}/api/health',timeout=3) as response:
            assert json.load(response)['storage'] == 'available'
    finally:
        # Terminate only the process tree created for this disposable installation.
        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=15)
        process.wait(timeout=15)
