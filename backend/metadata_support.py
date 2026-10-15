"""Catalogue-only date/location corrections, reviewed bulk edits, and provenance.

Embedded values are retained separately. Effective media values keep existing
search/map clients compatible. No operation here writes an original file.
"""
import calendar
import hashlib
import json
import math
import re
import uuid
from datetime import date, datetime, timezone, timedelta
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from . import core

router = APIRouter(prefix="/api/metadata", tags=["Metadata"])
DATE_LOW = "capture_low(m.taken)"
DATE_HIGH = "capture_high(coalesce((SELECT json_extract(mo.payload,'$.date.end') FROM media_overrides mo WHERE mo.media_id=m.id),m.taken))"
NO_GPS = "NOT coalesce((m.latitude BETWEEN -90 AND 90 AND m.longitude BETWEEN -180 AND 180),0)"
UNKNOWN = NO_GPS + " AND NOT EXISTS(SELECT 1 FROM media_places up WHERE up.media_id=m.id AND (up.country_id IS NOT NULL OR up.city_id IS NOT NULL))"


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def bounds(value):
    if not value:
        return None, None
    try:
        from .search_dates import period
        return period(str(value)[:10])
    except (ValueError, TypeError):
        return None, None


def migrate(c):
    c.executescript("""
      CREATE TABLE IF NOT EXISTS media_original_metadata(
        media_id TEXT PRIMARY KEY REFERENCES media(id) ON DELETE CASCADE,
        taken TEXT,latitude REAL,longitude REAL,file_created REAL,file_modified REAL,
        imported_at TEXT,places TEXT);
      CREATE TABLE IF NOT EXISTS media_overrides(
        media_id TEXT PRIMARY KEY REFERENCES media(id) ON DELETE CASCADE,
        payload TEXT NOT NULL,updated_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS metadata_previews(
        id TEXT PRIMARY KEY,payload TEXT NOT NULL,evidence TEXT NOT NULL,created TEXT NOT NULL);
    """)
    for event in ("INSERT", "UPDATE", "DELETE"):
        c.execute(f"CREATE TRIGGER IF NOT EXISTS clock_overrides_{event} AFTER {event} ON media_overrides BEGIN UPDATE catalogue_clock SET revision=revision+1 WHERE id=1; END")


def payload(c, mid):
    row = c.execute("SELECT payload FROM media_overrides WHERE media_id=?", (mid,)).fetchone()
    return json.loads(row[0]) if row else {}


def remember_original(c, row):
    places = c.execute("SELECT * FROM media_places WHERE media_id=?", (row['id'],)).fetchone()
    c.execute("INSERT OR IGNORE INTO media_original_metadata(media_id,taken,latitude,longitude,file_modified,places) VALUES(?,?,?,?,?,?)",
              (row['id'], row['taken'], row['latitude'], row['longitude'], row['mtime'], json.dumps(dict(places)) if places else None))


def record_embedded(c, mid, info, stat):
    """Called inside the indexing transaction, before exposing effective values."""
    c.execute("""INSERT INTO media_original_metadata(media_id,taken,latitude,longitude,file_created,file_modified,imported_at)
        VALUES(?,?,?,?,?,?,?) ON CONFLICT(media_id) DO UPDATE SET taken=excluded.taken,
        latitude=excluded.latitude,longitude=excluded.longitude,file_created=excluded.file_created,
        file_modified=excluded.file_modified,imported_at=coalesce(media_original_metadata.imported_at,excluded.imported_at),places=NULL""",
        (mid, info['taken'], info['latitude'], info['longitude'], getattr(stat, 'st_birthtime', None), stat.st_mtime, timestamp()))
    materialize(c, mid)


def manual_place(c, location):
    pid = location.get('place_id')
    if pid:
        place = c.execute("SELECT * FROM geographic_places WHERE id=?", (pid,)).fetchone()
        if place is None:
            raise HTTPException(409, "Saved place no longer exists; preview the edit again")
        country = pid if place['kind'] == 'country' else None
        if place['kind'] != 'country' and place['country']:
            r = c.execute("SELECT id FROM geographic_places WHERE kind='country' AND label=?", (place['country'],)).fetchone()
            country = r[0] if r else None
        return country, pid if place['kind'] != 'country' else None
    label = location.get('label', '').strip()
    if label:
        pid = 'manual:' + hashlib.sha256(label.casefold().encode()).hexdigest()[:24]
        c.execute("INSERT OR IGNORE INTO geographic_places VALUES(?,?, 'city','',NULL,NULL,?)", (pid, label, label.casefold()))
        return None, pid
    return None, None


