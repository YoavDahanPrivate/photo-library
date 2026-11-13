"""Cross-run Sync caches are tested only with disposable folders/catalogues."""
import json
import os
import time
import uuid
from types import SimpleNamespace

import pytest
from tests.test_catalogue import client
from tests.test_discovery_checkpoint import scan


def walk(scan, mode='sync', identity=None):
    from backend.discovery_checkpoint import DiscoveryCheckpoint
    from backend.source_management import inventory
    _, _, _, _, did, _ = scan
    cp = DiscoveryCheckpoint(identity or uuid.uuid4().hex, mode)
    progress = {}
    result = inventory(did, checkpoint=cp, progress=lambda **kw: progress.update(kw))
    cp.discard()
    return result, progress


def touch_folder(path):
    # Force a distinct timestamp even on filesystems with coarse resolution.
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))


def old_file(path, data=b'new isolated original'):
    path.write_bytes(data)
    os.utime(path, (time.time()-120, time.time()-120))
    touch_folder(path.parent)


def test_first_sync_builds_cache_then_reuses_all_file_metadata(scan, monkeypatch):
    from backend.discovery_checkpoint import DiscoveryCheckpoint
    first, progress = walk(scan)
    assert len(first) == 60 and progress['folders_read'] == 5
    assert progress['folders_reused'] == 0
    def forbidden(*args):
        raise AssertionError('Unchanged Sync enumerated files or fetched file metadata')
    monkeypatch.setattr(DiscoveryCheckpoint, 'list_directory', staticmethod(forbidden))
    monkeypatch.setattr(DiscoveryCheckpoint, 'metadata', staticmethod(forbidden))
    second, progress = walk(scan)
    assert second == first
    assert progress['folders_reused'] == 5 and progress['folders_read'] == 0
    assert progress['file_metadata_reused'] == 60


def test_deep_changes_discovered_through_unchanged_ancestors(scan, monkeypatch):
    from backend.discovery_checkpoint import DiscoveryCheckpoint
    _, _, _, root, _, _ = scan
    walk(scan)
    ancestor_stamp = (root.stat().st_mtime_ns, (root/'A').stat().st_mtime_ns)
    new = root/'A/Nested/Deep/new.jpg'
    old_file(new)
    assert ancestor_stamp == (root.stat().st_mtime_ns, (root/'A').stat().st_mtime_ns)
    listed = []
    original = DiscoveryCheckpoint.list_directory
    def listing(directory, *args):
        listed.append(directory)
        return original(directory, *args)
    monkeypatch.setattr(DiscoveryCheckpoint, 'list_directory', staticmethod(listing))
    files, progress = walk(scan)
    assert len(files) == 61 and str(new) in files
    assert listed == [new.parent]
    assert progress['folders_reused'] == 4 and progress['folders_read'] == 1
    nested = root/'A/Nested/Deep/Even deeper'
    nested.mkdir()
    old_file(nested/'video.mp4')
    touch_folder(nested.parent)
    files, _ = walk(scan)
    assert str(nested/'video.mp4') in files


