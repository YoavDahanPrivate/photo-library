import json, threading, os, sqlite3, logging
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
from ipaddress import IPv4Address
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException, Query, Request, Depends
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .core import DATA, PHONES, db, init, original

from . import storage_runtime
storage_runtime.initialize(force=True)
from contextlib import asynccontextmanager
from . import sync_service

@asynccontextmanager
async def lifespan(app):
    from . import duplicates
    try:
        with sync_service.scan_lock(): duplicates.recover()
    except RuntimeError: pass
    except (OSError,sqlite3.Error):
        logging.getLogger(__name__).exception("Storage unavailable during startup recovery")
    sync_service.start_scheduler()
    try:
        yield
    finally:
        sync_service.stop_scheduler()

app = FastAPI(title="Dahan Photo Library prototype", lifespan=lifespan)
@app.exception_handler(sqlite3.Error)
async def catalogue_error(request: Request, error: sqlite3.Error):
    logging.getLogger(__name__).exception("Catalogue request failed", exc_info=error)
    code=getattr(error,"sqlite_errorcode",0) & 255
    unavailable=code in (sqlite3.SQLITE_IOERR,sqlite3.SQLITE_CANTOPEN,sqlite3.SQLITE_READONLY,sqlite3.SQLITE_FULL,sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED) or any(word in str(error).lower() for word in ("disk i/o", "unable to open", "readonly", "database is locked"))
    detail=("Library storage is unavailable or busy. Check that the data drive is connected and writable, then retry. Saved sync checkpoints are retained." if unavailable else "The library catalogue could not be read. Check the service logs before resuming sync.")
    return JSONResponse({"detail":detail},status_code=503 if unavailable else 500,headers={"Retry-After":"5"} if unavailable else None)

@app.exception_handler(OSError)
async def filesystem_error(request: Request, error: OSError):
    logging.getLogger(__name__).exception("Library filesystem access failed", exc_info=error)
    return JSONResponse({"detail":storage_runtime.DETAIL},status_code=503,headers={"Retry-After":"5"})


@app.get("/api/health")
def health():
    return storage_runtime.health()


app.include_router(sync_service.router)
from . import source_management
app.include_router(source_management.router)
from . import advanced_layout
app.include_router(advanced_layout.router)
from . import source_discovery
app.include_router(source_discovery.router)
from . import folder_picker
app.include_router(folder_picker.router)
from . import network_access
app.include_router(network_access.router)
from .duplicates import router as duplicate_router
app.include_router(duplicate_router)
lan_address = os.environ.get("DAHAN_LAN_ADDRESS", "").strip()
if lan_address:
    lan_address = str(IPv4Address(lan_address))
allowed_hosts = {"localhost", "127.0.0.1", "testserver"}
allowed_origins = {
    "http://localhost",
    "http://127.0.0.1",
    "http://localhost:80",
    "http://127.0.0.1:80",
    "http://localhost:8765",
    "http://localhost:8766",
    "http://127.0.0.1:8766",
    "http://127.0.0.1:8765",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
}
if lan_address:
    allowed_hosts.add(lan_address)
    allowed_origins.add(f"http://{lan_address}:8765")
    allowed_origins.add(f"http://{lan_address}")
    allowed_origins.add(f"http://{lan_address}:80")


for name in ("dahanoffice", "dahanoffice.local"):
    allowed_hosts.add(name)
    allowed_origins.add(f"http://{name}")
    allowed_origins.add(f"http://{name}:80")

