import pytest
from tests.test_catalogue import client


def coordinates(core, values):
    with core.db() as db:
        for identity, lat, lon in values:
            db.execute(
                "UPDATE media SET latitude=?,longitude=? WHERE id=?",
                (lat, lon, identity),
            )


def test_places_counts_and_intersections(client):
    c, core = client
    coordinates(core, [("0", 32.05, 34.85), ("1", 32.06, 34.86)])
    result = c.get("/api/places").json()
    assert (result["known"], result["unknown"], len(result["groups"])) == (2, 1, 1)
    area = result["groups"][0]
    bounds = {
        "location": "bounds",
        **{k: area[k] for k in ["south", "north", "west", "east"]},
    }
    assert c.get("/api/media", params=bounds).json()["total"] == area["count"]
    intersect = list(bounds.items()) + [
        ("people", 1),
        ("people", 2),
        ("phones", "Yoav14ProMax"),
        ("albums", "Yoav14ProMax\x1fRecents"),
        ("start", "2026-09-06"),
        ("end", "2026-09-06"),
    ]
    assert c.get("/api/media", params=intersect).json()["items"][0]["id"] == "0"
    assert c.get("/api/places", params=intersect).json()["known"] == 1
    assert (
        c.get("/api/media", params={**bounds, "start": "2026-09-07"}).json()["total"]
        == 0
    )
    assert (
        c.get("/api/media", params={"location": "unknown"}).json()["items"][0]["id"]
        == "2"
    )


def test_cell_edges_and_invalid_partial_gps(client):
    c, core = client
    coordinates(core, [("0", 32.0, 34.8), ("1", 32.1, 34.9), ("2", 32.0, None)])
    bounds = dict(location="bounds", south=32, north=32.1, west=34.8, east=34.9)
    assert [m["id"] for m in c.get("/api/media", params=bounds).json()["items"]] == [
        "0"
    ]
    assert c.get("/api/places").json()["unknown"] == 1
    for group in c.get("/api/places").json()["groups"]:
        params = {
            "location": "bounds",
            **{k: group[k] for k in ["south", "north", "west", "east"]},
        }
        assert c.get("/api/media", params=params).json()["total"] == group["count"]


def test_radius_dateline_and_poles(client):
    c, core = client
    coordinates(core, [("0", 0, 179.95), ("1", 0, -179.95), ("2", 0, 170)])
    params = dict(location="radius", latitude=0, longitude=180, radius_km=6)
    assert c.get("/api/media", params=params).json()["total"] == 2
    assert c.get("/api/media", params={**params, "radius_km": 5}).json()["total"] == 0
    bounds = dict(location="bounds", south=-1, north=1, west=179, east=-179)
    assert c.get("/api/media", params=bounds).json()["total"] == 2
    coordinates(core, [("0", 90, 180), ("1", 89.99, -179), ("2", None, None)])
    assert (
        c.get(
            "/api/media",
            params=dict(location="radius", latitude=90, longitude=0, radius_km=2),
        ).json()["total"]
        == 2
    )
    assert (
        c.get(
            "/api/media",
            params=dict(location="bounds", south=89.9, north=90, west=179.9, east=180),
        ).json()["total"]
        == 1
    )


def test_exact_radius_boundary(client):
    c, core = client
    from backend.geo import distance_km

    coordinates(core, [("0", 0, 0), ("1", 0, 0.01), ("2", 0, 0.02)])
    edge = distance_km(0, 0.01, 0, 0)
    params = dict(location="radius", latitude=0, longitude=0, radius_km=edge)
    assert c.get("/api/media", params=params).json()["total"] == 2
    assert (
        c.get("/api/media", params={**params, "radius_km": edge - 0.00001}).json()[
            "total"
        ]
        == 1
    )


@pytest.mark.parametrize(
    "params",
    [
        {"location": "radius", "latitude": 91, "longitude": 0, "radius_km": 1},
        {"location": "radius", "latitude": 0, "longitude": 0, "radius_km": 0},
        {"location": "radius", "latitude": "nan", "longitude": 0, "radius_km": 1},
        {"location": "radius", "latitude": 0},
        {"location": "bounds", "south": 10, "north": 0, "west": 0, "east": 1},
        {"location": "unknown", "latitude": 0},
    ],
)
def test_invalid_geography(client, params):
    c, _ = client
    assert c.get("/api/media", params=params).status_code == 422


def test_all_decimal_cell_boundaries():
    from backend.geo import summarize

    for axis, offset, cells in [("latitude", 90, 1800), ("longitude", 180, 3600)]:
        for i in range(cells):
            value = round(i / 10 - offset, 1)
            row = {"id": "edge", "latitude": 0, "longitude": 0, axis: value}
            group = summarize([row])["groups"][0]
            low, high = ("south", "north") if axis == "latitude" else ("west", "east")
            assert group[low] <= value < group[high]
