"""Run after deploying a verified build to record files checked by Start-DahanLibrary."""
import argparse
import hashlib
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("application", type=Path, help="Deployment folder containing backend and frontend/dist")
args = parser.parse_args()
root = args.application.resolve()
version = json.loads((root / "frontend/dist/version.json").read_text(encoding="utf-8"))["version"]
files = []
for directory in ["backend", "frontend/src", "frontend/dist"]:
    for path in sorted((root / directory).rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            files.append({"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
(root / "deployed-release.json").write_text(json.dumps({"version": version, "files": files}, indent=2), encoding="utf-8")
print("Release manifest recorded:", version)