@app.middleware("http")
async def trusted_hosts(request: Request, call_next):
    host = request.headers.get("host", "").split(":")[0]
    if host not in allowed_hosts:
        return JSONResponse(
            {"detail": "Host not enabled for this prototype"}, status_code=403
        )
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin and origin not in allowed_origins:
            return JSONResponse(
                {"detail": "Cross-origin writes disabled"}, status_code=403
            )
    progress_request = request.url.path.startswith("/api/people/operations/") and (request.method=="GET" or request.url.path.endswith("/cancel"))
    if request.url.path.startswith("/api/") and request.url.path != "/api/health" and not progress_request:
        from starlette.concurrency import run_in_threadpool
        if not await run_in_threadpool(storage_runtime.initialize):
            return JSONResponse({"detail":storage_runtime.DETAIL},status_code=503,headers={"Retry-After":"5"})
    response = await call_next(request)
    path = request.url.path
    if path in ("/", "/index.html", "/version.json", "/manifest.webmanifest"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
    elif path.startswith("/brand/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/api/status")
def status():
    with db() as c:
        counts = {
            r["status"]: r["n"]
            for r in c.execute("SELECT status,count(*) n FROM media m WHERE " + source_management.VISIBLE + " GROUP BY status")
        }
        return dict(
            total=sum(v for k,v in counts.items() if k not in ("trashed","superseded","missing")),
            revision=c.execute("SELECT revision FROM catalogue_clock WHERE id=1").fetchone()[0],
            counts=counts,
            faces=c.execute("SELECT count(*) FROM faces").fetchone()[0],
            scan=scan_status(),
            database="Disposable SQLite prototype; production PostgreSQL storage pending",
            features=dict(
                semantic_search=False,
                accounts=False,
                continuous_sync=False,
                live_photo_pairing=False,
            ),
        )


def scan_status():
    try:
        data = json.loads((DATA / "scan-state.json").read_text(encoding="utf-8"))
        import time

        data["stale"] = (
            data.get("state") == "running"
            and time.time() - (DATA / "scan-state.json").stat().st_mtime > 300
        )
        return data
    except (OSError, ValueError):
        return None


@app.post("/api/scan/pause")
def pause_scan():
    (DATA / "scan-pause").write_text("Pause requested", encoding="utf-8")
    return {"ok": True}


@app.get("/api/sources")
def sources():
    with db() as c:
        return [
            dict(r)
            for r in c.execute(
                "SELECT phone,album,m.database_id,m.source_id,m.album_id,(SELECT alias FROM library_databases WHERE id=m.database_id) database_alias,count(*) count FROM media m WHERE status NOT IN ('missing','superseded','trashed') AND " + source_management.VISIBLE + " GROUP BY m.database_id,m.source_id,m.album_id,phone,album ORDER BY phone,album"
            )
        ]


def media_filters(
    request: Request,
    hide_format_duplicates: bool = False,
    database_ids: list[str] = Query(default=[]),
    include_child_databases: bool = False,
    linked_source_ids: list[str] = Query(default=[]),
    source_ids: list[str] = Query(default=[]),
    album_ids: list[str] = Query(default=[]),
    phones: list[str] = Query(default=[]),
    albums: list[str] = Query(default=[]),
    people: list[int] = Query(default=[]),
    kind: Literal["photo", "video"] | None = None,
    orientation: Literal["portrait", "landscape", "square"] | None = None,
    start: str | None = None,
    end: str | None = None,
    q: str = "",
    expression: str = Query(default="", max_length=4000),
    geo: str = Query(default="", max_length=20000),
    location: Literal["any", "known", "unknown", "no_gps", "bounds", "radius"] = "any",
    south: float | None = Query(default=None, ge=-90, le=90),
    north: float | None = Query(default=None, ge=-90, le=90),
    west: float | None = Query(default=None, ge=-180, le=180),
    east: float | None = Query(default=None, ge=-180, le=180),
    latitude: float | None = Query(default=None, ge=-90, le=90),
    longitude: float | None = Query(default=None, ge=-180, le=180),
    radius_km: float | None = Query(default=None, gt=0, le=20020),
):
    clauses = ["m.status='ready'", source_management.VISIBLE]
    args = []
    if database_ids and include_child_databases:
        with db() as catalogue:
            expanded=sorted({d['id'] for did in database_ids for d in advanced_layout.descendants(catalogue,did)})
        if not expanded:clauses.append("0")
        database_ids=expanded
    if linked_source_ids:
        clauses.append("EXISTS(SELECT 1 FROM linked_source_members lm JOIN linked_sources lg ON lg.id=lm.linked_id WHERE lm.source_id=m.source_id AND lg.visible=1 AND lm.linked_id IN ("+','.join('?' for _ in linked_source_ids)+"))")
        args.extend(linked_source_ids)
    for col, values in [
        ("m.database_id", database_ids),
        ("m.source_id", source_ids),
        ("m.album_id", album_ids),
        ("m.phone", phones),
        ("m.phone || char(31) || m.album", albums),
    ]:
        if values:
            clauses.append(col + " IN (" + ",".join("?" for _ in values) + ")")
            args.extend(values)
    if kind:
        clauses.append("m.kind=?")
        args.append(kind)
    if orientation == "landscape":
        clauses.append("m.width>m.height")
    if orientation == "portrait":
        clauses.append("m.height>m.width")
    if orientation == "square":
        clauses.append("m.height=m.width")
    if start:
        clauses.append(metadata_support.DATE_HIGH+">=?")
        args.append(start)
    if end:
        clauses.append(metadata_support.DATE_LOW+"<=?")
        args.append(end)
    for person in people:
        clauses.append(
            "EXISTS(SELECT 1 FROM faces f WHERE f.media_id=m.id AND f.person_id=? AND f.status!='dismissed')"
        )
        args.append(person)
    if q:
        clauses.append("(m.name LIKE ? ESCAPE '\\' OR m.album LIKE ? ESCAPE '\\')")
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        args.extend(["%" + escaped + "%"] * 2)
    from .search import compile_search

    map_context = request.url.path == "/api/map-context"
    expression_sql, expression_args = compile_search(expression, ignore_geography=map_context)
    clauses.append(expression_sql)
    args.extend(expression_args)
    from .geo import add_location, add_selection

    if geo and (
        location != "any"
        or any(
            v is not None
            for v in [south, north, west, east, latitude, longitude, radius_km]
        )
    ):
        raise HTTPException(
            422, "Use either the geographic selection or legacy location parameters."
        )
    if map_context:
        geo, location = "", "any"
        south = north = west = east = latitude = longitude = radius_km = None
    add_selection(clauses, args, geo)

    add_location(
        clauses,
        args,
        location,
        south,
        north,
        west,
        east,
        latitude,
        longitude,
        radius_km,
    )
    where=" AND ".join(clauses)
    if hide_format_duplicates:
        from .library_view import collapse_format_pairs
        return collapse_format_pairs(where,args)
    return where,args


from . import metadata_support
metadata_support.register_routes(media_filters)
app.include_router(metadata_support.router)

@app.get("/api/places")
def places(filters=Depends(media_filters)):
    from .geo import summarize

    where, args = filters
    with db() as c:
        rows = c.execute(
            "SELECT m.id,m.latitude,m.longitude FROM media m WHERE "
            + where
            + " ORDER BY m.taken DESC,m.id",
            args,
        ).fetchall()
    return summarize(rows)


@app.get("/api/place-options")
def place_options(filters=Depends(media_filters)):
    where, args = filters
    with db() as c:
        rows = c.execute(
            "SELECT gp.country_id,gp.city_id FROM media m LEFT JOIN media_places gp ON gp.media_id=m.id WHERE "
            + where,
            args,
        ).fetchall()
        counts = {}
        for row in rows:
            for identity in row:
                if identity:
                    counts[identity] = counts.get(identity, 0) + 1
        options = [
            dict(r)
            for r in c.execute(
                "SELECT * FROM geographic_places ORDER BY kind DESC,label,country,id"
            )
        ]
        from .search_places import aliases
        for option in options:
            option["search_aliases"] = aliases(option)
            option["count"] = counts.get(option["id"], 0)
        coverage = c.execute(
            "SELECT count(*) total,sum(country_id IS NOT NULL) countries,sum(city_id IS NOT NULL) cities FROM media_places"
        ).fetchone()
        return dict(options=options, coverage=dict(coverage))


@app.get("/api/map-context")
@app.get("/api/map-results")
def map_results(request: Request, filters=Depends(media_filters)):
    from .map_results import map_response
    return map_response(filters, request)


@app.get("/api/map/labels")
def map_labels(
    south: float = Query(ge=-90,le=90), north: float = Query(ge=-90,le=90),
    west: float = Query(ge=-180,le=180), east: float = Query(ge=-180,le=180),
    span: float = Query(gt=0,le=360),
):
    if south > north or west > east:
        raise HTTPException(422,"Invalid map viewport bounds")
    from .map_labels import city_labels
    return dict(cities=city_labels(south,north,west,east,span))


@app.get("/api/map/countries")
def country_map():
    path = DATA / "maps" / "countries.geojson"
    if not path.is_file():
        raise HTTPException(404, "Offline boundaries not installed")
    return FileResponse(
        path,
        media_type="application/geo+json",
        headers={"Cache-Control": "private, max-age=86400"},
    )


@app.get("/api/map/land")
def map_land():
    path = DATA / "maps" / "land.geojson"
    if not path.is_file():
        raise HTTPException(404, "Offline coastline not installed")
    return FileResponse(
        path,
        media_type="application/geo+json",
        headers={"Cache-Control": "private, max-age=86400"},
    )


@app.get("/api/media")
def media(
    filters=Depends(media_filters),
    order: Literal["asc", "desc"] = "desc",
    sort_by: Literal["capture", "file"] = "capture",
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=80, ge=1, le=200),
):
    where, args = filters
    with db() as c:
        total = c.execute(
            "SELECT count(*) FROM media m WHERE " + where, args
        ).fetchone()[0]
        sorting = f"m.taken IS NULL,m.taken {order.upper()},m.id" if sort_by=='capture' else f"coalesce((SELECT file_created FROM media_original_metadata om WHERE om.media_id=m.id),m.mtime) IS NULL,coalesce((SELECT file_created FROM media_original_metadata om WHERE om.media_id=m.id),m.mtime) {order.upper()},m.id"
        rows = c.execute(
            "SELECT m.id,m.database_id,m.source_id,m.album_id,(SELECT alias FROM library_databases WHERE id=m.database_id) database_alias,m.name,m.phone,m.album,m.kind,m.taken,m.width,m.height,m.duration,m.latitude,m.longitude FROM media m WHERE "
            + where
            + f" ORDER BY {sorting} LIMIT ? OFFSET ?",
            args + [limit, offset],
        ).fetchall()
        items = [dict(r) for r in rows]
        for item in items:
            item.update(location_details(c, item["id"]))
            item.update(metadata_support.details(c, item["id"]))
        return dict(total=total, items=items)


