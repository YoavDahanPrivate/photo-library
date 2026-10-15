import hashlib, io, json, random, re, subprocess, time, urllib.request
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
import cv2, numpy as np, imageio_ffmpeg, pillow_heif
from PIL import Image, ImageOps, ExifTags
from .core import DATA, ROOT, PHONES, db, init, original

pillow_heif.register_heif_opener()
IMAGES = {
    ".jpg",
    ".jpeg",
    ".heic",
    ".heif",
    ".png",
    ".gif",
    ".webp",
    ".tif",
    ".tiff",
    ".dng",
    ".bmp",
    ".avif",
}
VIDEOS = {".mov", ".mp4", ".m4v", ".avi", ".mkv", ".mts", ".m2ts", ".3gp", ".webm"}
MODELS = DATA.parent / "models"
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def choose(paths, limit=200):
    buckets = defaultdict(list)
    for p in paths:
        buckets[(p.suffix.lower(), p.parent.name)].append(p)
    rng = random.Random(20260910)
    keys = sorted(buckets)
    rng.shuffle(keys)
    queues = []
    for key in keys:
        values = sorted(buckets[key])
        rng.shuffle(values)
        queues.append(deque(values))
    result = []
    while queues and len(result) < limit:
        again = []
        for q in queues:
            if len(result) == limit:
                break
            result.append(q.popleft())
            if q:
                again.append(q)
        queues = again
    return result


def sample():
    from .source_management import inventory
    import uuid
    files=inventory()
    grouped=defaultdict(list)
    for path,entry in files.items(): grouped[entry["source_id"]].append(Path(path))
    report=[]
    with db() as c:
        for sid,paths in grouped.items():
            selected=choose(paths);formats=defaultdict(int)
            for path in selected:
                entry=files[str(path)];cols=list(entry)
                c.execute("INSERT OR IGNORE INTO media(id,"+",".join(cols)+") VALUES("+",".join("?" for _ in range(len(cols)+1))+")",[uuid.uuid4().hex[:24],*entry.values()])
                formats[path.suffix.lower()]+=1
            report.append(dict(phone=files[str(paths[0])]["phone"],source_id=sid,available=len(paths),selected=len(selected),formats=dict(formats)))
    (DATA/"sample-report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report),flush=True)


def models():
    MODELS.mkdir(exist_ok=True)
    manifest = []
    for name, remote in [
        ("yunet", "face_detection_yunet/face_detection_yunet_2023mar.onnx"),
        ("sface", "face_recognition_sface/face_recognition_sface_2021dec.onnx"),
    ]:
        url = "https://huggingface.co/opencv/opencv_zoo/resolve/main/models/" + remote
        dest = MODELS / (name + ".onnx")
        if not dest.exists():
            urllib.request.urlretrieve(url, dest.with_suffix(".download"))
            dest.with_suffix(".download").replace(dest)
        manifest.append(
            dict(
                file=dest.name,
                url=url,
                sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),
            )
        )
        license_file = MODELS / (name + "-LICENSE")
        if not license_file.exists():
            urllib.request.urlretrieve(
                "https://raw.githubusercontent.com/opencv/opencv_zoo/main/models/"
                + remote.split("/")[0]
                + "/LICENSE",
                license_file,
            )
    (MODELS / "manifest.json").write_text(json.dumps(manifest, indent=2))


def ff(args, timeout=90):
    return subprocess.run(
        [FFMPEG, "-hide_banner", "-nostdin", *args],
        capture_output=True,
        timeout=timeout,
    )


