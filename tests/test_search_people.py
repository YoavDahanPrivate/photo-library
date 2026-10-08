import json
import numpy as np
import pytest
from tests.test_catalogue import client
from tests.test_search_geography import seed


def ids(c, expression):
    r = c.get("/api/media", params={"expression": expression})
    assert r.status_code == 200, r.text
    assert (
        c.get("/api/map-results", params={"expression": expression}).json()["total"]
        == r.json()["total"]
    )
    return {r["id"] for r in r.json()["items"]}


def test_expressions(client):
    c, core = client
    seed(core)
    assert ids(c, '"Maya" && not "Daniel"') == {"1"}
    assert ids(c, 'Only ("Maya" and "Daniel")') == {"0"}
    assert ids(c, 'Just "Maya"') == {"1"}
    assert ids(c, 'Place("Country A") and Place("Town B")') == {"1"}
    assert ids(c, '("Daniel" or Place("Town B")) and date > 2025 and date < 2027') == {
        "0",
        "1",
    }
    assert ids(c, "date >= 2025 and date < 2026") == set()
    with core.db() as db:
        db.execute(
            "INSERT INTO faces(id,media_id,person_id,status) VALUES('unknown','1',NULL,'manual')"
        )
    assert ids(c, 'Just "Maya"') == {"1"}
    assert ids(c, 'Only "Maya"') == set()
    with core.db() as db:
        db.execute("UPDATE faces SET status='dismissed' WHERE id='unknown'")
    assert ids(c, 'Only "Maya"') == {"1"}
    with core.db() as db:
        db.execute(
            "INSERT INTO faces(id,media_id,person_id,status) VALUES('duplicate','1',1,'manual')"
        )
    assert ids(c, 'Only "Maya"') == set()


@pytest.mark.parametrize(
    "expression",
    [
        "Only ()",
        "Maya Daniel",
        '"missing"',
        "date > rubbish",
        "date = 2025-99-99",
        "Maya AND",
        "(Maya",
        'Place("missing")',
        '"Maya"; DROP TABLE people',
        "not " * 180 + "Maya",
    ],
)
def test_invalid_search(client, expression):
    c, _ = client
    assert (
        c.get("/api/search/validate", params={"expression": expression}).status_code
        == 422
    )


def test_sort_and_details(client):
    c, core = client
    seed(core)
    with core.db() as db:
        db.execute("UPDATE media SET taken='2024-01-01T12:00:00' WHERE id='1'")
        db.execute("UPDATE media SET taken=NULL WHERE id='2'")
    assert [m["id"] for m in c.get("/api/media?order=asc").json()["items"]] == [
        "1",
        "0",
        "2",
    ]
    assert [m["id"] for m in c.get("/api/media?order=desc").json()["items"]] == [
        "0",
        "1",
        "2",
    ]
    detail = c.get("/api/media/1").json()
    assert detail["city"] == "Town B" and detail["people_names"] == ["Maya"]


def test_unknown_bucket_preserves_identities_and_undo(client):
    c, core = client
    with core.db() as db:
        db.execute("INSERT INTO people(id) VALUES(3)")
        db.execute("INSERT INTO faces(id,media_id,person_id) VALUES('unnamed','2',3)")
    assert c.post("/api/people/archive-unnamed").json()["moved"] == 1
    people = c.get("/api/people").json()
    assert any(p["id"] == -1 for p in people) and not any(p["id"] == 3 for p in people)
    assert c.get("/api/faces?person=-1").json()[0]["person_id"] == 3
    assert c.post("/api/people/archive-unnamed").json()["moved"] == 0
    assert c.post("/api/undo").status_code == 200
    assert any(p["id"] == 3 for p in c.get("/api/people").json())


def seed_vectors(core):
    a = np.zeros(128, dtype=np.float32)
    a[0] = 1
    b = np.zeros(128, dtype=np.float32)
    b[1] = 1
    with core.db() as db:
        db.execute("UPDATE faces SET embedding=? WHERE person_id=1", (a.tobytes(),))
        db.execute("UPDATE faces SET embedding=? WHERE person_id=2", (b.tobytes(),))
        db.execute(
            "INSERT INTO faces(id,media_id,embedding) VALUES('candidate','2',?)",
            (a.tobytes(),),
        )