def materialize(c, mid):
    raw = c.execute("SELECT * FROM media_original_metadata WHERE media_id=?", (mid,)).fetchone()
    if raw is None:
        return
    override = payload(c, mid)
    taken = override.get('date', {}).get('value', raw['taken'])
    loc = override.get('location')
    lat, lon = (loc.get('latitude'), loc.get('longitude')) if loc is not None else (raw['latitude'], raw['longitude'])
    c.execute("UPDATE media SET taken=?,latitude=?,longitude=? WHERE id=?", (taken, lat, lon, mid))
    c.execute("DELETE FROM media_places WHERE media_id=?", (mid,))
    if loc is not None:
        country, city = manual_place(c, loc)
        c.execute("INSERT INTO media_places VALUES(?,?,?,?,?)", (mid, country, city, None, 'manual-location-v1'))
    elif raw['places']:
        p = json.loads(raw['places'])
        c.execute("INSERT INTO media_places VALUES(?,?,?,?,?)", (mid, p['country_id'], p['city_id'], p['distance_km'], p['version']))


def preserve_location(c, mid):
    """Reapply a manual place after automatic enrichment."""
    loc = payload(c, mid).get('location')
    if loc is None:
        p=c.execute('SELECT * FROM media_places WHERE media_id=?',(mid,)).fetchone()
        if p:
            c.execute('UPDATE media_original_metadata SET places=? WHERE media_id=?',(json.dumps(dict(p)),mid))
    if loc is not None and (loc.get('label') or loc.get('place_id')):
        country, city = manual_place(c, loc)
        c.execute("INSERT OR REPLACE INTO media_places VALUES(?,?,?,?,?)", (mid, country, city, None, 'manual-location-v1'))


def details(c, mid):
    row = c.execute("SELECT taken,latitude,longitude,mtime,metadata FROM media WHERE id=?", (mid,)).fetchone()
    raw = c.execute("SELECT * FROM media_original_metadata WHERE media_id=?", (mid,)).fetchone()
    override = payload(c, mid)
    manual_date = override.get('date')
    loc = override.get('location')
    tags=json.loads(row['metadata'] or '{}')
    embedded_field=next((key for key in ('DateTimeOriginal','DateTimeDigitized','DateTime') if tags.get(key)),None)
    if embedded_field is None and 'ffmpeg_probe' in tags:embedded_field='Video creation_time'
    return dict(
        embedded_date_field=embedded_field,
        date_source='manual' if manual_date else ('embedded' if row['taken'] else 'unknown'),
        date_precision=('range' if manual_date.get('end') else {4:'year',7:'month',10:'day'}.get(len(manual_date['value']), 'datetime')) if manual_date else ('datetime' if row['taken'] and len(row['taken']) > 10 else 'day' if row['taken'] else 'unknown'),
        date_end=manual_date.get('end') if manual_date else None,
        date_approximate=manual_date.get('approximate', False) if manual_date else False,
        location_source='manual' if loc else ('embedded' if row['latitude'] is not None and row['longitude'] is not None else 'unknown'),
        location_precision=('point' if loc.get('latitude') is not None else 'place') if loc else ('point' if row['latitude'] is not None and row['longitude'] is not None else 'unknown'),
        location_label=loc.get('label') if loc else None,
        embedded_taken=raw['taken'] if raw else row['taken'],
        embedded_latitude=raw['latitude'] if raw else row['latitude'],
        embedded_longitude=raw['longitude'] if raw else row['longitude'],
        file_created=raw['file_created'] if raw else None,
        file_modified=raw['file_modified'] if raw else row['mtime'],
        imported_at=raw['imported_at'] if raw else None,
        metadata_override=override,
    )


