"""Reviewed subtree ownership and cross-database logical Sources."""
import hashlib,json,os
from collections import defaultdict
from pathlib import Path,PurePosixPath
from typing import Literal
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,Field,field_validator
from . import core,source_management as sm

router=APIRouter(tags=['Advanced layout'])

def migrate(c):
    columns={r[1] for r in c.execute('PRAGMA table_info(library_databases)')}
    if 'parent_id' not in columns:c.execute('ALTER TABLE library_databases ADD COLUMN parent_id TEXT REFERENCES library_databases(id)')
    if 'parent_path' not in columns:c.execute('ALTER TABLE library_databases ADD COLUMN parent_path TEXT')
    for name in ('default_source_visible','default_source_sync'):
        if name not in columns:c.execute('ALTER TABLE library_databases ADD COLUMN '+name+' INTEGER NOT NULL DEFAULT 1')
    for sql in (
      'CREATE INDEX IF NOT EXISTS database_parent ON library_databases(parent_id)',
      '''CREATE TABLE IF NOT EXISTS library_source_rules(id TEXT PRIMARY KEY,database_id TEXT NOT NULL REFERENCES library_databases(id) ON DELETE CASCADE,path TEXT NOT NULL,source_id TEXT NOT NULL REFERENCES library_sources(id) ON DELETE CASCADE,layout TEXT NOT NULL,UNIQUE(database_id,path))''',
      '''CREATE TABLE IF NOT EXISTS linked_sources(id TEXT PRIMARY KEY,alias TEXT NOT NULL,visible INTEGER NOT NULL DEFAULT 1)''',
      '''CREATE TABLE IF NOT EXISTS linked_source_members(linked_id TEXT NOT NULL REFERENCES linked_sources(id) ON DELETE CASCADE,source_id TEXT NOT NULL REFERENCES library_sources(id) ON DELETE CASCADE,PRIMARY KEY(linked_id,source_id))''',
      'CREATE INDEX IF NOT EXISTS linked_member_source ON linked_source_members(source_id,linked_id)',
    ):c.execute(sql)

def read_indexes(c):
    c.execute('CREATE INDEX IF NOT EXISTS media_source_status ON media(source_id,status,database_id)')
    c.execute('CREATE INDEX IF NOT EXISTS media_database_relative ON media(database_id,relative_path)')

def descendants(c,did):
    return [dict(r) for r in c.execute('''WITH RECURSIVE family(id) AS (SELECT ? UNION ALL SELECT d.id FROM library_databases d JOIN family f ON d.parent_id=f.id) SELECT d.* FROM library_databases d JOIN family f ON f.id=d.id''',(did,))]

def related_ids(c,did):
    ids={d['id'] for d in descendants(c,did)}
    row=sm.get_database(c,did)
    while row.get('parent_id'):
        ids.add(row['parent_id']);row=sm.get_database(c,row['parent_id'])
    return ids

def effective_exclusions(c,d):
    return sorted(set(json.loads(d['exclusions'])+[r[0] for r in c.execute('SELECT parent_path FROM library_databases WHERE parent_id=?',(d['id'],))]))

def rules(c,did):
    return [dict(r) for r in c.execute('''SELECT r.*,s.alias FROM library_source_rules r JOIN library_sources s ON s.id=r.source_id WHERE r.database_id=? ORDER BY length(r.path) DESC,r.path''',(did,))]

def inside(path,prefix):
    if os.name=='nt':path,prefix=path.casefold(),prefix.casefold()
    return path==prefix or path.startswith(prefix+'/')
def relative(value):
    value=value.replace('\\','/')
    if not value or value=='.' or PurePosixPath(value).is_absolute() or any(p in ('','..','.') for p in value.split('/')) or ':' in value:
        raise ValueError('Choose a relative folder below the Database, without .. or empty segments')
    return value

