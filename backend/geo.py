"""Offline geographic predicates. Coordinates are WGS84 decimal degrees."""

import math
import json
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, ValidationError, model_validator
from decimal import Decimal, ROUND_FLOOR

VALID = "(m.latitude BETWEEN -90 AND 90 AND m.longitude BETWEEN -180 AND 180)"


class Rectangle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(max_length=80)
    south: float = Field(ge=-90, le=90)
    north: float = Field(ge=-90, le=90)
    west: float = Field(ge=-180, le=180)
    east: float = Field(ge=-180, le=180)

    @model_validator(mode="after")
    def ordered(self):
        if self.south >= self.north or self.west == self.east:
            raise ValueError(
                "Area must have positive height and nonzero longitude span"
            )
        return self


class GeographicSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    places: list[str] = Field(default_factory=list, max_length=40)
    unknown: bool = False
    no_gps: bool = False
    includes: list[Rectangle] = Field(default_factory=list, max_length=20)
    excludes: list[Rectangle] = Field(default_factory=list, max_length=20)


def add_selection(clauses, args, raw):
    from fastapi import HTTPException

    if not raw:
        return
    try:
        selection = GeographicSelection.model_validate_json(raw)
    except ValidationError:
        raise HTTPException(
            422,
            "Invalid geographic selection; use at most 20 include/exclude rectangles and 40 places.",
        )
    positives, negatives = [], []
    if selection.places:
        from .core import db

        with db() as c:
            valid_ids = {r[0] for r in c.execute("SELECT id FROM geographic_places")}
        if not set(selection.places) <= valid_ids:
            raise HTTPException(422, "Unknown geographic place identifier")
        marks = ",".join("?" for _ in selection.places)
        positives.append(
            f"EXISTS(SELECT 1 FROM media_places gp WHERE gp.media_id=m.id AND (gp.country_id IN ({marks}) OR gp.city_id IN ({marks})))"
        )
        args.extend(selection.places * 2)
    if selection.unknown:
        from .metadata_support import UNKNOWN
        positives.append('('+UNKNOWN+')')
    if selection.no_gps:
        positives.append(f"NOT coalesce({VALID},0)")
    for areas, target in [
        (selection.includes, positives),
        (selection.excludes, negatives),
    ]:
        for area in areas:
            terms, values = [], []
            add_location(
                terms,
                values,
                "bounds",
                area.south,
                area.north,
                area.west,
                area.east,
                None,
                None,
                None,
            )
            target.append("(" + " AND ".join(terms) + ")")
            args.extend(values)
    if positives:
        clauses.append("(" + " OR ".join(positives) + ")")
    if negatives:
        clauses.append("NOT coalesce((" + " OR ".join(negatives) + "),0)")


def distance_km(lat, lon, center_lat, center_lon):
    if lat is None or lon is None:
        return None
    a, b = math.radians(lat), math.radians(center_lat)
    h = (
        math.sin((a - b) / 2) ** 2
        + math.cos(a) * math.cos(b) * math.sin(math.radians(lon - center_lon) / 2) ** 2
    )
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1.0, max(0.0, h))))


def add_location(clauses, args, location, south, north, west, east, lat, lon, radius):
    from fastapi import HTTPException

    bounds = [south, north, west, east]
    circle = [lat, lon, radius]
    if location == "bounds":
        if (
            None in bounds
            or south >= north
            or west == east
            or any(v is not None for v in circle)
        ):
            raise HTTPException(
                422, "Provide south < north and distinct west/east bounds only."
            )
        clauses.extend(
            [VALID, "m.latitude>=?", "m.latitude" + ("<=?" if north == 90 else "<?")]
        )
        args.extend([south, north])
        operator = "AND" if west < east else "OR"
        clauses.append(
            f"(m.longitude>=? {operator} m.longitude{'<=' if east == 180 else '<'}?)"
        )
        args.extend([west, east])
    elif location == "radius":
        if None in circle or any(v is not None for v in bounds):
            raise HTTPException(422, "Provide latitude, longitude and radius_km only.")
        clauses.extend([VALID, "distance_km(m.latitude,m.longitude,?,?)<=?"])
        args.extend([lat, lon, radius])
    else:
        if any(v is not None for v in bounds + circle):
            raise HTTPException(422, "Coordinates require bounds or radius mode.")
        if location == "known":
            clauses.append(VALID)
        elif location == "unknown":
            from .metadata_support import UNKNOWN
            clauses.append('('+UNKNOWN+')')
        elif location == 'no_gps':
            clauses.append(f"NOT coalesce({VALID},0)")


def summarize(rows):
    groups = {}
    unknown = 0
    for row in rows:
        lat, lon = row["latitude"], row["longitude"]
        if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            unknown += 1
            continue
        # Decimal boundaries must agree with the half-open SQL bounds; binary
        # arithmetic can otherwise put e.g. -89.9 in the preceding cell.
        y = min(
            1799,
            int(
                ((Decimal(str(lat)) + 90) * 10).to_integral_value(rounding=ROUND_FLOOR)
            ),
        )
        x = min(
            3599,
            int(
                ((Decimal(str(lon)) + 180) * 10).to_integral_value(rounding=ROUND_FLOOR)
            ),
        )
        key = f"{y}:{x}"
        if key not in groups:
            south, west = round(y / 10 - 90, 1), round(x / 10 - 180, 1)
            groups[key] = dict(
                id=key,
                south=south,
                north=round(south + 0.1, 1),
                west=west,
                east=round(west + 0.1, 1),
                latitude=round(south + 0.05, 2),
                longitude=round(west + 0.05, 2),
                count=0,
                cover=row["id"],
            )
        groups[key]["count"] += 1
    return dict(
        groups=sorted(groups.values(), key=lambda g: (-g["count"], g["id"])),
        unknown=unknown,
        known=len(rows) - unknown,
        total=len(rows),
    )