def photo(path):
    with Image.open(path) as source:
        exif = source.getexif()
        tags = dict(exif)
        try:
            tags.update(exif.get_ifd(34665))
        except Exception:
            pass
        raw = {
            ExifTags.TAGS.get(k, str(k)): str(v)[:1000]
            for k, v in tags.items()
            if not isinstance(v, bytes)
        }
        taken = None
        for key in (36867, 36868, 306):
            try:
                taken = datetime.strptime(
                    str(tags[key])[:19], "%Y:%m:%d %H:%M:%S"
                ).isoformat()
                break
            except (KeyError, ValueError):
                pass
        lat = lon = None
        try:
            gps = exif.get_ifd(34853)

            def deg(v):
                return float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600

            lat = deg(gps[2]) * (-1 if gps.get(1) == "S" else 1)
            lon = deg(gps[4]) * (-1 if gps.get(3) == "W" else 1)
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            pass
        image = ImageOps.exif_transpose(source).convert("RGB")
    return [(0, image)], dict(
        taken=taken,
        latitude=lat,
        longitude=lon,
        metadata=raw,
        width=image.width,
        height=image.height,
        duration=None,
    )


def video(path):
    text = ff(["-i", str(path)], 30).stderr.decode(errors="replace")
    match = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", text)
    duration = (
        sum(float(n) * f for n, f in zip(match.groups(), (3600, 60, 1))) if match else 0
    )
    date = re.search(r"creation_time\s*:\s*(\S+)", text)
    gps = re.search(
        r"(?:location(?:-eng)?|com.apple.quicktime.location.ISO6709)\s*:\s*([+-]\d+\.\d+)([+-]\d+\.\d+)",
        text,
    )
    size = re.search(r"Video:.*? (\d{2,6})x(\d{2,6})(?:[ ,])", text)
    width, height = map(int, size.groups()) if size else (0, 0)
    rotation = re.search(r"rotation of (-?\d+(?:\.\d+)?)", text)
    if rotation and round(float(rotation.group(1))) % 180:
        width, height = height, width
    frames = []
    for t in sorted(set(round(duration * f, 3) for f in (0.15, 0.5, 0.85))):
        r = ff(
            [
                "-ss",
                str(t),
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-vf",
                "scale=1280:1280:force_original_aspect_ratio=decrease",
                "-f",
                "image2pipe",
                "-vcodec",
                "mjpeg",
                "pipe:1",
            ]
        )
        if r.returncode or not r.stdout:
            raise RuntimeError(r.stderr.decode(errors="replace")[-1000:])
        frames.append((t, Image.open(io.BytesIO(r.stdout)).convert("RGB")))
    return frames, dict(
        taken=date.group(1) if date else None,
        latitude=float(gps.group(1)) if gps else None,
        longitude=float(gps.group(2)) if gps else None,
        metadata={"ffmpeg_probe": text[:16000]},
        duration=duration,
        width=width or frames[0][1].width,
        height=height or frames[0][1].height,
    )


class Recognition:
    def __init__(self):
        cv2.setNumThreads(2)
        self.detector = cv2.FaceDetectorYN.create(
            str(MODELS / "yunet.onnx"), "", (320, 320), 0.9, 0.3, 1000
        )
        self.encoder = cv2.FaceRecognizerSF.create(str(MODELS / "sface.onnx"), "")

    def process(self, mid, t, image):
        frame = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
        scale = min(1, 960 / max(frame.shape[:2]))
        if scale < 1:
            frame = cv2.resize(
                frame, (round(frame.shape[1] * scale), round(frame.shape[0] * scale))
            )
        self.detector.setInputSize((frame.shape[1], frame.shape[0]))
        _, faces = self.detector.detect(frame)
        if faces is None:
            return
        with db() as c:
            for i, face in enumerate(faces):
                x, y, w, h = face[:4]
                if min(w, h) < 28:
                    continue
                vec = (
                    self.encoder.feature(self.encoder.alignCrop(frame, face))
                    .flatten()
                    .astype(np.float32)
                )
                vec /= max(float(np.linalg.norm(vec)), 1e-9)
                fid = hashlib.sha256(f"{mid}:{t}:{i}".encode()).hexdigest()[:24]
                pad = max(w, h) * 0.2
                crop = frame[
                    max(0, int(y - pad)) : min(frame.shape[0], int(y + h + pad)),
                    max(0, int(x - pad)) : min(frame.shape[1], int(x + w + pad)),
                ]
                if not crop.size:
                    continue
                ok, jpg = cv2.imencode(".jpg", crop)
                if ok:
                    (DATA / "faces" / f"{fid}.jpg").write_bytes(jpg.tobytes())
                c.execute(
                    "INSERT OR IGNORE INTO faces(id,media_id,timestamp,bbox,embedding,bbox_width,bbox_height) VALUES(?,?,?,?,?,?,?)",
                    (
                        fid,
                        mid,
                        t,
                        json.dumps([float(v / scale) for v in face[:4]]),
                        vec.tobytes(),
                        image.width,
                        image.height,
                    ),
                )