def location_details(c, identity):
    row = c.execute(
        "SELECT city.label city,country.label country FROM media_places mp LEFT JOIN geographic_places city ON city.id=mp.city_id LEFT JOIN geographic_places country ON country.id=mp.country_id WHERE mp.media_id=?",
        (identity,),
    ).fetchone()
    names = [
        r[0]
        for r in c.execute(
            "SELECT DISTINCT p.name FROM faces f JOIN people p ON p.id=f.person_id WHERE f.media_id=? AND f.status!='dismissed' AND trim(coalesce(p.name,''))!='' ORDER BY p.name",
            (identity,),
        )
    ]
    return dict(
        city=row["city"] if row else None,
        country=row["country"] if row else None,
        people_names=names,
    )


@app.get("/api/search/validate")
def validate_search(expression: str = Query(default="", max_length=4000)):
    from .search import compile_search

    _, _, canonical = compile_search(expression, canonical=True)
    return {"valid": True, "expression": canonical}


def get_media(identity):
    with db() as c:
        row = c.execute("SELECT m.* FROM media m WHERE id=? AND " + source_management.VISIBLE, (identity,)).fetchone()
    if row is None:
        raise HTTPException(404, "Media not found")
    return row


@app.get("/api/media/{identity}")
def detail(identity: str):
    row = dict(get_media(identity))
    row.pop("path", None)
    row["metadata"] = json.loads(row["metadata"] or "{}")
    with db() as c:
        hierarchy = c.execute("""
            SELECT s.relative_path source_relative_path,a.relative_path album_relative_path
            FROM library_sources s LEFT JOIN library_albums a ON a.source_id=s.id AND a.id=?
            WHERE s.id=?
        """, (row.get("album_id"), row.get("source_id"))).fetchone()
        if hierarchy:
            row.update(dict(hierarchy))
        row.update(location_details(c, identity))
        row.update(metadata_support.details(c, identity))
        row["faces"] = [
            dict(r)
            for r in c.execute(
                "SELECT f.id,f.person_id,f.timestamp,f.bbox,f.bbox_width,f.bbox_height,p.name FROM faces f LEFT JOIN people p ON p.id=f.person_id WHERE f.media_id=? AND f.status!='dismissed'",
                (identity,),
            )
        ]
    return row



