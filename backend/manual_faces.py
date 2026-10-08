"""User supplied photo regions, using cached oriented previews only."""

import json
import uuid
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator
from PIL import Image
from .core import db
from . import core

router = APIRouter(prefix="/api/media")


class FaceRegion(BaseModel):
    x: float = Field(ge=0, lt=1)
    y: float = Field(ge=0, lt=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)
    person_id: int | None = Field(default=None, gt=0)
    name: str | None = Field(default=None, max_length=100)
    replaces: str | None = None

    @model_validator(mode="after")
    def valid(self):
        if self.x + self.width > 1.000001 or self.y + self.height > 1.000001:
            raise ValueError("Face box must stay inside the photo")
        if bool(self.person_id) == bool((self.name or "").strip()):
            raise ValueError("Choose an existing person or enter one new name")
        return self


def signature(crop):
    try:
        import cv2
        import numpy as np
        from .indexer import Recognition

        if min(crop.size) < 40:
            return None
        frame = cv2.cvtColor(np.asarray(crop), cv2.COLOR_RGB2BGR)
        if (
            cv2.Laplacian(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()
            < 60
        ):
            return None
        recognition = Recognition()
        recognition.detector.setInputSize((frame.shape[1], frame.shape[0]))
        _, faces = recognition.detector.detect(frame)
        if faces is None or len(faces) != 1:
            return None
        face = faces[0]
        x, y, w, h = face[:4]
        if min(w, h) < 28 or w * h / (crop.width * crop.height) < 0.2:
            return None
        value = (
            recognition.encoder.feature(recognition.encoder.alignCrop(frame, face))
            .flatten()
            .astype(np.float32)
        )
        norm = float(np.linalg.norm(value))
        return (
            (value / norm).tobytes() if norm > 0 and np.isfinite(value).all() else None
        )
    except Exception:
        # Manual identity remains useful when models or landmarks are unavailable.
        return None


@router.post("/{identity}/manual-face")
def save_face(identity: str, body: FaceRegion):
    with db() as c:
        media = c.execute("SELECT kind FROM media WHERE id=?", (identity,)).fetchone()
    if media is None:
        raise HTTPException(404, "Photo not found")
    if media["kind"] != "photo":
        raise HTTPException(422, "Manual face boxes currently support photos only")
    try:
        with Image.open(core.DATA / "thumbs" / f"{identity}-large.jpg") as image:
            width, height = image.size
            x, y = round(body.x * width), round(body.y * height)
            right, bottom = min(width, round((body.x + body.width) * width)), min(
                height, round((body.y + body.height) * height)
            )
            if right - x < 8 or bottom - y < 8:
                raise HTTPException(
                    422, "Draw a larger face box (at least 8 pixels each side)"
                )
            crop = image.crop((x, y, right, bottom)).convert("RGB")
    except OSError as error:
        raise HTTPException(409, "The cached photo preview is unavailable") from error
    embedding = signature(crop)
    fid = uuid.uuid4().hex
    destination = core.DATA / "faces" / f"{fid}.jpg"
    try:
        with db() as c:
            c.execute("BEGIN IMMEDIATE")
            person = body.person_id
            created = []
            if person is not None:
                if (
                    c.execute("SELECT id FROM people WHERE id=?", (person,)).fetchone()
                    is None
                ):
                    raise HTTPException(404, "Person no longer exists")
            else:
                name = body.name.strip()
                if any(
                    (r["name"] or "").casefold() == name.casefold()
                    for r in c.execute("SELECT name FROM people")
                ):
                    raise HTTPException(
                        409, "That name already exists; select the saved person"
                    )
                person = c.execute(
                    "INSERT INTO people(name) VALUES(?)", (name,)
                ).lastrowid
                created = [person]
            previous = [dict(id=fid, person_id=None, status="dismissed")]
            if body.replaces:
                old = c.execute(
                    "SELECT id,person_id,status FROM faces WHERE id=? AND media_id=? AND status!=?",
                    (body.replaces, identity, "dismissed"),
                ).fetchone()
                if old is None:
                    raise HTTPException(409, "This face changed; reopen the photo")
                previous.append(dict(old))
                c.execute(
                    "UPDATE faces SET status='dismissed' WHERE id=?", (body.replaces,)
                )
            for r in c.execute(
                "SELECT id,bbox,bbox_width,bbox_height FROM faces WHERE media_id=? AND status!='dismissed'",
                (identity,),
            ):
                if r["id"] == body.replaces:
                    continue
                coords = json.loads(r["bbox"] or "[]")
                if len(coords) != 4:
                    continue
                a, b, w, h = coords
                scale_x = width / (r["bbox_width"] or width)
                scale_y = height / (r["bbox_height"] or height)
                a, w = a * scale_x, w * scale_x
                b, h = b * scale_y, h * scale_y
                overlap = max(0, min(right, a + w) - max(x, a)) * max(
                    0, min(bottom, b + h) - max(y, b)
                )
                if overlap / max(1, min((right - x) * (bottom - y), w * h)) > 0.6:
                    raise HTTPException(
                        409,
                        "A face already exists here. Select its box to reassign or redraw it.",
                    )
            destination.parent.mkdir(exist_ok=True)
            crop.thumbnail((320, 320))
            crop.save(destination, quality=90)
            c.execute(
                "INSERT INTO faces(id,media_id,person_id,timestamp,bbox,embedding,status,bbox_width,bbox_height) VALUES(?,?,?,0,?,?,'manual',?,?)",
                (
                    fid,
                    identity,
                    person,
                    json.dumps([x, y, right - x, bottom - y]),
                    embedding,
                    width,
                    height,
                ),
            )
            c.execute("DELETE FROM face_suggestions")
            c.execute(
                "INSERT INTO actions(description,previous) VALUES(?,?)",
                (
                    "Add or redraw manual face",
                    json.dumps({"faces": previous, "created_people": created}),
                ),
            )
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return dict(id=fid, person_id=person, recognition_ready=embedding is not None)