def test_reevaluate_and_undo(client):
    c, core = client
    seed_vectors(core)
    c.post("/api/people/archive-unnamed")
    result = c.post("/api/people/reevaluate").json()
    assert result["assigned"] == 0 and result["suggestions"] == 1
    assert c.get('/api/people/suggestions').json()[0]['confidence'] == 'high'
    assert c.post('/api/faces/correct', json={'face_ids':['candidate'],'action':'move','target':1,'from_suggestion':True}).status_code == 200
    with core.db() as db:
        assert (
            db.execute("SELECT person_id FROM faces WHERE id='candidate'").fetchone()[0]
            == 1
        )
    c.post("/api/undo")
    assert len(c.get("/api/faces?person=-1").json()) == 1
    c.post(
        "/api/faces/correct",
        json={"face_ids": ["candidate"], "action": "move", "target": 1},
    )
    c.post("/api/faces/correct", json={"face_ids": ["candidate"], "action": "unknown"})
    assert c.post("/api/people/reevaluate").json()["assigned"] == 0
    assert c.get("/api/people/suggestions").json() == []


def test_suggestions_reject_and_rename(client):
    c, core = client
    seed_vectors(core)
    with core.db() as db:
        db.execute("UPDATE faces SET embedding=NULL WHERE id='c'")
    result = c.post("/api/people/reevaluate").json()
    assert result["assigned"] == 0 and result["suggestions"] == 1
    assert (
        c.post(
            "/api/people/reject-suggestion",
            json={"face_id": "candidate", "person_id": 1},
        ).status_code
        == 200
    )
    assert c.post("/api/people/reevaluate").json()["suggestions"] == 0
    c.post("/api/undo")
    assert c.post("/api/people/reevaluate").json()["suggestions"] == 1
    assert (
        c.post("/api/people/1/name", json={"name": "Renamed Maya"}).status_code == 200
    )
    assert ids(c, '"Renamed Maya"') == {"0", "1"}
    assert c.post("/api/people/1/name", json={"name": "Daniel"}).status_code == 409


def test_duplicate_names_have_explicit_identity(client):
    c, core = client
    with core.db() as db:
        db.execute("INSERT INTO people(id,name) VALUES(3,'Maya')")
        db.execute("INSERT INTO faces(id,media_id,person_id,status) VALUES('second_maya','2',3,'manual')")
    assert (
        c.get("/api/search/validate", params={"expression": 'Only "Maya"'}).status_code
        == 422
    )
    assert ids(c, 'Only "Maya [#1]"') == {"1"}
    assert ids(c, 'Person("Maya [#3]")') == {"2"}


def test_bucket_rename_undo(client):
    c, core = client
    with core.db() as db:
        db.execute("UPDATE people SET name=NULL WHERE id=1")
    c.post("/api/people/archive-unnamed")
    assert c.post("/api/people/1/name", json={"name": "Maya"}).status_code == 200
    assert not c.get("/api/faces?person=-1").json()
    c.post("/api/undo")
    assert len(c.get("/api/faces?person=-1").json()) == 2


def test_selected_unnamed_groups_only_and_undo(client):
    c, core = client
    with core.db() as db:
        db.execute("INSERT INTO people(id) VALUES(3),(4)")
        db.execute(
            "INSERT INTO faces(id,media_id,person_id) VALUES('u3','2',3),('u4','2',4)"
        )
    assert (
        c.post("/api/people/archive-unnamed", json={"person_ids": [3, 3]}).json()[
            "moved"
        ]
        == 1
    )
    assert [f["id"] for f in c.get("/api/faces?person=-1").json()] == ["u3"]
    assert any(p["id"] == 4 for p in c.get("/api/people").json())
    c.post("/api/undo")
    assert c.get("/api/faces?person=-1").json() == []
    assert (
        c.post("/api/people/archive-unnamed", json={"person_ids": []}).status_code
        == 422
    )
    assert (
        c.post("/api/people/archive-unnamed", json={"person_ids": [3, 1]}).status_code
        == 409
    )
    assert c.get("/api/faces?person=-1").json() == []
    assert (
        c.post("/api/people/archive-unnamed", json={"person_ids": [9999]}).status_code
        == 409
    )