def resolve_assignment(c,d,path,aliases=None):
    aliases=aliases if aliases is not None else {r['relative_path']:r['alias'] for r in c.execute('SELECT relative_path,alias FROM library_sources WHERE database_id=?',(d['id'],))}
    owned=d.get('_source_rules')
    if owned is None:owned=rules(c,d['id'])
    for rule in owned:
        if inside(path,rule['path']):
            suffix=path[len(rule['path'])+1:]
            a=sm.assignment(suffix,rule['layout'],{'':rule['alias']},d['alias'])
            a.update(source_key=rule['path'],source=rule['alias']);return a
    return sm.assignment(path,d['layout'],aliases,d['alias'])

class Change(BaseModel):
    path:str=Field(max_length=4096)
    kind:Literal['source','database','inherit','default']
    alias:str=Field(default='',max_length=200)
    layout:Literal['collection','sources','single_album']='collection'
    source_aliases:dict[str,str]=Field(default_factory=dict,max_length=1000)
    exclusions:list[str]=Field(default_factory=list,max_length=1000)
    @field_validator('path')
    @classmethod
    def path_ok(cls,value):return value if value=='.' else relative(value)
    @field_validator('alias')
    @classmethod
    def alias_ok(cls,value):return value.strip()
    @field_validator('source_aliases')
    @classmethod
    def aliases_ok(cls,value):
        for key in value:
            if key:relative(key)
        return sm.Layout.aliases(value)
    @field_validator('exclusions')
    @classmethod
    def exclusions_ok(cls,value):return sm.Layout.relative_exclusions(value)

class Plan(BaseModel):
    changes:list[Change]=Field(min_length=1,max_length=100)
    representative_files:list[str]=Field(default_factory=list,max_length=10000)
    @field_validator('representative_files')
    @classmethod
    def relative_files(cls,values):return [relative(value) for value in dict.fromkeys(values)]

def evidence(c,did):
    family=descendants(c,did);ids=[d['id'] for d in family];marks=','.join('?' for _ in ids)
    rows=[tuple(r) for r in c.execute(f'SELECT id,database_id,source_id,album_id,relative_path,status FROM media WHERE database_id IN ({marks}) ORDER BY id',ids)]
    config=[{k:d[k] for k in ('id','root','layout','revision','parent_id','parent_path')} for d in family]
    config+=rules(c,did)
    members=[tuple(r) for r in c.execute('SELECT linked_id,source_id FROM linked_source_members ORDER BY linked_id,source_id')]
    return hashlib.sha256(json.dumps([rows,config,members],sort_keys=True).encode()).hexdigest()

