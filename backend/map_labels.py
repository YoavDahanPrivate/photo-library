"""Small viewport-scoped label responses from the installed offline gazetteer."""
import sqlite3
from . import core

def city_labels(south,north,west,east,span):
    path=core.DATA/'maps'/'gazetteer.sqlite'
    if not path.is_file() or span > 80:
        return []
    codes = ['PPLC'] if span > 35 else ['PPLC','PPLA'] if span > 12 else ['PPLC','PPLA','PPLA2'] if span > 4 else []
    clause = 'lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?'
    args=[south,north,west,east]
    if codes:
        clause += ' AND feature_code IN ('+','.join('?' for _ in codes)+')'
        args += codes
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as c:
        c.row_factory=sqlite3.Row
        return [dict(r) for r in c.execute(
            'SELECT id,name,lat,lon,feature_code FROM cities WHERE '+clause+
            " ORDER BY CASE feature_code WHEN 'PPLC' THEN 0 WHEN 'PPLA' THEN 1 WHEN 'PPLA2' THEN 2 ELSE 3 END, ((lat-?)*(lat-?)+(lon-?)*(lon-?)),id LIMIT 180",
            args+[(south+north)/2]*2+[(west+east)/2]*2)]