def test_review_preserves_other_suggestions_and_learns_next_pass(client):
    c, core = client
    seed_vectors(core)
    with core.db() as db:
        db.execute("UPDATE faces SET embedding=NULL WHERE id='c'")
        db.execute(
            "INSERT INTO faces(id,media_id,embedding) SELECT 'candidate2','1',embedding FROM faces WHERE id='candidate'"
        )
    assert c.post("/api/people/reevaluate").json()["suggestions"] == 2
    body = {
        "face_ids": ["candidate"],
        "action": "move",
        "target": 1,
        "from_suggestion": True,
    }
    assert c.post("/api/faces/correct", json=body).status_code == 200
    assert [s["face_id"] for s in c.get("/api/people/suggestions").json()] == [
        "candidate2"
    ]
    with core.db() as db:
        assert (
            db.execute("SELECT person_id FROM faces WHERE id='candidate2'").fetchone()[
                0
            ]
            is None
        )
        assert (
            db.execute("SELECT status FROM faces WHERE id='candidate'").fetchone()[0]
            == "manual"
        )
    assert c.post("/api/faces/correct", json=body).status_code == 409
    assert c.post("/api/people/reevaluate").json()["assigned"] == 0
    assert c.get('/api/people/suggestions').json()[0]['confidence'] == 'high'


def test_review_rejection_preserves_other_cards_and_stale_accept_is_safe(client):
    c, core = client
    seed_vectors(core)
    with core.db() as db:
        db.execute("UPDATE faces SET embedding=NULL WHERE id='c'")
        db.execute(
            "INSERT INTO faces(id,media_id,embedding) SELECT 'candidate2','1',embedding FROM faces WHERE id='candidate'"
        )
    c.post("/api/people/reevaluate")
    assert (
        c.post(
            "/api/people/reject-suggestion",
            json={"face_id": "candidate", "person_id": 1},
        ).status_code
        == 200
    )
    assert [s["face_id"] for s in c.get("/api/people/suggestions").json()] == [
        "candidate2"
    ]
    assert (
        c.post(
            "/api/faces/correct",
            json={"face_ids": ["candidate2"], "action": "move", "target": 2},
        ).status_code
        == 200
    )
    assert (
        c.post(
            "/api/faces/correct",
            json={
                "face_ids": ["candidate2"],
                "action": "move",
                "target": 1,
                "from_suggestion": True,
            },
        ).status_code
        == 409
    )
    with core.db() as db:
        assert (
            db.execute("SELECT person_id FROM faces WHERE id='candidate2'").fetchone()[
                0
            ]
            == 2
        )


def test_suggested_group_bulk_assignment_preserves_other_guesses_and_undo(client):
    c, core = client
    with core.db() as db:
        db.execute("INSERT INTO people(id) VALUES(3),(4)")
        db.execute("INSERT INTO faces(id,media_id,person_id,status) VALUES('g1','0',3,'manual'),('g2','1',3,'manual'),('other','2',4,'manual')")
        db.execute("INSERT INTO face_suggestions VALUES('g1',1,0.6,0.1),('other',2,0.6,0.1)")
    suggestions = c.get('/api/people/suggestions').json()
    assert next(s for s in suggestions if s['face_id']=='g1')['source_person_id'] == 3
    result = c.post('/api/faces/correct', json={'face_ids':['g1','g2'],'action':'move','target':1})
    assert result.status_code == 200
    assert [s['face_id'] for s in c.get('/api/people/suggestions').json()] == ['other']
    with core.db() as db:
        assert [r[0] for r in db.execute("SELECT person_id FROM faces WHERE id IN ('g1','g2')")] == [1,1]
    assert c.post('/api/undo').status_code == 200
    with core.db() as db:
        assert [r[0] for r in db.execute("SELECT person_id FROM faces WHERE id IN ('g1','g2')")] == [3,3]


