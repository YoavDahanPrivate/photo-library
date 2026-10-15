"""Bounded, photo-disjoint evaluation of optional per-person matching rules."""
import hashlib
import json
import uuid
import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from . import core

router = APIRouter(prefix='/api/people/calibration', tags=['People'])
DEFAULT = dict(score=.70, margin=.12, support=2)


def migrate(c):
    c.executescript('''
        CREATE TABLE IF NOT EXISTS face_match_profiles(
          id TEXT PRIMARY KEY,report TEXT NOT NULL,revision TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 0,
          created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS face_match_evidence(
          face_id TEXT PRIMARY KEY REFERENCES faces(id) ON DELETE CASCADE,
          support INTEGER NOT NULL,score_cutoff REAL NOT NULL,margin_cutoff REAL NOT NULL);
    ''')


def revision(c):
    return json.dumps(tuple(c.execute('SELECT coalesce(max(id),0),coalesce(sum(undone),0) FROM actions').fetchone()))


def token(row):
    return hashlib.sha256(row['embedding']+str(row['person_id']).encode()).hexdigest()


def thresholds(c, rows):
    profile = c.execute('SELECT report FROM face_match_profiles WHERE active=1 ORDER BY created DESC,id LIMIT 1').fetchone()
    if not profile:
        return {}, None
    report = json.loads(profile[0])
    actual = {row['id']:row for row in rows}
    # New approvals can extend the gallery. Relabelled/deleted training examples
    # invalidate the profile instead of preserving rules learned from wrong labels.
    if any(identity not in actual or token(actual[identity]) != expected for identity,expected in report['anchors'].items()):
        return {}, 'Saved labels changed; conservative matching is being used. Analyze again.'
    return {item['person_id']:item['proposed'] for item in report['people'] if item['eligible']}, None


def profile_mode(c):
    active=c.execute('SELECT id,report FROM face_match_profiles WHERE active=1 LIMIT 1').fetchone()
    if not active:
        return dict(active_id=None,effective_mode='conservative',active_people=0,mode_reason='No calibrated rules have been enabled.')
    report=json.loads(active['report'])
    anchors=report['anchors']
    rows=c.execute("""SELECT f.id,f.person_id,f.embedding FROM faces f JOIN media m ON m.id=f.media_id
        WHERE f.id IN (SELECT value FROM json_each(?)) AND f.status!='dismissed' AND m.status='ready'""",
        (json.dumps(list(anchors)),)).fetchall()
    valid=len(rows)==len(anchors) and all(token(row)==anchors[row['id']] for row in rows)
    return dict(active_id=active['id'],effective_mode='calibrated' if valid else 'conservative',
                active_people=sum(person['eligible'] for person in report['people']) if valid else 0,
                mode_reason='Validated per-person adjustments are enabled.' if valid else 'Saved labels changed. Conservative rules are in use; analyze again.')


@router.get('')
def status():
    with core.db() as c:
        row = c.execute('SELECT id,report,revision,created FROM face_match_profiles ORDER BY created DESC,rowid DESC LIMIT 1').fetchone()
        mode=profile_mode(c)
        if not row:
            return dict(report=None,report_stale=False,**mode)
        report=json.loads(row['report'])
        report.pop('anchors',None)
        return dict(report=dict(id=row['id'],created=row['created'],**report),report_stale=row['revision']!=revision(c),**mode)


class Apply(BaseModel):
    profile_id: str
    confirm: bool = False


@router.post('/apply')
def apply(body: Apply):
    if not body.confirm:
        raise HTTPException(422,'Confirm the reviewed calibration report')
    with core.db() as c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT * FROM face_match_profiles WHERE id=?',(body.profile_id,)).fetchone()
        if not row or row['revision'] != revision(c):
            raise HTTPException(409,'Saved face reviews changed. Analyze again before enabling these rules.')
        report = json.loads(row['report'])
        if not any(person['eligible'] for person in report['people']):
            raise HTTPException(409,'No person has enough independent evidence for a validated adjustment')
        c.execute('UPDATE face_match_profiles SET active=0')
        c.execute('UPDATE face_match_profiles SET active=1 WHERE id=?',(body.profile_id,))
        # Existing high flags reflect the previous rules; clear them until the
        # next full reevaluation publishes a consistent replacement atomically.
        c.execute('DELETE FROM high_confidence_faces')
    return dict(ok=True,profile_id=body.profile_id,reevaluate_required=True)


@router.post('/reset')
def reset():
    with core.db() as c:
        c.execute('UPDATE face_match_profiles SET active=0')
        c.execute('DELETE FROM high_confidence_faces')
    return dict(ok=True,reevaluate_required=True)


def metrics(samples, person, rule):
    accepted = [item for item in samples if item['predicted']==person and item['score']>=rule['score'] and item['margin']>=rule['margin'] and item['support']>=2]
    correct = sum(item['actual']==person for item in accepted)
    return dict(accepted=len(accepted),correct=correct,mistakes=len(accepted)-correct,
                positive_examples=sum(item['actual']==person for item in samples),
                negative_examples=sum(item['actual']!=person for item in samples))


