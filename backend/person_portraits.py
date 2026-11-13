"""Person display portraits, independent of recognition and face assignments."""
import json

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field
from . import core, cache_images

router = APIRouter(prefix='/api/people', tags=['Person portraits'])


def eligible():
    from .source_management import VISIBLE
    return ("f.status!='dismissed' AND m.status='ready' AND " + VISIBLE +
            " AND NOT EXISTS(SELECT 1 FROM unknown_faces u WHERE u.face_id=f.id)")


def decorate(c, rows):
    """Both People and name tools resolve the same saved portrait choice."""
    chosen = {r['person_id']: r['face_id'] for r in c.execute(
        "SELECT pp.person_id,pp.face_id FROM person_portraits pp "
        "JOIN faces f ON f.id=pp.face_id AND f.person_id=pp.person_id "
        "JOIN media m ON m.id=f.media_id WHERE " + eligible())}
    for row in rows:
        row['portrait_custom'] = row['id'] in chosen
        if row['portrait_custom']:
            row['cover'] = chosen[row['id']]
    return rows


def person_row(c, person):
    row = c.execute('SELECT id,name FROM people WHERE id=?',(person,)).fetchone()
    if row is None:
        raise HTTPException(404,'Person not found')
    return dict(row)


def current(c, person):
    row = person_row(c,person)
    row['automatic_cover'] = row['cover'] = c.execute('SELECT min(f.id) FROM faces f JOIN media m ON m.id=f.media_id '
                             'WHERE f.person_id=? AND '+eligible(),(person,)).fetchone()[0]
    return decorate(c,[row])[0]


@router.get('/{person}/portrait')
def choices(person: int = Path(ge=1), offset: int = Query(0,ge=0), limit: int = Query(30,ge=1,le=100)):
    with core.db() as c:
        identity = current(c,person)
        where = 'f.person_id=? AND '+eligible()
        total = c.execute('SELECT count(*) FROM faces f JOIN media m ON m.id=f.media_id WHERE '+where,(person,)).fetchone()[0]
        items = [dict(row) for row in c.execute(
            'SELECT f.id,f.media_id,f.timestamp,m.name,m.kind,m.taken FROM faces f '
            'JOIN media m ON m.id=f.media_id WHERE '+where+
            ' ORDER BY m.taken IS NULL,m.taken DESC,f.id LIMIT ? OFFSET ?',
            (person,limit,offset))]
        for item in items:
            item['available'] = cache_images.exists('faces/'+item['id']+'.jpg')
    return dict(person=identity,total=total,offset=offset,limit=limit,items=items)


class PortraitChoice(BaseModel):
    face_id: str | None = Field(...,min_length=1,max_length=240)


@router.post('/{person}/portrait')
def choose(person: int, body: PortraitChoice):
    if person <= 0:
        raise HTTPException(422,'Choose an individual person, not a shared unknown bucket')
    with core.db() as c:
        c.execute('BEGIN IMMEDIATE')
        person_row(c,person)
        if body.face_id is not None:
            valid = c.execute('SELECT f.id FROM faces f JOIN media m ON m.id=f.media_id '
                              'WHERE f.id=? AND f.person_id=? AND '+eligible(),(body.face_id,person)).fetchone()
            if not valid:
                raise HTTPException(409,'That face is no longer available for this person. Refresh the portrait choices.')
            if not cache_images.exists('faces/'+body.face_id+'.jpg'):
                raise HTTPException(409,'This face preview is unavailable. Choose another portrait.')
        previous = c.execute('SELECT face_id FROM person_portraits WHERE person_id=?',(person,)).fetchone()
        old = previous[0] if previous else None
        if old != body.face_id:
            c.execute('INSERT INTO actions(description,previous) VALUES(?,?)',
                      ('Change person portrait',json.dumps({'portrait':{'person_id':person,'face_id':old}})))
            if body.face_id is None:
                c.execute('DELETE FROM person_portraits WHERE person_id=?',(person,))
            else:
                c.execute('INSERT OR REPLACE INTO person_portraits VALUES(?,?)',(person,body.face_id))
        return current(c,person)


def undo(c, previous):
    person, face = previous['person_id'],previous['face_id']
    person_row(c,person)
    if face is not None and c.execute('SELECT 1 FROM faces WHERE id=?',(face,)).fetchone():
        c.execute('INSERT OR REPLACE INTO person_portraits VALUES(?,?)',(person,face))
    else:
        c.execute('DELETE FROM person_portraits WHERE person_id=?',(person,))
