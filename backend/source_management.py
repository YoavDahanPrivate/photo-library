"""Registered roots and deliberate, catalogue-only hierarchy changes.

Folder interpretation is never changed by a scan. Names and locations are mutable;
media, source and database identities are not.
"""
import hashlib
import json
import os
import re
import sqlite3
import time
import uuid
from collections import Counter
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from . import core

router = APIRouter(prefix="/api/databases", tags=["Databases"])
IMAGES = {".jpg", ".jpeg", ".heic", ".heif", ".png", ".gif", ".webp", ".tif", ".tiff", ".dng", ".bmp", ".avif"}
VIDEOS = {".mov", ".mp4", ".m4v", ".avi", ".mkv", ".mts", ".m2ts", ".3gp", ".webm"}
SKIP = {".dtrash", "photoprismstorage", "$recycle.bin", "system volume information"}
VISIBLE = "(m.database_id IS NULL OR EXISTS(SELECT 1 FROM library_databases ld WHERE ld.id=m.database_id AND ld.visible=1)) AND (m.source_id IS NULL OR EXISTS(SELECT 1 FROM library_sources ls WHERE ls.id=m.source_id AND ls.visible=1))"


def identity():
    return uuid.uuid4().hex


def migrate(c):
    # No filesystem discovery during startup, including when a drive is offline.
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='library_meta'").fetchone():
        backup = core.database_dir() / "catalogue-before-source-management.sqlite"
        if not backup.exists():
            with sqlite3.connect(backup) as snapshot:
                c.backup(snapshot)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS library_databases(
      id TEXT PRIMARY KEY,root TEXT NOT NULL UNIQUE,alias TEXT NOT NULL,layout TEXT NOT NULL,
      exclusions TEXT NOT NULL DEFAULT '[]',visible INTEGER NOT NULL DEFAULT 1,
      sync_enabled INTEGER NOT NULL DEFAULT 1,schedule TEXT,next_due TEXT,
      availability TEXT NOT NULL DEFAULT 'unknown',last_error TEXT,revision INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS library_sources(
      id TEXT PRIMARY KEY,database_id TEXT NOT NULL REFERENCES library_databases(id),
      relative_path TEXT NOT NULL,alias TEXT NOT NULL,visible INTEGER NOT NULL DEFAULT 1,
      sync_enabled INTEGER NOT NULL DEFAULT 1,active INTEGER NOT NULL DEFAULT 1,UNIQUE(database_id,relative_path));
    CREATE TABLE IF NOT EXISTS library_albums(
      id TEXT PRIMARY KEY,source_id TEXT NOT NULL REFERENCES library_sources(id),
      relative_path TEXT NOT NULL,alias TEXT NOT NULL,UNIQUE(source_id,relative_path));
    CREATE TABLE IF NOT EXISTS library_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS library_previews(
      id TEXT PRIMARY KEY,purpose TEXT NOT NULL,database_id TEXT,payload TEXT NOT NULL,
      evidence TEXT NOT NULL,revision INTEGER,created TEXT NOT NULL);
    """)
    from .advanced_layout import migrate as migrate_advanced
    migrate_advanced(c)
    c.execute("BEGIN IMMEDIATE")
    columns = {r[1] for r in c.execute("PRAGMA table_info(media)")}
    for col in ("database_id", "source_id", "album_id", "relative_path"):
        if col not in columns:
            c.execute(f"ALTER TABLE media ADD COLUMN {col} TEXT")
    from .advanced_layout import read_indexes
    read_indexes(c)
    c.execute("CREATE INDEX IF NOT EXISTS media_database ON media(database_id,source_id)")
    c.execute("CREATE INDEX IF NOT EXISTS media_album_status ON media(album_id,status)")
    if c.execute("SELECT 1 FROM library_meta WHERE key='legacy_migrated'").fetchone():
        return
    # The legacy layout remains intact until the owner explicitly previews a change.
    did = identity()
    c.execute("INSERT INTO library_databases(id,root,alias,layout) VALUES(?,?,?,'legacy')",
              (did, str(core.ROOT.resolve()), core.ROOT.name or "Photos"))
    # Carry an installed library's calendar forward into its first Database.
    sync_path = core.database_dir() / "sync.sqlite"
    if sync_path.is_file():
        with sqlite3.connect(sync_path) as sync:
            if sync.execute("SELECT 1 FROM sqlite_master WHERE name='settings'").fetchone():
                setting = sync.execute("SELECT value,next_due FROM settings WHERE id=1").fetchone()
                if setting:
                    c.execute("UPDATE library_databases SET schedule=?,next_due=? WHERE id=?", (*setting, did))
    sources = {}
    for phone in core.PHONES:
        sid = identity()
        c.execute("INSERT INTO library_sources(id,database_id,relative_path,alias) VALUES(?,?,?,?)", (sid, did, phone, phone))
        sources[phone] = sid
    has_versions = c.execute("SELECT 1 FROM sqlite_master WHERE name='sync_versions'").fetchone()
    for row in c.execute("SELECT id,path,phone,album FROM media").fetchall():
        path = row["path"]
        if path.startswith("archived://") and has_versions:
            version = c.execute("SELECT source_path FROM sync_versions WHERE old_id=?", (row["id"],)).fetchone()
            if version:
                path = version[0]
        try:
            relative = Path(path).relative_to(core.ROOT).as_posix()
        except ValueError:
            continue
        phone = row["phone"]
        if phone not in sources:
            continue
        sid = sources[phone]
        parts = PurePosixPath(relative).parts
        album_rel = parts[1] if len(parts) > 2 else "."
        aid = album(c, sid, album_rel, row["album"] or "Main folder")
        c.execute("UPDATE media SET database_id=?,source_id=?,album_id=?,relative_path=? WHERE id=?",
                  (did, sid, aid, relative, row["id"]))
    c.execute("INSERT INTO library_meta VALUES('legacy_migrated','1')")


def album(c, sid, relative, alias):
    row = c.execute("SELECT id FROM library_albums WHERE source_id=? AND relative_path=?", (sid, relative)).fetchone()
    if row:
        return row[0]
    aid = identity()
    c.execute("INSERT INTO library_albums VALUES(?,?,?,?)", (aid, sid, relative, alias))
    return aid


def root_path(value):
    path = Path(value).expanduser()
    from .network_access import ensure_access
    try:
        ensure_access(path)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    except (RuntimeError, OSError) as error:
        raise HTTPException(409, str(error)) from None
    if not path.is_absolute():
        raise HTTPException(422, "Choose an absolute server folder path")
    if path.is_symlink() or path.is_junction():
        raise HTTPException(422, "The root must not be a symbolic link or junction")
    return path.resolve()


def validate_overlap(c, root, except_id=None):
    for row in c.execute("SELECT id,root FROM library_databases"):
        if row["id"] == except_id:
            continue
        if except_id:
            current=get_database(c,except_id)
            from .advanced_layout import related_ids
            if root==Path(current["root"]) and row["id"] in related_ids(c,except_id):
                continue
        other = Path(os.path.abspath(row["root"]))
        if root.is_relative_to(other) or other.is_relative_to(root):
            raise HTTPException(409, "This root overlaps a registered database: " + str(other))
    for data in {core.DATA.resolve(), core.database_dir().resolve()}:
        if root.is_relative_to(data) or data.is_relative_to(root):
            raise HTTPException(409, "Original roots must not overlap application runtime data or database storage")


class Layout(BaseModel):
    root: str = Field(min_length=1, max_length=4096)
    interpretation: Literal["auto", "collection", "sources", "single_album"] = "auto"
    alias: str = Field(default="", max_length=200)
    source_aliases: dict[str, str] = Field(default_factory=dict)
    exclusions: list[str] = Field(default_factory=list, max_length=1000)

    @field_validator("exclusions")
    @classmethod
    def relative_exclusions(cls, values):
        result = []
        for value in values:
            value = value.strip().replace("\\", "/")
            if not value or value == "." or PurePosixPath(value).is_absolute() or ".." in PurePosixPath(value).parts or ":" in value:
                raise ValueError("Exclusions must be relative folder paths without '..'")
            result.append(value.rstrip("/"))
        return sorted(set(result))

    @field_validator("source_aliases")
    @classmethod
    def aliases(cls, values):
        if any(not v.strip() or len(v) > 200 for v in values.values()):
            raise ValueError("Source aliases must contain 1 to 200 characters")
        return {k: v.strip() for k, v in values.items()}


def excluded(relative, exclusions):
    return any(relative.casefold() == e.casefold() or relative.casefold().startswith(e.casefold() + "/") for e in exclusions)


def walk(root, exclusions=(), control=lambda: None, check_readable=False, progress=lambda **kw: None, on_batch=None):
    progress(current_folder=str(root),current_file="")
    from .network_access import ensure_access
    ensure_access(root)
    if not root.is_dir() or root.is_symlink() or root.is_junction():
        raise RuntimeError("Source unavailable: " + str(root))
    files = []; pending=[]; last_batch=time.monotonic()
    def flush():
        nonlocal last_batch
        if pending and on_batch:on_batch(list(pending))
        pending.clear();last_batch=time.monotonic()
    def failed(error):
        raise error
    for directory, dirs, names in os.walk(root, followlinks=False, onerror=failed):
        control()
        progress(current_folder=str(directory),current_file="",folders_delta=1)
        dirs[:] = sorted(d for d in dirs if d.casefold() not in SKIP
                         and not Path(directory, d).is_symlink() and not Path(directory, d).is_junction()
                         and not excluded(Path(directory, d).relative_to(root).as_posix(), exclusions))
        for name in sorted(names):
            p = Path(directory, name)
            if p.suffix.lower() not in IMAGES | VIDEOS or p.is_symlink():
                continue
            control()
            progress(current_folder=str(directory),current_file=name)
            st = p.stat()
            if check_readable:
                try:
                    with p.open("rb") as readable:
                        readable.read(1)
                except OSError as error:
                    raise OSError("Cannot read media file: " + p.relative_to(root).as_posix()) from error
            files.append(dict(relative=p.relative_to(root).as_posix(), bytes=st.st_size, mtime=st.st_mtime))
            progress(media_delta=1)
            if on_batch:
                pending.append(files[-1])
                if len(pending)>=50 or time.monotonic()-last_batch>=5:flush()
        if on_batch:flush()
    if not root.is_dir():
        raise RuntimeError("Source disconnected during inventory: " + str(root))
    flush()
    return files


def detect(files):
    depths = Counter(len(PurePosixPath(f["relative"]).parts) - 1 for f in files)
    branches = Counter(PurePosixPath(f["relative"]).parts[0] for f in files if "/" in f["relative"])
    root_count = depths[0]
    phone = re.compile(r"iphone|ipad|pixel|galaxy|phone|android|\d+(?:pro|max|plus)|(?:^|[ _-])backup(?:$|[ _-])", re.I)
    camera_folders = {"dcim", "camera", "screenshots", "whatsapp images", "whatsapp video"}
    content_branches = {PurePosixPath(f["relative"]).parts[0] for f in files
                        if len(PurePosixPath(f["relative"]).parts) > 2
                        and PurePosixPath(f["relative"]).parts[1].casefold() in camera_folders}
    phone_count = sum(n for branch, n in branches.items() if phone.search(branch) or branch in content_branches)
    total = len(files)
    ratio = phone_count / total if total else 0
    mode = "sources" if branches and ratio >= .7 else "collection"
    warnings = []
    if not files:
        warnings.append("No supported media found. Check the root and exclusions before registering.")
    if 0 < ratio < .7 or (mode == "sources" and ratio < 1):
        warnings.append("Mixed phone-like and ordinary folders; review whether folders are Sources or Albums.")
    if root_count and branches:
        warnings.append("Media occurs both at the root and inside folders; root media needs a Main folder assignment.")
    if mode == "collection" and sum(n for d, n in depths.items() if d >= 2) > total / 2:
        warnings.append("Deep nesting could also represent Sources. Suggested as one collection; verify the preview.")
    if total and max(depths.values()) / total < .7:
        warnings.append("No predominant folder depth; the root contains mixed layouts.")
    reason = ("Most media belongs to phone backup folders, suggested as Sources." if mode == "sources" else
              "Suggested as one collection. Folder paths become Albums; ordinary album folders are not Sources.")
    return dict(interpretation=mode, ambiguous=bool(warnings), warnings=warnings, reason=reason,
                depth_counts=dict(depths), branch_counts=dict(branches))


def assignment(relative, layout, aliases, database_alias):
    parts = PurePosixPath(relative).parts
    source = parts[0] if layout in ("sources", "legacy") and len(parts) > 1 else ""
    folders = parts[1:-1] if source else parts[:-1]
    album_rel = "/".join(folders) or "."
    label = (folders[0] if folders else "(Phone root)") if layout == "legacy" else " › ".join(folders) or "Main folder"
    if layout == "legacy":
        album_rel = folders[0] if folders else "."
    if layout == "single_album":
        album_rel, label = ".", "Main folder"
    return dict(source_key=source, source=aliases.get(source, source or database_alias + " Collection"),
                album_key=album_rel, album=label)


def evidence(files):
    return hashlib.sha256(json.dumps(sorted(files, key=lambda f: f["relative"]), sort_keys=True).encode()).hexdigest()


def get_database(c, did):
    row = c.execute("SELECT * FROM library_databases WHERE id=?", (did,)).fetchone()
    if not row:
        raise HTTPException(404, "Database not found")
    return dict(row)


@contextmanager
def mutation_lock():
    from .sync_service import scan_lock
    try:
        with scan_lock():
            yield
    except RuntimeError as e:
        raise HTTPException(409, str(e))


@router.get("")
def databases():
    with core.db() as c:
        result = []
        for row in c.execute("SELECT * FROM library_databases ORDER BY alias,id"):
            d = dict(row)
            from .advanced_layout import rules
            d["source_overrides"] = rules(c,d["id"])
            d["children"] = [dict(r) for r in c.execute("SELECT id,alias,parent_path FROM library_databases WHERE parent_id=? ORDER BY alias",(d["id"],))]
            d["exclusions"] = json.loads(d["exclusions"])
            d["schedule"] = json.loads(d["schedule"]) if d["schedule"] else None
            d["sources"] = [dict(r) for r in c.execute("SELECT * FROM library_sources WHERE database_id=? ORDER BY alias,id", (d["id"],))]
            for s in d["sources"]:
                for key in ("visible", "sync_enabled", "active"):
                    s[key] = bool(s[key])
                s["albums"] = [dict(r) for r in c.execute("""
                    SELECT a.id,a.relative_path,a.alias,count(m.id) media_count,
                           coalesce(sum(m.kind='photo'),0) photos,
                           coalesce(sum(m.kind='video'),0) videos,
                           min(CASE WHEN m.status='ready' THEN m.id END) cover
                    FROM library_albums a LEFT JOIN media m ON m.album_id=a.id
                      AND m.status NOT IN ('missing','superseded','trashed')
                    WHERE a.source_id=? GROUP BY a.id,a.relative_path,a.alias
                    HAVING count(m.id)>0 ORDER BY a.alias,a.id
                    """, (s["id"],))]
                s["album_count"] = len(s["albums"])
                s["media_count"] = sum(a["media_count"] for a in s["albums"])
            root = Path(d["root"])
            required = [root] + [root / s["relative_path"] for s in d["sources"] if s["active"] and s["sync_enabled"] and s["relative_path"]]
            try:
                from .network_access import ensure_access
                ensure_access(root)
                d["availability"] = "available" if all(p.is_dir() and not p.is_symlink() and not p.is_junction() for p in required) else "unavailable"
            except (RuntimeError, OSError) as error:
                d["availability"] = "unavailable"
                d["last_error"] = str(error)
            d["media_count"] = c.execute("SELECT count(*) FROM media WHERE database_id=?", (d["id"],)).fetchone()[0]
            d["source_count"] = sum(s["active"] for s in d["sources"])
            d["album_count"] = sum(s["album_count"] for s in d["sources"] if s["active"])
            result.append(d)
        return result


def build_preview(body, did=None, purpose="register", persist=True, structure_override=None):
    quick = purpose == "register" and did is None
    structure = None
    if quick:
        # Avoid a remote resolve/stat in the request thread: the helper bounds
        # every filesystem operation and supplies the canonical validated root.
        candidate = Path(body.root).expanduser()
        if not candidate.is_absolute():
            raise HTTPException(422, "Choose an absolute server folder path")
        with core.db() as c:
            validate_overlap(c, Path(os.path.abspath(candidate)))
        try:
            from .source_preview import inspect
            structure = structure_override if structure_override is not None else inspect(candidate, body.exclusions)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        except (OSError, RuntimeError) as error:
            raise HTTPException(409, str(error)) from None
        root = Path(structure['root'])
    else:
        root = root_path(body.root)
    with core.db() as c:
        validate_overlap(c, root, did)
        d = get_database(c, did) if did else None
        if d and purpose == "layout" and root != Path(d["root"]):
            raise HTTPException(422, "Use Reconnect to change a root")
    try:
        files = structure["files"] if structure else walk(root, body.exclusions, check_readable=True)
    except (OSError, RuntimeError) as e:
        raise HTTPException(409, str(e))
    suggestion = detect(files)
    if structure:
        info=structure['inspection']
        suggestion['reason']=('Complete accessible folder tree discovered. ' if info['kind']=='directory_tree' and not info['truncated'] else 'Suggested from representative filenames and directory structure. ')+suggestion['reason']
        if info['truncated']:
            suggestion['ambiguous']=True
            suggestion['warnings'].append('This is a bounded sample, not a complete inventory. Review the layout; totals and file access are checked during sync.')
        suggestion['warnings'].extend(info['warnings'])
        if info['truncated']:
            suggestion['warnings'].append('Some folders were not inspected ('+', '.join(info['limits'])+'). Unseen files will follow your approved interpretation.')
    mode = suggestion["interpretation"] if body.interpretation == "auto" else body.interpretation
    alias = body.alias.strip() or (d["alias"] if d else root.name or "Photos")
    assignments = [(f, assignment(f["relative"], mode, body.source_aliases, alias)) for f in files]
    sources = {}
    groups = {}
    for f, a in assignments:
        sources[a["source_key"]] = a["source"]
        groups.setdefault((a["source_key"], a["album_key"]), []).append({"relative": f["relative"], "database": alias, **a})
    if structure and mode == 'sources':
        for folder in structure.get('folder_tree',[]):
            relative=folder['relative']
            if relative!='.' and '/' not in relative:
                sources.setdefault(relative,body.source_aliases.get(relative,relative))
    if not sources:
        sources[""] = body.source_aliases.get("", alias + " Collection")
    # Return every discovered Album, with at most three representative files.
    # The UI pages by Album; a row limit must never conceal discovered branches.
    samples = [sample for key in sorted(groups) for sample in groups[key][:3]]
    payload = dict(root=str(root), interpretation=mode, alias=alias, source_aliases=sources, exclusions=body.exclusions)
    if structure:
        payload['preview_kind']='directory_sample'
        payload['preview_truncated']=structure['inspection']['truncated'] or structure['inspection']['kind']=='directory_tree'
    token = identity()
    from .sync_service import now
    with core.db() as c:
        if persist:
            c.execute("DELETE FROM library_previews WHERE created<?", ((now() - __import__('datetime').timedelta(hours=24)).isoformat(),))
            c.execute("INSERT INTO library_previews VALUES(?,?,?,?,?,?,?)",
                      (token, purpose, did, json.dumps(payload), structure["evidence"] if structure else evidence(files), d["revision"] if d else None, now().isoformat()))
        affected = c.execute("SELECT count(*) FROM media WHERE database_id=?", (did,)).fetchone()[0] if did else 0
    metadata_report = None  # Metadata is read during sync, not layout approval.
    folder_tree=[]
    for folder in (structure or {}).get('folder_tree',[]):
        relative=folder['relative']
        a=assignment(('' if relative=='.' else relative+'/')+'__folder_preview__.jpg',mode,sources,alias)
        source_folder=mode in ('sources','legacy') and relative!='.' and '/' not in relative
        role='Source folder' if source_folder or relative=='.' else 'Album' if folder['direct_media'] else 'Container folder' if folder['children'] else 'Folder'
        folder_tree.append(dict(**folder,source=a['source'],album=a['album'],source_key=a['source_key'],album_key=a['album_key'],role=role))
    return dict(folder_tree=folder_tree,inspection=structure["inspection"] if structure else None, metadata_report=metadata_report, token=token if persist else None, **payload, suggestion=suggestion, media_count=len(files), album_count=len(groups),
                sources=[dict(key=k, alias=v) for k, v in sources.items()], samples=samples,
                affected_media=affected, annotations_preserved=True)


@router.post("/analyze")
def analyze(body: Layout):
    return build_preview(body, persist=False)


@router.post("/{did}/analyze")
def analyze_layout(did: str, body: Layout):
    return build_preview(body, did, "layout", persist=False)


@router.post("/preview")
def preview(body: Layout):
    return build_preview(body)


@router.post("/{did}/layout-preview")
def layout_preview(did: str, body: Layout):
    return build_preview(body, did, "layout")


class Confirm(BaseModel):
    token: str
    confirm: bool = False


def checked_preview(c, body, purpose, did=None):
    if not body.confirm:
        raise HTTPException(422, "Confirm the reviewed preview")
    row = c.execute("SELECT * FROM library_previews WHERE id=? AND purpose=?", (body.token, purpose)).fetchone()
    if not row or row["database_id"] != did:
        raise HTTPException(409, "Preview missing, already used, or belongs to a different database")
    from .sync_service import now
    from datetime import datetime, timedelta
    if now() - datetime.fromisoformat(row["created"]) > timedelta(hours=24):
        raise HTTPException(409, "Preview expired; analyze again")
    if did and get_database(c, did)["revision"] != row["revision"]:
        raise HTTPException(409, "Database changed since preview; analyze again")
    return row, json.loads(row["payload"])


def ensure_sources(c, did, aliases):
    for relative, alias in aliases.items():
        existing=c.execute("SELECT id,relative_path FROM library_sources WHERE database_id=? AND relative_path=?",(did,relative)).fetchone()
        if not existing and os.name=="nt":
            existing=next((row for row in c.execute("SELECT id,relative_path FROM library_sources WHERE database_id=?",(did,)) if row["relative_path"].casefold()==relative.casefold()),None)
        if existing:
            c.execute("UPDATE library_sources SET relative_path=?,alias=?,active=1 WHERE id=?",(relative,alias,existing["id"]))
        else:
            policy=c.execute("SELECT default_source_visible,default_source_sync FROM library_databases WHERE id=?",(did,)).fetchone()
            c.execute("INSERT INTO library_sources(id,database_id,relative_path,alias,visible,sync_enabled) VALUES(?,?,?,?,?,?)",(identity(),did,relative,alias,*policy))


def assign_entry(c, d, relative):
    aliases = {r["relative_path"]: r["alias"] for r in c.execute("SELECT relative_path,alias FROM library_sources WHERE database_id=?", (d["id"],))}
    from .advanced_layout import resolve_assignment
    a = resolve_assignment(c,d,relative,aliases)
    ensure_sources(c, d["id"], {a["source_key"]: a["source"]})
    sid = c.execute("SELECT id FROM library_sources WHERE database_id=? AND relative_path=?", (d["id"], a["source_key"])).fetchone()[0]
    aid = album(c, sid, a["album_key"], a["album"])
    return dict(database_id=d["id"], source_id=sid, album_id=aid, relative_path=relative, phone=a["source"], album=a["album"])


@router.post("/register", status_code=201)
def register(body: Confirm):
    with mutation_lock(), core.db() as c:
        c.execute("BEGIN IMMEDIATE")
        row, p = checked_preview(c, body, "register")
        if p.get('preview_kind') == 'directory_sample':
            try:
                from .source_preview import inspect
                structure=inspect(p['root'],p['exclusions'])
            except (ValueError,OSError,RuntimeError) as error:
                raise HTTPException(409,str(error)) from None
            root=Path(structure['root'])
            if str(root)!=p['root']:
                raise HTTPException(409,'Root changed since preview; preview again')
            # A complete directory listing can detect changed names. Partial
            # samples cannot assert the whole tree is unchanged; fixed layout
            # rules deliberately apply to unseen/new files at the first sync.
            if not p.get('preview_truncated') and (structure['inspection']['truncated'] or structure['evidence']!=row['evidence']):
                raise HTTPException(409,'Folder structure changed since preview; preview again')
        else:
            root = root_path(p["root"])
            try:
                files = walk(root, p["exclusions"], check_readable=True)
            except (OSError, RuntimeError) as e:
                raise HTTPException(409, str(e))
            if evidence(files) != row["evidence"]:
                raise HTTPException(409, "Files changed since preview; analyze again")
        validate_overlap(c, root)
        did = identity()
        c.execute("INSERT INTO library_databases(id,root,alias,layout,exclusions) VALUES(?,?,?,?,?)",
                  (did, p["root"], p["alias"], p["interpretation"], json.dumps(p["exclusions"])))
        ensure_sources(c, did, p["source_aliases"])
        c.execute("DELETE FROM library_previews WHERE id=?", (body.token,))
    return {"id": did, "registered": True, "indexed": False}


@router.post("/{did}/layout-confirm")
def confirm_layout(did: str, body: Confirm):
    with mutation_lock(), core.db() as c:
        from .advanced_layout import rules
        if rules(c,did) or c.execute("SELECT 1 FROM library_databases WHERE parent_id=?",(did,)).fetchone():
            raise HTTPException(409,"Use Advanced relayout for a Database with subtree layouts")
        c.execute("BEGIN IMMEDIATE")
        row, p = checked_preview(c, body, "layout", did)
        try:
            files = walk(root_path(p["root"]), p["exclusions"])
        except (OSError, RuntimeError) as e:
            raise HTTPException(409, str(e))
        if evidence(files) != row["evidence"]:
            raise HTTPException(409, "Files changed since preview; analyze again")
        d = get_database(c, did)
        d.update(layout=p["interpretation"], alias=p["alias"])
        c.execute("UPDATE library_sources SET active=0 WHERE database_id=?", (did,))
        ensure_sources(c, did, p["source_aliases"])
        for media in c.execute("SELECT id,relative_path FROM media WHERE database_id=?", (did,)).fetchall():
            if media["relative_path"]:
                a = assign_entry(c, d, media["relative_path"])
                c.execute("UPDATE media SET source_id=?,album_id=?,phone=?,album=? WHERE id=?",
                          (a["source_id"], a["album_id"], a["phone"], a["album"], media["id"]))
        c.execute("UPDATE library_databases SET layout=?,alias=?,exclusions=?,revision=revision+1 WHERE id=?",
                  (p["interpretation"], p["alias"], json.dumps(p["exclusions"]), did))
        c.execute("DELETE FROM library_previews WHERE id=?", (body.token,))
    return {"migrated": True, "annotations_preserved": True}


class Edit(BaseModel):
    alias: str | None = Field(default=None, min_length=1, max_length=200)
    visible: bool | None = None
    sync_enabled: bool | None = None
    schedule: dict | None = None

    @field_validator("alias")
    @classmethod
    def nonblank(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Alias must not be blank")
        return value.strip() if value else value


@router.patch("/{did}")
def edit_database(did: str, body: Edit):
    from .sync_service import Settings, next_due, now
    values = body.model_dump(exclude_unset=True)
    if "schedule" in values and values["schedule"] is not None:
        try:
            setting = Settings.model_validate(values["schedule"])
        except ValueError as e:
            raise HTTPException(422, str(e))
        values.update(schedule=setting.model_dump_json(), next_due=next_due(setting, now()))
    elif "schedule" in values:
        values["next_due"] = None
    if any(values[k] is None for k in ("alias", "visible", "sync_enabled") if k in values):
        raise HTTPException(422, "Alias and controls cannot be null")
    with mutation_lock(), core.db() as c:
        get_database(c, did)
        if values:
            c.execute("UPDATE library_databases SET " + ",".join(k + "=?" for k in values) + ",revision=revision+1 WHERE id=?", [*values.values(), did])
            c.execute("UPDATE catalogue_clock SET revision=revision+1 WHERE id=1")
    return {"saved": True}


@router.patch("/{did}/sources/{sid}")
def edit_source(did: str, sid: str, body: Edit):
    values = body.model_dump(exclude_unset=True)
    if "schedule" in values or any(v is None for v in values.values()):
        raise HTTPException(422, "Sources support alias, visibility and sync controls; schedules belong to Databases")
    with mutation_lock(), core.db() as c:
        source = c.execute("SELECT * FROM library_sources WHERE id=? AND database_id=?", (sid, did)).fetchone()
        if not source:
            raise HTTPException(404, "Source not found")
        if values:
            c.execute("UPDATE library_sources SET " + ",".join(k + "=?" for k in values) + " WHERE id=?", [*values.values(), sid])
        if "alias" in values:
            c.execute("UPDATE media SET phone=? WHERE source_id=?", (values["alias"], sid))
        c.execute("UPDATE library_databases SET revision=revision+1 WHERE id=?", (did,))
        c.execute("UPDATE catalogue_clock SET revision=revision+1 WHERE id=1")
    return {"saved": True}


def inventory_roots(did=None, global_scheduled=False):
    with core.db() as c:
        return [dict(r) for r in c.execute("SELECT * FROM library_databases WHERE sync_enabled=1" + (" AND id=?" if did else "") + (" AND schedule IS NULL" if global_scheduled else ""), (did,) if did else ())]


def inventory(did=None, control=lambda: None, global_scheduled=False, progress=lambda **kw: None, on_batch=None, checkpoint=None):
    roots = inventory_roots(did, global_scheduled)
    files = {}
    folders, found = checkpoint.prepare(roots) if checkpoint else (0, 0)
    if checkpoint:
        phase = "Rechecking folders after Database settings changed" if checkpoint.invalidated else "Continuing saved folder scan" if checkpoint.resumed else "Reading source folders"
        progress(phase=phase,folders_checked=folders,media_found=found)
    else:
        progress(folders_checked=folders,media_found=found)
    def walking_progress(**values):
        nonlocal folders,found
        folders+=values.pop("folders_delta",0)
        found+=values.pop("media_delta",0)
        progress(folders_checked=folders,media_found=found,**values)
    scopes = []
    for d in roots:
        root = Path(d["root"])
        with core.db() as c:
            sources = [dict(r) for r in c.execute("SELECT * FROM library_sources WHERE database_id=? AND active=1", (d["id"],))]
        from .advanced_layout import rules,effective_exclusions
        with core.db() as c:
            d["_source_rules"]=rules(c,d["id"])
            exclusions=effective_exclusions(c,d)
        enabled = {s["relative_path"] for s in sources if s["sync_enabled"]}
        # Legacy explicitly registered phone folders must all be available.
        required = [root / s["relative_path"] for s in sources if s["sync_enabled"] and s["relative_path"] and not excluded(s["relative_path"],exclusions)]
        try:
            from .network_access import ensure_access
            progress(current_folder=str(root),current_file="")
            ensure_access(root)
            if any(not p.is_dir() or p.is_symlink() or p.is_junction() for p in required):
                raise RuntimeError("Source unavailable: " + str(next(p for p in required if not p.is_dir() or p.is_symlink() or p.is_junction())))
            def map_batch(listed):
                control()
                batch={}
                with core.db() as c:
                    for f in listed:
                        progress(current_folder=str((root / f["relative"]).parent),current_file=Path(f["relative"]).name)
                        from .advanced_layout import resolve_assignment
                        a=resolve_assignment(c,d,f["relative"],{s["relative_path"]:s["alias"] for s in sources})
                        known=next((s for s in sources if s["relative_path"]==a["source_key"]),None)
                        if known and not known["sync_enabled"]:continue
                        if d["layout"]=="legacy" and a["source_key"] not in enabled:continue
                        info=assign_entry(c,d,f["relative"])
                        if not known and not c.execute("SELECT sync_enabled FROM library_sources WHERE id=?",(info["source_id"],)).fetchone()[0]:continue
                        p=root/f["relative"]
                        batch[str(p)]=dict(path=str(p),**info,name=p.name,extension=p.suffix.lower(),
                            kind="video" if p.suffix.lower() in VIDEOS else "photo",bytes=f["bytes"],mtime=f["mtime"])
                files.update(batch)
                if on_batch:on_batch(d,batch)
                return batch
            if checkpoint:
                files.update(checkpoint.walk(d,exclusions,control,walking_progress,map_batch))
            elif on_batch:
                walk(root,exclusions,control,progress=walking_progress,on_batch=map_batch)
            else:
                map_batch(walk(root,exclusions,control,progress=walking_progress))
            with core.db() as c:
                scopes.extend(s[0] for s in c.execute("SELECT id FROM library_sources WHERE database_id=? AND sync_enabled=1 AND active=1",(d["id"],)))
                c.execute("UPDATE library_databases SET availability='available',last_error=NULL WHERE id=?",(d["id"],))
        except (OSError, RuntimeError) as e:
            with core.db() as c:
                c.execute("UPDATE library_databases SET availability='unavailable',last_error=? WHERE id=?", (str(e), d["id"]))
            # A failure aborts this inventory before any missing records are changed.
            raise
    return Inventory(files, scopes, [(d["id"], d["root"]) for d in roots], resumed=bool(checkpoint and checkpoint.resumed))


class Inventory(dict):
    def __init__(self, files, scopes, roots, resumed=False):
        super().__init__(files)
        self.resumed = resumed
        self.scopes = scopes
        self.roots = roots


def verify_available(files):
    if isinstance(files, Inventory):
        if any(not Path(root).is_dir() for _, root in files.roots):
            raise RuntimeError("Source disconnected; catalogue not reconciled")
        with core.db() as c:
            for sid in files.scopes:
                row = c.execute("SELECT d.root,s.relative_path FROM library_sources s JOIN library_databases d ON d.id=s.database_id WHERE s.id=?", (sid,)).fetchone()
                if row and not (Path(row[0]) / row[1]).is_dir():
                    raise RuntimeError("Source disconnected; catalogue not reconciled")


def source_root(row):
    keys = row.keys()
    sid = row["source_id"] if "source_id" in keys else None
    # Old callers select only a subset of media columns.
    if not sid and "id" in keys:
        with core.db() as c:
            found = c.execute("SELECT source_id FROM media WHERE id=?", (row["id"],)).fetchone()
            sid = found[0] if found else None
    if sid:
        with core.db() as c:
            source = c.execute("SELECT d.root,s.relative_path FROM library_sources s JOIN library_databases d ON d.id=s.database_id WHERE s.id=?", (sid,)).fetchone()
        if source:
            root = Path(source["root"])
            from .network_access import ensure_access
            ensure_access(root)
            base = root / source["relative_path"]
            for p in (base, *base.parents):
                if p.is_relative_to(root) and (p.is_symlink() or p.is_junction()):
                    raise ValueError("Registered root must not traverse links")
            return base.resolve()
    if row["phone"] in core.PHONES:
        base = core.ROOT / row["phone"]
        if any(p.is_symlink() or p.is_junction() for p in (core.ROOT, base)):
            raise ValueError("Legacy root must not traverse links")
        return base.resolve()
    raise ValueError("Source not registered")


class Reconnect(BaseModel):
    root: str


def reconnect_evidence(c, did, root):
    entries = []
    rows = c.execute("SELECT * FROM media WHERE database_id=? AND status NOT IN ('superseded','missing','trashed')", (did,)).fetchall()
    for row in rows:
        relative = row["relative_path"]
        if not relative or ".." in PurePosixPath(relative).parts:
            raise HTTPException(409, "A catalogue entry lacks a safe relative path")
        p = root / relative
        if not p.is_file() or p.is_symlink() or not p.resolve().is_relative_to(root):
            raise HTTPException(409, "Reconnect root lacks matching file: " + relative)
        before = p.stat()
        if before.st_size != row["bytes"]:
            raise HTTPException(409, "Reconnect file differs: " + relative)
        old = Path(row["path"])
        expected = row["sha"]
        if not expected and old.is_file():
            with old.open("rb") as f:
                expected = hashlib.file_digest(f, "sha256").hexdigest()
        if not expected:
            raise HTTPException(409, "Cannot verify unhashed offline original: " + relative)
        with p.open("rb") as f:
            digest = hashlib.file_digest(f, "sha256").hexdigest()
        after = p.stat()
        if digest != expected or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise HTTPException(409, "Reconnect file differs or changed: " + relative)
        entries.append(dict(id=row["id"], relative=relative, sha=digest, bytes=after.st_size, mtime=after.st_mtime))
    # Trashed files must remain recoverable at the new root too.
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    d = get_database(c, did)
    if "duplicate_trash" in tables:
        for trash in c.execute("SELECT t.* FROM duplicate_trash t JOIN media m ON m.id=t.media_id WHERE m.database_id=? AND t.state='trashed'", (did,)):
            try:
                rel = Path(trash["trash"]).relative_to(d["root"])
            except ValueError:
                raise HTTPException(409, "Trash is outside the registered root")
            p = root / rel
            if not p.is_file() or not p.resolve().is_relative_to(root):
                raise HTTPException(409, "Reconnect must include recoverable trash: " + str(rel))
            with p.open("rb") as f:
                if hashlib.file_digest(f, "sha256").hexdigest() != trash["sha"]:
                    raise HTTPException(409, "Recoverable trash differs")
    return entries


@router.post("/{did}/reconnect-preview")
def reconnect_preview(did: str, body: Reconnect):
    from .sync_service import now
    root = root_path(body.root)
    if not root.is_dir():
        raise HTTPException(409, "Reconnect root unavailable")
    with mutation_lock(), core.db() as c:
        d = get_database(c, did)
        from . import advanced_reconnect
        if advanced_reconnect.needed(c,did):return advanced_reconnect.preview(c,did,root)
        validate_overlap(c, root, did)
        try:
            entries = reconnect_evidence(c, did, root)
        except OSError as e:
            raise HTTPException(409, str(e))
        token = identity()
        c.execute("INSERT INTO library_previews VALUES(?,?,?,?,?,?,?)", (token, "reconnect", did, json.dumps({"root": str(root)}), evidence(entries), d["revision"], now().isoformat()))
    return dict(token=token, old_root=d["root"], root=str(root), verified_media=len(entries), samples=entries[:20], annotations_preserved=True)


@router.post("/{did}/reconnect-confirm")
def reconnect_confirm(did: str, body: Confirm):
    with mutation_lock(), core.db() as c:
        c.execute("BEGIN IMMEDIATE")
        row, p = checked_preview(c, body, "reconnect", did)
        root = root_path(p["root"])
        if p.get("family"):
            from . import advanced_reconnect
            return advanced_reconnect.confirm(c,did,row,p)
        validate_overlap(c, root, did)
        d = get_database(c, did)
        try:
            entries = reconnect_evidence(c, did, root)
        except OSError as e:
            raise HTTPException(409, str(e))
        if evidence(entries) != row["evidence"]:
            raise HTTPException(409, "Reconnect files changed since preview")
        stats = {e["id"]: e for e in entries}
        for m in c.execute("SELECT id,path,relative_path FROM media WHERE database_id=?", (did,)).fetchall():
            if m["relative_path"] and not m["path"].startswith("archived://"):
                c.execute("UPDATE media SET path=? WHERE id=?", (str(root / m["relative_path"]), m["id"]))
            if m["id"] in stats:
                e = stats[m["id"]]
                c.execute("UPDATE media SET bytes=?,mtime=?,sha=? WHERE id=?", (e["bytes"], e["mtime"], e["sha"], m["id"]))
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "duplicate_trash" in tables:
            for t in c.execute("SELECT t.* FROM duplicate_trash t JOIN media m ON m.id=t.media_id WHERE m.database_id=?", (did,)).fetchall():
                paths = []
                for key in ("source", "trash"):
                    try:
                        paths.append(str(root / Path(t[key]).relative_to(d["root"])))
                    except ValueError:
                        raise HTTPException(409, "Trash history has an unexpected path")
                c.execute("UPDATE duplicate_trash SET source=?,trash=? WHERE media_id=?", (*paths, t["media_id"]))
        c.execute("UPDATE library_databases SET root=?,availability='available',last_error=NULL,revision=revision+1 WHERE id=?", (str(root), did))
        c.execute("DELETE FROM library_previews WHERE id=?", (body.token,))
    return {"reconnected": True, "annotations_preserved": True}


def removal_snapshot(c, did):
    media = [tuple(r) for r in c.execute("SELECT id,path,status FROM media WHERE database_id=? ORDER BY id", (did,))]
    faces = [tuple(r) for r in c.execute("SELECT f.id,f.person_id,f.status FROM faces f JOIN media m ON m.id=f.media_id WHERE m.database_id=? ORDER BY f.id", (did,))]
    overrides=[tuple(r) for r in c.execute('SELECT o.media_id,o.payload FROM media_overrides o JOIN media m ON m.id=o.media_id WHERE m.database_id=? ORDER BY o.media_id',(did,))]
    return dict(media=len(media), faces=len(faces), fingerprint=hashlib.sha256(json.dumps([media, faces,overrides]).encode()).hexdigest())


@router.post("/{did}/removal-preview")
def removal_preview(did: str):
    from .sync_service import now
    with mutation_lock(), core.db() as c:
        if c.execute("SELECT 1 FROM library_databases WHERE parent_id=?",(did,)).fetchone():
            raise HTTPException(409,"Remove or reconnect child Databases separately before removing their parent")
        d = get_database(c, did)
        counts = removal_snapshot(c, did)
        token = identity()
        payload = dict(alias=d["alias"], stage=1, **counts)
        c.execute("INSERT INTO library_previews VALUES(?,?,?,?,?,?,?)", (token, "remove", did, json.dumps(payload), counts["fingerprint"], d["revision"], now().isoformat()))
    return dict(token=token, **payload, originals_preserved=True, warning="Remove catalogue media, faces and their annotations. Original files and recoverable trash remain on disk.")


class RemoveConfirm(Confirm):
    typed_alias: str = ""


@router.post("/{did}/removal-first-confirm")
def removal_first(did: str, body: Confirm):
    with mutation_lock(), core.db() as c:
        row, p = checked_preview(c, body, "remove", did)
        if p["stage"] != 1:
            raise HTTPException(409, "First confirmation was already used")
        token = identity()
        p["stage"] = 2
        c.execute("INSERT INTO library_previews VALUES(?,?,?,?,?,?,?)", (token, "remove", did, json.dumps(p), row["evidence"], row["revision"], row["created"]))
        c.execute("DELETE FROM library_previews WHERE id=?", (body.token,))
    return dict(token=token, alias=p["alias"], media=p["media"], faces=p["faces"], final_confirmation_required=True)


@router.post("/{did}/removal-final-confirm")
def removal_final(did: str, body: RemoveConfirm):
    with mutation_lock(), core.db() as c:
        sync_path = core.database_dir() / "sync.sqlite"
        attached = sync_path.is_file()
        if attached:
            c.execute("ATTACH DATABASE ? AS sync_catalogue", (str(sync_path),))
        c.execute("BEGIN IMMEDIATE")
        row, p = checked_preview(c, body, "remove", did)
        if c.execute("SELECT 1 FROM library_databases WHERE parent_id=?",(did,)).fetchone():
            raise HTTPException(409,"A parent Database with children cannot be removed")
        if p["stage"] != 2 or body.typed_alias != p["alias"]:
            raise HTTPException(422, "Complete both confirmations and type the Database alias exactly")
        if removal_snapshot(c, did)["fingerprint"] != row["evidence"]:
            raise HTTPException(409, "Catalogue changed since removal preview; review again")
        c.execute("CREATE TEMP TABLE removed_media AS SELECT id FROM media WHERE database_id=?", (did,))
        c.execute("CREATE TEMP TABLE removed_faces AS SELECT id FROM faces WHERE media_id IN (SELECT id FROM removed_media)")
        if attached:
            if c.execute("SELECT 1 FROM sync_catalogue.sqlite_master WHERE name='work'").fetchone():
                c.execute("DELETE FROM sync_catalogue.work WHERE media_id IN (SELECT id FROM removed_media)")
            if c.execute("SELECT 1 FROM sync_catalogue.sqlite_master WHERE name='file_hashes'").fetchone():
                prefix=get_database(c,did)['root'].rstrip("\\/")+os.sep
                c.execute("DELETE FROM sync_catalogue.file_hashes WHERE substr(path,1,?)=?",(len(prefix),prefix))
            for table in ("discovery_files", "discovery_folders", "discovery_roots"):
                if c.execute("SELECT 1 FROM sync_catalogue.sqlite_master WHERE name=?",(table,)).fetchone():
                    c.execute(f"DELETE FROM sync_catalogue.{table} WHERE database_id=?",(did,))
            if c.execute("SELECT 1 FROM sync_catalogue.sqlite_master WHERE name='streaming_roots'").fetchone():
                c.execute("DELETE FROM sync_catalogue.streaming_roots WHERE database_id=?",(did,))
            if c.execute("SELECT 1 FROM sync_catalogue.sqlite_master WHERE name='runs'").fetchone():
                c.execute("UPDATE sync_catalogue.runs SET state='cancelled',error='Database removed from catalogue' WHERE json_extract(progress,'$.database_id')=?", (did,))
        # Discover every FK-dependent annotation table; fail atomically if a future
        # schema adds a dependency we cannot delete, rather than disabling FKs.
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in tables:
            if table in ("media", "faces"):
                continue
            for fk in c.execute(f'PRAGMA foreign_key_list("{table}")').fetchall():
                target = {"faces": "removed_faces", "media": "removed_media"}.get(fk[2])
                if target:
                    c.execute(f'DELETE FROM "{table}" WHERE "{fk[3]}" IN (SELECT id FROM {target})')
        for table, column in (("sync_missing", "media_id"), ("duplicate_trash", "media_id"), ("sync_versions", "old_id"), ("sync_versions", "new_id")):
            if table in tables:
                c.execute(f'DELETE FROM "{table}" WHERE "{column}" IN (SELECT id FROM removed_media)')
        mids = {r[0] for r in c.execute("SELECT id FROM removed_media")}
        fids = {r[0] for r in c.execute("SELECT id FROM removed_faces")}
        # Invalidate only undo batches and duplicate plans touching deleted rows.
        def references(value):
            if isinstance(value, dict):
                return any(references(v) for v in value.values())
            if isinstance(value, list):
                return any(references(v) for v in value)
            return isinstance(value, str) and value in mids | fids
        def prune(value):
            if isinstance(value, dict):
                return {k: prune(v) for k, v in value.items()}
            if isinstance(value, list):
                return [prune(v) for v in value if not (isinstance(v, str) and v in mids | fids)
                        and not (isinstance(v, dict) and (v.get("id") in mids | fids or v.get("media_id") in mids))]
            return value
        for preview in c.execute('SELECT id,payload FROM metadata_previews').fetchall():
            if references(json.loads(preview['payload'])):
                c.execute('DELETE FROM metadata_previews WHERE id=?',(preview['id'],))
        for a in c.execute("SELECT id,previous FROM actions").fetchall():
            previous = json.loads(a["previous"] or "{}")
            if references(previous):
                kept = prune(previous)
                if any(v for v in kept.values() if isinstance(v, (list, dict))):
                    c.execute("UPDATE actions SET previous=? WHERE id=?", (json.dumps(kept), a["id"]))
                else:
                    c.execute("DELETE FROM actions WHERE id=?", (a["id"],))
        if "duplicate_groups" in tables:
            for g in c.execute("SELECT id,keeper,members FROM duplicate_groups").fetchall():
                if g["keeper"] in mids or references(json.loads(g["members"])):
                    if "duplicate_rules" in tables:
                        c.execute("DELETE FROM duplicate_rules WHERE group_id=?", (g["id"],))
                    c.execute("DELETE FROM duplicate_groups WHERE id=?", (g["id"],))
        c.execute("DELETE FROM faces WHERE id IN (SELECT id FROM removed_faces)")
        c.execute("DELETE FROM media WHERE id IN (SELECT id FROM removed_media)")
        c.execute("DELETE FROM library_albums WHERE source_id IN (SELECT id FROM library_sources WHERE database_id=?)", (did,))
        c.execute("DELETE FROM library_sources WHERE database_id=?", (did,))
        c.execute("DELETE FROM library_previews WHERE database_id=?", (did,))
        c.execute("DELETE FROM library_databases WHERE id=?", (did,))
        c.execute("UPDATE catalogue_clock SET revision=revision+1 WHERE id=1")
    # Derivative files are intentionally retained; this operation never touches files.
    return {"removed_media": p["media"], "removed_faces": p["faces"], "originals_preserved": True}


@router.post("/{did}/sync", status_code=202)
def sync_database(did: str):
    from .sync_service import start_run
    with core.db() as c:
        d = get_database(c, did)
        if not d["sync_enabled"]:
            raise HTTPException(409, "Resume database syncing before Sync now")
    return start_run(database_id=did)