@app.get("/api/media/{identity}/neighbors")
def media_neighbors(identity:str,filters=Depends(media_filters),order:Literal["asc","desc"]="desc",sort_by:Literal["capture","file"]="capture"):
    where,args=filters
    sorting=f"m.taken IS NULL,m.taken {order.upper()},m.id" if sort_by=='capture' else f"coalesce((SELECT file_created FROM media_original_metadata om WHERE om.media_id=m.id),m.mtime) IS NULL,coalesce((SELECT file_created FROM media_original_metadata om WHERE om.media_id=m.id),m.mtime) {order.upper()},m.id"
    with db() as c:
        rows=c.execute(f"""WITH ranked AS (
          SELECT m.id,lag(m.id) OVER (ORDER BY {sorting}) previous,
          lead(m.id) OVER (ORDER BY {sorting}) next,
          row_number() OVER (ORDER BY {sorting}) position,count(*) OVER () total
          FROM media m WHERE {where}
        ), center AS (SELECT position FROM ranked WHERE id=?)
        SELECT * FROM ranked WHERE position BETWEEN
          (SELECT position-3 FROM center) AND (SELECT position+3 FROM center)
        ORDER BY position""",[*args,identity]).fetchall()
    window=[dict(row) for row in rows]
    result=next((row for row in window if row['id']==identity),dict(id=identity,previous=None,next=None,position=None,total=0))
    return {**result,"window":window}