def project(c,d,changes,representative_files=()):
    current_rules=rules(c,d['id']);proposed=[dict(r) for r in current_rules]
    base=dict(d);aliases={r['relative_path']:r['alias'] for r in c.execute('SELECT relative_path,alias FROM library_sources WHERE database_id=?',(d['id'],))}
    children=[];seen=set()
    existing_children=[dict(r) for r in c.execute('SELECT * FROM library_databases WHERE parent_id=?',(d['id'],))]
    for change in changes:
        path=change.path
        if path!='.' and change.kind in ('source','database'):
            folder=Path(d['root'])/path
            if folder.is_dir():
                try:path=folder.resolve().relative_to(Path(d['root']).resolve()).as_posix();change.path=path
                except ValueError:raise HTTPException(422,'Selected folder must remain within the Database')
        if path.casefold() in seen:raise HTTPException(422,'Each folder can have only one staged change')
        seen.add(path.casefold())
        if path=='.' and change.kind!='default':raise HTTPException(422,'The Database root uses its default layout')
        if path!='.' and change.kind=='default':raise HTTPException(422,'Default layout applies to the Database root')
        if any(inside(path,child['parent_path']) for child in existing_children):raise HTTPException(409,'This folder belongs to a child Database. Open that Database to edit it.')
        if change.kind=='default':
            base.update(layout=change.layout,alias=change.alias or d['alias'],exclusions=json.dumps(change.exclusions));aliases.update(change.source_aliases)
            for rule in proposed:
                if rule['path'] in change.source_aliases:rule['alias']=change.source_aliases[rule['path']]
        elif change.kind=='database':
            if any(inside(path,other.path) or inside(other.path,path) for other in changes if other is not change and other.path!='.'):
                raise HTTPException(422,'Create a child Database first, then edit folders within it separately')
            if any(inside(child['parent_path'],path) for child in existing_children):raise HTTPException(409,'This folder already contains a child Database')
            root=sm.root_path(str(Path(d['root'])/path))
            if not root.is_dir():raise HTTPException(409,'The selected folder is unavailable; reconnect it before relayout')
            if not root.is_relative_to(Path(d['root'])) or root==Path(d['root']):raise HTTPException(422,'Child Database must remain within its parent')
            related=related_ids(c,d['id'])
            for other in c.execute('SELECT id,root FROM library_databases'):
                if other['id'] in related:continue
                other_root=Path(other['root'])
                if root.is_relative_to(other_root) or other_root.is_relative_to(root):raise HTTPException(409,'The selected folder overlaps another Database')
            children.append(dict(path=path,id='new:'+path,alias=change.alias or PurePosixPath(path).name,layout=change.layout,source_aliases=change.source_aliases))
        else:
            proposed=[r for r in proposed if r['path']!=path]
            if change.kind=='source':
                if change.layout=='sources':raise HTTPException(422,'A Source cannot contain another default Source level. Use a child Database for that layout.')
                folder=Path(d['root'])/path
                if not folder.is_dir() or not folder.resolve().is_relative_to(Path(d['root']).resolve()) or any(p.is_symlink() or p.is_junction() for p in (folder,*folder.parents) if p.is_relative_to(Path(d['root']))):raise HTTPException(409,'Selected Source folder is unavailable or is a link')
                proposed.append(dict(path=path,layout=change.layout,alias=change.alias or PurePosixPath(path).name))
    proposed.sort(key=lambda r:len(r['path']),reverse=True);base['_source_rules']=proposed
    rows=[dict(r) for r in c.execute('SELECT id,relative_path,source_id,album_id,phone,album,status FROM media WHERE database_id=? ORDER BY id',(d['id'],))]
    existing_paths={r['relative_path'] for r in rows}
    rows.extend(dict(id=None,relative_path=path,source_id=None,album_id=None,phone='',album='',status='unindexed') for path in representative_files if path not in existing_paths)
    assignments=[]
    for row in rows:
        path=row['relative_path']
        if not path:continue
        child=next((ch for ch in children if inside(path,ch['path'])),None)
        if child:
            child_relative=path[len(child['path'])+1:]
            child_aliases=dict(child['source_aliases'])
            for key,value in aliases.items():
                if inside(key,child['path']):child_aliases.setdefault(key[len(child['path']):].lstrip('/'),value)
            child_rules=[dict(r,path=r['path'][len(child['path']):].lstrip('/'),alias=child['source_aliases'].get(r['path'][len(child['path']):].lstrip('/'),r['alias'])) for r in proposed if inside(r['path'],child['path']) and r['path']!=child['path']]
            child_rules.sort(key=lambda r:len(r['path']),reverse=True)
            proposed_db=dict(id=child['id'],alias=child['alias'],layout=child['layout'],_source_rules=child_rules)
            a=resolve_assignment(c,proposed_db,child_relative,child_aliases)
            owner=child['id'];owner_alias=child['alias'];rel=child_relative
        else:
            a=resolve_assignment(c,base,path,aliases);owner=d['id'];owner_alias=base['alias'];rel=path
        assignments.append(dict(media_id=row['id'],relative=path,new_relative=rel,database_id=owner,database=owner_alias,old_source_id=row['source_id'],old_album_id=row['album_id'],old_source=row['phone'],old_album=row['album'],**a))
    # Linked Sources can follow a split into narrower folders. A merge into a
    # broader physical Source would expose additional files and needs unlinking.
    linked={r['source_id'] for r in c.execute('SELECT DISTINCT source_id FROM linked_source_members')}
    source_paths={r['id']:Path(r['root'])/r['relative_path'] for r in c.execute('SELECT s.id,s.relative_path,d.root FROM library_sources s JOIN library_databases d ON d.id=s.database_id')}
    for a in assignments:
        if a['old_source_id'] not in linked:continue
        owner_root=Path(d['root'])/(a['database_id'][4:] if a['database_id'].startswith('new:') else '')
        target=owner_root/a['source_key']
        if not target.is_relative_to(source_paths[a['old_source_id']]):raise HTTPException(409,'This merge would broaden a Linked Source. Unlink the affected Source first, then preview again.')
    group_members=defaultdict(set)
    for member in c.execute('SELECT linked_id,source_id FROM linked_source_members'):group_members[member['linked_id']].add(member['source_id'])
    for a in assignments:
        if not a['media_id']:continue
        owner_root=Path(d['root'])/(a['database_id'][4:] if a['database_id'].startswith('new:') else '')
        target=owner_root/a['source_key']
        existing_ids={sid for sid,path in source_paths.items() if path==target}
        if any(existing_ids & members and a['old_source_id'] not in members for members in group_members.values()):
            raise HTTPException(409,'This merge would broaden an existing Linked Source. Unlink the affected Source first, then preview again.')
    controls={r['id']:dict(r) for r in c.execute('SELECT * FROM library_sources')}
    target_controls=defaultdict(set);merged=set()
    for a in assignments:
        old=controls.get(a['old_source_id'])
        if not old:continue
        owner_root=Path(d['root'])/(a['database_id'][4:] if a['database_id'].startswith('new:') else '')
        target=owner_root/a['source_key'];key=str(target)
        target_controls[key].add((old['visible'],old['sync_enabled']))
        for sid,physical in source_paths.items():
            if physical==target:target_controls[key].add((controls[sid]['visible'],controls[sid]['sync_enabled']))
        if not target.is_relative_to(source_paths[a['old_source_id']]):merged.add(key)
    if any(len(target_controls[key])>1 for key in merged):
        raise HTTPException(409,'These Sources have different visibility or sync settings. Align their controls before merging, or keep them as separate Sources.')
    return base,proposed,children,assignments