def propose(tuning, validation, person):
    baseline = metrics(validation,person,DEFAULT)
    # Threshold selection sees tuning labels only. Validation is used once to
    # accept/reject that proposal, never to search for another passing setting.
    choices = []
    for score in np.arange(.55,.701,.025):
        for margin in (.06,.08,.10,.12):
            rule = dict(score=round(float(score),3),margin=margin,support=2)
            result = metrics(tuning,person,rule)
            if result['correct']>=10 and result['mistakes']==0:
                choices.append((result['correct'],rule['score']+rule['margin'],rule))
    if not choices:
        return dict(proposed=DEFAULT,eligible=False,baseline=baseline,validation=baseline,reason='Not enough reliable tuning matches')
    rule = max(choices,key=lambda item:item[:2])[2]
    tested = metrics(validation,person,rule)
    enough = tested['positive_examples']>=15 and tested['negative_examples']>=50 and tested['correct']>=10
    eligible = enough and tested['mistakes']==0 and tested['correct']>baseline['correct']
    return dict(proposed=rule if eligible else DEFAULT,eligible=eligible,baseline=baseline,validation=tested,
                reason='More held-back matches with no observed mistakes' if eligible else 'Conservative rules retained; independent evidence did not justify a change')


def analyze(progress=lambda *args:None):
    from .people_review import vector
    progress('Reading calibration examples')
    with core.db() as c:
        saved_revision = revision(c)
        rows = [dict(row) for row in c.execute('''SELECT f.id,f.media_id,f.person_id,f.status,f.embedding,p.name,m.sha
            FROM faces f JOIN people p ON p.id=f.person_id JOIN media m ON m.id=f.media_id
            WHERE trim(coalesce(p.name,''))!='' AND m.status='ready'
            AND f.status NOT IN ('dismissed','reevaluated','scan-suggested','auto-sync') ORDER BY f.id''')]
    buckets = {}
    for row in rows:
        value = vector(row['embedding'])
        if value is None:
            continue
        key = row['sha'] or row['media_id']
        # All frames/copies of a known photograph stay in the same partition.
        fold = int(hashlib.sha256(str(key).encode()).hexdigest()[:8],16)%4
        buckets.setdefault(row['person_id'],dict(name=row['name'],fit={},tune={},test={}))['fit' if fold<2 else 'tune' if fold==2 else 'test'].setdefault(str(key),(row,value))
    gallery = []
    queries = []
    anchors = {}
    for person, bucket in buckets.items():
        # Equal per-person caps prevent a person with thousands of photos from
        # dominating the bounded study. Stable hash order avoids date bias.
        for partition,limit in (('fit',96),('tune',40),('test',40)):
            selected = sorted(bucket[partition].items(),key=lambda item:hashlib.sha256(item[0].encode()).hexdigest())[:limit]
            for _, (row,value) in selected:
                anchors[row['id']] = token(row)
            if partition=='fit' and selected:
                gallery.append((person,np.stack([item[1][1] for item in selected])))
            elif partition!='fit':
                queries.extend((partition,row,value) for _,(row,value) in selected)
    tuning,validation = [],[]
    progress('Testing held-back photographs',0,len(queries),'faces')
    for offset in range(0,len(queries),64):
        batch = queries[offset:offset+64]
        matrix = np.stack([value for _,_,value in batch])
        rankings = [[] for _ in batch]
        for person,refs in gallery:
            scores = matrix @ refs.T
            for index in range(len(batch)):
                rankings[index].append((float(scores[index].max()),person,int((scores[index]>=.55).sum())))
        for (partition,row,_),ranking in zip(batch,rankings):
            if not ranking:
                continue
            ranking.sort(reverse=True)
            score,predicted,support = ranking[0]
            item = dict(actual=row['person_id'],predicted=predicted,score=score,
                        margin=score-(ranking[1][0] if len(ranking)>1 else 0),support=support)
            (tuning if partition=='tune' else validation).append(item)
            # Open-set check: simulate this person being absent from the gallery,
            # then test whether another identity would wrongly accept the face.
            others = [entry for entry in ranking if entry[1]!=row['person_id']]
            if others:
                wrong_score,wrong_person,wrong_support = others[0]
                (tuning if partition=='tune' else validation).append(dict(
                    actual=None,predicted=wrong_person,score=wrong_score,
                    margin=wrong_score-(others[1][0] if len(others)>1 else 0),support=wrong_support))
        progress('Testing held-back photographs',min(offset+64,len(queries)),len(queries),'faces')
    people = []
    for index,(person,bucket) in enumerate(buckets.items()):
        progress('Evaluating matching rules',index,len(buckets),'people')
        people.append(dict(person_id=person,name=bucket['name'],reference_photos=min(96,len(bucket['fit'])),
                           tuning_photos=min(40,len(bucket['tune'])),validation_photos=min(40,len(bucket['test'])),
                           **propose(tuning,validation,person)))
    report = dict(model='OpenCV SFace',people=people,anchors=anchors,
                  eligible_people=sum(person['eligible'] for person in people),
                  additional_validation_matches=sum(person['validation']['correct']-person['baseline']['correct'] for person in people if person['eligible']),
                  tuning_faces=len(tuning),validation_faces=len(validation),
                  note='This study compares against saved labels, which can contain mistakes or past automatic confirmations. Zero observed mistakes is not a guaranteed accuracy percentage. Nearby burst photos can still be related; known copies and video frames are kept together. New rules require explicit confirmation.')
    progress('Saving calibration report')
    identity = uuid.uuid4().hex
    with core.db() as c:
        c.execute('BEGIN IMMEDIATE')
        if revision(c)!=saved_revision:
            raise HTTPException(409,'Saved face reviews changed during calibration. Analyze again.')
        c.execute('INSERT INTO face_match_profiles(id,report,revision) VALUES(?,?,?)',(identity,json.dumps(report),saved_revision))
    return dict(profile_id=identity,eligible_people=report['eligible_people'],validation_faces=len(validation),additional_validation_matches=report['additional_validation_matches'])