@app.get("/api/media/{identity}/thumbnail")
def thumbnail(identity: str, size: Literal["small", "medium", "large"] = "medium"):
    get_media(identity)
    path = DATA / "thumbs" / f"{identity}-{size}.jpg"
    if not path.exists():
        raise HTTPException(404, "Thumbnail not ready")
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@app.get("/api/media/{identity}/display-original")
def display_original(identity: str):
    from .viewer import photo_response
    return photo_response(get_media(identity))


@app.get("/api/media/{identity}/original")
def get_original(identity: str, download: bool = False):
    row = get_media(identity)
    try:
        path = original(row)
    except ValueError:
        raise HTTPException(403, "Invalid source")
    except (RuntimeError, OSError):
        raise HTTPException(503, "Network source unavailable or saved access needs updating") from None
    if not path.is_file():
        raise HTTPException(404, "Source offline or missing")
    return FileResponse(path, filename=row["name"], content_disposition_type="attachment" if download else "inline")


preview_lock = threading.Lock()


@app.post("/api/media/{identity}/preview")
def create_preview(identity: str):
    row = get_media(identity)
    if row["kind"] != "video":
        raise HTTPException(400, "Not a video")
    from .indexer import ff

    target = DATA / "previews" / f"{identity}.mp4"
    target.parent.mkdir(exist_ok=True)
    with preview_lock:
        if not target.exists():
            temp = target.with_suffix(".partial.mp4")
            try:
                result = ff(
                    [
                        "-y",
                        "-i",
                        str(original(row)),
                        "-t",
                        "60",
                        "-vf",
                        "scale=960:960:force_original_aspect_ratio=decrease:force_divisible_by=2",
                        "-c:v",
                        "libx264",
                        "-preset",
                        "veryfast",
                        "-crf",
                        "25",
                        "-pix_fmt",
                        "yuv420p",
                        "-c:a",
                        "aac",
                        "-movflags",
                        "+faststart",
                        str(temp),
                    ],
                    180,
                )
                if result.returncode:
                    raise RuntimeError("Preview encoding failed")
                temp.replace(target)
            except Exception as e:
                temp.unlink(missing_ok=True)
                raise HTTPException(500, str(e))
    return dict(url=f"/api/media/{identity}/preview", max_seconds=60)


