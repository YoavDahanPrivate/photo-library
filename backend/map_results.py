"""Bounded, revision-keyed map summaries, shared by matching and context queries."""
from collections import OrderedDict
from threading import Lock
from . import core
from .geo import VALID

_cache = OrderedDict()
_lock = Lock()

def cached_map_results(filters):
    where, args = filters
    # Serialize duplicate requests: identical context/results are computed once.
    with _lock, core.db() as c:
        revision = c.execute('SELECT revision FROM catalogue_clock WHERE id=1').fetchone()[0]
        key = (str(core.DATA), revision, where, tuple(args))
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
        rows = [dict(r) for r in c.execute(
            'WITH selected AS MATERIALIZED (SELECT m.id,m.latitude,m.longitude FROM media m WHERE ' + where + ') '
            'SELECT CASE WHEN ' + VALID + ' THEN m.latitude END latitude, '
            'CASE WHEN ' + VALID + ' THEN m.longitude END longitude, count(*) count, '
            'min(m.id) cover,min(city.label) city,min(country.label) country '
            'FROM selected m LEFT JOIN media_places mp ON mp.media_id=m.id '
            'LEFT JOIN geographic_places city ON city.id=mp.city_id '
            'LEFT JOIN geographic_places country ON country.id=mp.country_id '
            'GROUP BY 1,2 ORDER BY 1,2', args)]
        points = [r for r in rows if r['latitude'] is not None]
        total = sum(r['count'] for r in rows)
        known = sum(r['count'] for r in points)
        result = dict(points=points,total=total,known=known,unknown=total-known)
        _cache[key] = result
        while len(_cache) > 6:
            _cache.popitem(last=False)
        return result


def map_response(filters, request):
    import gzip
    import json
    from starlette.responses import Response
    data = json.dumps(cached_map_results(filters),separators=(',',':'),ensure_ascii=False).encode('utf-8')
    encodings = request.headers.get('accept-encoding','').lower().split(',')
    use_gzip = False
    for entry in encodings:
        parts = [p.strip() for p in entry.split(';')]
        if parts[0] != 'gzip':
            continue
        try:
            use_gzip = float(next((p[2:] for p in parts[1:] if p.startswith('q=')), '1')) > 0
        except ValueError:
            pass
    headers = {'Vary':'Accept-Encoding','Cache-Control':'no-store'}
    if use_gzip:
        data = gzip.compress(data,compresslevel=1)
        headers['Content-Encoding'] = 'gzip'
    return Response(data,media_type='application/json',headers=headers)
