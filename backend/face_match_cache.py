"""Reuse unchanged comparisons; this cache never decides or assigns identities."""
import hashlib
import json
import logging
import os
import uuid
import zipfile
import numpy as np
from . import core

VERSION = 'sface-128-support055-v1'
MAX_CELLS = 20_000_000


def digest(value):
    return hashlib.sha256(value).hexdigest()


def compare(candidates, groups, progress):
    """Exact legacy scores, invalidating changed references and candidate vectors."""
    count = len(candidates)
    ids = [str(row['id']) for row, _ in candidates]
    fingerprints = [digest(vector.tobytes()+str(row['media_id']).encode()) for row, vector in candidates]
    signatures = [digest(refs.tobytes()+json.dumps(mids.tolist()).encode()) for _, refs, mids in groups]
    path = core.DATA/'face-matching'/'comparisons.npz'
    cached = None
    try:
        if path.is_file() and path.stat().st_size < 160*1024**2:
            with np.load(path, allow_pickle=False) as saved:
                metadata = json.loads(str(saved['metadata']))
                if metadata['version'] == VERSION:
                    old_best,old_support=saved['best'],saved['support']
                    expected=(len(metadata['ids']),len(metadata['people']))
                    if (old_best.shape!=expected or old_support.shape!=expected
                        or len(metadata['fingerprints'])!=expected[0] or len(metadata['signatures'])!=expected[1]
                        or not np.isfinite(old_best).all() or not np.isfinite(old_support).all()
                        or np.any(old_best < -1.001) or np.any(old_best > 1.001)
                        or np.any(old_support < 0) or np.any(old_support > 2)):
                        raise ValueError('Invalid face comparison cache')
                    cached = (metadata,old_best,old_support)
    except (OSError, ValueError, KeyError, TypeError, EOFError, zipfile.BadZipFile, json.JSONDecodeError):
        pass
    best = np.full((count, len(groups)), -1, dtype=np.float32)
    support = np.zeros((count, len(groups)), dtype=np.uint8)
    todo = []
    reused = 0
    old_rows, old_groups = {}, {}
    if cached is not None:
        metadata, old_best, old_support = cached
        expected = (len(metadata['ids']), len(metadata['people']))
        if old_best.shape == old_support.shape == expected:
            old_rows = {key:(index, fp) for index,(key,fp) in enumerate(zip(metadata['ids'],metadata['fingerprints']))}
            old_groups = {person:(index, sig) for index,(person,sig) in enumerate(zip(metadata['people'],metadata['signatures']))}
    for column, (person, refs, mids) in enumerate(groups):
        previous = old_groups.get(person)
        pending = []
        for row, (identity, fp) in enumerate(zip(ids, fingerprints)):
            old_row = old_rows.get(identity)
            if previous and previous[1] == signatures[column] and old_row and old_row[1] == fp:
                best[row,column] = old_best[old_row[0],previous[0]]
                support[row,column] = old_support[old_row[0],previous[0]]
                reused += len(refs)
            else:
                pending.append(row)
        todo.append(pending)
    total = sum(len(rows)*len(groups[column][1]) for column, rows in enumerate(todo))
    processed = 0
    progress('Comparing updated faces' if reused else 'Comparing faces', 0, total, 'comparisons')
    for column, ((person, refs, mids), rows) in enumerate(zip(groups,todo)):
        for offset in range(0, len(rows), 128):
            indices = rows[offset:offset+128]
            matrix = np.stack([candidates[index][1] for index in indices])
            corroboration = [set() for _ in indices]
            maximum = np.full(len(indices), -1.0)
            for start in range(0, len(refs), 512):
                scores = matrix @ refs[start:start+512].T
                maximum = np.maximum(maximum,scores.max(axis=1))
                media = mids[start:start+512]
                for index, original in enumerate(indices):
                    if len(corroboration[index]) < 2:
                        corroboration[index].update(media[(scores[index]>=.55)&(media!=candidates[original][0]['media_id'])].tolist())
                processed += len(indices)*len(refs[start:start+512])
                progress('Comparing updated faces' if reused else 'Comparing faces', processed, total, 'comparisons')
            best[indices,column] = maximum
            support[indices,column] = [min(2,len(items)) for items in corroboration]
    # Cancellation is checked before publishing an advisory cache. Atomic replace
    # means concurrent or interrupted passes can at worst lose a speed-up.
    progress('Saving comparison cache', processed, total, 'comparisons')
    if count*len(groups) <= MAX_CELLS:
        temporary = None
        try:
            path.parent.mkdir(parents=True,exist_ok=True)
            temporary = path.with_name(uuid.uuid4().hex+'.npz')
            metadata = dict(version=VERSION,ids=ids,fingerprints=fingerprints,
                            people=[person for person,_,_ in groups],signatures=signatures)
            np.savez_compressed(temporary,metadata=np.asarray(json.dumps(metadata)),best=best,support=support)
            os.replace(temporary,path)
        except OSError:
            logging.getLogger(__name__).warning('Face comparison cache unavailable; matching remains correct')
        finally:
            if temporary:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
    rankings = [[(float(best[row,column]),person,int(support[row,column])) for column,(person,_,_) in enumerate(groups)] for row in range(count)]
    return rankings, dict(comparisons=total,reused_comparisons=reused)
