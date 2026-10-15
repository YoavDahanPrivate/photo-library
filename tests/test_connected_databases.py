"""Real access and picker guards, entirely against disposable catalogue fixtures."""
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from tests.test_catalogue import client


def local_client(api, address="127.0.0.1", host="127.0.0.1"):
    return TestClient(api.app, base_url="http://"+host, client=(address, 50123))


def test_analysis_is_read_only_and_defaults_from_actual_tree(client,tmp_path):
    api,core=client
    root=tmp_path/'Photo archive'
    for relative in ('Family/one.jpg','Travel/Italy/Rome/two.jpg'):
        path=root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fixture')
    with core.db() as c:
        before=[tuple(r) for r in c.execute('SELECT * FROM library_databases')]
        previews=c.execute('SELECT count(*) FROM library_previews').fetchone()[0]
    result=api.post('/api/databases/analyze',json={'root':str(root)})
    assert result.status_code==200,result.text
    result=result.json()
    assert result['alias']=='Photo archive' and result['interpretation']=='collection'
    assert result['token'] is None
    assert {s['album'] for s in result['samples']}=={'Family','Travel › Italy › Rome'}
    with core.db() as c:
        assert [tuple(r) for r in c.execute('SELECT * FROM library_databases')]==before
        assert c.execute('SELECT count(*) FROM library_previews').fetchone()[0]==previews


def test_camera_contents_suggest_sources_even_without_phone_names(client,tmp_path):
    api,_=client
    root=tmp_path/'Backups'
    for relative in ('Alex/Camera/a.jpg','Sam/DCIM/b.jpg'):
        path=root/relative;path.parent.mkdir(parents=True);path.write_bytes(b'fixture')
    result=api.post('/api/databases/analyze',json={'root':str(root)}).json()
    assert result['interpretation']=='sources'
    assert {s['source'] for s in result['samples']}=={'Alex','Sam'}


@pytest.mark.parametrize('root,code',[('relative-folder',422),('missing',409)])
def test_analysis_rejects_invalid_root(client,tmp_path,root,code):
    api,_=client
    value=str(tmp_path/root) if root=='missing' else root
    assert api.post('/api/databases/analyze',json={'root':value}).status_code==code


def test_layout_preview_defers_media_readability_checks_until_sync(client,tmp_path,monkeypatch):
    api,core=client
    root=tmp_path/'Photos';root.mkdir();file=root/'a.jpg';file.write_bytes(b'fixture')
    from backend import source_management as sm
    original=Path.open
    def denied(self,*args,**kwargs):
        if self==file:raise PermissionError('fixture denied')
        return original(self,*args,**kwargs)
    monkeypatch.setattr(Path,'open',denied)
    for endpoint in ('analyze','preview'):
        response=api.post('/api/databases/'+endpoint,json={'root':str(root)})
        assert response.status_code==200,response.text
    result=api.post('/api/databases/register',json={'token':response.json()['token'],'confirm':True})
    assert result.status_code==201,result.text
    # An explicit content check still catches the error; registration does not
    # claim it tested readability of every photograph.
    with pytest.raises(OSError,match='Cannot read media file'):
        sm.walk(root,check_readable=True)


def test_local_native_picker_returns_real_backend_path(client,tmp_path,monkeypatch):
    api,_=client
    from backend import folder_picker as picker
    chosen=tmp_path/'Chosen folder';chosen.mkdir()
    seen=[]
    monkeypatch.setattr(picker,'native_directory',lambda initial:(seen.append(initial) or {'root':str(chosen),'cancelled':False}))
    local=local_client(api)
    assert local.get('/api/databases/folders/capabilities').json()['available']==(os.name=='nt')
    if os.name!='nt':return
    response=local.post('/api/databases/folders/pick',json={'initial':str(tmp_path)},headers={'origin':'http://127.0.0.1'})
    assert response.status_code==200,response.text
    assert response.json()=={'root':str(chosen),'cancelled':False}
    assert seen==[str(tmp_path)]


@pytest.mark.parametrize('address,host,headers',[
    ('192.0.2.10','127.0.0.1',{}),
    ('127.0.0.1','dahanoffice',{}),
    ('127.0.0.1','127.0.0.1',{'x-forwarded-for':'127.0.0.1'}),
    ('127.0.0.1','127.0.0.1',{'forwarded':'for=127.0.0.1'}),
    ('127.0.0.1','127.0.0.1',{'origin':'http://remote.invalid'}),
])
def test_remote_proxy_or_cross_origin_never_opens_picker(client,monkeypatch,address,host,headers):
    api,_=client
    from backend import folder_picker as picker
    def forbidden(initial):raise AssertionError('Remote request opened a native dialog')
    monkeypatch.setattr(picker,'native_directory',forbidden)
    connection=local_client(api,address,host)
    assert connection.get('/api/databases/folders/capabilities',headers=headers).json()['available'] is False
    assert connection.post('/api/databases/folders/pick',json={},headers=headers).status_code==403


def test_picker_cancel_busy_and_failure_leave_guard_usable(client,monkeypatch):
    api,_=client
    from backend import folder_picker as picker
    if os.name!='nt':return
    local=local_client(api)
    monkeypatch.setattr(picker,'native_directory',lambda initial:{'root':None,'cancelled':True})
    assert local.post('/api/databases/folders/pick',json={}).json()['cancelled'] is True
    picker._dialog_lock.acquire()
    try:assert local.post('/api/databases/folders/pick',json={}).status_code==409
    finally:picker._dialog_lock.release()
    def timed_out(initial):raise subprocess.TimeoutExpired('fixture',180)
    monkeypatch.setattr(picker,'native_directory',timed_out)
    assert local.post('/api/databases/folders/pick',json={}).status_code==408
    assert picker._dialog_lock.acquire(False)
    picker._dialog_lock.release()


def test_native_command_keeps_paths_out_of_executable_text(monkeypatch):
    from backend import folder_picker as picker
    captured={}
    def run(command,**options):
        captured.update(command=command,**options)
        return SimpleNamespace(returncode=0,stdout=json.dumps({'root':None,'cancelled':True}))
    monkeypatch.setattr(picker.subprocess,'run',run)
    path="D:\\Photos\\'; Write-Output unwanted"
    assert picker.native_directory(path)['cancelled']
    assert path not in captured['command'][-1]
    assert captured['env']['DAHAN_PICKER_INITIAL']==path
    assert '-STA' in captured['command'] and 'FolderBrowserDialog' in captured['command'][-1]
    assert captured['timeout']==180
