"""Exact country aliases shared by search and autocomplete; no substring matching."""
import json
import unicodedata
from functools import lru_cache
from . import core


def normalized(value):
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c)).split())


@lru_cache(maxsize=4)
def _country_aliases(path, stamp):
    try:
        features = json.loads(path.read_text(encoding="utf-8"))["features"]
    except (OSError, ValueError, KeyError):
        return {}
    result = {}
    for feature in features:
        p = feature["properties"]
        code = p.get("ADM0_A3")
        values = [v for k, v in p.items() if k.startswith("NAME") or k in ("ADMIN", "ISO_A2", "ISO_A2_EH", "ISO_A3", "ADM0_A3", "FORMAL_EN", "ABBREV")]
        result["country:" + str(code)] = [v for v in values if isinstance(v, str) and v and v != "-99"]
    return result


def aliases(place):
    values = [place["id"], place["label"]]
    if place["kind"] == "country":
        path = core.DATA / "maps" / "countries.geojson"
        try:
            values += _country_aliases(path, path.stat().st_mtime_ns).get(place["id"], [])
        except OSError:
            pass
        values.append(place["id"].removeprefix("country:"))
        values += {
            "country:USA": ["USA", "US", "U.S.", "U.S.A.", "United States", "United States of America", "America"],
            "country:GBR": ["UK", "U.K.", "United Kingdom", "Great Britain", "Britain"],
            "country:ARE": ["UAE", "United Arab Emirates"],
        }.get(place["id"], [])
    return sorted(set(values), key=str.casefold)


def matching_places(connection, name):
    target = normalized(name)
    return [dict(r) for r in connection.execute("SELECT id,label,kind FROM geographic_places")
            if any(normalized(value) == target for value in aliases(r))]
