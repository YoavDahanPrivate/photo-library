"""Download public map references and build their local index without indexing media."""
import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path
from urllib.request import urlopen
from . import core

REFERENCES = {
    "land.geojson": "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_land.geojson",
    "countries.geojson": "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson",
    "cities1000.zip": "https://download.geonames.org/export/dump/cities1000.zip",
}
LAND_SHA256 = "9e0729ee253ca7d7a5c4ae9395fb1902264c5377c52e224d13dd85010e2835d9"


def validate(path, name):
    if name.endswith(".geojson"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("type") != "FeatureCollection" or not data.get("features"):
            raise ValueError("Invalid map reference: " + name)
    else:
        with zipfile.ZipFile(path) as archive:
            if "cities1000.txt" not in archive.namelist() or archive.testzip() is not None:
                raise ValueError("Invalid city reference archive")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if name == "land.geojson" and digest != LAND_SHA256:
        raise ValueError("Overview map changed upstream; review its checksum before installation")
    return digest


def install():
    maps = core.DATA / "maps"
    maps.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for name, url in REFERENCES.items():
        target = maps / name
        if not target.exists():
            print("Downloading " + name, flush=True)
            with tempfile.TemporaryDirectory(prefix=".reference-", dir=maps) as directory:
                temporary = Path(directory) / name
                with urlopen(url, timeout=60) as response, temporary.open("wb") as output:
                    shutil.copyfileobj(response, output)
                validate(temporary, name)
                temporary.replace(target)
        manifest[name] = {"url": url, "sha256": validate(target, name)}
    from .place_names import build_reference
    reference = build_reference(maps)
    try:
        count = reference.execute("SELECT count(*) FROM cities").fetchone()[0]
    finally:
        reference.close()
    (maps / "reference-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"maps": str(maps), "reference_cities": count}))


if __name__ == "__main__":
    install()
