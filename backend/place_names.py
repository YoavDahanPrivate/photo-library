"""One-time, offline geographic enrichment of existing GPS; never reads originals."""

import hashlib
import json
import math
import sqlite3
import unicodedata
import zipfile
from datetime import datetime, timezone
from .core import DATA, db, init
from .geo import distance_km


def normalize(value):
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(c)
    )


def ring_contains(lon, lat, ring):
    inside = False
    for i, (x, y) in enumerate(ring):
        x0, y0 = ring[i - 1]
        if (y > lat) != (y0 > lat) and lon < (x0 - x) * (lat - y) / (y0 - y) + x:
            inside = not inside
    return inside


def country_polygons(features):
    result = []
    for f in features:
        g = f["geometry"]
        polygons = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        for polygon in polygons:
            outer = polygon[0]
            bounds = (
                min(p[0] for p in outer),
                min(p[1] for p in outer),
                max(p[0] for p in outer),
                max(p[1] for p in outer),
            )
            result.append((bounds, polygon, f["properties"]))
    return result


def lookup_country(lon, lat, polygons):
    matches = {}
    for (w, s, e, n), rings, props in polygons:
        if (
            w <= lon <= e
            and s <= lat <= n
            and ring_contains(lon, lat, rings[0])
            and not any(ring_contains(lon, lat, hole) for hole in rings[1:])
        ):
            matches[props["ADM0_A3"]] = props
    # Do not resolve overlapping/disputed geometry by arbitrary file order.
    return next(iter(matches.values())) if len(matches) == 1 else None


def enrich():
    init()
    maps = DATA / "maps"
    features = json.loads((maps / "countries.geojson").read_text(encoding="utf-8"))[
        "features"
    ]
    polygons = country_polygons(features)
    reference = sqlite3.connect(maps / "gazetteer.sqlite")
    reference.row_factory = sqlite3.Row
    reference.create_function("distance_km", 4, distance_km)
    reference.execute(
        "CREATE TABLE IF NOT EXISTS cities(id TEXT PRIMARY KEY,name TEXT,aliases TEXT,lat REAL,lon REAL,country TEXT)"
    )
    if "feature_code" not in {r[1] for r in reference.execute("PRAGMA table_info(cities)")}:
        reference.execute("ALTER TABLE cities ADD COLUMN feature_code TEXT")
    if not reference.execute("SELECT count(*) FROM cities WHERE feature_code IS NOT NULL").fetchone()[0]:
        with zipfile.ZipFile(maps / "cities1000.zip") as archive:
            rows = []
            for line in archive.open("cities1000.txt"):
                c = line.decode("utf-8").rstrip("\n").split("\t")
                rows.append(
                    (
                        c[0],
                        c[1],
                        normalize(" ".join(c[1:4])),
                        float(c[4]),
                        float(c[5]),
                        c[8],
                        c[7],
                    )
                )
            reference.executemany("INSERT OR REPLACE INTO cities VALUES(?,?,?,?,?,?,?)", rows)
            reference.execute(
                "CREATE INDEX IF NOT EXISTS city_country_lat ON cities(country,lat)"
            )
            reference.commit()
    with db() as c:
        media = c.execute(
            "SELECT id,latitude,longitude FROM media WHERE status='ready' AND latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180"
        ).fetchall()
        country_count = city_count = 0
        for m in media:
            lat, lon = m["latitude"], m["longitude"]
            country = lookup_country(lon, lat, polygons)
            cid = cityid = distance = None
            if country:
                cid = "country:" + country["ADM0_A3"]
                name = country.get("NAME_EN") or country["ADMIN"]
                aliases = normalize(
                    " ".join(
                        str(v)
                        for k, v in country.items()
                        if k.startswith("NAME") or k == "ADMIN"
                    )
                )
                c.execute(
                    "INSERT OR REPLACE INTO geographic_places VALUES(?,?,?,?,?,?,?)",
                    (cid, name, "country", name, None, None, aliases),
                )
                country_count += 1
                # Nearest same-country settlement, at most 25 km; no city-boundary claim.
                nearest = reference.execute(
                    "SELECT *,distance_km(lat,lon,?,?) d FROM cities WHERE country=? AND lat BETWEEN ? AND ? AND feature_code IN ('PPL','PPLA','PPLA2','PPLA3','PPLA4','PPLA5','PPLC') ORDER BY d,id LIMIT 1",
                    (
                        lat,
                        lon,
                        country.get("ISO_A2_EH", country.get("ISO_A2")),
                        lat - 0.23,
                        lat + 0.23,
                    ),
                ).fetchone()
                if nearest and nearest["d"] <= 25:
                    cityid, distance = "city:" + nearest["id"], nearest["d"]
                    c.execute(
                        "INSERT OR REPLACE INTO geographic_places VALUES(?,?,?,?,?,?,?)",
                        (
                            cityid,
                            nearest["name"],
                            "city",
                            name,
                            nearest["lat"],
                            nearest["lon"],
                            nearest["aliases"],
                        ),
                    )
                    city_count += 1
            c.execute(
                "INSERT OR REPLACE INTO media_places VALUES(?,?,?,?,?)",
                (m["id"], cid, cityid, distance, "NE50m-GeoNames1000-settlement25km-v2"),
            )
        c.execute("DELETE FROM geographic_places WHERE id NOT IN (SELECT country_id FROM media_places WHERE country_id IS NOT NULL UNION SELECT city_id FROM media_places WHERE city_id IS NOT NULL)")
    report = dict(
        gps=len(media),
        country=country_count,
        near_city=city_count,
        reference_cities=reference.execute("SELECT count(*) FROM cities").fetchone()[0],
        created=datetime.now(timezone.utc).isoformat(),
        sources={
            name: hashlib.sha256((maps / name).read_bytes()).hexdigest()
            for name in ["countries.geojson", "cities1000.zip"]
        },
    )
    (maps / "naming-report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps(report))


if __name__ == "__main__":
    enrich()