@app.get("/api/media/{identity}/preview")
def preview(identity: str):
    get_media(identity)
    path = DATA / "previews" / f"{identity}.mp4"
    if not path.exists():
        raise HTTPException(404, "Generate preview first")
    return FileResponse(path, media_type="video/mp4")


@app.get("/api/people")
def people():
    with db() as c:
        result = [
            dict(r)
            for r in c.execute(
                f"SELECT p.id,p.name,count(f.id) count,min(f.id) cover FROM people p JOIN faces f ON f.person_id=p.id WHERE f.status!='dismissed' AND EXISTS(SELECT 1 FROM media m WHERE m.id=f.media_id AND m.status='ready' AND {source_management.VISIBLE}) AND NOT EXISTS(SELECT 1 FROM unknown_faces u WHERE u.face_id=f.id) GROUP BY p.id ORDER BY p.name IS NULL,p.name,count(f.id) DESC"
            )
        ]
        unassigned = c.execute(
            f"SELECT count(*) count,min(id) cover FROM faces WHERE person_id IS NULL AND status='manual' AND EXISTS(SELECT 1 FROM media m WHERE m.id=faces.media_id AND m.status='ready' AND {source_management.VISIBLE}) AND NOT EXISTS(SELECT 1 FROM unknown_faces u WHERE u.face_id=faces.id)"
        ).fetchone()
        if unassigned["count"]:
            result.insert(
                0,
                dict(
                    id=0,
                    name="Unassigned faces",
                    count=unassigned["count"],
                    cover=unassigned["cover"],
                ),
            )
        bucket = c.execute(
            f"SELECT count(*) count,min(f.id) cover FROM faces f JOIN unknown_faces u ON u.face_id=f.id WHERE f.status!='dismissed' AND EXISTS(SELECT 1 FROM media m WHERE m.id=f.media_id AND m.status='ready' AND {source_management.VISIBLE})"
        ).fetchone()
        if bucket["count"]:
            result.insert(
                0,
                dict(
                    id=-1,
                    name="Unknown People",
                    count=bucket["count"],
                    cover=bucket["cover"],
                ),
            )
        return result


@app.get("/api/faces")
def faces(person: int | None = None, unknown: bool = False):
    where = f"status!='dismissed' AND EXISTS(SELECT 1 FROM media m WHERE m.id=faces.media_id AND m.status='ready' AND {source_management.VISIBLE})"
    args = []
    if person == -1:
        where += " AND EXISTS(SELECT 1 FROM unknown_faces u WHERE u.face_id=faces.id)"
    elif person is not None:
        where += " AND person_id=?"
        args.append(person)
    if unknown:
        where += " AND person_id IS NULL AND NOT EXISTS(SELECT 1 FROM unknown_faces u WHERE u.face_id=faces.id)"
    with db() as c:
        return [
            dict(r)
            for r in c.execute(
                "SELECT id,media_id,person_id,timestamp,status FROM faces WHERE "
                + where
                + " ORDER BY media_id,timestamp LIMIT 2000",
                args,
            )
        ]


@app.get("/api/faces/{identity}/thumbnail")
def face_thumb(identity: str):
    with db() as c:
        face=c.execute("SELECT media_id FROM faces WHERE id=?",(identity,)).fetchone()
    if not face: raise HTTPException(404,"Face not found")
    get_media(face[0])
    with db() as c:
        row = c.execute("SELECT id FROM faces WHERE id=?", (identity,)).fetchone()
    if row is None:
        raise HTTPException(404, "Face not found")
    path = DATA / "faces" / f"{identity}.jpg"
    if not path.exists():
        raise HTTPException(404, "Face crop unavailable")
    return FileResponse(path, media_type="image/jpeg")


@app.get("/api/people-name-records")
def people_name_records():
    with db() as c:
        rows=[dict(r) for r in c.execute("SELECT p.id,p.name,count(f.id) faces,min(f.id) cover FROM people p LEFT JOIN faces f ON f.person_id=p.id WHERE trim(coalesce(p.name,''))!='' GROUP BY p.id ORDER BY p.name,p.id")]
    counts={}
    for row in rows:
        key=row['name'].strip().casefold()
        counts[key]=counts.get(key,0)+1
    for row in rows:
        row['conflict']=counts[row['name'].strip().casefold()]>1
    return rows