@router.get('/api/databases/{did}/advanced-layout')
def tree(did:str):
    with core.db() as c:
        d=sm.get_database(c,did);family=descendants(c,did);folders={'.':0}
        for owned in family:
            prefix=Path(owned['root']).relative_to(Path(d['root'])).as_posix();prefix='' if prefix=='.' else prefix+'/'
            for row in c.execute("SELECT relative_path FROM media WHERE database_id=? AND relative_path IS NOT NULL",(owned['id'],)):
                parts=(prefix+row[0]).split('/')[:-1];folders['.']+=1
                for i in range(1,len(parts)+1):
                    path='/'.join(parts[:i]);folders[path]=folders.get(path,0)+1
        for source in c.execute('SELECT relative_path FROM library_sources WHERE database_id=?',(did,)):
            parts=source[0].split('/') if source[0] else []
            for i in range(1,len(parts)+1):folders.setdefault('/'.join(parts[:i]),0)
        return dict(database=d,folders=[dict(path=p,media=n) for p,n in sorted(folders.items())],rules=rules(c,did),children=[ch for ch in family if ch['id']!=did],catalogue_only=True)

@router.post('/api/databases/{did}/advanced-preview')
def preview(did:str,body:Plan):
    from .sync_service import now
    with core.db() as c:
        c.execute('BEGIN')
        d=sm.get_database(c,did);base,proposed,children,assignments=project(c,d,body.changes,body.representative_files)
        changed=[a for a in assignments if a['database_id']!=did or a['source']!=a['old_source'] or a['album']!=a['old_album'] or any(ch.kind!='default' and inside(a['relative'],ch.path) for ch in body.changes)]
        token=sm.identity();payload=body.model_dump()
        fingerprint=evidence(c,did)
        examples=defaultdict(list)
        for a in changed:
            key=(a['database_id'],a['source_key'],a['album_key'])
            if len(examples[key])<3:examples[key].append(a)
        groups=c.execute('''SELECT DISTINCT g.alias FROM linked_sources g JOIN linked_source_members lm ON lm.linked_id=g.id JOIN media m ON m.source_id=lm.source_id WHERE m.database_id=?''',(did,)).fetchall()
        c.commit()
        c.execute('INSERT INTO library_previews VALUES(?,?,?,?,?,?,?)',(token,'advanced',did,json.dumps(payload),fingerprint,d['revision'],now().isoformat()))
        return dict(token=token,affected_media=sum(a['media_id'] is not None for a in changed),new_databases=children,source_rules=proposed,samples=[dict(a,relative=a['new_relative'],previous_relative=a['relative']) for rows in examples.values() for a in rows],annotations_preserved=True,originals_preserved=True,linked_sources=[r[0] for r in groups],note='Child Databases own their subtrees. Parent scans exclude those folders. New child schedules start off. Linked Sources follow narrower Source splits.')

