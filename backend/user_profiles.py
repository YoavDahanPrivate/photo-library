"""Preferences and activity for authenticated accounts."""
import json
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from .core import db

router = APIRouter(prefix='/api/profiles', tags=['profiles'])
NAMES = ('Yoav', 'Hila', 'Bar', 'Rotem', 'Guy', 'Drora', 'Guest')

def now():
    return datetime.now(timezone.utc).isoformat()

def migrate(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS user_profiles(
      id TEXT PRIMARY KEY, name TEXT NOT NULL, theme TEXT NOT NULL DEFAULT 'sage',
      source_ids TEXT, source_names TEXT, last_login_at TEXT, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS user_people_preferences(
      profile_id TEXT PRIMARY KEY REFERENCES user_profiles(id), preferences TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS user_activity(
      id INTEGER PRIMARY KEY, profile_id TEXT NOT NULL REFERENCES user_profiles(id),
      kind TEXT NOT NULL, occurred_at TEXT NOT NULL, details TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS user_activity_profile_time ON user_activity(profile_id,id DESC);
    ''')
    # Multi-selection is temporary UI state, including for previously saved choices.
    c.execute("UPDATE user_people_preferences SET preferences=json_remove(preferences,'$.selection') "
              "WHERE json_valid(preferences) AND json_type(preferences,'$.selection') IS NOT NULL")
    c.executemany('INSERT OR IGNORE INTO user_profiles(id,name,created_at) VALUES(?,?,?)',
                  [(name.lower(), name, now()) for name in NAMES])

def record(c, profile_id, kind, details):
    if not c.execute('SELECT 1 FROM user_profiles WHERE id=?', (profile_id,)).fetchone():
        raise HTTPException(404, 'Profile not found')
    c.execute('INSERT INTO user_activity(profile_id,kind,occurred_at,details) VALUES(?,?,?,?)',
              (profile_id, kind, now(), json.dumps(details, ensure_ascii=False)))

def profile(c, identity):
    row = c.execute('SELECT * FROM user_profiles WHERE id=?', (identity,)).fetchone()
    if not row:
        raise HTTPException(404, 'Profile not found')
    result = dict(row)
    for key in ('source_ids', 'source_names'):
        result[key] = json.loads(result[key]) if result[key] is not None else None
    saved = c.execute('SELECT preferences FROM user_people_preferences WHERE profile_id=?', (identity,)).fetchone()
    result['people_browse'] = json.loads(saved['preferences']) if saved else None
    return result

@router.get('')
def list_profiles():
    with db() as c:
        return [dict(r) for r in c.execute('SELECT id,name,last_login_at FROM user_profiles ORDER BY rowid')]

@router.post('/{identity}/select')
def select_profile(identity: str):
    with db() as c:
        profile(c, identity)
        return profile(c, identity)

class Preferences(BaseModel):
    theme: Literal['sage','ocean','plum','black','dark','white']
    source_ids: list[str] = Field(max_length=1000)
    source_names: list[str] = Field(max_length=1000)

@router.put('/{identity}/preferences')
def save_preferences(identity: str, body: Preferences):
    if any(len(s)>300 for s in body.source_ids+body.source_names):
        raise HTTPException(422, 'Source identifier is too long')
    with db() as c:
        profile(c, identity)
        c.execute('UPDATE user_profiles SET theme=?,source_ids=?,source_names=? WHERE id=?',
                  (body.theme, json.dumps(list(dict.fromkeys(body.source_ids))), json.dumps(list(dict.fromkeys(body.source_names))), identity))
        return profile(c, identity)

class PeopleDirections(BaseModel):
    name: Literal['asc','desc'] = 'asc'
    count: Literal['asc','desc'] = 'desc'

class PeoplePreferences(BaseModel):
    known: bool = True
    unknown: bool = False
    action: Literal["search", "edit"] = "search"
    sort: Literal['name','count'] = 'count'
    directions: PeopleDirections = Field(default_factory=PeopleDirections)

@router.put('/{identity}/people-preferences')
def save_people_preferences(identity: str, body: PeoplePreferences):
    if not body.known and not body.unknown:
        raise HTTPException(422, 'Show at least one group of people')
    with db() as c:
        profile(c, identity)
        c.execute('INSERT INTO user_people_preferences(profile_id,preferences) VALUES(?,?) '
                  'ON CONFLICT(profile_id) DO UPDATE SET preferences=excluded.preferences',
                  (identity, json.dumps(body.model_dump())))
        return profile(c, identity)

class SearchEvent(BaseModel):
    expression: str = Field(max_length=4000)
    source_names: list[str] = Field(default_factory=list, max_length=1000)

@router.post('/{identity}/searches')
def record_search(identity: str, body: SearchEvent):
    with db() as c:
        record(c, identity, 'search', body.model_dump())
    return {'ok': True}

@router.get('/{identity}/activity')
def activity(identity: str):
    with db() as c:
        profile(c, identity)
        return [{**dict(row), 'details': json.loads(row['details'])} for row in c.execute(
            'SELECT id,kind,occurred_at,details FROM user_activity WHERE profile_id=? ORDER BY id DESC LIMIT 100', (identity,))]

def record_download(identity, media_id, file_kind):
    with db() as c:
        record(c, identity, 'download_requested', {'media_id': media_id, 'format': file_kind})
