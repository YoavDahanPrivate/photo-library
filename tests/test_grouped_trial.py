import hashlib,json,math
import numpy as np
import pytest
from tests.test_catalogue import client


def vec(angle=0):
    value=np.zeros(128,dtype=np.float32);value[0]=math.cos(angle);value[1]=math.sin(angle)
    return value


def records(count=35):
    return [dict(face_id=f'group-{index:03}',person_id=1,name='Maya',score=.65,margin=.09,source_person_id=3,confidence='lower',taken='2020-01-01') for index in range(count)]


def seed(core,count=35):
    with core.db() as c:
        c.execute('INSERT INTO people(id) VALUES(3)')
        for row in records(count):
            c.execute("INSERT INTO faces(id,media_id,person_id,status,embedding) VALUES(?,'2',3,'suggested',?)",(row['face_id'],vec().tobytes()))
            c.execute('INSERT INTO face_suggestions VALUES(?,?,?,?)',(row['face_id'],1,.65,.09))


def test_groups_cannot_bridge_two_different_appearances():
    from backend.grouped_review import cluster
    rows=records(3);vectors={row['face_id']:vec(index*math.pi/6) for index,row in enumerate(rows)}
    groups,singles=cluster(rows,vectors)
    assert sorted(group['count'] for group in groups)==[2] and len(singles)==1
    for group in groups:
        matrix=np.stack([vectors[row['face_id']] for row in group['matches']])
        assert (matrix@matrix.T).min()>=.78


def test_groups_are_bounded_disjoint_deterministic_and_identity_specific():
    from backend.grouped_review import cluster
    rows=records(150);rows[-1]={**rows[-1],'person_id':2,'name':'Daniel'}
    vectors={row['face_id']:vec() for row in rows}
    groups,singles=cluster(rows,vectors)
    assert sorted(group['count'] for group in groups)==[21,64,64]
    ids=[row['face_id'] for group in groups for row in group['matches']]
    assert len(set(ids))==len(ids)==149 and len(singles)==1
    again,_=cluster(list(reversed(rows)),vectors)
    assert [group['id'] for group in again]==[group['id'] for group in groups]


def test_read_only_group_preview_and_paging_cover_all_members(client):
    api,core=client;seed(core,150)
    with core.db() as c:before=[tuple(row) for row in c.execute('SELECT * FROM faces ORDER BY id')]
    result=api.get('/api/people/review-groups?limit=1').json()
    assert result['total_groups']==3 and result['grouped_faces']==150 and result['individual_faces']==0
    assert len(result['groups'])==1 and len(result['groups'][0]['matches'])==64
    all_ids=set()
    for page in range(3):
        group=api.get('/api/people/review-groups',params={'offset':page,'limit':1}).json()['groups'][0]
        ids={row['face_id'] for row in group['matches']}
        assert not ids&all_ids;all_ids.update(ids)
        assert set(group['representatives'])<=ids
    assert len(all_ids)==150
    with core.db() as c:
        assert [tuple(row) for row in c.execute('SELECT * FROM faces ORDER BY id')]==before
        assert c.execute('SELECT count(*) FROM actions').fetchone()[0]==0
    assert api.get('/api/people/review-groups?cohesion=unsafe').status_code==422
    assert api.get('/api/people/review-groups?offset=-1').status_code==422


def test_preview_excludes_rejections_high_named_unready_and_filters_person(client):
    api,core=client;seed(core,10)
    with core.db() as c:
        c.execute("INSERT INTO face_rejections VALUES('group-000',1)")
        c.execute("INSERT INTO high_confidence_faces VALUES('group-001')")
        c.execute("UPDATE faces SET person_id=2 WHERE id='group-002'")
        c.execute("UPDATE faces SET status='dismissed' WHERE id='group-003'")
    assert api.get('/api/people/review-groups').json()['total_faces']==6
    assert api.get('/api/people/review-groups?person_id=2').json()['total_faces']==0
    with core.db() as c:c.execute("UPDATE media SET status='pending' WHERE id='2'")
    assert api.get('/api/people/review-groups').json()['total_faces']==0