class DateEdit(BaseModel):
    model_config = ConfigDict(extra='forbid')
    value: str = Field(max_length=10)
    end: str | None = Field(default=None, max_length=10)
    approximate: bool = False

    @model_validator(mode='after')
    def valid(self):
        if not re.fullmatch(r'\d{4}(?:-\d{2}){0,2}', self.value):
            raise ValueError('Use YYYY, YYYY-MM or YYYY-MM-DD')
        low, high = bounds(self.value)
        if low is None:
            raise ValueError('Invalid capture date')
        if self.end:
            if not re.fullmatch(r'\d{4}(?:-\d{2}){0,2}', self.end) or bounds(self.end)[0] is None or bounds(self.end)[1] < low:
                raise ValueError('Invalid or reversed date range')
        return self


class LocationEdit(BaseModel):
    model_config = ConfigDict(extra='forbid')
    label: str = Field(default='', max_length=200)
    place_id: str | None = Field(default=None, max_length=100)
    latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)

    @model_validator(mode='after')
    def valid(self):
        self.label = self.label.strip()
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError('Provide both latitude and longitude')
        if not self.label and not self.place_id and self.latitude is None:
            raise ValueError('Choose a place, enter a place name, or provide coordinates')
        return self


class Edit(BaseModel):
    model_config = ConfigDict(extra='forbid')
    media_ids: list[str] = Field(default_factory=list, max_length=5000)
    date: DateEdit | None = None
    location: LocationEdit | None = None
    mode: Literal['fill_missing', 'replace'] = 'fill_missing'
    restore: Literal['date', 'location', 'both'] | None = None

    @model_validator(mode='after')
    def valid(self):
        if self.restore and (self.date or self.location):
            raise ValueError('Restore cannot be combined with new values')
        if not (self.date or self.location or self.restore):
            raise ValueError('Choose a date or location to edit')
        return self


def new_payload(c, row, edit):
    old = payload(c, row['id'])
    updated = dict(old)
    if edit.restore:
        if edit.restore in ('both', 'date'): updated.pop('date', None)
        if edit.restore in ('both', 'location'): updated.pop('location', None)
    if edit.date and (edit.mode == 'replace' or not row['taken']):
        updated['date'] = edit.date.model_dump(exclude_none=True)
    if edit.location:
        known = row['latitude'] is not None and row['longitude'] is not None and -90 <= row['latitude'] <= 90 and -180 <= row['longitude'] <= 180
        known = known or bool(c.execute("SELECT 1 FROM media_places WHERE media_id=? AND (country_id IS NOT NULL OR city_id IS NOT NULL)", (row['id'],)).fetchone())
        if edit.mode == 'replace' or not known:
            loc = edit.location.model_dump(exclude_none=True)
            if loc.get('place_id'):
                p = c.execute('SELECT label FROM geographic_places WHERE id=?', (loc['place_id'],)).fetchone()
                if not p: raise HTTPException(422, 'Choose an existing place or enter a place name')
                loc['label'] = p[0]
            updated['location'] = loc
    return old, updated


def evidence(c, ids):
    digest = hashlib.sha256()
    rows = []
    for start in range(0, len(ids), 500):
        part = ids[start:start+500]
        rows.extend(c.execute('SELECT m.id,m.taken,m.latitude,m.longitude,m.status,o.payload,(SELECT country_id FROM media_places WHERE media_id=m.id),(SELECT city_id FROM media_places WHERE media_id=m.id) FROM media m LEFT JOIN media_overrides o ON o.media_id=m.id WHERE m.id IN ('+','.join('?' for _ in part)+') ORDER BY m.id', part).fetchall())
    for row in sorted(rows, key=lambda r:r['id']):
        digest.update(json.dumps(tuple(row), ensure_ascii=False).encode())
    return digest.hexdigest()


