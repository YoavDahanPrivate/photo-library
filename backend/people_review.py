from .source_management import VISIBLE
"""Reevaluation uses frozen saved exemplars, never its own new predictions."""

import json
import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from .core import db

router = APIRouter(prefix="/api/people")

from .bulk_review import ApprovalBatch, approve_batch

router.add_api_route("/approve-suggestions", approve_batch, methods=["POST"])
from .people_jobs import router as operations_router
router.include_router(operations_router)


class Rejection(BaseModel):
    face_id: str
    person_id: int


@router.post("/reject-suggestion")
def reject_suggestion(body: Rejection):
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        if (
            c.execute(
                "SELECT 1 FROM face_suggestions WHERE face_id=? AND person_id=?",
                (body.face_id, body.person_id),
            ).fetchone()
            is None
        ):
            raise HTTPException(
                409, "This suggestion changed. Reevaluate to refresh it."
            )
        previous = [dict(r) for r in c.execute("SELECT * FROM face_rejections")]
        c.execute(
            "INSERT OR IGNORE INTO face_rejections VALUES(?,?)",
            (body.face_id, body.person_id),
        )
        c.execute("DELETE FROM face_suggestions WHERE face_id=?", (body.face_id,))
        c.execute(
            "INSERT INTO actions(description,previous) VALUES(?,?)",
            ("Reject suggested identity", json.dumps({"rejections": previous})),
        )
    return {"ok": True}


class ArchiveSelection(BaseModel):
    person_ids: list[int] = Field(min_length=1, max_length=2000)


@router.post("/archive-unnamed")
def archive_unnamed(body: ArchiveSelection | None = None):
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        restriction, args = "", []
        if body is not None:
            args = list(dict.fromkeys(body.person_ids))
            placeholders = ",".join("?" for _ in args)
            valid = c.execute(
                f"SELECT id FROM people WHERE id IN ({placeholders}) AND trim(coalesce(name,''))=''",
                args,
            ).fetchall()
            if len(valid) != len(args):
                raise HTTPException(
                    409,
                    "One of these groups was named or removed. Refresh and select unnamed groups again.",
                )
            restriction = f" AND f.person_id IN ({placeholders})"
        before = [r[0] for r in c.execute("SELECT face_id FROM unknown_faces")]
        c.execute(
            "INSERT OR IGNORE INTO unknown_faces SELECT f.id FROM faces f LEFT JOIN people p ON p.id=f.person_id WHERE f.status!='dismissed' AND trim(coalesce(p.name,''))=''"
            + restriction,
            args,
        )
        count = c.execute("SELECT count(*) FROM unknown_faces").fetchone()[0] - len(
            before
        )
        if count:
            c.execute(
                "INSERT INTO actions(description,previous) VALUES(?,?)",
                (
                    "Move unnamed faces to Unknown People",
                    json.dumps({"unknown_faces": before}),
                ),
            )
    return {"moved": count}


@router.get("/suggestions")
def suggestions():
    with db() as c:
        return [
            dict(r)
            for r in c.execute(
                f"SELECT s.*,CASE WHEN EXISTS(SELECT 1 FROM high_confidence_faces h WHERE h.face_id=s.face_id) THEN 'high' ELSE 'lower' END AS confidence,p.name,f.media_id,f.person_id AS source_person_id FROM face_suggestions s JOIN people p ON p.id=s.person_id JOIN faces f ON f.id=s.face_id LEFT JOIN people current_person ON current_person.id=f.person_id WHERE f.status!='dismissed' AND trim(coalesce(current_person.name,''))='' AND trim(coalesce(p.name,''))!='' AND EXISTS(SELECT 1 FROM media m WHERE m.id=f.media_id AND {VISIBLE}) ORDER BY s.score DESC,s.face_id"
            )
        ]


def vector(blob):
    if not blob or len(blob) != 128 * 4:
        return None
    value = np.frombuffer(blob, np.float32)
    norm = np.linalg.norm(value)
    return value / norm if np.isfinite(value).all() and norm > 0 else None


@router.post("/reevaluate")
def reevaluate_request():
    return reevaluate()