def test_group_approval_uses_exact_selection_and_one_undo(client):
    api,core=client;seed(core)
    group=api.get('/api/people/review-groups').json()['groups'][0]
    selected=[{key:row[key] for key in ('face_id','person_id','source_person_id')} for row in group['matches'][:-2]]
    response=api.post('/api/people/approve-suggestions',json={'matches':selected})
    assert response.status_code==200 and response.json()['approved']==33
    with core.db() as c:
        assert c.execute("SELECT count(*) FROM faces WHERE id LIKE 'group-%' AND person_id=1").fetchone()[0]==33
        assert c.execute('SELECT count(*) FROM actions').fetchone()[0]==1
    assert api.post('/api/undo',json={}).status_code==200
    assert api.get('/api/people/review-groups').json()['grouped_faces']==35


def test_stale_member_cancels_the_entire_group_batch(client):
    api,core=client;seed(core)
    group=api.get('/api/people/review-groups').json()['groups'][0]
    selected=[{key:row[key] for key in ('face_id','person_id','source_person_id')} for row in group['matches']]
    with core.db() as c:c.execute("INSERT INTO face_rejections VALUES('group-001',1)")
    assert api.post('/api/people/approve-suggestions',json={'matches':selected}).status_code==409
    with core.db() as c:
        assert c.execute("SELECT count(*) FROM faces WHERE id LIKE 'group-%' AND person_id=1").fetchone()[0]==0
        assert c.execute('SELECT count(*) FROM actions').fetchone()[0]==0


def study_rows(count=600):
    return [dict(id=f'face-{index}',person_id=1,media_id=f'photo-{index}',sha=f'content-{index}',embedding=vec().tobytes(),name='Maya') for index in range(count)]


def test_full_study_uses_all_fit_photos_and_independent_tuning_validation():
    from backend.face_study import study
    rows=study_rows();report=study(rows)
    expected=sum(int(hashlib.sha256(row['sha'].encode()).hexdigest()[:8],16)%4<2 for row in rows)
    assert report['method']=='full-photo-gallery-v2' and report['reference_photos']==expected>96
    assert report['people'][0]['reference_photos']==expected
    assert report['people'][0]['tuning_photos']==report['people'][0]['validation_photos']==80
    assert len(report['anchors'])==expected+160
    copies=[{**row,'id':'copy-'+row['id'],'media_id':'copy-'+row['media_id']} for row in rows]
    copied=study(rows+copies)
    assert copied['reference_photos']==expected and copied['validation_faces']==report['validation_faces']


def test_study_compares_to_enabled_rules_and_retains_validated_existing_rule(monkeypatch):
    from backend.face_study import study
    from backend import face_calibration
    def unchanged(tuning,validation,person,baseline_rule=None):
        assert baseline_rule==dict(score=.6,margin=.08,support=2)
        return dict(eligible=False,proposed=face_calibration.DEFAULT,baseline=dict(mistakes=0,correct=30),validation=dict(mistakes=0,correct=30),reason='No gain')
    monkeypatch.setattr(face_calibration,'propose',unchanged)
    result=study(study_rows(),baseline_rules={1:dict(score=.6,margin=.08,support=2)})
    person=result['people'][0]
    assert person['retained'] and person['proposed']['score']==.6 and not person['eligible']


def test_report_cannot_overwrite_a_changed_baseline_profile(client):
    api,core=client
    from backend.face_calibration import revision
    with core.db() as c:
        c.execute("INSERT INTO face_match_profiles(id,report,revision,active) VALUES('old','{}','[]',1)")
        report=dict(people=[dict(person_id=1,eligible=True)],anchors={},baseline_profile_ids=[])
        c.execute('INSERT INTO face_match_profiles(id,report,revision) VALUES(?,?,?)',('new',json.dumps(report),revision(c)))
    response=api.post('/api/people/calibration/apply',json={'profile_id':'new','confirm':True})
    assert response.status_code==409
    with core.db() as c:assert c.execute("SELECT active FROM face_match_profiles WHERE id='old'").fetchone()[0]==1


def test_retained_rules_are_effective_in_enabled_profile(client):
    _,core=client
    from backend.face_calibration import thresholds,profile_mode
    with core.db() as c:
        report=dict(people=[dict(person_id=1,eligible=False,retained=True,proposed=dict(score=.6,margin=.08,support=2))],anchors={})
        c.execute("INSERT INTO face_match_profiles(id,report,revision,active) VALUES('retained',?,'[]',1)",(json.dumps(report),))
        assert thresholds(c,[])[0][1]['score']==.6
        assert profile_mode(c)['active_people']==1
