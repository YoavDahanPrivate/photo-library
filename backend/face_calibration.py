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
    had_rejection_evidence = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='face_rejection_evidence'").fetchone() is not None
    c.executescript('''
        CREATE TABLE IF NOT EXISTS face_match_profiles(
          id TEXT PRIMARY KEY,report TEXT NOT NULL,revision TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 0,
          created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS face_match_evidence(
          face_id TEXT PRIMARY KEY REFERENCES faces(id) ON DELETE CASCADE,
          support INTEGER NOT NULL,score_cutoff REAL NOT NULL,margin_cutoff REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS face_rejection_evidence(
          face_id TEXT PRIMARY KEY REFERENCES faces(id) ON DELETE CASCADE,
          rejection_score REAL NOT NULL,rejection_floor REAL,rejection_examples INTEGER NOT NULL);
    ''')
    if not had_rejection_evidence:
        # Old flags did not account for rejected lookalikes. A normal reevaluation
        # rebuilds them; existing suggestions/annotations remain intact.
        c.executescript('DELETE FROM high_confidence_faces;')


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
    return {item['person_id']:item['proposed'] for item in report['people'] if item['eligible'] or item.get('retained')}, None


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
                active_people=sum(person['eligible'] or person.get('retained',False) for person in report['people']) if valid else 0,
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
        baseline_changed='baseline_profile_ids' in report and row['id']!=mode['active_id'] and report['baseline_profile_ids']!=[item[0] for item in c.execute('SELECT id FROM face_match_profiles WHERE active=1 ORDER BY id')]
        return dict(report=dict(id=row['id'],created=row['created'],**report),report_stale=row['revision']!=revision(c) or baseline_changed,**mode)


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
        if 'baseline_profile_ids' in report and report['baseline_profile_ids']!=[item[0] for item in c.execute('SELECT id FROM face_match_profiles WHERE active=1 ORDER BY id')]:
            raise HTTPException(409,'Enabled rules changed. Analyze again before enabling this report.')
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


def propose(tuning, validation, person, baseline_rule=None):
    baseline = metrics(validation,person,baseline_rule or DEFAULT)
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
    return dict(proposed=rule if eligible else DEFAULT,tested_rule=rule,eligible=eligible,baseline=baseline,validation=tested,
                reason='More held-back matches with no observed mistakes' if eligible else 'Conservative rules retained; independent evidence did not justify a change')


def analyze(progress=lambda *args:None):
    progress('Reading calibration examples')
    with core.db() as c:
        saved_revision = revision(c)
        baseline_ids=[row[0] for row in c.execute('SELECT id FROM face_match_profiles WHERE active=1 ORDER BY id')]
        rows = [dict(row) for row in c.execute('''SELECT f.id,f.media_id,f.person_id,f.status,f.embedding,p.name,m.sha
            FROM faces f JOIN people p ON p.id=f.person_id JOIN media m ON m.id=f.media_id
            WHERE trim(coalesce(p.name,''))!='' AND m.status='ready'
            AND f.status NOT IN ('dismissed','reevaluated','scan-suggested','auto-sync') ORDER BY f.id''')]
        policy,_=thresholds(c,rows)
    from .face_study import study
    report=study(rows,progress,baseline_rules=policy)
    report['baseline_profile_ids']=baseline_ids
    progress('Saving calibration report')
    identity = uuid.uuid4().hex
    with core.db() as c:
        c.execute('BEGIN IMMEDIATE')
        if revision(c)!=saved_revision or [row[0] for row in c.execute('SELECT id FROM face_match_profiles WHERE active=1 ORDER BY id')]!=baseline_ids:
            raise HTTPException(409,'Saved face reviews changed during calibration. Analyze again.')
        c.execute('INSERT INTO face_match_profiles(id,report,revision) VALUES(?,?,?)',(identity,json.dumps(report),saved_revision))
    return dict(profile_id=identity,eligible_people=report['eligible_people'],validation_faces=report['validation_faces'],additional_validation_matches=report['additional_validation_matches'])