@app.post("/api/people/{person}/clear-unused-name")
def clear_unused_name(person:int):
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        row=c.execute("SELECT * FROM people WHERE id=?",(person,)).fetchone()
        if row is None: raise HTTPException(404,"Person not found")
        if c.execute("SELECT 1 FROM faces WHERE person_id=? LIMIT 1",(person,)).fetchone():
            raise HTTPException(409,"This record has faces. Rename it instead of clearing it.")
        c.execute("INSERT INTO actions(description,previous) VALUES(?,?)",('Clear unused person name',json.dumps({'people':[dict(row)]})))
        c.execute("UPDATE people SET name=NULL WHERE id=?",(person,))
    return {'ok':True}


class Rename(BaseModel):
    name: str = Field(min_length=1, max_length=100)


@app.post("/api/people/{person}/name")
def rename(person: int, body: Rename):
    if not body.name.strip():
        raise HTTPException(400, "Name cannot be blank")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        previous = c.execute("SELECT * FROM people WHERE id=?", (person,)).fetchone()
        if previous is None:
            raise HTTPException(404, "Person not found")
        c.execute(
            "INSERT INTO actions(description,previous) VALUES(?,?)",
            (
                "Rename person",
                json.dumps(
                    {
                        "people": [dict(previous)],
                        "unknown_faces": [
                            r[0] for r in c.execute("SELECT face_id FROM unknown_faces")
                        ],
                    }
                ),
            ),
        )
        duplicate = c.execute(
            "SELECT id,name FROM people WHERE id!=?", (person,)
        ).fetchall()
        if any(
            (r["name"] or "").casefold() == body.name.strip().casefold()
            for r in duplicate
        ):
            raise HTTPException(
                409,
                "That name already exists. Move faces into the existing person instead.",
            )
        c.execute("UPDATE people SET name=? WHERE id=?", (body.name.strip(), person))
        c.execute(
            "DELETE FROM unknown_faces WHERE face_id IN (SELECT id FROM faces WHERE person_id=?)",
            (person,),
        )
        c.execute("DELETE FROM face_suggestions")
    return {"ok": True}


class Correction(BaseModel):
    from_suggestion: bool = False
    expected_person: int | None = None
    face_ids: list[str] = Field(min_length=1, max_length=2000)
    action: Literal["move", "split", "unknown", "dismiss"]
    target: int | None = None
    name: str | None = Field(default=None, max_length=100)