@router.post('/api/databases/{did}/advanced-confirm')
def confirm(did:str,body:sm.Confirm):
    with sm.mutation_lock(),core.db() as c:
        c.execute('BEGIN IMMEDIATE')
        saved,payload=sm.checked_preview(c,body,'advanced',did)
        if evidence(c,did)!=saved['evidence']:raise HTTPException(409,'Catalogue or Linked Source membership changed. Review a fresh preview.')
        d=sm.get_database(c,did);changes=Plan.model_validate(payload).changes;base,proposed,children,assignments=project(c,d,changes)
        old_controls={r['id']:dict(r) for r in c.execute('SELECT * FROM library_sources')}
        old_assignments={ch.path:resolve_assignment(c,d,ch.path+'/__future__.jpg') for ch in changes if ch.kind in ('source','database')}
        new_ids={};new_databases=[]
        for child in children:
            cid=sm.identity();new_ids[child['id']]=cid;new_databases.append(cid)
            inherited=[e[len(child['path'])+1:] for e in json.loads(base['exclusions']) if e.startswith(child['path']+'/')]
            schedule=json.dumps(dict(frequency='off',time='03:00',weekday=6,month_day=1,timezone='UTC',auto_assign=True))
            c.execute('''INSERT INTO library_databases(id,root,alias,layout,exclusions,visible,sync_enabled,schedule,parent_id,parent_path) VALUES(?,?,?,?,?,?,?,?,?,?)''',(cid,str(Path(d['root'])/child['path']),child['alias'],child['layout'],json.dumps(inherited),d['visible'],d['sync_enabled'] if not sm.excluded(child['path'],json.loads(base['exclusions'])) else 0,schedule,did,child['path']))
            prior=next((source for source in old_controls.values() if source['database_id']==did and source['relative_path']==old_assignments[child['path']]['source_key']),None)
            c.execute('UPDATE library_databases SET default_source_visible=?,default_source_sync=? WHERE id=?',(prior['visible'] if prior else d['default_source_visible'],prior['sync_enabled'] if prior else d['default_source_sync'],cid))
            # Reuse identities for Sources already anchored within the new child.
            for source in c.execute('SELECT * FROM library_sources WHERE database_id=?',(did,)).fetchall():
                if inside(source['relative_path'],child['path']):
                    suffix=source['relative_path'][len(child['path']):].lstrip('/')
                    c.execute('UPDATE library_sources SET database_id=?,relative_path=? WHERE id=?',(cid,suffix,source['id']))
            for rule in c.execute('SELECT * FROM library_source_rules WHERE database_id=?',(did,)).fetchall():
                if inside(rule['path'],child['path']):
                    if rule['path']==child['path']:c.execute('DELETE FROM library_source_rules WHERE id=?',(rule['id'],))
                    else:c.execute('UPDATE library_source_rules SET database_id=?,path=? WHERE id=?',(cid,rule['path'][len(child['path'])+1:],rule['id']))
            child_aliases=dict(child['source_aliases'])
            prior=next((source for source in old_controls.values() if source['database_id']==did and source['relative_path']==old_assignments[child['path']]['source_key']),None)
            if prior and c.execute('SELECT 1 FROM linked_source_members WHERE source_id=?',(prior['id'],)).fetchone():
                child_aliases.setdefault('',child['alias']+' Root files')
            sm.ensure_sources(c,cid,child_aliases)
            for source in c.execute('SELECT * FROM library_sources WHERE database_id=?',(cid,)).fetchall():
                if prior and source['id'] not in old_controls:
                    c.execute('UPDATE library_sources SET visible=?,sync_enabled=? WHERE id=?',(prior['visible'],prior['sync_enabled'],source['id']))
                    c.execute('INSERT OR IGNORE INTO linked_source_members SELECT linked_id,? FROM linked_source_members WHERE source_id=?',(source['id'],prior['id']))
        default=next((ch for ch in changes if ch.kind=='default'),None)
        if default:c.execute('UPDATE library_databases SET layout=?,alias=?,exclusions=? WHERE id=?',(base['layout'],base['alias'],json.dumps(default.exclusions),did))
        desired={r['path']:r for r in proposed if not any(inside(r['path'],ch['path']) for ch in children)}
        for rule in c.execute('SELECT * FROM library_source_rules WHERE database_id=?',(did,)).fetchall():
            if rule['path'] not in desired:c.execute('DELETE FROM library_source_rules WHERE id=?',(rule['id'],))
        for path,rule in desired.items():
            sm.ensure_sources(c,did,{path:rule['alias']})
            sid=c.execute('SELECT id FROM library_sources WHERE database_id=? AND relative_path=?',(did,path)).fetchone()[0]
            c.execute('''INSERT INTO library_source_rules(id,database_id,path,source_id,layout) VALUES(?,?,?,?,?) ON CONFLICT(database_id,path) DO UPDATE SET source_id=excluded.source_id,layout=excluded.layout''',(sm.identity(),did,path,sid,rule['layout']))
            if sid not in old_controls and path in old_assignments:
                prior=next((s for s in old_controls.values() if s['database_id']==did and s['relative_path']==old_assignments[path]['source_key']),None)
                if prior:
                    c.execute('UPDATE library_sources SET visible=?,sync_enabled=? WHERE id=?',(prior['visible'],prior['sync_enabled'],sid))
                    c.execute('INSERT OR IGNORE INTO linked_source_members SELECT linked_id,? FROM linked_source_members WHERE source_id=?',(sid,prior['id']))
        source_inheritance=defaultdict(list)
        source_cache={};album_cache={}
        for a in assignments:
            owner=new_ids.get(a['database_id'],a['database_id']);source_key=(owner,a['source_key'])
            if source_key not in source_cache:
                sm.ensure_sources(c,owner,{a['source_key']:a['source']})
                source_cache[source_key]=c.execute('SELECT id FROM library_sources WHERE database_id=? AND relative_path=?',source_key).fetchone()[0]
            sid=source_cache[source_key];album_key=(sid,a['album_key'])
            if album_key not in album_cache:album_cache[album_key]=sm.album(c,sid,a['album_key'],a['album'])
            aid=album_cache[album_key]
            if (owner,sid,aid,a['new_relative'],a['source'],a['album'])!=(did,a['old_source_id'],a['old_album_id'],a['relative'],a['old_source'],a['old_album']):
                c.execute('UPDATE media SET database_id=?,source_id=?,album_id=?,relative_path=?,phone=?,album=? WHERE id=?',(owner,sid,aid,a['new_relative'],a['source'],a['album'],a['media_id']))
            if a['old_source_id'] in old_controls:source_inheritance[sid].append(old_controls[a['old_source_id']])
            if a['old_source_id']!=sid:c.execute('''INSERT OR IGNORE INTO linked_source_members(linked_id,source_id) SELECT linked_id,? FROM linked_source_members WHERE source_id=?''',(sid,a['old_source_id']))
        for sid,previous in source_inheritance.items():
            if sid in old_controls:previous.append(old_controls[sid])
            c.execute('UPDATE library_sources SET visible=?,sync_enabled=? WHERE id=?',(min(s['visible'] for s in previous),min(s['sync_enabled'] for s in previous),sid))
        for owner in [did,*new_databases]:
            c.execute('''UPDATE library_sources SET active=CASE WHEN relative_path='' OR EXISTS(SELECT 1 FROM media m WHERE m.source_id=library_sources.id) OR EXISTS(SELECT 1 FROM library_source_rules r WHERE r.source_id=library_sources.id) THEN 1 ELSE 0 END WHERE database_id=?''',(owner,))
            c.execute('UPDATE library_databases SET revision=revision+1 WHERE id=?',(owner,))
        for child in children:
            for key in child['source_aliases']:c.execute('UPDATE library_sources SET active=1 WHERE database_id=? AND relative_path=?',(new_ids[child['id']],key))
        c.execute('UPDATE catalogue_clock SET revision=revision+1 WHERE id=1')
        c.execute('DELETE FROM library_previews WHERE id=?',(body.token,))
    return dict(applied=True,new_database_ids=new_databases,annotations_preserved=True,originals_preserved=True)

