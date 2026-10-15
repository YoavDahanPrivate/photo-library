"""Approve the exact reviewed selection without reading embeddings or rescoring faces."""
import json

from fastapi import HTTPException
from pydantic import BaseModel, Field

from .core import db
from .source_management import VISIBLE


class Approval(BaseModel):
    face_id: str = Field(min_length=1, max_length=200)
    person_id: int
    source_person_id: int | None


class ApprovalBatch(BaseModel):
    matches: list[Approval] = Field(min_length=1, max_length=50000)


def approve_batch(body: ApprovalBatch):
    return apply_batch(body)


def apply_batch(body: ApprovalBatch, *, require_high=False, before_commit=lambda: None, description=None):
    selected = {row.face_id: row for row in body.matches}
    if len(selected) != len(body.matches):
        raise HTTPException(422, "Each face must appear only once")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        # A temporary relation avoids SQLite's bound-parameter limit and keeps
        # validation, snapshots and writes proportional to this selection.
        c.execute("CREATE TEMP TABLE review_selection(face_id TEXT PRIMARY KEY,person_id INTEGER,source_person_id INTEGER)")
        c.executemany("INSERT INTO review_selection VALUES(?,?,?)",
                      [(r.face_id, r.person_id, r.source_person_id) for r in body.matches])
        before_commit()
        high_guard = "AND EXISTS(SELECT 1 FROM high_confidence_faces h WHERE h.face_id=f.id)" if require_high else ""
        rows = c.execute(f"""SELECT f.id,f.person_id,f.status
            FROM review_selection r JOIN faces f ON f.id=r.face_id
            JOIN face_suggestions s ON s.face_id=f.id AND s.person_id=r.person_id
            JOIN people target ON target.id=r.person_id
            LEFT JOIN people current_person ON current_person.id=f.person_id
            WHERE f.status!='dismissed' AND f.person_id IS r.source_person_id {high_guard}
            AND trim(coalesce(current_person.name,''))=''
            AND trim(coalesce(target.name,''))!=''
            AND NOT EXISTS(SELECT 1 FROM face_rejections x WHERE x.face_id=f.id AND x.person_id=r.person_id)
            AND EXISTS(SELECT 1 FROM media m WHERE m.id=f.media_id AND m.status='ready' AND {VISIBLE})""").fetchall()
        if len(rows) != len(selected):
            raise HTTPException(409, "Some matches changed or are unavailable. No changes made; refresh the matches before approving again.")
        scope = "face_id IN (SELECT face_id FROM review_selection)"
        previous = {"faces": [dict(row) for row in rows]}
        previous["review_batch"] = {
            "unknown": [row[0] for row in c.execute(f"SELECT face_id FROM unknown_faces WHERE {scope}")],
            "rejections": [dict(row) for row in c.execute(f"SELECT * FROM face_rejections WHERE {scope}")],
            "approvals": [dict(row) for row in c.execute(f"SELECT * FROM review_approvals WHERE {scope}")],
            "suggestions": [dict(row) for row in c.execute(f"SELECT * FROM face_suggestions WHERE {scope}")],
            "high": [row[0] for row in c.execute(f"SELECT face_id FROM high_confidence_faces WHERE {scope}")],
        }
        c.execute("INSERT INTO actions(description,previous) VALUES(?,?)",
                  (description or f"Approve {len(rows)} suggested matches", json.dumps(previous)))
        c.execute("""INSERT OR IGNORE INTO face_rejections(face_id,person_id)
            SELECT f.id,f.person_id FROM faces f JOIN review_selection r ON r.face_id=f.id
            WHERE f.person_id IS NOT NULL AND f.person_id!=r.person_id""")
        c.execute(f"DELETE FROM unknown_faces WHERE {scope}")
        c.execute(f"DELETE FROM face_suggestions WHERE {scope}")
        c.execute(f"DELETE FROM high_confidence_faces WHERE {scope}")
        c.execute("""INSERT OR REPLACE INTO review_approvals(face_id,person_id)
            SELECT face_id,person_id FROM review_selection""")
        c.execute("""UPDATE faces SET person_id=(SELECT person_id FROM review_selection r WHERE r.face_id=faces.id),status='manual'
            WHERE id IN (SELECT face_id FROM review_selection)""")
        before_commit()
    return {"ok": True, "approved": len(rows)}