@app.post("/api/faces/correct")
def correct(body: Correction):
    ids = list(dict.fromkeys(body.face_ids))
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        previous = c.execute(
            "SELECT id,person_id,status FROM faces WHERE id IN ("
            + ",".join("?" for _ in ids)
            + ")",
            ids,
        ).fetchall()
        if len(previous) != len(ids):
            raise HTTPException(404, "Face not found; no changes made")
        if body.expected_person is not None and any(row['person_id'] != body.expected_person for row in previous):
            raise HTTPException(409, "This face assignment changed. Refresh before correcting it.")
        if body.from_suggestion:
            if (
                body.action != "move"
                or len(ids) != 1
                or c.execute(
                    "SELECT 1 FROM face_suggestions s JOIN faces f ON f.id=s.face_id "
                    "LEFT JOIN people p ON p.id=f.person_id "
                    "WHERE s.face_id=? AND s.person_id=? AND f.status!='dismissed' "
                    "AND trim(coalesce(p.name,''))=''",
                    (ids[0], body.target),
                ).fetchone()
                is None
            ):
                raise HTTPException(
                    409, "This suggestion changed. Reevaluate to refresh it."
                )
        target = body.target
        if body.action == "move" and (
            target is None
            or c.execute("SELECT id FROM people WHERE id=?", (target,)).fetchone()
            is None
        ):
            raise HTTPException(400, "Choose an existing person")
        if body.action == "split":
            target = c.execute(
                "INSERT INTO people(name) VALUES(?)",
                ((body.name or "").strip() or None,),
            ).lastrowid
        if body.action in ("unknown", "dismiss"):
            target = None
        state = "dismissed" if body.action == "dismiss" else "manual"
        queue_before = [r[0] for r in c.execute("SELECT face_id FROM unknown_faces")]
        rejects_before = [dict(r) for r in c.execute("SELECT * FROM face_rejections")]
        c.execute(
            "INSERT INTO actions(description,previous) VALUES(?,?)",
            (
                body.action,
                json.dumps(
                    {
                        "faces": [dict(r) for r in previous],
                        "unknown_faces": queue_before,
                        "rejections": rejects_before,
                    }
                ),
            ),
        )
        for row in previous:
            if row["person_id"] is not None and row["person_id"] != target:
                c.execute(
                    "INSERT OR IGNORE INTO face_rejections VALUES(?,?)",
                    (row["id"], row["person_id"]),
                )
            c.execute("DELETE FROM unknown_faces WHERE face_id=?", (row["id"],))
            if target is not None:
                c.execute(
                    "DELETE FROM face_rejections WHERE face_id=? AND person_id=?",
                    (row["id"], target),
                )
        c.executemany(
            "DELETE FROM face_suggestions WHERE face_id=?", [(i,) for i in ids]
        )
        if body.from_suggestion:
            c.execute("INSERT OR REPLACE INTO review_approvals(face_id,person_id) VALUES(?,?)", (ids[0], target))
        c.executemany(
            "UPDATE faces SET person_id=?,status=? WHERE id=?",
            [(target, state, i) for i in ids],
        )
    return dict(ok=True, person_id=target)


@app.post("/api/undo")
def undo():
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        action = c.execute(
            "SELECT * FROM actions WHERE undone=0 ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if action is None:
            raise HTTPException(400, "Nothing to undo")
        previous = json.loads(action["previous"])
        if "review_batch" in previous:
            from .bulk_review import undo_batch
            undo_batch(c, previous)
            c.execute("UPDATE actions SET undone=1 WHERE id=?", (action["id"],))
            return dict(ok=True, description=action["description"])
        if 'metadata' in previous:
            metadata_support.undo(c, previous['metadata'])
            c.execute("UPDATE actions SET undone=1 WHERE id=?", (action['id'],))
            return dict(ok=True,description=action['description'])
        for f in previous.get("faces", []):
            c.execute(
                "UPDATE faces SET person_id=?,status=? WHERE id=?",
                (f["person_id"], f["status"], f["id"]),
            )
        for p in previous.get("people", []):
            c.execute("UPDATE people SET name=? WHERE id=?", (p["name"], p["id"]))
        if "unknown_faces" in previous:
            c.execute("DELETE FROM unknown_faces")
            c.executemany(
                "INSERT INTO unknown_faces VALUES(?)",
                [(i,) for i in previous["unknown_faces"]],
            )
        if "rejections" in previous:
            c.execute("DELETE FROM face_rejections")
            c.executemany(
                "INSERT INTO face_rejections VALUES(?,?)",
                [(r["face_id"], r["person_id"]) for r in previous["rejections"]],
            )
        if previous.get("auto_sync"):
            for f in previous.get("faces", []):
                c.execute("INSERT OR IGNORE INTO face_rejections VALUES(?,?)", (f["id"],f["target"]))
                if f.get("unknown"): c.execute("INSERT OR IGNORE INTO unknown_faces VALUES(?)",(f["id"],))
        c.execute("DELETE FROM face_suggestions")
        for person in previous.get("created_people", []):
            c.execute(
                "DELETE FROM people WHERE id=? AND NOT EXISTS(SELECT 1 FROM faces WHERE person_id=?)",
                (person, person),
            )
        c.execute("UPDATE actions SET undone=1 WHERE id=?", (action["id"],))
    return dict(ok=True, description=action["description"])


from .people_review import router as review_router

app.include_router(review_router)
from .manual_faces import router as manual_router

app.include_router(manual_router)

DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if DIST.is_dir():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")
