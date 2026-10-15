"""Photo-disjoint calibration with a gallery representing every eligible photo."""
import hashlib
import numpy as np


def study(rows, progress=lambda *args: None, *, reference_limit=None, query_limit=80, consensus=False, baseline_rules=None):
    from .people_review import vector
    from .face_calibration import propose, token
    baseline_rules=baseline_rules or {}
    buckets={}
    for index,row in enumerate(rows):
        if index%512==0:progress('Partitioning independent photographs',index,len(rows),'faces')
        value=vector(row['embedding'])
        if value is None:continue
        key=str(row['sha'] or row['media_id'])
        fold=int(hashlib.sha256(key.encode()).hexdigest()[:8],16)%4
        bucket=buckets.setdefault(row['person_id'],dict(name=row['name'],fit={},tune={},test={}))
        bucket['fit' if fold<2 else 'tune' if fold==2 else 'test'].setdefault(key,(row,value))
    gallery=[];queries=[];anchors={};counts={}
    for person,bucket in buckets.items():
        counts[person]={}
        for partition in ('fit','tune','test'):
            selected=sorted(bucket[partition].items(),key=lambda item:hashlib.sha256(item[0].encode()).hexdigest())
            limit=reference_limit if partition=='fit' else query_limit
            if limit is not None:selected=selected[:limit]
            counts[person][partition]=len(selected)
            for _,(row,_) in selected:anchors[row['id']]=token(row)
            if partition=='fit' and selected:gallery.append((person,np.stack([item[1][1] for item in selected])))
            elif partition!='fit':queries.extend((partition,row,value) for _,(row,value) in selected)
    tuning=[];validation=[]
    total=sum(len(queries)*len(refs) for _,refs in gallery);done=0
    for offset in range(0,len(queries),64):
        batch=queries[offset:offset+64];matrix=np.stack([value for _,_,value in batch])
        rankings=[[] for _ in batch]
        for person,refs in gallery:
            maximum=np.full(len(batch),-1.);support=np.zeros(len(batch),dtype=np.int32)
            best_three=np.full((len(batch),3),-1.,dtype=np.float32)
            for start in range(0,len(refs),512):
                scores=matrix@refs[start:start+512].T
                maximum=np.maximum(maximum,scores.max(axis=1))
                if consensus:
                    merged=np.concatenate((best_three,scores),axis=1)
                    best_three=np.partition(merged,merged.shape[1]-3,axis=1)[:,-3:]
                support+=np.sum(scores>=.55,axis=1)
                done+=scores.size
                progress('Testing independent photographs',done,total,'comparisons')
            if consensus:maximum=best_three[:,-min(3,len(refs)):].mean(axis=1)
            for index in range(len(batch)):rankings[index].append((float(maximum[index]),person,int(support[index])))
        for (partition,row,_),ranking in zip(batch,rankings):
            if not ranking:continue
            ranking.sort(reverse=True)
            score,predicted,support=ranking[0]
            samples=tuning if partition=='tune' else validation
            samples.append(dict(actual=row['person_id'],face_id=row['id'],media_id=row['media_id'],actual_name=row['name'],predicted=predicted,score=score,
                margin=score-(ranking[1][0] if len(ranking)>1 else 0),support=support))
            others=[entry for entry in ranking if entry[1]!=row['person_id']]
            if others:
                wrong_score,wrong_person,wrong_support=others[0]
                samples.append(dict(actual=None,face_id=row['id'],media_id=row['media_id'],actual_name=row['name'],predicted=wrong_person,score=wrong_score,
                    margin=wrong_score-(others[1][0] if len(others)>1 else 0),support=wrong_support))
    people=[]
    for index,(person,bucket) in enumerate(buckets.items()):
        progress('Evaluating person-specific rules',index,len(buckets),'people')
        proposal=propose(tuning,validation,person,baseline_rule=baseline_rules.get(person))
        retained=person in baseline_rules and not proposal['eligible'] and proposal['baseline']['mistakes']==0
        if retained:
            proposal.update(proposed=baseline_rules[person],reason='Existing calibrated rules retained')
        conflicts=[dict(face_id=item['face_id'],media_id=item['media_id'],actual_name=item['actual_name'],proposed_name=bucket['name'],open_set=item['actual'] is None) for item in validation
            if item['predicted']==person and item['actual']!=person
            and item['score']>=proposal.get('tested_rule',proposal['proposed'])['score'] and item['margin']>=proposal.get('tested_rule',proposal['proposed'])['margin'] and item['support']>=2][:6]
        people.append(dict(person_id=person,name=bucket['name'],reference_photos=counts[person]['fit'],
            tuning_photos=counts[person]['tune'],validation_photos=counts[person]['test'],retained=retained,
            conflicts=conflicts,**proposal))
    return dict(model='OpenCV SFace',method='photo-consensus-v1' if consensus else 'full-photo-gallery-v2' if reference_limit is None else 'bounded-photo-gallery-v1',
        people=people,anchors=anchors,eligible_people=sum(person['eligible'] for person in people),
        additional_validation_matches=sum(person['validation']['correct']-person['baseline']['correct'] for person in people if person['eligible']),
        tuning_faces=len(tuning),validation_faces=len(validation),reference_photos=sum(len(refs) for _,refs in gallery),
        note='Every eligible reference photograph participates. Tuning and validation are separated by photo/content hash; known copies and frames stay together. Results use saved labels, which can contain mistakes or previous automatic confirmations. Zero observed errors is not a guarantee. Enabling changes confidence rules and requires review; no faces are assigned by this study.')