def reevaluate(progress=lambda *args, **kwargs: None):
    # Score outside a write transaction so the library remains usable during a large pass.
    progress("Reading saved faces")
    with db() as c:
        revision=c.execute("SELECT coalesce(max(id),0),coalesce(sum(undone),0) FROM actions").fetchone()
        revision=tuple(revision)
        rows=c.execute("SELECT f.id,f.media_id,f.person_id,f.status,f.embedding,p.name FROM faces f LEFT JOIN people p ON p.id=f.person_id WHERE f.status!='dismissed' AND EXISTS(SELECT 1 FROM media m WHERE m.id=f.media_id AND m.status='ready')").fetchall()
        rejected={(r[0],r[1]) for r in c.execute("SELECT face_id,person_id FROM face_rejections")}
    saved={};candidates=[]
    progress("Preparing face references", 0, len(rows), "faces")
    for index,row in enumerate(rows):
        if index % 256 == 0: progress("Preparing face references", index, len(rows), "faces")
        v=vector(row["embedding"])
        if v is None: continue
        if (row["name"] or "").strip():
            if row["status"] not in ("reevaluated","scan-suggested","auto-sync"):
                saved.setdefault(row["person_id"],[]).append((v,row["media_id"]))
        else: candidates.append((row,v))
    groups=[(person,np.stack([v for v,_ in refs]),np.asarray([mid for _,mid in refs])) for person,refs in saved.items()]
    plans=[]
    comparisons=0
    total_comparisons=len(candidates)*sum(len(refs) for _,refs,_ in groups)
    progress("Comparing faces", 0, total_comparisons, "comparisons")
    for offset in range(0,len(candidates),128):
        batch=candidates[offset:offset+128]
        matrix=np.stack([v for _,v in batch])
        rankings=[[] for _ in batch]
        for person,refs,media_ids in groups:
            best=np.full(len(batch),-1.0)
            support=[set() for _ in batch]
            for start in range(0,len(refs),512):
                scores=matrix @ refs[start:start+512].T
                comparisons+=len(batch)*len(refs[start:start+512])
                progress("Comparing faces", comparisons, total_comparisons, "comparisons")
                best=np.maximum(best,scores.max(axis=1))
                mids=media_ids[start:start+512]
                for i,(row,_) in enumerate(batch):
                    if len(support[i])<2:
                        support[i].update(mids[(scores[i]>=0.55)&(mids!=row["media_id"])].tolist())
            for i in range(len(batch)): rankings[i].append((float(best[i]),person,len(support[i])))
        for (row,_),scores in zip(batch,rankings):
            scores.sort(reverse=True)
            if not scores: continue
            score,person,support=scores[0]
            margin=score-(scores[1][0] if len(scores)>1 else 0)
            if (row["id"],person) in rejected or score<0.55 or margin<0.06: continue
            plans.append((row["id"],person,score,margin,score>=0.70 and margin>=0.12 and support>=2))
    progress("Saving suggestions")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        if tuple(c.execute("SELECT coalesce(max(id),0),coalesce(sum(undone),0) FROM actions").fetchone())!=revision:
            raise HTTPException(409,"Face corrections changed during matching. Please retry.")
        progress("Saving suggestions")
        c.execute("DELETE FROM face_suggestions")
        c.execute("DELETE FROM high_confidence_faces")
        c.executemany("INSERT INTO face_suggestions VALUES(?,?,?,?)",[p[:4] for p in plans])
        c.executemany("INSERT INTO high_confidence_faces VALUES(?)",[(p[0],) for p in plans if p[4]])
    return {"evaluated":len(candidates),"assigned":0,"suggestions":len(plans),"saved_people":len(saved)}

@router.get("/{group_id}/match")
def group_match(group_id: int):
    """Read-only, on-demand identity hint. Never changes assignments or queues."""
    with db() as c:
        group = c.execute("SELECT name FROM people WHERE id=?", (group_id,)).fetchone()
        if group is None or (group['name'] or '').strip():
            return {"match": None}
        rows = c.execute("SELECT id,embedding FROM faces WHERE person_id=? AND status!='dismissed'", (group_id,)).fetchall()
        examples = c.execute("SELECT f.person_id,f.embedding,p.name FROM faces f JOIN people p ON p.id=f.person_id WHERE trim(coalesce(p.name,''))!='' AND f.status NOT IN ('dismissed','reevaluated','scan-suggested','auto-sync')").fetchall()
        rejected = {r[0] for r in c.execute("SELECT DISTINCT r.person_id FROM face_rejections r JOIN faces f ON f.id=r.face_id WHERE f.person_id=? AND f.status!='dismissed'", (group_id,))}
    candidates = [v for row in rows if (v := vector(row['embedding'])) is not None]
    if not candidates:
        return {"match": None}
    saved, names = {}, {}
    for row in examples:
        v = vector(row['embedding'])
        if v is not None:
            saved.setdefault(row['person_id'], []).append(v)
            names[row['person_id']] = row['name']
    scores = []
    # Bounded matrix blocks avoid allocating group-size x library-size arrays.
    for person, exemplars in saved.items():
        best = []
        for offset in range(0, len(candidates), 64):
            batch = np.stack(candidates[offset:offset+64])
            maximum = np.full(len(batch), -1.0)
            for start in range(0, len(exemplars), 512):
                maximum = np.maximum(maximum, (batch @ np.stack(exemplars[start:start+512]).T).max(axis=1))
            best.extend(maximum.tolist())
        scores.append((float(np.mean(best)), person, sum(v >= 0.55 for v in best)))
    scores.sort(reverse=True)
    if not scores:
        return {"match": None}
    score, person, support = scores[0]
    margin = score - (scores[1][0] if len(scores) > 1 else 0)
    if person in rejected or score < 0.55 or margin < 0.06 or support < len(candidates) * 0.6:
        return {"match": None}
    return {"match": {"person_id": person, "name": names[person], "count": support}}


@router.get("/review/approved")
def approved_reviews():
    with db() as c:
        return [dict(r) for r in c.execute(f"SELECT a.face_id,a.person_id,p.name FROM review_approvals a JOIN faces f ON f.id=a.face_id JOIN people p ON p.id=a.person_id WHERE f.person_id=a.person_id AND f.status='manual' AND EXISTS(SELECT 1 FROM media m WHERE m.id=f.media_id AND {VISIBLE}) ORDER BY a.created DESC,a.face_id LIMIT 2000")]
