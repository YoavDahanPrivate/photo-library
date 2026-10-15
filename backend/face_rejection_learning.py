"""Person-specific separation from rejected examples, using saved embeddings only.

Confirmed positives protect their neighbourhoods. A rejection never globally
raises an identity's cutoff or changes encoder weights/previous assignments.
"""
import numpy as np

NEGATIVE_MIN = .55
NEIGHBOUR_MIN = .65
POSITIVE_GUARD = .05
SEPARATION = .04
VETO_MARGIN = .03
CONFLICT_SIMILARITY = .95


def invalidate_high(c, people):
    """An automatic batch must not consume flags made before new feedback."""
    c.executemany(
        "DELETE FROM high_confidence_faces WHERE face_id IN "
        "(SELECT face_id FROM face_suggestions WHERE person_id=?)",
        [(person,) for person in set(people) if person is not None],
    )


def build(rows, groups, rejected, progress=lambda *args: None):
    from .people_review import vector
    actual = {row['id']: row for row in rows}
    positives = {person: refs for person, refs, _ in groups}
    negative = {}
    conflicts = 0
    for face, person in sorted(rejected):
        row = actual.get(face)
        if row is None or person not in positives or row['status'] == 'dismissed':
            continue
        # A later explicit confirmation wins over a contradictory old rejection.
        if row['person_id'] == person and (row['name'] or '').strip():
            conflicts += 1
            continue
        value = vector(row['embedding'])
        if value is not None:
            negative.setdefault(person, {})[value.tobytes()] = value
    total = sum(len(values)*len(positives[person]) for person, values in negative.items())
    processed = 0
    result = {}
    progress('Learning from rejected faces', 0, total, 'comparisons')
    for person, values in negative.items():
        refs = positives[person]
        values = np.stack(list(values.values()))
        nearest = np.full(len(values), -1., dtype=np.float32)
        for offset in range(0, len(values), 128):
            batch = values[offset:offset+128]
            for start in range(0, len(refs), 512):
                scores = batch @ refs[start:start+512].T
                nearest[offset:offset+len(batch)] = np.maximum(
                    nearest[offset:offset+len(batch)], scores.max(axis=1))
                processed += len(batch)*len(refs[start:start+512])
                progress('Learning from rejected faces', processed, total, 'comparisons')
        # Nearly identical positive/negative labels cannot be resolved from an
        # embedding. Keep the exact rejection but do not generalize the conflict.
        valid = nearest < CONFLICT_SIMILARITY
        conflicts += int((~valid).sum())
        if valid.any():
            result[person] = (values[valid], np.maximum(NEIGHBOUR_MIN, nearest[valid]+POSITIVE_GUARD))
    return result, dict(rejection_examples=sum(len(refs) for refs, _ in result.values()),
                        rejection_conflicts=conflicts)


def assess(person, matrix, positive_scores, learned, progress=lambda *args: None):
    """Return (withhold, strongest negative, required positive score) per face.

    Stronger confirmed matches survive. Only a close negative neighbour that
    beats positive evidence is withheld; borderline separation lowers confidence.
    Temporary matrices are bounded, and rejection changes need no cache flush.
    """
    count = len(matrix)
    if person not in learned:
        return [(False, None, None)]*count
    refs, radii = learned[person]
    nearest = np.full(count, -1., dtype=np.float32)
    withheld = np.zeros(count, dtype=bool)
    processed, total = 0, count*len(refs)
    progress('Checking rejected lookalikes', processed, total, 'comparisons')
    for offset in range(0, count, 128):
        batch = matrix[offset:offset+128]
        positive = np.asarray(positive_scores[offset:offset+len(batch)])
        for start in range(0, len(refs), 256):
            scores = batch @ refs[start:start+256].T
            nearest[offset:offset+len(batch)] = np.maximum(nearest[offset:offset+len(batch)], scores.max(axis=1))
            withheld[offset:offset+len(batch)] |= (
                (scores >= radii[start:start+256]) &
                (scores >= positive[:, None]+VETO_MARGIN)
            ).any(axis=1)
            processed += len(batch)*len(refs[start:start+256])
            progress('Checking rejected lookalikes', processed, total, 'comparisons')
    return [(bool(blocked), float(score), float(score)+SEPARATION if score >= NEGATIVE_MIN else None)
            for blocked, score in zip(withheld, nearest)]