def undo_batch(c, previous):
    """Restore only the batch's records, preserving unrelated scanner work."""
    saved = previous["review_batch"]
    c.execute("CREATE TEMP TABLE undo_review_selection(face_id TEXT PRIMARY KEY)")
    c.executemany("INSERT INTO undo_review_selection VALUES(?)", [(f["id"],) for f in previous["faces"]])
    c.executemany("UPDATE faces SET person_id=?,status=? WHERE id=?",
                  [(f["person_id"], f["status"], f["id"]) for f in previous["faces"]])
    for table in ("unknown_faces", "face_rejections", "review_approvals", "face_suggestions", "high_confidence_faces"):
        c.execute(f"DELETE FROM {table} WHERE face_id IN (SELECT face_id FROM undo_review_selection)")
    c.executemany("INSERT INTO unknown_faces VALUES(?)", [(fid,) for fid in saved["unknown"]])
    c.executemany("INSERT INTO high_confidence_faces VALUES(?)", [(fid,) for fid in saved["high"]])
    c.executemany("INSERT INTO face_rejections VALUES(?,?)", [(r["face_id"],r["person_id"]) for r in saved["rejections"]])
    c.executemany("INSERT INTO review_approvals(face_id,person_id,created) VALUES(?,?,?)", [(r["face_id"],r["person_id"],r["created"]) for r in saved["approvals"]])
    c.executemany("INSERT INTO face_suggestions VALUES(?,?,?,?)", [(r["face_id"],r["person_id"],r["score"],r["margin"]) for r in saved["suggestions"]])


def reject_batch(body: ApprovalBatch):
    """Reject the exact current proposals as one transaction and undo action."""
    selected = {row.face_id: row for row in body.matches}
    if len(selected) != len(body.matches):
        raise HTTPException(422, "Each face must appear only once")
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        c.execute("CREATE TEMP TABLE review_selection(face_id TEXT PRIMARY KEY,person_id INTEGER,source_person_id INTEGER)")
        c.executemany("INSERT INTO review_selection VALUES(?,?,?)",
                      [(row.face_id, row.person_id, row.source_person_id) for row in body.matches])
        rows = c.execute(f"""SELECT f.id,f.person_id,f.status
            FROM review_selection r JOIN faces f ON f.id=r.face_id
            JOIN face_suggestions s ON s.face_id=f.id AND s.person_id=r.person_id
            JOIN people target ON target.id=r.person_id
            LEFT JOIN people current_person ON current_person.id=f.person_id
            WHERE f.status!='dismissed' AND f.person_id IS r.source_person_id
            AND trim(coalesce(current_person.name,''))=''
            AND trim(coalesce(target.name,''))!=''
            AND NOT EXISTS(SELECT 1 FROM face_rejections x WHERE x.face_id=f.id AND x.person_id=r.person_id)
            AND EXISTS(SELECT 1 FROM media m WHERE m.id=f.media_id AND m.status='ready' AND {VISIBLE})""").fetchall()
        if len(rows) != len(selected):
            raise HTTPException(409, "Some matches changed or are unavailable. No changes made; refresh the matches before rejecting again.")
        scope = "face_id IN (SELECT face_id FROM review_selection)"
        previous = {"faces": [dict(row) for row in rows], "review_batch": {
            "unknown": [row[0] for row in c.execute(f"SELECT face_id FROM unknown_faces WHERE {scope}")],
            "rejections": [dict(row) for row in c.execute(f"SELECT * FROM face_rejections WHERE {scope}")],
            "approvals": [dict(row) for row in c.execute(f"SELECT * FROM review_approvals WHERE {scope}")],
            "suggestions": [dict(row) for row in c.execute(f"SELECT * FROM face_suggestions WHERE {scope}")],
            "high": [row[0] for row in c.execute(f"SELECT face_id FROM high_confidence_faces WHERE {scope}")],
        }}
        c.execute("INSERT INTO actions(description,previous) VALUES(?,?)",
                  (f"Reject {len(rows)} suggested matches", json.dumps(previous)))
        c.execute("INSERT OR IGNORE INTO face_rejections SELECT face_id,person_id FROM review_selection")
        # Learned rejection evidence can change other high flags for these people.
        # A set-based query stays bounded even for thousands of selected matches.
        c.execute("""DELETE FROM high_confidence_faces WHERE face_id IN (
            SELECT face_id FROM face_suggestions WHERE person_id IN (SELECT DISTINCT person_id FROM review_selection))""")
        c.execute(f"DELETE FROM face_suggestions WHERE {scope}")
    return {"ok": True, "rejected": len(rows), "learning_pending": True,
            "confidence_invalidated_for": sorted({row.person_id for row in body.matches})}
