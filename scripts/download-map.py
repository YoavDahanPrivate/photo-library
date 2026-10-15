"""One-time installation of the public-domain offline overview coastline."""
import hashlib
import os
from pathlib import Path
from urllib.request import urlopen

URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_land.geojson"
SHA256 = "9e0729ee253ca7d7a5c4ae9395fb1902264c5377c52e224d13dd85010e2835d9"
data_directory = os.environ.get("DAHAN_DATA")
if not data_directory:
    raise SystemExit("Set DAHAN_DATA to the intended runtime directory before installing maps.")
target = Path(data_directory) / "maps" / "land.geojson"
if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == SHA256:
    print("Offline map already installed.")
else:
    data = urlopen(URL, timeout=60).read()
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise RuntimeError("Upstream map changed; review the dataset before updating its checksum.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    print(f"Installed offline map: {target}")