def test_on_demand_group_match_without_reevaluation(client):
    c, core = client
    seed_vectors(core)
    with core.db() as db:
        db.execute("INSERT INTO people(id) VALUES(3)")
        db.execute("UPDATE faces SET person_id=3 WHERE id='candidate'")
    assert c.get('/api/people/suggestions').json() == []
    assert c.get('/api/people/3/match').json()['match']['person_id'] == 1
    with core.db() as db:
        assert db.execute("SELECT person_id FROM faces WHERE id='candidate'").fetchone()[0] == 3
        assert db.execute("SELECT count(*) FROM face_suggestions").fetchone()[0] == 0
        db.execute("INSERT INTO face_rejections VALUES('candidate',1)")
    assert c.get('/api/people/3/match').json()['match'] is None
    assert c.get('/api/people/1/match').json()['match'] is None


def test_on_demand_match_hides_ambiguous_and_missing_vectors(client):
    c, core = client
    seed_vectors(core)
    with core.db() as db:
        db.execute("INSERT INTO people(id) VALUES(3)")
        db.execute("UPDATE faces SET person_id=3 WHERE id='candidate'")
        db.execute("UPDATE faces SET embedding=(SELECT embedding FROM faces WHERE id='a') WHERE id='b'")
    assert c.get('/api/people/3/match').json()['match'] is None
    with core.db() as db:
        db.execute("UPDATE faces SET embedding=NULL WHERE id='candidate'")
    assert c.get('/api/people/3/match').json()['match'] is None


def test_review_confidence_approval_and_wrong_person(client):
    c, core = client
    seed_vectors(core)
    result = c.post('/api/people/reevaluate').json()
    assert result['assigned'] == 0
    with core.db() as db:
        assert db.execute("SELECT person_id FROM faces WHERE id='candidate'").fetchone()[0] is None
    assert c.get('/api/people/suggestions').json()[0]['confidence'] == 'high'
    assert c.post('/api/faces/correct',json={'face_ids':['candidate'],'action':'move','target':1,'from_suggestion':True}).status_code == 200
    assert c.get('/api/people/review/approved').json()[0]['face_id'] == 'candidate'
    assert c.post('/api/faces/correct',json={'face_ids':['candidate'],'action':'unknown'}).status_code == 200
    assert c.get('/api/people/review/approved').json() == []
    c.post('/api/people/reevaluate')
    assert c.get('/api/people/suggestions').json() == []


def test_lower_confidence_requires_approval(client):
    c, core = client
    seed_vectors(core)
    with core.db() as db:
        db.execute("UPDATE faces SET embedding=NULL WHERE id='c'")
    c.post('/api/people/reevaluate')
    assert c.get('/api/people/suggestions').json()[0]['confidence'] == 'lower'


def test_includes_alias_and_group_semantics(client):
    c, core = client
    assert ids(c, 'Includes ("Maya")') == ids(c, 'Person("Maya")') == {'0','1'}
    assert ids(c, 'Includes ("Maya" and "Daniel")') == {'0'}
    assert ids(c, 'Includes ("Maya") and not Includes ("Daniel")') == {'1'}
    with core.db() as db:
        db.execute("INSERT INTO faces(id,media_id,status) VALUES('extra','1','manual')")
    assert ids(c, 'Just ("Maya")') == {'1'}
    assert ids(c, 'Only ("Maya")') == set()


def test_unified_search_filter_terms(client):
    c, core = client
    seed(core)
    with core.db() as db:
        db.execute("UPDATE media SET phone='NewPhone',album='Trips',width=800,height=400,kind='photo',latitude=40,longitude=10 WHERE id='1'")
    assert ids(c, 'Phone("NewPhone") and Album("Trips") and MediaType("photo") and Orientation("landscape")') == {'1'}
    assert ids(c, 'Phone("NewPhone") and Area("39,41,9,11")') == {'1'}
    assert ids(c, 'Phone("NewPhone") and not Area("39,41,9,11")') == set()
    assert ids(c, 'Text("Trips")') == {'1'}
    for value in ['Area("nan,41,9,11")','Area("-100,41,9,11")','MediaType("bad")','Location("bad")']:
        assert c.get('/api/search/validate',params={'expression':value}).status_code == 422
