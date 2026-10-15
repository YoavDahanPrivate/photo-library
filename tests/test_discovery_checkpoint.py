"""Pause/crash recovery uses disposable directories and SQLite databases."""
import json
import os
import time
from contextlib import nullcontext

import pytest
from tests.test_catalogue import client
from tests.test_source_management import register


@pytest.fixture
def scan(client, tmp_path, monkeypatch):
    api, core = client
    from backend import sync_service as sync, incremental_import, full_scan
    root = tmp_path / 'checkpoint-originals'
    for folder, count in [('A', 55), ('A/Nested/Deep', 2), ('B', 3)]:
        directory = root / folder
        directory.mkdir(parents=True)
        for i in range(count):
            file = directory / f'{i:03}.jpg'
            file.write_bytes(b'isolated original bytes')
            os.utime(file, (time.time()-120, time.time()-120))
    did, _ = register(api, root, interpretation='collection')
    with sync.store() as c:
        c.execute('INSERT INTO runs VALUES(?,?,NULL,?,?,?,NULL)',
                  ('checkpoint-test', sync.now().isoformat(), 'running', 'manual',
                   json.dumps({'database_id': did})))
        c.execute('UPDATE settings SET value=?', (sync.Settings(auto_assign=False).model_dump_json(),))
    sync.worker_context.run_id = 'checkpoint-test'
    sync.worker_context.database_id = did
    sync.worker_context.global_scheduled = False
    sync.worker_context.pending_progress = {}
    sync.worker_context.last_progress = 0
    sync.worker_context.preview_publisher = None
    # Replace image decoding only; real catalogue publication, assignment,
    # directory traversal, transactions and checkpoint storage still run.
    def previews(self, ids):
        with sync.store() as c:
            c.executemany("INSERT OR IGNORE INTO work VALUES(?,?,'preview',1,NULL)",
                          [(self.run_id, mid) for mid in ids])
        with core.db() as c:
            c.executemany("UPDATE media SET status='ready' WHERE id=?", [(mid,) for mid in ids])
    monkeypatch.setattr(incremental_import.PreviewPublisher, 'process', previews)
    monkeypatch.setattr(sync, 'process_pending', lambda run_id: 0)
    monkeypatch.setattr(full_scan, 'assign_new_faces', lambda **kw: 0)
    yield api, core, sync, root, did, previews
    publisher = getattr(sync.worker_context, 'preview_publisher', None)
    if publisher:
        publisher.close()
    sync.worker_context.preview_publisher = None
    sync.worker_context.run_id = None
    sync.worker_context.database_id = None
    sync.worker_context.pending_progress = {}
    sync.live_progress.clear()


def resume_context(sync):
    with sync.store() as c:
        c.execute('DELETE FROM controls')
        c.execute("UPDATE runs SET state='running' WHERE id='checkpoint-test'")
    sync.worker_context.run_id = 'checkpoint-test'