class Linked(BaseModel):
    alias:str=Field(min_length=1,max_length=200)
    source_ids:list[str]=Field(min_length=1,max_length=1000)
    visible:bool=True
    @field_validator('alias')
    @classmethod
    def nonblank(cls,value):
        if not value.strip():raise ValueError('Give the Linked Source a name')
        return value.strip()
    @field_validator('source_ids')
    @classmethod
    def unique(cls,values):return list(dict.fromkeys(values))

def linked_list(c):
    result=[]
    for row in c.execute('SELECT * FROM linked_sources ORDER BY alias,id'):
        group=dict(row);group['visible']=bool(group['visible'])
        group['members']=[dict(r) for r in c.execute('''SELECT s.id,s.alias,s.database_id,s.relative_path,s.active,s.visible,d.alias database_alias FROM linked_source_members lm JOIN library_sources s ON s.id=lm.source_id JOIN library_databases d ON d.id=s.database_id WHERE lm.linked_id=? ORDER BY d.alias,s.alias''',(group['id'],))]
        group['media_count']=c.execute("SELECT count(*) FROM media m WHERE m.status='ready' AND "+sm.VISIBLE+' AND m.source_id IN (SELECT source_id FROM linked_source_members WHERE linked_id=?)',(group['id'],)).fetchone()[0]
        result.append(group)
    return result

