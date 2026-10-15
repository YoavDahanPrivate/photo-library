"""User-started approval rounds: saved high-confidence matches, then reevaluation."""
from . import core
from .bulk_review import ApprovalBatch, apply_batch
from .source_management import VISIBLE

BATCH_SIZE = 50000


def selection():
    with core.db() as c:
        return [dict(row) for row in c.execute(f"""
            SELECT s.face_id,s.person_id,f.person_id source_person_id
            FROM face_suggestions s JOIN high_confidence_faces h ON h.face_id=s.face_id
            JOIN faces f ON f.id=s.face_id JOIN people target ON target.id=s.person_id
            LEFT JOIN people current_person ON current_person.id=f.person_id
            WHERE f.status!='dismissed' AND trim(coalesce(current_person.name,''))=''
            AND trim(coalesce(target.name,''))!=''
            AND NOT EXISTS(SELECT 1 FROM face_rejections r WHERE r.face_id=f.id AND r.person_id=s.person_id)
            AND EXISTS(SELECT 1 FROM media m WHERE m.id=f.media_id AND m.status='ready' AND {VISIBLE})
            ORDER BY s.score DESC,s.face_id""")]


def run(state, progress, save, check_stop):
    from .people_review import reevaluate
    last = {}
    while True:
        check_stop()
        progress('Checking high-confidence matches')
        matches = selection()
        state['remaining_high'] = len(matches)
        if not matches:
            return dict(approved=state['approved_total'], rounds=state['rounds_completed'],
                        suggestions=last.get('suggestions', 0), stop_reason='no-high-confidence')
        state.update(round=state['rounds_completed']+1, round_total=len(matches), round_approved=0)
        progress('Approving high-confidence matches', 0, len(matches), 'matches')
        # Each committed batch has the same undo behavior as manual Approve all.
        # Larger rounds are bounded, with a safe stop point between batches.
        for offset in range(0, len(matches), BATCH_SIZE):
            check_stop()
            result = apply_batch(ApprovalBatch(matches=matches[offset:offset+BATCH_SIZE]),
                                 require_high=True, before_commit=check_stop,
                                 description=f"Auto approve high-confidence matches (round {state['round']})")
            count = result['approved']
            state['approved_total'] += count
            state['round_approved'] += count
            state['remaining_high'] -= count
            state['review_revision'] += 1
            if state['round_approved'] == len(matches):
                state['rounds_completed'] += 1
            # Publish committed counts before observing a late Stop request.
            state.update(phase='Approving high-confidence matches', processed=state['round_approved'],
                         total=len(matches), unit='matches')
            save()
            check_stop()
        last = reevaluate(progress=progress)
        state['review_revision'] += 1
        save()