def test_clean_pause_skips_completed_folders_and_reuses_unfinished_batch(scan, monkeypatch):
    api, core, sync, root, did, previews = scan
    from backend import incremental_import
    from backend.discovery_checkpoint import DiscoveryCheckpoint
    def pause_during_batch(self, ids):
        previews(self, ids[:10])
        sync.control_run(self.run_id, 'pause')
        sync.check_control(self.run_id)
    monkeypatch.setattr(incremental_import.PreviewPublisher, 'process', pause_during_batch)
    sync.execute('checkpoint-test', nullcontext())
    assert sync.status()['runs'][0]['state'] == 'paused'
    with sync.store() as c:
        assert c.execute('SELECT clean_pause FROM discovery_sessions').fetchone()[0] == 1
    with core.db() as c:
        ids = {r[0] for r in c.execute('SELECT id FROM media WHERE database_id=?', (did,))}
        annotated = next(iter(ids))
        c.execute("INSERT INTO faces(id,media_id,person_id,status) VALUES('checkpoint-annotation',?,1,'manual')", (annotated,))
    listing = DiscoveryCheckpoint.list_directory
    metadata = DiscoveryCheckpoint.metadata
    def check_listing(directory, *args):
        assert directory not in (root, root/'A')
        return listing(directory, *args)
    def check_metadata(saved_root, directory, names):
        if directory == root/'A':
            assert names[0] >= '050.jpg'  # No stat calls for the saved pending batch.
        return metadata(saved_root, directory, names)
    monkeypatch.setattr(DiscoveryCheckpoint, 'list_directory', staticmethod(check_listing))
    monkeypatch.setattr(DiscoveryCheckpoint, 'metadata', staticmethod(check_metadata))
    monkeypatch.setattr(incremental_import.PreviewPublisher, 'process', previews)
    # Newly added files in a saved directory belong to the next sync.
    (root/'A'/'later.jpg').write_bytes(b'added after the clean pause')
    resume_context(sync)
    sync.execute('checkpoint-test', nullcontext())
    assert sync.status()['runs'][0]['state'] == 'completed'
    with core.db() as c:
        rows = c.execute('SELECT id FROM media WHERE database_id=?', (did,)).fetchall()
        assert len(rows) == 60 and ids.issubset({r[0] for r in rows})
        assert tuple(c.execute("SELECT media_id,person_id,status FROM faces WHERE id='checkpoint-annotation'").fetchone()) == (annotated, 1, 'manual')
    with sync.store() as c:
        assert c.execute('SELECT count(*) FROM discovery_files').fetchone()[0] == 0
    assert (root/'A'/'000.jpg').read_bytes() == b'isolated original bytes'


def test_crash_revalidates_only_unfinished_batch_and_preserves_ids(scan, monkeypatch):
    api, core, sync, root, did, previews = scan
    from backend import incremental_import
    from backend.discovery_checkpoint import DiscoveryCheckpoint
    class SimulatedCrash(BaseException): pass
    def crash(self, ids):
        previews(self, ids[:10])
        raise SimulatedCrash()
    monkeypatch.setattr(incremental_import.PreviewPublisher, 'process', crash)
    with pytest.raises(SimulatedCrash):
        sync.inventory()
    with core.db() as c:
        mid = c.execute('SELECT id FROM media WHERE path=?', (str(root/'A'/'001.jpg'),)).fetchone()[0]
    file = root/'A'/'000.jpg'
    file.write_bytes(b'changed during the crashed interval')
    os.utime(file, (time.time()-60, time.time()-60))
    listing = DiscoveryCheckpoint.list_directory
    metadata = DiscoveryCheckpoint.metadata
    revisited = []
    def check_listing(directory, *args):
        assert directory not in (root, root/'A')
        return listing(directory, *args)
    def track(saved_root, directory, names):
        revisited.extend((directory, name) for name in names)
        return metadata(saved_root, directory, names)
    monkeypatch.setattr(DiscoveryCheckpoint, 'list_directory', staticmethod(check_listing))
    monkeypatch.setattr(DiscoveryCheckpoint, 'metadata', staticmethod(track))
    monkeypatch.setattr(incremental_import.PreviewPublisher, 'process', previews)
    files = sync.inventory()
    assert len(files) == 60
    assert (root/'A', '000.jpg') in revisited
    assert files[str(file)]['bytes'] == file.stat().st_size
    with core.db() as c:
        assert c.execute('SELECT id FROM media WHERE path=?', (str(root/'A'/'001.jpg'),)).fetchone()[0] == mid


def test_complete_inventory_reused_until_new_sync(scan, monkeypatch):
    api, core, sync, root, did, previews = scan
    from backend.discovery_checkpoint import DiscoveryCheckpoint
    first = sync.inventory()
    with core.db() as c:
        before = c.execute('SELECT count(*) FROM media WHERE database_id=?', (did,)).fetchone()[0]
    (root/'A'/'later.jpg').write_bytes(b'new next-sync file')
    listing = DiscoveryCheckpoint.list_directory
    monkeypatch.setattr(DiscoveryCheckpoint, 'list_directory', staticmethod(lambda *args: pytest.fail('Completed inventory walked again')))
    assert dict(sync.inventory()) == dict(first)
    assert sync.status_progress('checkpoint-test')['media_found'] == 60
    monkeypatch.setattr(DiscoveryCheckpoint, 'list_directory', staticmethod(listing))
    with sync.store() as c:
        c.execute("INSERT INTO runs VALUES('new-sync',?,NULL,'running','manual',?,NULL)",
                  (sync.now().isoformat(), json.dumps({'database_id': did})))
    sync.worker_context.run_id = 'new-sync'
    assert len(sync.inventory()) == 61
    assert before == 60


