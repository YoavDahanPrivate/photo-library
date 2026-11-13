"""Cross-run directory listings for Sync; Full Sync always bypasses these."""
import json
import math
from pathlib import Path, PurePosixPath

SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_folder_cache(
 database_id TEXT NOT NULL,relative TEXT NOT NULL,signature TEXT NOT NULL,
 stamp TEXT NOT NULL,children TEXT NOT NULL,files TEXT NOT NULL,
 PRIMARY KEY(database_id,relative));
CREATE TABLE IF NOT EXISTS discovery_cache_state(
 run_id TEXT NOT NULL,database_id TEXT NOT NULL,relative TEXT NOT NULL,
 stamp TEXT,children TEXT NOT NULL,cached_files TEXT,
 PRIMARY KEY(run_id,database_id,relative));
"""


def stamp(directory):
    stat = directory.stat()
    if stat.st_mtime_ns <= 0:
        return None
    return json.dumps([stat.st_mtime_ns, stat.st_dev, stat.st_ino])


def load(c, database_id, relative, signature, current_stamp):
    if current_stamp is None:
        return None
    row = c.execute("SELECT children,files FROM sync_folder_cache WHERE database_id=? "
                    "AND relative=? AND signature=? AND stamp=?",
                    (database_id, relative, signature, current_stamp)).fetchone()
    if row is None:
        return None
    try:
        children, files = json.loads(row['children']), json.loads(row['files'])
        if not isinstance(children, list) or not isinstance(files, list):
            return None
        expected = relative or '.'
        def direct(value):
            return (isinstance(value, str) and bool(value) and '\\' not in value
                    and not Path(value).is_absolute() and not Path(value).drive
                    and '..' not in PurePosixPath(value).parts
                    and PurePosixPath(value).parent.as_posix() == expected)
        if any(not direct(child) for child in children) or len(set(children)) != len(children):
            return None
        names = set()
        for entry in files:
            if (not isinstance(entry, dict) or not direct(entry.get('relative'))
                    or entry['relative'] in names or type(entry.get('bytes')) is not int
                    or entry['bytes'] < 0 or type(entry.get('mtime')) not in (int, float)
                    or not math.isfinite(entry['mtime'])):
                return None
            names.add(entry['relative'])
        return children, files
    except (TypeError, ValueError, KeyError):
        return None


def publish(c, run_id, database_id, relative, root, names, signature, current_stamp):
    state = c.execute("SELECT stamp,children FROM discovery_cache_state WHERE run_id=? "
                      "AND database_id=? AND relative=?", (run_id, database_id, relative)).fetchone()
    if not state or not current_stamp or state['stamp'] != current_stamp:
        # A concurrent folder change must force enumeration on the next Sync.
        c.execute('DELETE FROM sync_folder_cache WHERE database_id=? AND relative=?',
                  (database_id, relative))
        return
    paths = [str(root / relative / name) for name in names]
    records = c.execute("SELECT path,entry FROM discovery_files WHERE run_id=? AND database_id=? "
                        "AND path IN (SELECT value FROM json_each(?)) ORDER BY path",
                        (run_id, database_id, json.dumps(paths))).fetchall()
    files = []
    for row in records:
        entry = json.loads(row['entry'])
        files.append(dict(relative=Path(row['path']).relative_to(root).as_posix(),
                          bytes=entry['bytes'], mtime=entry['mtime']))
    c.execute('INSERT OR REPLACE INTO sync_folder_cache VALUES(?,?,?,?,?,?)',
              (database_id, relative, signature, current_stamp, state['children'], json.dumps(files)))
