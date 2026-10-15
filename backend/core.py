import os, sqlite3
from pathlib import Path

DATA = Path(os.environ.get("DAHAN_DATA", "D:/DahanPhotoLibraryData/prototype"))
ROOT = Path(os.environ.get("DAHAN_SOURCE", "D:/DahanPhotosSync"))
PHONES = ("Yoav14ProMax", "Bar\u2019s iPhone", "iPhoneX Hila")


def database_dir():
    return Path(os.environ.get("DAHAN_DATABASE_DIR") or DATA)


def database_path(name):
    path = database_dir() / name
    if os.environ.get("DAHAN_REQUIRE_EXISTING_DATABASE") == "1" and (not path.is_file() or path.stat().st_size == 0):
        raise OSError("Expected library database is unavailable: " + str(path))
    return path


def db():
    path = database_path("catalogue.sqlite")
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path, timeout=30)
    c.row_factory = sqlite3.Row
    from .geo import distance_km

    c.create_function("distance_km", 4, distance_km, deterministic=True)
    from .metadata_support import bounds
    c.create_function("capture_low", 1, lambda value: bounds(value)[0], deterministic=True)
    c.create_function("capture_high", 1, lambda value: bounds(value)[1], deterministic=True)
    c.execute("PRAGMA foreign_keys=ON")
    return c


def init():
    with db() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(
            """
        CREATE TABLE IF NOT EXISTS media(id TEXT PRIMARY KEY,path TEXT UNIQUE,phone TEXT,album TEXT,name TEXT,kind TEXT,extension TEXT,bytes INTEGER,mtime REAL,sha TEXT,taken TEXT,width INTEGER,height INTEGER,duration REAL,latitude REAL,longitude REAL,metadata TEXT,status TEXT DEFAULT 'pending',error TEXT,face_status TEXT DEFAULT 'pending');
        CREATE INDEX IF NOT EXISTS media_scope ON media(phone,album,taken);
        CREATE TABLE IF NOT EXISTS geographic_places(id TEXT PRIMARY KEY,label TEXT,kind TEXT,country TEXT,latitude REAL,longitude REAL,aliases TEXT);
        CREATE TABLE IF NOT EXISTS media_places(media_id TEXT PRIMARY KEY REFERENCES media(id),country_id TEXT,city_id TEXT,distance_km REAL,version TEXT);
        CREATE INDEX IF NOT EXISTS media_places_country ON media_places(country_id,media_id);
        CREATE INDEX IF NOT EXISTS media_places_city ON media_places(city_id,media_id);
        CREATE TABLE IF NOT EXISTS people(id INTEGER PRIMARY KEY,name TEXT);
        CREATE TABLE IF NOT EXISTS faces(id TEXT PRIMARY KEY,media_id TEXT REFERENCES media(id),person_id INTEGER REFERENCES people(id),timestamp REAL,bbox TEXT,embedding BLOB,status TEXT DEFAULT 'suggested');
        CREATE INDEX IF NOT EXISTS faces_person ON faces(person_id);
        CREATE INDEX IF NOT EXISTS faces_media ON faces(media_id,status,person_id);
        CREATE INDEX IF NOT EXISTS media_ready_taken ON media(status,taken,id);
        CREATE TABLE IF NOT EXISTS unknown_faces(face_id TEXT PRIMARY KEY REFERENCES faces(id));
        CREATE TABLE IF NOT EXISTS face_rejections(face_id TEXT REFERENCES faces(id),person_id INTEGER REFERENCES people(id),PRIMARY KEY(face_id,person_id));
        CREATE TABLE IF NOT EXISTS high_confidence_faces(face_id TEXT PRIMARY KEY REFERENCES faces(id));
        CREATE TABLE IF NOT EXISTS review_approvals(face_id TEXT PRIMARY KEY REFERENCES faces(id),person_id INTEGER REFERENCES people(id),created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS face_suggestions(face_id TEXT PRIMARY KEY REFERENCES faces(id),person_id INTEGER REFERENCES people(id),score REAL,margin REAL);
        CREATE TABLE IF NOT EXISTS actions(id INTEGER PRIMARY KEY,description TEXT,previous TEXT,undone INTEGER DEFAULT 0,created TEXT DEFAULT CURRENT_TIMESTAMP);
        """
        )

        c.executescript("""
        CREATE TABLE IF NOT EXISTS catalogue_clock(id INTEGER PRIMARY KEY,revision INTEGER NOT NULL);
        INSERT OR IGNORE INTO catalogue_clock VALUES(1,0);
        """)
        for table in ("media","faces","media_places"):
            for event in ("INSERT","UPDATE","DELETE"):
                c.execute(f"CREATE TRIGGER IF NOT EXISTS clock_{table}_{event} AFTER {event} ON {table} BEGIN UPDATE catalogue_clock SET revision=revision+1 WHERE id=1; END")

        columns = {row[1] for row in c.execute("PRAGMA table_info(faces)")}
        for name in ("bbox_width", "bbox_height"):
            if name not in columns:
                c.execute(f"ALTER TABLE faces ADD COLUMN {name} INTEGER")

        from .source_management import migrate
        migrate(c)
        from .metadata_support import migrate as migrate_metadata
        migrate_metadata(c)

def original(row):
    from .source_management import source_root
    from .network_access import ensure_access
    base = source_root(row)
    ensure_access(base)
    p = Path(row["path"]).resolve()
    if not p.is_relative_to(base):
        raise ValueError("Source outside its registered root")
    lexical = Path(row["path"])
    for ancestor in (lexical, *lexical.parents):
        if ancestor.is_relative_to(base) and (ancestor.is_symlink() or ancestor.is_junction()):
            raise ValueError("Source must not traverse links")
    return p
