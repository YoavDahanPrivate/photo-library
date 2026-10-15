"""Durable directory snapshots and bounded, replayable publication batches.

Only sync.sqlite is written. Originals are never altered. Completed folders
belong to this scan's snapshot; a later Sync now discovers subsequent changes.
"""
import hashlib
import json
import os
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS discovery_sessions(
 run_id TEXT PRIMARY KEY,signature TEXT NOT NULL,clean_pause INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS discovery_roots(
 run_id TEXT NOT NULL,database_id TEXT NOT NULL,complete INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(run_id,database_id));
CREATE TABLE IF NOT EXISTS discovery_folders(
 run_id TEXT NOT NULL,database_id TEXT NOT NULL,relative TEXT NOT NULL,
 snapshot TEXT,cursor INTEGER NOT NULL DEFAULT 0,batch TEXT,
 done INTEGER NOT NULL DEFAULT 0,media_count INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(run_id,database_id,relative));
CREATE TABLE IF NOT EXISTS discovery_files(
 run_id TEXT NOT NULL,database_id TEXT NOT NULL,path TEXT NOT NULL,entry TEXT NOT NULL,
 PRIMARY KEY(run_id,database_id,path));
"""


def manifest(roots):
    from . import core, advanced_layout
    values = []
    with core.db() as c:
        for d in roots:
            value = {key: d.get(key) for key in (
                'id', 'root', 'layout', 'revision', 'default_source_sync',
                'parent_id', 'parent_path')}
            value['exclusions'] = advanced_layout.effective_exclusions(c, d)
            value['rules'] = advanced_layout.rules(c, d['id'])
            # Automatic creation of enabled Sources during discovery must not
            # invalidate its own checkpoint. Manual Source edits bump revision.
            value['disabled_sources'] = [tuple(r) for r in c.execute(
                'SELECT id,relative_path FROM library_sources WHERE database_id=? '
                'AND (sync_enabled=0 OR active=0) ORDER BY id', (d['id'],))]
            values.append(value)
    return hashlib.sha256(json.dumps(sorted(values, key=lambda d: d['id']),
                                    sort_keys=True).encode()).hexdigest()


class DiscoveryCheckpoint:
    def __init__(self, run_id):
        self.run_id = run_id
        self.clean_resume = False
        self.resumed = False
        self.invalidated = False

    def prepare(self, roots):
        from . import sync_service as sync
        signature = manifest(roots)
        with sync.store() as c:
            row = c.execute('SELECT * FROM discovery_sessions WHERE run_id=?',
                            (self.run_id,)).fetchone()
            self.clean_resume = bool(row and row['signature'] == signature and row['clean_pause'])
            if row and row['signature'] != signature:
                self.invalidated = True
                self._discard(c)
                row = None
            self.resumed = row is not None
            c.execute('INSERT OR REPLACE INTO discovery_sessions VALUES(?,?,0)',
                      (self.run_id, signature))
            for d in roots:
                c.execute('INSERT OR IGNORE INTO discovery_roots VALUES(?,?,0)',
                          (self.run_id, d['id']))
                c.execute('INSERT OR IGNORE INTO discovery_folders '
                          '(run_id,database_id,relative) VALUES(?,?,?)',
                          (self.run_id, d['id'], ''))
            folders = c.execute('SELECT count(*) FROM discovery_folders WHERE run_id=? '
                                'AND snapshot IS NOT NULL', (self.run_id,)).fetchone()[0]
            found = c.execute('SELECT coalesce(sum(media_count),0) FROM discovery_folders '
                              'WHERE run_id=?', (self.run_id,)).fetchone()[0]
        return folders, found

    def valid_for(self, roots):
        from . import sync_service as sync
        with sync.store() as c:
            row = c.execute('SELECT signature FROM discovery_sessions WHERE run_id=?',
                            (self.run_id,)).fetchone()
        # Older reconciled runs have no discovery snapshot and can still finish
        # their existing processing queues without a new folder inventory.
        return row is None or row['signature'] == manifest(roots)

    def mark_paused(self):
        from . import sync_service as sync
        with sync.store() as c:
            c.execute('UPDATE discovery_sessions SET clean_pause=1 WHERE run_id=?',
                      (self.run_id,))

    def _discard(self, c):
        for table in ('discovery_files', 'discovery_folders', 'discovery_roots', 'discovery_sessions'):
            c.execute(f'DELETE FROM {table} WHERE run_id=?', (self.run_id,))

    def discard(self):
        from . import sync_service as sync
        with sync.store() as c:
            self._discard(c)

    @staticmethod
    def check_directory(root, directory):
        if not directory.is_relative_to(root):
            raise RuntimeError('Checkpoint folder is outside its Database')
        for ancestor in (directory, *directory.parents):
            if ancestor.is_relative_to(root) and (ancestor.is_symlink() or ancestor.is_junction()):
                raise RuntimeError('Source must not traverse links: ' + str(ancestor))
        if not directory.is_dir():
            raise RuntimeError('Source unavailable: ' + str(directory))

    @staticmethod
    def list_directory(directory, root, exclusions):
        from .source_management import SKIP, IMAGES, VIDEOS, excluded
        dirs, names = [], []
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                if entry.is_symlink() or path.is_junction():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if entry.name.casefold() not in SKIP and not excluded(
                            path.relative_to(root).as_posix(), exclusions):
                        dirs.append(path.relative_to(root).as_posix())
                elif path.suffix.lower() in IMAGES | VIDEOS and entry.is_file(follow_symlinks=False):
                    names.append(entry.name)
        return sorted(dirs), sorted(names)

    @staticmethod
    def metadata(root, directory, names):
        result = []
        for name in names:
            path = directory / name
            if path.is_symlink() or path.is_junction():
                raise RuntimeError('Source must not traverse links: ' + str(path))
            stat = path.stat()
            result.append(dict(relative=path.relative_to(root).as_posix(),
                               bytes=stat.st_size, mtime=stat.st_mtime))
        return result

    def walk(self, database, exclusions, control, progress, on_batch):
        from . import sync_service as sync
        root, did = Path(database['root']), database['id']
        key = (self.run_id, did)
        while True:
            control()
            with sync.store() as c:
                row = c.execute('SELECT * FROM discovery_folders WHERE run_id=? AND '
                                'database_id=? AND done=0 ORDER BY relative LIMIT 1', key).fetchone()
            if row is None:
                break
            directory = root / row['relative']
            self.check_directory(root, directory)
            progress(current_folder=str(directory), current_file='')
            folder_key = (*key, row['relative'])
            if row['snapshot'] is None:
                # Finish and commit this directory listing before honoring a
                # clean pause. A crash can repeat only this uncertain listing.
                dirs, names = self.list_directory(directory, root, exclusions)
                with sync.store() as c:
                    c.execute('UPDATE discovery_folders SET snapshot=? WHERE run_id=? '
                              'AND database_id=? AND relative=?', (json.dumps(names), *folder_key))
                    c.executemany('INSERT OR IGNORE INTO discovery_folders '
                                  '(run_id,database_id,relative) VALUES(?,?,?)',
                                  [(*key, child) for child in dirs])
                progress(folders_delta=1)
            else:
                names = json.loads(row['snapshot'])
            cursor = row['cursor']
            while cursor < len(names):
                control()
                end = min(cursor + 50, len(names))
                batch = json.loads(row['batch']) if row['batch'] else None
                if batch is None or not self.clean_resume:
                    batch = self.metadata(root, directory, names[cursor:end])
                    with sync.store() as c:
                        c.execute('UPDATE discovery_folders SET batch=? WHERE run_id=? '
                                  'AND database_id=? AND relative=?', (json.dumps(batch), *folder_key))
                # Publication is idempotent, with a separate per-media durable
                # work queue. Commit the cursor only once the whole batch returns.
                control()
                mapped = on_batch(batch)
                with sync.store() as c:
                    c.executemany('INSERT OR REPLACE INTO discovery_files VALUES(?,?,?,?)',
                                  [(self.run_id, did, path, json.dumps(entry))
                                   for path, entry in mapped.items()])
                    c.execute('UPDATE discovery_folders SET cursor=?,batch=NULL,media_count=media_count+? '
                              'WHERE run_id=? AND database_id=? AND relative=?',
                              (end, len(batch), *folder_key))
                progress(media_delta=len(batch))
                cursor = end
                row = dict(row, batch=None)
            with sync.store() as c:
                c.execute('UPDATE discovery_folders SET done=1 WHERE run_id=? AND database_id=? '
                          'AND relative=?', folder_key)
        self.check_directory(root, root)
        with sync.store() as c:
            c.execute('UPDATE discovery_roots SET complete=1 WHERE run_id=? AND database_id=?', key)
            return {r['path']: json.loads(r['entry']) for r in c.execute(
                'SELECT path,entry FROM discovery_files WHERE run_id=? AND database_id=? ORDER BY path', key)}
