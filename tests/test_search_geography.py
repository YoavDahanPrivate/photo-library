import json
import pytest
from tests.test_catalogue import client


def area(identity, west, east, south=0, north=10):
    return dict(id=identity, south=south, north=north, west=west, east=east)


def seed(core):
    with core.db() as c:
        c.execute("UPDATE media SET latitude=5,longitude=5 WHERE id='0'")
        c.execute("UPDATE media SET latitude=5,longitude=15 WHERE id='1'")
        c.execute(
            "INSERT INTO geographic_places VALUES('country:A','Country A','country','Country A',NULL,NULL,'country a')"
        )
        c.execute(
            "INSERT INTO geographic_places VALUES('city:B','Town B','city','Country A',5,15,'town b')"
        )
        c.execute("INSERT INTO media_places VALUES('0','country:A',NULL,NULL,'test')")
        c.execute("INSERT INTO media_places VALUES('1','country:A','city:B',0,'test')")


def request(c, selection, **filters):
    params = {"geo": json.dumps(selection), **filters}
    media = c.get("/api/media", params=params)
    assert media.status_code == 200, media.text
    result = media.json()
    map_result = c.get("/api/map-results", params=params).json()
    assert result["total"] == map_result["total"]
    assert sum(p["count"] for p in map_result["points"]) == map_result["known"]
    assert map_result["known"] + map_result["unknown"] == result["total"]
    return {m["id"] for m in result["items"]}


def test_or_includes_and_exclusion_precedence(client):
    c, core = client
    seed(core)
    a, b = area("a", 0, 10), area("b", 10, 20)
    assert request(c, {"includes": [a, b]}) == {"0", "1"}
    assert request(c, {"includes": [a, a, b]}) == {"0", "1"}
    assert request(c, {"includes": [a, b], "excludes": [a]}) == {"1"}
    assert request(c, {"places": ["country:A"], "excludes": [a]}) == {"1"}
    assert request(c, {"places": ["city:B"], "includes": [a]}) == {"0", "1"}
    assert request(c, {"places": ["city:B", "country:A"]}) == {"0", "1"}


def test_unknown_and_negative_only(client):
    c, core = client
    seed(core)
    assert request(c, {"unknown": True}) == {"2"}
    assert request(c, {"unknown": True, "includes": [area("a", 0, 10)]}) == {"0", "2"}
    assert request(c, {"excludes": [area("a", 0, 10)]}) == {"1", "2"}
    assert request(
        c,
        {
            "unknown": True,
            "includes": [area("a", 0, 10)],
            "excludes": [area("b", 0, 20)],
        },
    ) == {"2"}
    assert request(c, {}) == {"0", "1", "2"}


def test_all_other_filters_intersect(client):
    c, core = client
    seed(core)
    selection = {"places": ["country:A"]}
    assert request(
        c,
        selection,
        people=[1, 2],
        phones="Yoav14ProMax",
        albums="Yoav14ProMax\x1fRecents",
        start="2026-09-06",
        end="2026-09-06",
    ) == {"0"}
    assert request(c, selection, phones="__no_phone_selected__") == set()
    assert request(c, selection, people=[1, 2], phones="Bar\u2019s iPhone") == set()
    assert request(c, selection, kind="video") == set()
    assert request(c, selection, q="2.jpg") == set()
    assert request(c, selection, orientation="landscape") == set()
    assert request(c, selection, start="2026-09-07") == set()
    options = c.get("/api/place-options", params={"people": [1, 2]}).json()["options"]
    assert {p["id"]: p["count"] for p in options} == {"country:A": 1, "city:B": 0}


def test_dateline_selection(client):
    c, core = client
    seed(core)
    with core.db() as db:
        db.execute("UPDATE media SET longitude=179 WHERE id='0'")
        db.execute("UPDATE media SET longitude=-179 WHERE id='1'")
    assert request(
        c,
        {"includes": [area("date", 170, -170)], "excludes": [area("west", -180, -175)]},
    ) == {"0"}


@pytest.mark.parametrize(
    "selection",
    [
        {"includes": [area("bad", 5, 5)]},
        {"includes": [area("bad", 0, 1, 10, 0)]},
        {"includes": [area("bad", 181, 190)]},
        {"includes": [area("bad", 0, 10, float("nan"), 10)]},
        {"includes": [area(str(i), 0, 1) for i in range(21)]},
        {"places": ["country:missing"]},
        {"unsupported": "ignore me"},
    ],
)
def test_invalid_selection_rejected(client, selection):
    c, _ = client
    assert c.get("/api/media", params={"geo": json.dumps(selection)}).status_code == 422


def test_country_holes_overlap_and_aliases():
    from backend.place_names import country_polygons, lookup_country, normalize

    outer = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
    hole = [[3, 3], [6, 3], [6, 6], [3, 6], [3, 3]]
    feature = {
        "properties": {"ADM0_A3": "A"},
        "geometry": {"type": "Polygon", "coordinates": [outer, hole]},
    }
    polygons = country_polygons([feature])
    assert lookup_country(1, 1, polygons)["ADM0_A3"] == "A"
    assert lookup_country(4, 4, polygons) is None
    assert lookup_country(50, 50, polygons) is None
    duplicate = {**feature, "properties": {"ADM0_A3": "B"}}
    assert lookup_country(1, 1, country_polygons([feature, duplicate])) is None
    assert normalize("São PAULO") == "sao paulo"
