"""Read-only cohesive review sets. Grouping never changes face assignments."""
from collections import defaultdict
import hashlib
import numpy as np
from typing import Literal
from fastapi import APIRouter,Query
from . import core
from .source_management import VISIBLE

router=APIRouter(prefix='/api/people')
MIN_SIMILARITY=.78
MAX_GROUP=64
BLOCK=512
MAX_ANALYZED=20000


def cluster(rows, vectors, minimum_similarity=MIN_SIMILARITY):
    """Every pair in a group must pass; a bridge cannot merge lookalikes."""
    by_person=defaultdict(list)
    for row in rows:
        if row['face_id'] in vectors:by_person[row['person_id']].append(row)
    groups=[];singles=[]
    for person,items in by_person.items():
        items.sort(key=lambda row:(-row['score'],row['face_id']))
        for offset in range(0,len(items),BLOCK):
            batch=items[offset:offset+BLOCK]
            matrix=np.stack([vectors[row['face_id']] for row in batch])
            similarities=matrix@matrix.T
            remaining=set(range(len(batch)))
            while remaining:
                seed=min(remaining)
                members=[seed]
                neighbours=sorted((index for index in remaining if index!=seed and similarities[seed,index]>=minimum_similarity),key=lambda index:(-float(similarities[seed,index]),batch[index]['face_id']))
                for index in neighbours:
                    if len(members)>=MAX_GROUP:break
                    if np.all(similarities[index,members]>=minimum_similarity):members.append(index)
                remaining.difference_update(members)
                if len(members)<2:
                    singles.append(batch[seed]);continue
                matches=[batch[index] for index in members]
                local=similarities[np.ix_(members,members)]
                central=int(local.mean(axis=1).argmax())
                extremes=[central,int(local[central].argmin()),int(np.argmin([row['score'] for row in matches]))]
                # Include another date/source context when available, then fill.
                extremes+=sorted(range(len(matches)),key=lambda index:(matches[index].get('taken') or '',matches[index]['face_id']))
                representative=[]
                for index in extremes:
                    identity=matches[index]['face_id']
                    if identity not in representative:representative.append(identity)
                    if len(representative)==4:break
                identity=hashlib.sha256((str(person)+':'+','.join(sorted(row['face_id'] for row in matches))).encode()).hexdigest()[:24]
                groups.append(dict(id=identity,person_id=person,name=matches[0]['name'],count=len(matches),
                    minimum_similarity=round(float(local.min()),4),representatives=representative,matches=matches,
                    first_date=min((row['taken'][:10] for row in matches if row.get('taken')),default=None),
                    last_date=max((row['taken'][:10] for row in matches if row.get('taken')),default=None)))
    groups.sort(key=lambda group:(-group['count'],group['name'],group['id']))
    return groups,singles


@router.get('/review-groups')
def review_groups(person_id:int|None=None,offset:int=Query(0,ge=0),limit:int=Query(4,ge=1,le=12),cohesion:Literal['tight','broader']='tight'):
    from .people_review import vector
    with core.db() as c:
        c.execute("BEGIN")
        condition=' AND s.person_id=?' if person_id is not None else ''
        args=[person_id] if person_id is not None else []
        query=f'''FROM face_suggestions s JOIN faces f ON f.id=s.face_id JOIN people p ON p.id=s.person_id
          JOIN media m ON m.id=f.media_id LEFT JOIN people current ON current.id=f.person_id
          WHERE f.status!='dismissed' AND trim(coalesce(current.name,''))='' AND trim(coalesce(p.name,''))!=''
          AND m.status='ready' AND NOT EXISTS(SELECT 1 FROM high_confidence_faces h WHERE h.face_id=s.face_id)
          AND NOT EXISTS(SELECT 1 FROM face_rejections r WHERE r.face_id=f.id AND r.person_id=s.person_id)
          AND {VISIBLE} {condition}'''
        total=c.execute('SELECT count(*) '+query,args).fetchone()[0]
        records=c.execute('SELECT s.*,p.name,f.person_id source_person_id,f.embedding,f.media_id,m.taken '+query+' ORDER BY s.person_id,s.score DESC,s.face_id LIMIT ?',[*args,MAX_ANALYZED]).fetchall()
        rows=[];vectors={}
        for record in records:
            row=dict(record);value=vector(row.pop('embedding'))
            row['confidence']='lower'
            rows.append(row)
            if value is not None:vectors[row['face_id']]=value
    floor=MIN_SIMILARITY if cohesion=='tight' else .70
    groups,singles=cluster(rows,vectors,floor)
    covered=sum(group['count'] for group in groups)
    return dict(groups=groups[offset:offset+limit],total_groups=len(groups),grouped_faces=covered,
        individual_faces=total-covered,total_faces=total,analyzed_faces=len(rows),offset=offset,limit=limit,
        similarity_floor=floor,cohesion=cohesion,maximum_group=MAX_GROUP)
