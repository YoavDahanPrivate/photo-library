"""Reconnect a complete declared Database family without changing its identities."""
import hashlib,json
from pathlib import Path
from fastapi import HTTPException
from . import core,source_management as sm,advanced_layout as advanced

def needed(c,did):
    d=sm.get_database(c,did)
    return bool(d.get('parent_id') or c.execute('SELECT 1 FROM library_databases WHERE parent_id=?',(did,)).fetchone())

def inspect(c,did,root):
    selected=sm.get_database(c,did);old_root=Path(selected['root']);family=advanced.descendants(c,did)
    related=advanced.related_ids(c,did)
    if selected.get('parent_id'):
        parent=Path(sm.get_database(c,selected['parent_id'])['root'])
        if root==parent or not root.is_relative_to(parent):raise HTTPException(409,'A child Database must reconnect within its parent folder')
    if any(root.is_relative_to(data) or data.is_relative_to(root) for data in {core.DATA.resolve(),core.database_dir().resolve()}):raise HTTPException(409,'Original roots must not overlap runtime data or database storage')
    for other in c.execute('SELECT id,root FROM library_databases'):
        if other['id'] in related:continue
        other_root=Path(other['root'])
        if root.is_relative_to(other_root) or other_root.is_relative_to(root):raise HTTPException(409,'Reconnect target overlaps another Database')
    targets=[];all_entries=[]
    ids={d['id'] for d in family}
    for d in family:
        destination=root/Path(d['root']).relative_to(old_root)
        if not destination.is_dir():raise HTTPException(409,'Reconnect must include child folder: '+str(destination))
        entries=sm.reconnect_evidence(c,d['id'],destination)
        for entry in entries:
            path=str(destination/entry['relative'])
            collision=c.execute('SELECT database_id FROM media WHERE path=?',(path,)).fetchone()
            if collision and collision['database_id'] not in ids:raise HTTPException(409,'Reconnect target already contains records owned by another Database')
        targets.append(dict(id=d['id'],old_root=d['root'],root=str(destination),revision=d['revision']))
        all_entries.extend(dict(entry,database_id=d['id']) for entry in entries)
    fingerprint=hashlib.sha256(json.dumps([targets,sorted(all_entries,key=lambda e:(e['database_id'],e['relative']))],sort_keys=True).encode()).hexdigest()
    return targets,all_entries,fingerprint

def preview(c,did,root):
    from .sync_service import now
    targets,entries,fingerprint=inspect(c,did,root);d=sm.get_database(c,did);token=sm.identity()
    c.execute('INSERT INTO library_previews VALUES(?,?,?,?,?,?,?)',(token,'reconnect',did,json.dumps({'root':str(root),'family':True}),fingerprint,d['revision'],now().isoformat()))
    return dict(token=token,old_root=d['root'],root=str(root),verified_media=len(entries),samples=entries[:20],database_count=len(targets),annotations_preserved=True)

def confirm(c,did,row,payload):
    root=sm.root_path(payload['root']);targets,entries,fingerprint=inspect(c,did,root)
    if fingerprint!=row['evidence']:raise HTTPException(409,'Database family or files changed. Review a fresh reconnect preview.')
    stats={entry['id']:entry for entry in entries};tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for target in targets:
        for media in c.execute('SELECT id,path,relative_path FROM media WHERE database_id=?',(target['id'],)).fetchall():
            if media['relative_path'] and not media['path'].startswith('archived://'):c.execute('UPDATE media SET path=? WHERE id=?',(str(Path(target['root'])/media['relative_path']),media['id']))
            if media['id'] in stats:
                entry=stats[media['id']];c.execute('UPDATE media SET bytes=?,mtime=?,sha=? WHERE id=?',(entry['bytes'],entry['mtime'],entry['sha'],media['id']))
        if 'duplicate_trash' in tables:
            for trash in c.execute('SELECT t.* FROM duplicate_trash t JOIN media m ON m.id=t.media_id WHERE m.database_id=?',(target['id'],)).fetchall():
                try:paths=[str(Path(target['root'])/Path(trash[key]).relative_to(target['old_root'])) for key in ('source','trash')]
                except ValueError:raise HTTPException(409,'Trash history has an unexpected path')
                c.execute('UPDATE duplicate_trash SET source=?,trash=? WHERE media_id=?',(*paths,trash['media_id']))
        c.execute("UPDATE library_databases SET root=?,availability='available',last_error=NULL,revision=revision+1 WHERE id=?",(target['root'],target['id']))
    d=sm.get_database(c,did)
    if d.get('parent_id'):
        parent=sm.get_database(c,d['parent_id']);c.execute('UPDATE library_databases SET parent_path=? WHERE id=?',(root.relative_to(parent['root']).as_posix(),did));c.execute('UPDATE library_databases SET revision=revision+1 WHERE id=?',(parent['id'],))
    c.execute('DELETE FROM library_previews WHERE id=?',(row['id'],))
    return dict(reconnected=True,database_count=len(targets),annotations_preserved=True)