def cluster():
    with db() as c:
        known = c.execute(
            "SELECT * FROM faces WHERE person_id IS NOT NULL AND status!='dismissed' AND embedding IS NOT NULL"
        ).fetchall()
        vectors = [np.frombuffer(r["embedding"], np.float32) for r in known]
        persons = [r["person_id"] for r in known]
        for row in c.execute(
            "SELECT * FROM faces WHERE person_id IS NULL AND status='suggested' ORDER BY id"
        ).fetchall():
            v = np.frombuffer(row["embedding"], np.float32)
            person = None
            if vectors:
                scores = np.asarray(vectors) @ v
                index = int(np.argmax(scores))
                if scores[index] >= 0.55:
                    person = persons[index]
            if person is None:
                person = c.execute("INSERT INTO people(name) VALUES(NULL)").lastrowid
            c.execute("UPDATE faces SET person_id=? WHERE id=?", (person, row["id"]))
            vectors.append(v)
            persons.append(person)


def faces_only():
    """Enrich cached previews without repeating completed source decoding."""
    init()
    models()
    recognizer = Recognition()
    started = time.monotonic()
    with db() as c:
        rows = c.execute(
            "SELECT * FROM media WHERE status='ready' AND face_status!='ready' ORDER BY phone,name"
        ).fetchall()
    for n, row in enumerate(rows, 1):
        try:
            if row["kind"] == "photo":
                paths = [(0, DATA / "thumbs" / f'{row["id"]}-large.jpg')]
            else:
                times = sorted(
                    set(round((row["duration"] or 0) * f, 3) for f in (0.15, 0.5, 0.85))
                )
                paths = [
                    (t, DATA / "frames" / f'{row["id"]}-{i}.jpg')
                    for i, t in enumerate(times)
                ]
            for t, path in paths:
                with Image.open(path) as image:
                    recognizer.process(row["id"], t, image.convert("RGB"))
            with db() as c:
                c.execute(
                    "UPDATE media SET face_status='ready',error=NULL WHERE id=?",
                    (row["id"],),
                )
        except Exception as e:
            with db() as c:
                c.execute(
                    "UPDATE media SET face_status='error',error=? WHERE id=?",
                    (str(e)[:2000], row["id"]),
                )
        if n % 25 == 0 or n == len(rows):
            cluster()
            print(
                json.dumps(
                    dict(
                        faces_processed=n,
                        total=len(rows),
                        seconds=round(time.monotonic() - started, 1),
                    )
                ),
                flush=True,
            )
    with db() as c:
        report = dict(
            seconds=round(time.monotonic() - started, 1),
            face_count=c.execute("SELECT count(*) FROM faces").fetchone()[0],
            group_count=c.execute("SELECT count(*) FROM people").fetchone()[0],
            errors=[
                dict(r)
                for r in c.execute(
                    "SELECT id,error FROM media WHERE face_status='error'"
                )
            ],
        )
    (DATA / "face-report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps(report), flush=True)


def main():
    init()
    for name in ("thumbs", "faces", "frames", "previews"):
        (DATA / name).mkdir(exist_ok=True)
    with db() as c:
        existing = c.execute("SELECT count(*) FROM media").fetchone()[0]
    if not existing:
        sample()
    recognizer = None
    try:
        if not all((MODELS / (n + ".onnx")).exists() for n in ("yunet", "sface")):
            if "--offline" not in __import__("sys").argv:
                models()
        if all((MODELS / (n + ".onnx")).exists() for n in ("yunet", "sface")):
            recognizer = Recognition()
    except Exception as e:
        print("Face models unavailable: " + str(e), flush=True)
    started = time.monotonic()
    with db() as c:
        rows = c.execute(
            "SELECT * FROM media WHERE status!='ready' OR face_status!='ready' ORDER BY phone,kind,name"
        ).fetchall()
    for n, row in enumerate(rows, 1):
        try:
            path = original(row)
            before = path.stat()
            if time.time() - before.st_mtime < 30:
                continue
            with path.open("rb") as handle:
                sha = hashlib.file_digest(handle, "sha256").hexdigest()
            frames, info = photo(path) if row["kind"] == "photo" else video(path)
            after = path.stat()
            if (before.st_mtime_ns, before.st_size) != (
                after.st_mtime_ns,
                after.st_size,
            ):
                raise RuntimeError("Source changed; retry later")
            image = frames[0][1]
            for name, edge in [("small", 240), ("medium", 640), ("large", 1600)]:
                copy = image.copy()
                copy.thumbnail((edge, edge), Image.Resampling.LANCZOS)
                dest = DATA / "thumbs" / f'{row["id"]}-{name}.jpg'
                copy.save(dest.with_suffix(".tmp"), format="JPEG", quality=85)
                dest.with_suffix(".tmp").replace(dest)
            for i, (t, img) in enumerate(frames):
                if row["kind"] == "video":
                    img.save(DATA / "frames" / f'{row["id"]}-{i}.jpg', quality=85)
            with db() as c:
                c.execute(
                    "UPDATE media SET status='ready',error=NULL,sha=?,taken=?,width=?,height=?,duration=?,latitude=?,longitude=?,metadata=? WHERE id=?",
                    (
                        sha,
                        info["taken"],
                        info["width"],
                        info["height"],
                        info["duration"],
                        info["latitude"],
                        info["longitude"],
                        json.dumps(info["metadata"], ensure_ascii=False),
                        row["id"],
                    ),
                )
                from .metadata_support import record_embedded
                record_embedded(c, row['id'], info, before)
            try:
                if recognizer is not None:
                    for t, img in frames:
                        recognizer.process(row["id"], t, img)
                    with db() as c:
                        c.execute(
                            "UPDATE media SET face_status='ready' WHERE id=?",
                            (row["id"],),
                        )
            except Exception as e:
                with db() as c:
                    c.execute(
                        "UPDATE media SET face_status='error',error=? WHERE id=?",
                        (str(e)[:2000], row["id"]),
                    )
        except Exception as e:
            with db() as c:
                c.execute(
                    "UPDATE media SET status='error',error=? WHERE id=?",
                    (str(e)[:2000], row["id"]),
                )
        if n % 20 == 0 or n == len(rows):
            cluster()
            print(
                json.dumps(
                    dict(
                        processed=n,
                        total=len(rows),
                        seconds=round(time.monotonic() - started, 1),
                    )
                ),
                flush=True,
            )
    with db() as c:
        report = dict(
            seconds=round(time.monotonic() - started, 1),
            media=[
                dict(r)
                for r in c.execute(
                    "SELECT phone,kind,status,count(*) count FROM media GROUP BY phone,kind,status"
                )
            ],
            faces=c.execute("SELECT count(*) FROM faces").fetchone()[0],
            errors=[
                dict(r)
                for r in c.execute(
                    "SELECT id,name,error FROM media WHERE error IS NOT NULL"
                )
            ],
        )
    (DATA / "processing-report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    if "--faces-only" in __import__("sys").argv:
        faces_only()
    else:
        main()