def test_full_sync_bypasses_cache_and_detects_in_place_edit(scan):
    _, core, sync, root, _, _ = scan
    sync.worker_context.run_id = None
    first, _ = walk(scan, 'full')
    sync.reconcile(first)
    path = root/'A/000.jpg'
    with core.db() as c:
        mid = c.execute('SELECT id FROM media WHERE path=?', (str(path),)).fetchone()[0]
        c.execute("INSERT INTO faces(id,media_id,person_id,status) VALUES('cache-annotation',?,1,'manual')", (mid,))
    stamp = path.parent.stat()
    old_file(path, b'replacement photo content with a different size')
    os.utime(path.parent, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    quick, progress = walk(scan)
    assert quick[str(path)]['bytes'] == first[str(path)]['bytes']
    assert sync.reconcile(quick)['changed'] == 0
    full, progress = walk(scan, 'full')
    assert progress['folders_reused'] == 0 and progress['folders_read'] == 5
    assert full[str(path)]['bytes'] == path.stat().st_size
    assert sync.reconcile(full)['changed'] == 1
    with core.db() as c:
        assert c.execute('SELECT status FROM media WHERE id=?', (mid,)).fetchone()[0] == 'superseded'
        assert c.execute("SELECT person_id FROM faces WHERE id='cache-annotation'").fetchone()[0] == 1
    assert path.read_bytes() == b'replacement photo content with a different size'


def test_removal_move_and_restore_preserve_annotations_and_originals(scan):
    _, core, sync, root, _, _ = scan
    sync.worker_context.run_id = None
    files, _ = walk(scan)
    sync.reconcile(files)
    path = root/'B/000.jpg'
    with core.db() as c:
        mid = c.execute('SELECT id FROM media WHERE path=?', (str(path),)).fetchone()[0]
        c.execute("UPDATE media SET status='ready' WHERE id=?", (mid,))
        c.execute("INSERT INTO faces(id,media_id,person_id,status) VALUES('retained',?,1,'manual')", (mid,))
    moved = path.with_name('renamed.jpg')
    path.rename(moved)
    touch_folder(path.parent)
    files, _ = walk(scan)
    assert sync.reconcile(files)['moved'] >= 1
    with core.db() as c:
        assert c.execute('SELECT id FROM media WHERE path=?', (str(moved),)).fetchone()[0] == mid
    content = moved.read_bytes()
    moved.unlink()
    touch_folder(moved.parent)
    files, _ = walk(scan)
    assert sync.reconcile(files)['missing'] == 1
    old_file(moved, content)
    files, _ = walk(scan)
    assert sync.reconcile(files)['restored'] == 1
    with core.db() as c:
        assert tuple(c.execute("SELECT media_id,person_id,status FROM faces WHERE id='retained'").fetchone()) == (mid,1,'manual')
    assert moved.read_bytes() == content


def test_empty_and_removed_folders_refresh_and_prune_cache(scan):
    _, _, sync, root, did, _ = scan
    empty = root/'Empty'
    empty.mkdir()
    walk(scan)
    old_file(empty/'later.jpg')
    files, _ = walk(scan)
    assert str(empty/'later.jpg') in files
    for path in (root/'B').iterdir():
        path.unlink()
    (root/'B').rmdir()
    touch_folder(root)
    files, _ = walk(scan)
    assert not any(path.startswith(str(root/'B')+os.sep) for path in files)
    with sync.store() as c:
        assert c.execute("SELECT count(*) FROM sync_folder_cache WHERE database_id=? AND relative='B'", (did,)).fetchone()[0] == 0


def test_offline_folder_aborts_inventory_without_marking_media_missing(scan):
    _, core, sync, root, did, _ = scan
    sync.worker_context.run_id = None
    files, _ = walk(scan)
    sync.reconcile(files)
    parked = root.with_name('temporarily-offline')
    root.rename(parked)
    try:
        with pytest.raises((RuntimeError, OSError)):
            walk(scan)
        with core.db() as c:
            assert c.execute("SELECT count(*) FROM media WHERE database_id=? AND status='missing'", (did,)).fetchone()[0] == 0
    finally:
        parked.rename(root)
    assert len(walk(scan)[0]) == 60


@pytest.mark.parametrize('bad', ['not json', '[{"relative":"../escape.jpg","bytes":1,"mtime":1}]'])
def test_corrupt_cache_falls_back_to_reading_folder(scan, bad):
    _, _, sync, _, did, _ = scan
    walk(scan)
    with sync.store() as c:
        c.execute("UPDATE sync_folder_cache SET files=? WHERE database_id=? AND relative='A'", (bad,did))
    files, progress = walk(scan)
    assert len(files) == 60 and progress['folders_read'] == 1


def test_cache_signature_invalidation_and_database_scope(scan):
    _, core, sync, _, did, _ = scan
    walk(scan)
    with sync.store() as c:
        c.execute("INSERT INTO sync_folder_cache VALUES('another-database','','other','other','[]','[]')")
    with core.db() as c:
        c.execute('UPDATE library_databases SET revision=revision+1 WHERE id=?', (did,))
    files, progress = walk(scan)
    assert len(files) == 60 and progress['folders_read'] == 5
    with sync.store() as c:
        assert c.execute("SELECT count(*) FROM sync_folder_cache WHERE database_id='another-database'").fetchone()[0] == 1


def test_folder_changed_during_listing_is_not_cached(scan, monkeypatch):
    from backend.discovery_checkpoint import DiscoveryCheckpoint
    _, _, sync, root, did, _ = scan
    original = DiscoveryCheckpoint.list_directory
    def changed(directory, *args):
        result = original(directory, *args)
        if directory == root/'A':
            old_file(directory/'concurrent.jpg')
        return result
    monkeypatch.setattr(DiscoveryCheckpoint, 'list_directory', staticmethod(changed))
    files, _ = walk(scan)
    assert str(root/'A/concurrent.jpg') not in files
    with sync.store() as c:
        assert c.execute("SELECT count(*) FROM sync_folder_cache WHERE database_id=? AND relative='A'", (did,)).fetchone()[0] == 0
    monkeypatch.setattr(DiscoveryCheckpoint, 'list_directory', staticmethod(original))
    assert str(root/'A/concurrent.jpg') in walk(scan)[0]


def test_cache_stamp_includes_directory_identity(scan):
    from backend import folder_cache
    _, _, sync, root, did, _ = scan
    walk(scan)
    current = json.loads(folder_cache.stamp(root/'A'))
    current[2] += 1
    with sync.store() as c:
        c.execute("UPDATE sync_folder_cache SET stamp=? WHERE database_id=? AND relative='A'", (json.dumps(current),did))
    assert walk(scan)[1]['folders_read'] == 1


def test_api_modes_saved_and_resume_retains_mode_and_scope(scan, monkeypatch):
    api, _, sync, _, did, _ = scan
    started = []
    def thread(target, args, **kwargs):
        def start():
            started.append((args[0], sync.status_progress(args[0])))
            args[1].__exit__(None,None,None)
        return SimpleNamespace(start=start)
    monkeypatch.setattr(sync.threading, 'Thread', thread)
    for endpoint in ('/api/sync/now', f'/api/databases/{did}/sync'):
        for suffix, expected in [('', 'sync'), ('?mode=sync','sync'), ('?mode=full','full')]:
            response = api.post(endpoint+suffix, json={})
            assert response.status_code == 202, response.text
            identity, progress = started[-1]
            assert progress['sync_mode'] == expected
            assert progress.get('database_id') == (did if '/databases/' in endpoint else None)
            with sync.store() as c:
                c.execute("UPDATE runs SET state='paused' WHERE id=?", (identity,))
            assert api.post(f'/api/sync/runs/{identity}/resume', json={}).status_code == 202
            assert started[-1] == (identity,progress)
        assert api.post(endpoint+'?mode=unknown', json={}).status_code == 422


def test_clean_resume_retains_cached_pending_batch(scan, monkeypatch):
    from backend.discovery_checkpoint import DiscoveryCheckpoint
    from backend import source_management as sm
    _, _, sync, root, did, _ = scan
    walk(scan)
    cp = DiscoveryCheckpoint('fast-paused', 'sync')
    def pause(database, batch):
        if str(root/'A/000.jpg') in batch:
            raise RuntimeError('isolated pause')
    with pytest.raises(RuntimeError, match='isolated pause'):
        sm.inventory(did, checkpoint=cp, on_batch=pause)
    cp.mark_paused()
    def forbidden(*args):
        raise AssertionError('Clean cached resume re-read files')
    monkeypatch.setattr(DiscoveryCheckpoint, 'metadata', staticmethod(forbidden))
    monkeypatch.setattr(DiscoveryCheckpoint, 'list_directory', staticmethod(forbidden))
    files, progress = walk(scan, identity='fast-paused')
    assert len(files) == 60 and progress['folders_reused'] == 5


def test_unclean_resume_revalidates_unfinished_cached_files(scan, monkeypatch):
    from backend.discovery_checkpoint import DiscoveryCheckpoint
    from backend import source_management as sm
    _, _, _, root, did, _ = scan
    walk(scan)
    cp = DiscoveryCheckpoint('fast-interrupted','sync')
    def crash(database, batch):
        if str(root/'A/000.jpg') in batch:
            raise RuntimeError('isolated crash')
    with pytest.raises(RuntimeError, match='isolated crash'):
        sm.inventory(did, checkpoint=cp, on_batch=crash)
    original = DiscoveryCheckpoint.metadata
    checked = []
    def metadata(root, directory, names):
        checked.extend((directory/name) for name in names)
        return original(root,directory,names)
    monkeypatch.setattr(DiscoveryCheckpoint,'metadata',staticmethod(metadata))
    assert len(walk(scan,identity='fast-interrupted')[0]) == 60
    assert root/'A/000.jpg' in checked


def test_catalogue_removal_clears_only_its_cache_and_preserves_originals(scan):
    from backend.discovery_checkpoint import DiscoveryCheckpoint
    from backend import source_management as sm
    api, core, sync, root, did, _ = scan
    walk(scan)
    # Include an unfinished discovery-cache record as well as persistent entries.
    cp = DiscoveryCheckpoint('cache-to-remove','sync')
    def pause(database, batch):
        raise RuntimeError('fixture pause')
    with pytest.raises(RuntimeError):
        sm.inventory(did,checkpoint=cp,on_batch=pause)
    with sync.store() as c:
        c.execute("UPDATE runs SET state='completed'")
        c.execute("INSERT INTO sync_folder_cache VALUES('keep-other','','other','stamp','[]','[]')")
    original = (root/'A/000.jpg').read_bytes()
    preview = api.post(f'/api/databases/{did}/removal-preview',json={}).json()
    first = api.post(f'/api/databases/{did}/removal-first-confirm',json={'token':preview['token'],'confirm':True}).json()
    with core.db() as c:
        alias = c.execute('SELECT alias FROM library_databases WHERE id=?',(did,)).fetchone()[0]
    response = api.post(f'/api/databases/{did}/removal-final-confirm',json={'token':first['token'],'confirm':True,'typed_alias':alias})
    assert response.status_code == 200,response.text
    with sync.store() as c:
        for table in ('discovery_cache_state','sync_folder_cache'):
            assert c.execute(f'SELECT count(*) FROM {table} WHERE database_id=?',(did,)).fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM sync_folder_cache WHERE database_id='keep-other'").fetchone()[0] == 1
    assert (root/'A/000.jpg').read_bytes() == original