@router.get('/api/linked-sources')
def linked_sources():
    with core.db() as c:return linked_list(c)

@router.get('/api/library/hierarchy')
def hierarchy():
    with core.db() as c:
        return dict(databases=[dict(r) for r in c.execute('SELECT id,alias,parent_id,visible FROM library_databases ORDER BY alias,id')],sources=[dict(r) for r in c.execute('''SELECT s.id,s.alias,s.database_id,s.relative_path,s.active,s.visible,d.alias database_alias,d.visible database_visible FROM library_sources s JOIN library_databases d ON d.id=s.database_id ORDER BY d.alias,s.alias''')],linked_sources=linked_list(c))

def save_linked(c,body,gid=None):
    if gid and not c.execute('SELECT 1 FROM linked_sources WHERE id=?',(gid,)).fetchone():raise HTTPException(404,'Linked Source not found')
    for sid in body.source_ids:
        if not c.execute('SELECT 1 FROM library_sources WHERE id=?',(sid,)).fetchone():raise HTTPException(422,'One of the member Sources no longer exists')
    gid=gid or sm.identity()
    c.execute('INSERT INTO linked_sources VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET alias=excluded.alias,visible=excluded.visible',(gid,body.alias,body.visible))
    c.execute('DELETE FROM linked_source_members WHERE linked_id=?',(gid,))
    c.executemany('INSERT INTO linked_source_members VALUES(?,?)',[(gid,sid) for sid in body.source_ids])
    c.execute('UPDATE catalogue_clock SET revision=revision+1 WHERE id=1')
    return dict(id=gid,saved=True)

@router.post('/api/linked-sources',status_code=201)
def create_linked(body:Linked):
    with core.db() as c:
        c.execute('BEGIN IMMEDIATE');return save_linked(c,body)

@router.put('/api/linked-sources/{gid}')
def update_linked(gid:str,body:Linked):
    with core.db() as c:
        c.execute('BEGIN IMMEDIATE');return save_linked(c,body,gid)

@router.delete('/api/linked-sources/{gid}')
def delete_linked(gid:str):
    with core.db() as c:
        c.execute('BEGIN IMMEDIATE');c.execute('DELETE FROM linked_sources WHERE id=?',(gid,));c.execute('UPDATE catalogue_clock SET revision=revision+1 WHERE id=1')
    return dict(removed=True,member_sources_preserved=True)