def test_layout_revision_invalidates_saved_inventory(scan, monkeypatch):
    api, core, sync, root, did, previews = scan
    first = sync.inventory()
    with core.db() as c:
        c.execute('UPDATE library_databases SET revision=revision+1,exclusions=? WHERE id=?',
                  (json.dumps(['B']), did))
    files = sync.inventory()
    assert len(first) == 60 and len(files) == 57
    assert all(not path.startswith(str(root/'B')) for path in files)


def test_offline_root_does_not_reconcile_missing_or_discard_checkpoint(scan):
    api, core, sync, root, did, previews = scan
    sync.inventory()
    root.rename(root.with_name('disconnected'))
    with pytest.raises(RuntimeError, match='Source unavailable'):
        sync.inventory()
    with core.db() as c:
        assert not c.execute("SELECT 1 FROM media WHERE status='missing'").fetchone()
    with sync.store() as c:
        assert c.execute('SELECT count(*) FROM discovery_files').fetchone()[0] == 60


def test_disabled_schedules_still_recover_stale_scan_state(scan, monkeypatch):
    api, core, sync, root, did, previews = scan
    sync.inventory()
    before = sync.status_progress('checkpoint-test')
    monkeypatch.setenv('DAHAN_DISABLE_SCHEDULER', '1')
    sync.start_scheduler()
    assert sync.status()['runs'][0]['state'] == 'interrupted'
    assert sync.status_progress('checkpoint-test') == before
    with sync.store() as c:
        assert c.execute('SELECT count(*) FROM discovery_files').fetchone()[0] == 60


def test_moved_root_discards_old_paths_before_using_checkpoint(scan):
    api, core, sync, root, did, previews = scan
    sync.inventory()
    moved = root.with_name('moved-root')
    root.rename(moved)
    with core.db() as c:
        c.execute('UPDATE library_databases SET root=?,revision=revision+1 WHERE id=?',
                  (str(moved), did))
    files = sync.inventory()
    assert len(files) == 60
    assert all(path.startswith(str(moved)) for path in files)
    with sync.store() as c:
        assert not c.execute('SELECT 1 FROM discovery_files WHERE path LIKE ?', (str(root)+'%',)).fetchone()


def test_source_controls_invalidate_snapshot_without_reincluding_paused_source(scan):
    api, core, sync, root, did, previews = scan
    sync.inventory()
    with core.db() as c:
        sid = c.execute('SELECT id FROM library_sources WHERE database_id=?', (did,)).fetchone()[0]
        c.execute('UPDATE library_sources SET sync_enabled=0 WHERE id=?', (sid,))
        c.execute('UPDATE library_databases SET revision=revision+1 WHERE id=?', (did,))
    assert not sync.inventory()
    with core.db() as c:
        assert c.execute('SELECT count(*) FROM media WHERE database_id=?', (did,)).fetchone()[0] == 60


def test_pause_after_complete_inventory_resumes_processing_without_discovery(scan, monkeypatch):
    api, core, sync, root, did, previews = scan
    from backend.discovery_checkpoint import DiscoveryCheckpoint
    def pause_processing(run_id):
        sync.control_run(run_id, 'pause')
        sync.check_control(run_id)
    monkeypatch.setattr(sync, 'process_pending', pause_processing)
    sync.execute('checkpoint-test', nullcontext())
    assert sync.status()['runs'][0]['state'] == 'paused'
    assert sync.status_progress('checkpoint-test')['reconciled']
    monkeypatch.setattr(DiscoveryCheckpoint, 'list_directory', staticmethod(lambda *args: pytest.fail('Discovery repeated during processing resume')))
    monkeypatch.setattr(sync, 'process_pending', lambda run_id: 0)
    resume_context(sync)
    sync.execute('checkpoint-test', nullcontext())
    assert sync.status()['runs'][0]['state'] == 'completed'