def register_routes(media_filters):
    router.routes[:]=[r for r in router.routes if r.path!='/api/metadata/preview']
    @router.post('/preview')
    def preview(edit: Edit, filters=Depends(media_filters)):
        from .source_management import VISIBLE
        where, args = filters
        if edit.media_ids:
            ids = sorted(set(edit.media_ids))
            where = "m.status='ready' AND " + VISIBLE + ' AND m.id IN ('+','.join('?' for _ in ids)+')'
            args = ids
        with core.db() as c:
            c.execute('BEGIN IMMEDIATE')
            rows = c.execute('SELECT m.* FROM media m WHERE '+where+' ORDER BY m.id', args).fetchall()
            if edit.media_ids and len(rows) != len(set(edit.media_ids)):
                raise HTTPException(409, 'Some selected media are unavailable or hidden; refresh the selection')
            if len(rows) > 100000:
                raise HTTPException(422, 'Narrow this edit to at most 100,000 media')
            changed, samples = [], []
            for row in rows:
                before, after = new_payload(c, row, edit)
                if before != after:
                    changed.append(row['id'])
                    if len(samples) < 12:
                        raw=c.execute('SELECT taken,latitude,longitude FROM media_original_metadata WHERE media_id=?',(row['id'],)).fetchone()
                        raw_taken=raw['taken'] if raw else row['taken']
                        current_place=c.execute("SELECT coalesce(city.label,country.label) FROM media_places mp LEFT JOIN geographic_places city ON city.id=mp.city_id LEFT JOIN geographic_places country ON country.id=mp.country_id WHERE media_id=?",(row['id'],)).fetchone()
                        after_taken=after.get('date',{}).get('value',raw_taken)
                        after_loc=after.get('location')
                        description=(after_loc.get('label') or 'Manual point') if after_loc else (current_place[0] if current_place and not edit.restore else 'Embedded GPS' if (raw['latitude'] if raw else row['latitude']) is not None else 'Unknown')
                        samples.append(dict(id=row['id'],name=row['name'],source=row['phone'],album=row['album'],before=details(c,row['id']),taken=row['taken'],after=after,after_taken=after_taken,after_location=description))
            token = uuid.uuid4().hex
            data = dict(edit=edit.model_dump(), ids=changed)
            c.execute('DELETE FROM metadata_previews WHERE created<?', ((datetime.now(timezone.utc)-timedelta(hours=1)).isoformat(),))
            c.execute('INSERT INTO metadata_previews VALUES(?,?,?,?)', (token,json.dumps(data),evidence(c,changed),timestamp()))
        return dict(token=token,matched=len(rows),changed=len(changed),skipped=len(rows)-len(changed),samples=samples,originals_preserved=True)


class Confirm(BaseModel):
    token: str
    confirm: bool = False


@router.post('/confirm')
def confirm(body: Confirm):
    from .source_management import VISIBLE
    if not body.confirm:
        raise HTTPException(422, 'Confirm the reviewed metadata preview')
    with core.db() as c:
        c.execute('BEGIN IMMEDIATE')
        p = c.execute('SELECT * FROM metadata_previews WHERE id=?', (body.token,)).fetchone()
        if not p or datetime.fromisoformat(p['created']) < datetime.now(timezone.utc)-timedelta(hours=1):
            raise HTTPException(409, 'Preview expired or already used; preview again')
        data = json.loads(p['payload'])
        if evidence(c, data['ids']) != p['evidence']:
            raise HTTPException(409, 'Metadata changed since preview; preview again')
        edit = Edit.model_validate(data['edit'])
        previous = []
        for mid in data['ids']:
            row = c.execute("SELECT m.* FROM media m WHERE id=? AND m.status='ready' AND "+VISIBLE, (mid,)).fetchone()
            if row is None: raise HTTPException(409, 'Media was removed or hidden; preview again')
            before, after = new_payload(c, row, edit)
            remember_original(c, row)
            previous.append(dict(id=mid,before=before,after=after))
            if after:
                c.execute('INSERT OR REPLACE INTO media_overrides VALUES(?,?,?)', (mid,json.dumps(after),timestamp()))
            else:
                c.execute('DELETE FROM media_overrides WHERE media_id=?', (mid,))
            materialize(c, mid)
        if previous:
            action = c.execute('INSERT INTO actions(description,previous) VALUES(?,?)', ('Date/location edit for '+str(len(previous))+' media',json.dumps({'metadata':previous}))).lastrowid
        else: action = None
        c.execute('DELETE FROM metadata_previews WHERE id=?', (body.token,))
    return dict(changed=len(previous),action_id=action,originals_preserved=True)


