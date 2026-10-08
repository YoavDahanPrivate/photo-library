"""Resumable, additive full scan. Originals and reviewed identities are never rewritten."""

import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
import argparse
import hashlib
import json
import multiprocessing as mp
import shutil
import sqlite3
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from . import core


def stamp():
    return datetime.now(timezone.utc).isoformat()


def checkpoint(progress, **updates):
    progress.update(updates, updated=stamp())
    target = core.DATA / "scan-state.json"
    temp = target.with_suffix(".tmp")
    # Windows readers/antivirus may briefly deny replacement of an open file.
    # Progress publication must not terminate the durable indexing work.
    for attempt in range(8):
        try:
            temp.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(target)
            return True
        except PermissionError as error:
            if attempt == 7:
                print(f"Progress update deferred: {error}", flush=True)
                return False
            time.sleep(min(.05 * 2**attempt, 1))


def discover(state):
    from .indexer import IMAGES, VIDEOS

    for phone in core.PHONES:
        if not (core.ROOT / phone).is_dir():
            raise RuntimeError("Source phone unavailable: " + phone)
    with core.db() as c:
        existing = {
            r["path"]: (r["bytes"], r["mtime"])
            for r in c.execute("SELECT path,bytes,mtime FROM media")
        }
    batch = []
    reports = []
    changed = []
    errors = []
    added = 0

    def flush():
        nonlocal added
        if batch:
            with core.db() as c:
                inserted = c.executemany(
                    "INSERT OR IGNORE INTO media(id,path,phone,album,name,kind,extension,bytes,mtime) VALUES(?,?,?,?,?,?,?,?,?)",
                    batch,
                )
                added += inserted.rowcount
            batch.clear()

    for phone in core.PHONES:
        base = core.ROOT / phone
        counts = Counter()
        other = Counter()
        size = 0

        def walk_error(error):
            errors.append(str(error))

        for directory, dirs, files in os.walk(
            base, followlinks=False, onerror=walk_error
        ):
            dirs[:] = [
                d
                for d in dirs
                if d not in (".dtrash", "PhotoPrismStorage", "$RECYCLE.BIN")
                and not Path(directory, d).is_symlink()
                and not Path(directory, d).is_junction()
            ]
            for filename in files:
                path = Path(directory, filename)
                ext = path.suffix.lower()
                if ext not in IMAGES | VIDEOS:
                    other[ext] += 1
                    continue
                if path.is_symlink():
                    continue
                try:
                    stat = path.stat()
                except OSError as e:
                    errors.append(str(e))
                    continue
                counts[ext] += 1
                size += stat.st_size
                previous = existing.get(str(path))
                if previous is not None:
                    if previous != (stat.st_size, stat.st_mtime):
                        changed.append(str(path))
                    continue
                relative = path.relative_to(base)
                batch.append(
                    (
                        hashlib.sha256(str(path).encode()).hexdigest()[:24],
                        str(path),
                        phone,
                        (
                            relative.parts[0]
                            if len(relative.parts) > 1
                            else "(Phone root)"
                        ),
                        filename,
                        "video" if ext in VIDEOS else "photo",
                        ext,
                        stat.st_size,
                        stat.st_mtime,
                    )
                )
                if len(batch) >= 200:
                    flush()
                    checkpoint(
                        state, phase="discovering", added=added, current_phone=phone
                    )
        flush()
        reports.append(
            dict(
                phone=phone,
                files=sum(counts.values()),
                bytes=size,
                formats=dict(counts),
                other_files=dict(other),
            )
        )
    report = dict(
        phones=reports,
        added=added,
        changed_sources=changed,
        discovery_errors=errors,
        created=stamp(),
    )
    (core.DATA / "full-inventory.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


class Locations:
    def __init__(self):
        from .place_names import country_polygons
        from .geo import distance_km

        maps = core.DATA / "maps"
        self.polygons = country_polygons(
            json.loads((maps / "countries.geojson").read_text(encoding="utf-8"))[
                "features"
            ]
        )
        self.reference = sqlite3.connect(
            f'file:{(maps/"gazetteer.sqlite").as_posix()}?mode=ro', uri=True
        )
        self.reference.row_factory = sqlite3.Row
        self.reference.create_function("distance_km", 4, distance_km)
        self.cache = {}

    def resolve(self, lat, lon):
        from .place_names import lookup_country, normalize

        if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
        key = (lat, lon)
        if key in self.cache:
            return self.cache[key]
        country = lookup_country(lon, lat, self.polygons)
        cid = cityid = distance = None
        places = []
        if country:
            cid = "country:" + country["ADM0_A3"]
            name = country.get("NAME_EN") or country["ADMIN"]
            places.append((cid, name, "country", name, None, None, normalize(name)))
            nearest = self.reference.execute(
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
                cityid = "city:" + nearest["id"]
                distance = nearest["d"]
                places.append(
                    (
                        cityid,
                        nearest["name"],
                        "city",
                        name,
                        nearest["lat"],
                        nearest["lon"],
                        nearest["aliases"],
                    )
                )
        result = (cid, cityid, distance, places)
        self.cache[key] = result
        return result


recognizer = None
locations = None


def prepare_preview_worker():
    # Preview workers do not load face models or geographic references.
    from PIL import Image


def prepare_worker():
    global recognizer, locations
    from .indexer import Recognition

    recognizer = Recognition()
    locations = Locations()


def process_one(identity, preview_only=False):
    from .indexer import photo, video
    from PIL import Image

    try:
        with core.db() as c:
            row = c.execute("SELECT * FROM media WHERE id=?", (identity,)).fetchone()
        if row is None or row["status"] in ("missing", "superseded", "trashed"):
            return dict(id=identity, ok=True)
        if row["status"] != "ready":
            path = core.original(row)
            before = path.stat()
            if (before.st_size, before.st_mtime) != (row["bytes"], row["mtime"]):
                raise RuntimeError(
                    "Source changed since discovery; needs review before reindexing"
                )
            if time.time() - before.st_mtime < 30:
                raise RuntimeError("Source still being copied; resume later")
            with path.open("rb") as handle:
                digest = hashlib.file_digest(handle, "sha256").hexdigest()
            frames, info = photo(path) if row["kind"] == "photo" else video(path)
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (
                after.st_size,
                after.st_mtime_ns,
            ):
                raise RuntimeError("Source changed during decoding; resume later")
            for name, edge in [("small", 240), ("medium", 640), ("large", 1600)]:
                image = frames[0][1].copy()
                image.thumbnail((edge, edge), Image.Resampling.LANCZOS)
                target = core.DATA / "thumbs" / f"{identity}-{name}.jpg"
                image.save(target.with_suffix(".tmp"), format="JPEG", quality=85)
                target.with_suffix(".tmp").replace(target)
            if row["kind"] == "video":
                for i, (_, image) in enumerate(frames):
                    target = core.DATA / "frames" / f"{identity}-{i}.jpg"
                    image.save(target.with_suffix(".tmp"), format="JPEG", quality=85)
                    target.with_suffix(".tmp").replace(target)
            del frames
            with core.db() as c:
                c.execute(
                    "UPDATE media SET status='ready',error=NULL,sha=?,taken=?,width=?,height=?,duration=?,latitude=?,longitude=?,metadata=? WHERE id=?",
                    (
                        digest,
                        info["taken"],
                        info["width"],
                        info["height"],
                        info["duration"],
                        info["latitude"],
                        info["longitude"],
                        json.dumps(info["metadata"], ensure_ascii=False),
                        identity,
                    ),
                )
                row = c.execute(
                    "SELECT * FROM media WHERE id=?", (identity,)
                ).fetchone()
        if preview_only:
            return dict(id=identity, ok=True)
        if row["face_status"] != "ready":
            if row["kind"] == "photo":
                paths = [(0, core.DATA / "thumbs" / f"{identity}-large.jpg")]
            else:
                times = sorted(
                    set(round((row["duration"] or 0) * f, 3) for f in (0.15, 0.5, 0.85))
                )
                paths = [
                    (t, core.DATA / "frames" / f"{identity}-{i}.jpg")
                    for i, t in enumerate(times)
                ]
            for t, path in paths:
                with Image.open(path) as image:
                    recognizer.process(identity, t, image.convert("RGB"))
            with core.db() as c:
                c.execute(
                    "UPDATE media SET face_status='ready',error=NULL WHERE id=?",
                    (identity,),
                )
        location = locations.resolve(row["latitude"], row["longitude"])
        if location:
            cid, cityid, distance, places = location
            with core.db() as c:
                c.executemany(
                    "INSERT OR IGNORE INTO geographic_places VALUES(?,?,?,?,?,?,?)",
                    places,
                )
                c.execute(
                    "INSERT OR REPLACE INTO media_places VALUES(?,?,?,?,?)",
                    (
                        identity,
                        cid,
                        cityid,
                        distance,
                        "NE50m-GeoNames1000-settlement25km-v2",
                    ),
                )
        return dict(id=identity, ok=True)
    except Exception as e:
        return dict(id=identity, ok=False, error=f"{type(e).__name__}: {e}"[:1600])


def assign_new_faces(limit=1000, allow_named=True):
    """Bounded group exemplars, no rewriting of any assigned/manual face."""
    import numpy as np
    from .people_review import vector

    with core.db() as c:
        known = c.execute(
            "SELECT f.person_id,f.embedding,f.media_id,p.name FROM faces f JOIN people p ON p.id=f.person_id WHERE f.status!='dismissed' AND EXISTS(SELECT 1 FROM media m WHERE m.id=f.media_id AND m.status='ready') AND f.embedding IS NOT NULL AND (p.name IS NULL OR f.status NOT IN ('scan-suggested','auto-sync','reevaluated')) ORDER BY f.status='manual' DESC,f.id"
        ).fetchall()
        pending = c.execute(
            "SELECT id,embedding FROM faces WHERE person_id IS NULL AND status='suggested' AND embedding IS NOT NULL AND EXISTS(SELECT 1 FROM media m WHERE m.id=faces.media_id AND m.status='ready') ORDER BY id LIMIT ?",
            (limit,),
        ).fetchall()
    if not pending:
        return 0
    vectors = []
    persons = []
    named = []
    media = []
    counts = Counter()
    for r in known:
        if r["name"] and not allow_named:
            continue
        maximum = 12 if r["name"] else 3
        if counts[r["person_id"]] >= maximum:
            continue
        v = vector(r["embedding"])
        if v is not None:
            vectors.append(v)
            persons.append(r["person_id"])
            named.append(bool(r["name"]))
            media.append(r["media_id"])
            counts[r["person_id"]] += 1
    matrix = (
        np.asarray(vectors, dtype=np.float32)
        if vectors
        else np.empty((0, 128), np.float32)
    )
    named_ids = {p for p, n in zip(persons, named) if n}
    fresh = []
    plans = []
    next_group = -1
    for row in pending:
        v = vector(row["embedding"])
        if v is None:
            continue
        candidates = {}
        if len(matrix):
            scores = matrix @ v
            for index in np.flatnonzero(scores >= 0.60):
                identity = persons[index]
                candidates[identity] = max(
                    candidates.get(identity, -1), float(scores[index])
                )
        for identity, ref in fresh:
            score = float(ref @ v)
            if score >= 0.60:
                candidates[identity] = max(candidates.get(identity, -1), score)
        ranked = sorted(candidates.items(), key=lambda x: x[1], reverse=True)
        target = None
        if ranked:
            identity, score = ranked[0]
            is_named = identity in named_ids
            margin = score - (ranked[1][1] if len(ranked) > 1 else 0)
            # Saved identities need a stronger match. These remain suggested, reviewable assignments.
            support = (
                len(
                    {
                        media[i]
                        for i in range(len(persons))
                        if persons[i] == identity and float(scores[i]) >= 0.55
                    }
                )
                if is_named
                else 0
            )
            if (
                score >= (0.72 if is_named else 0.60)
                and margin >= (0.12 if is_named else 0.04)
                and (not is_named or support >= 2)
            ):
                target = identity
        if target is None:
            target = next_group
            next_group -= 1
            fresh.append((target, v))
        plans.append((row["id"], target))
    with core.db() as c:
        c.execute("BEGIN IMMEDIATE")
        new = {}
        for fid, target in plans:
            if (
                c.execute(
                    "SELECT 1 FROM faces WHERE id=? AND person_id IS NULL AND status='suggested'",
                    (fid,),
                ).fetchone()
                is None
            ):
                continue
            if target < 0:
                if target not in new:
                    new[target] = c.execute(
                        "INSERT INTO people(name) VALUES(NULL)"
                    ).lastrowid
                target = new[target]
            c.execute(
                "UPDATE faces SET person_id=?,status=? WHERE id=? AND person_id IS NULL AND status='suggested'",
                (target, "scan-suggested" if target in named_ids else "suggested", fid),
            )
    return len(plans)


def record_error(result):
    with core.db() as c:
        c.execute(
            "UPDATE media SET status=CASE WHEN status='ready' THEN status ELSE 'error' END,error=? WHERE id=?",
            (result["error"], result["id"]),
        )
        c.execute(
            "UPDATE media SET face_status=CASE WHEN face_status='ready' THEN face_status ELSE 'error' END WHERE id=?",
            (result["id"],),
        )


def totals():
    with core.db() as c:
        return dict(
            c.execute(
                "SELECT count(*) total,sum(status='ready') ready,sum(status='error') media_errors,sum(face_status='error') face_errors,sum(status='pending') pending FROM media"
            ).fetchone()
        )


def run(workers=2):
    import msvcrt

    core.init()
    lock = (core.DATA / "full-scan.lock").open("a+b")
    if lock.tell() == 0:
        lock.write(b"0")
        lock.flush()
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        raise RuntimeError("A full scan is already running")
    state = dict(
        started=stamp(),
        pid=os.getpid(),
        workers=workers,
        state="running",
        phase="preparing",
    )
    pool = None
    try:
        checkpoint(state)
        if shutil.disk_usage(core.DATA).free < 10 * 1024**3:
            raise RuntimeError("Less than 10 GiB free on the data SSD")
        from .indexer import MODELS

        for path in [
            MODELS / "yunet.onnx",
            MODELS / "sface.onnx",
            core.DATA / "maps" / "countries.geojson",
            core.DATA / "maps" / "gazetteer.sqlite",
        ]:
            if not path.is_file():
                raise RuntimeError(
                    "Required offline model/reference missing: " + str(path)
                )
        backups = core.DATA.parent / "backups"
        backups.mkdir(exist_ok=True)
        backup = backups / (
            "catalogue-before-full-scan-"
            + datetime.now().strftime("%Y%m%d-%H%M%S")
            + ".sqlite"
        )
        with core.db() as source, sqlite3.connect(backup) as destination:
            source.backup(destination, pages=256, sleep=0.02)
        checkpoint(state, backup=str(backup))
        for name in ("thumbs", "frames", "faces", "previews"):
            (core.DATA / name).mkdir(exist_ok=True)
        report = discover(state)
        checkpoint(
            state,
            phase="indexing",
            inventory=sum(p["files"] for p in report["phones"]),
            changed_sources=len(report["changed_sources"]),
            discovery_errors=len(report["discovery_errors"]),
            **totals(),
        )
        with core.db() as c:
            todo = [
                r["id"]
                for r in c.execute(
                    "SELECT id FROM media WHERE status NOT IN ('missing','superseded') AND (status!='ready' OR face_status!='ready' OR (latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180 AND NOT EXISTS(SELECT 1 FROM media_places mp WHERE mp.media_id=media.id))) ORDER BY phone,kind,name"
                )
            ]
        started = time.monotonic()
        done = 0
        failed = 0
        last = 0
        cursor = 0
        active = []
        last_report = 0
        pool = mp.get_context("spawn").Pool(
            workers, initializer=prepare_worker, maxtasksperchild=150
        )
        while cursor < len(todo) or active:
            if (core.DATA / "scan-pause").exists():
                if not active:
                    checkpoint(
                        state,
                        state="paused",
                        phase="paused",
                        processed=done,
                        **totals(),
                    )
                    return
            else:
                while cursor < len(todo) and len(active) < workers:
                    identity = todo[cursor]
                    cursor += 1
                    active.append(
                        (
                            identity,
                            pool.apply_async(process_one, (identity,)),
                            time.monotonic(),
                        )
                    )
            progressed = False
            for entry in list(active):
                identity, future, began = entry
                if future.ready():
                    try:
                        result = future.get()
                    except Exception as e:
                        result = dict(id=identity, ok=False, error=str(e)[:1600])
                    if not result["ok"]:
                        failed += 1
                        record_error(result)
                    active.remove(entry)
                    done += 1
                    progressed = True
                elif time.monotonic() - began > 240:
                    pool.terminate()
                    pool.join()
                    for mid, _, _ in active:
                        record_error(
                            dict(
                                id=mid,
                                error="Worker timed out or stopped; resume to retry",
                            )
                        )
                    failed += len(active)
                    done += len(active)
                    active = []
                    pool = mp.get_context("spawn").Pool(
                        workers, initializer=prepare_worker, maxtasksperchild=150
                    )
                    progressed = True
                    break
            if progressed and (done // 100 != last // 100):
                assign_new_faces()
                last = done
            elapsed = time.monotonic() - started
            if elapsed - last_report >= 5 or done == len(todo):
                last_report = elapsed
                checkpoint(
                    state,
                    processed=done,
                    to_process=len(todo),
                    run_errors=failed,
                    elapsed_seconds=round(elapsed),
                    remaining_seconds=(
                        round((len(todo) - done) * elapsed / done)
                        if done >= 50
                        else None
                    ),
                    **totals(),
                )
            if shutil.disk_usage(core.DATA).free < 10 * 1024**3:
                raise RuntimeError(
                    "Scan stopped with less than 10 GiB free; free space before resuming"
                )
            if not progressed:
                time.sleep(0.5)
        checkpoint(state, phase="grouping faces")
        while assign_new_faces():
            checkpoint(state, phase="grouping faces")
        issues = report["discovery_errors"] or report["changed_sources"] or failed
        checkpoint(
            state,
            state="completed_with_issues" if issues else "completed",
            phase="finished",
            finished=stamp(),
            **totals(),
        )
    except Exception as e:
        checkpoint(
            state, state="stopped", phase="error", error=f"{type(e).__name__}: {e}"
        )
        raise
    finally:
        if pool:
            pool.terminate()
            pool.join()
        lock.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, choices=(1, 2, 3, 4), default=2)
    args = parser.parse_args()
    run(args.workers)