def undo(c, previous):
    # All validations precede writes. Retain raw metadata refreshed by a rescan.
    for item in previous:
        if payload(c,item['id']) != item['after']:
            raise HTTPException(409, 'A newer metadata edit exists; undo that edit first')
    for item in previous:
        if not c.execute('SELECT 1 FROM media WHERE id=?',(item['id'],)).fetchone():
            continue
        if item['before']:
            c.execute('INSERT OR REPLACE INTO media_overrides VALUES(?,?,?)',(item['id'],json.dumps(item['before']),timestamp()))
        else:
            c.execute('DELETE FROM media_overrides WHERE media_id=?',(item['id'],))
        materialize(c,item['id'])


@router.get('/history')
def history():
    with core.db() as c:
        return [dict(r) for r in c.execute("SELECT id,description,created FROM actions WHERE undone=0 AND json_type(previous,'$.metadata')='array' ORDER BY id DESC LIMIT 20")]


@router.post('/undo/{action_id}')
def undo_action(action_id:int):
    with core.db() as c:
        c.execute('BEGIN IMMEDIATE')
        a = c.execute('SELECT * FROM actions WHERE id=? AND undone=0',(action_id,)).fetchone()
        if not a or 'metadata' not in json.loads(a['previous']): raise HTTPException(409,'This metadata change is no longer available to undo')
        undo(c,json.loads(a['previous'])['metadata'])
        c.execute('UPDATE actions SET undone=1 WHERE id=?',(action_id,))
    return dict(ok=True)


def file_report(root, files, limit=200):
    """Read metadata headers only; representative sampling is stated explicitly."""
    from .indexer import IMAGES, ff
    from pathlib import Path
    from PIL import Image
    counts = dict(capture_date=0,gps=0,file_date_only=0,no_metadata=0,unreadable=0)
    chosen = files if len(files)<=limit else [files[i*len(files)//limit] for i in range(limit)]
    examples=[]
    for f in chosen:
        p=root/f['relative']; taken=None; lat=lon=None; has_tags=False; error=None
        try:
            if p.suffix.lower() in IMAGES:
                with Image.open(p) as im:
                    exif=im.getexif(); tags=dict(exif)
                    try: tags.update(exif.get_ifd(34665))
                    except Exception: pass
                    has_tags=bool(tags)
                    for key in (36867,36868,306):
                        try: taken=datetime.strptime(str(tags[key])[:19],'%Y:%m:%d %H:%M:%S').isoformat();break
                        except (KeyError,ValueError): pass
                    try:
                        gps=exif.get_ifd(34853)
                        def deg(v): return float(v[0])+float(v[1])/60+float(v[2])/3600
                        lat=deg(gps[2])*(-1 if gps.get(1)=='S' else 1);lon=deg(gps[4])*(-1 if gps.get(3)=='W' else 1)
                    except (KeyError,TypeError,ValueError,ZeroDivisionError): pass
            else:
                text=ff(['-i',str(p)],5).stderr.decode(errors='replace')
                d=re.search(r'creation_time\s*:\s*(\S+)',text)
                taken=d[1] if d else None
                g=re.search(r'(?:location(?:-eng)?|com.apple.quicktime.location.ISO6709)\s*:\s*([+-]\d+\.\d+)([+-]\d+\.\d+)',text)
                if g:lat,lon=map(float,g.groups())
                has_tags=bool(d or g)
            counts['capture_date']+=bool(taken)
            counts['gps']+=lat is not None and lon is not None and -90<=lat<=90 and -180<=lon<=180
            counts['file_date_only']+=not taken and bool(f.get('mtime'))
            counts['no_metadata']+=not has_tags
        except Exception:
            counts['unreadable']+=1;error='Metadata could not be read; indexing will report decoder errors'
        if len(examples)<12:
            years=re.findall(r'(?<!\d)(?:18|19|20)\d{2}(?!\d)',f['relative'])
            examples.append(dict(relative=f['relative'],capture_date=taken,gps=lat is not None and lon is not None,file_modified=f['mtime'],suggested_year=years[0] if len(set(years))==1 else None,error=error))
    return dict(total_files=len(files),inspected=len(chosen),sampled=len(chosen)<len(files),counts=counts,examples=examples,
                note='Counts describe the inspected sample. File dates are filesystem timestamps, never assumed capture dates. Folder-year suggestions require confirmation.')
