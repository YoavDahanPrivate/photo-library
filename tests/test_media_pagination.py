import pytest
from tests.test_catalogue import client


@pytest.mark.parametrize('order', ['asc', 'desc'])
@pytest.mark.parametrize('sort_by', ['capture', 'file'])
def test_page_order_matches_original_sql_across_nulls_ties_and_boundaries(client, order, sort_by):
    _, core = client
    from backend.app import media_page_rows
    with core.db() as c:
        for i, taken in enumerate([None, '2024-01-01', '', '2024-01-01', None, '2025-01-01', '2023-01-01']):
            c.execute("INSERT INTO media(id,path,phone,album,name,kind,status,taken,mtime) VALUES(?,?,?,'Test',?,'photo','ready',?,?)",
                      ('page-'+str(i), '/fixture/'+str(i), 'Pagination fixture', str(i)+'.jpg', taken, 100-i))
        where="m.status='ready' AND m.phone=?"
        args=['Pagination fixture']
        sorting=f"m.taken IS NULL,m.taken {order.upper()},m.id" if sort_by=='capture' else f"coalesce((SELECT file_created FROM media_original_metadata om WHERE om.media_id=m.id),m.mtime) IS NULL,coalesce((SELECT file_created FROM media_original_metadata om WHERE om.media_id=m.id),m.mtime) {order.upper()},m.id"
        for limit in (1, 3, 5):
            for offset in range(10):
                expected=c.execute('SELECT m.id FROM media m WHERE '+where+' ORDER BY '+sorting+' LIMIT ? OFFSET ?', args+[limit,offset]).fetchall()
                actual=media_page_rows(c,'SELECT m.id FROM media m',where,args,order,sort_by,offset,limit)
                assert [r[0] for r in actual]==[r[0] for r in expected]


def test_later_pages_can_skip_total_and_format_snapshot_invalidates_on_revision(client):
    http, core = client
    from backend.app import ordered_media_ids
    with core.db() as c:
        for identity,name,extension,taken in [('pair-heic','one.heic','.heic','2024-01-01'),('pair-jpeg','one.jpg','.jpg','2024-01-01'),('other','other.jpg','.jpg','2023-01-01')]:
            c.execute("INSERT INTO media(id,path,phone,album,name,extension,kind,status,width,height,taken) VALUES(?,?,?,'Test',?,?,'photo','ready',80,60,?)",
                      (identity,'/fixture/'+name,'Pagination fixture',name,extension,taken))
    params={'phones':'Pagination fixture','hide_format_duplicates':'true','limit':1}
    first=http.get('/api/media',params=params).json()
    assert first['total']==2 and first['items'][0]['id']=='pair-heic'
    before=ordered_media_ids.cache_info().hits
    second=http.get('/api/media',params={**params,'offset':1,'include_total':'false'}).json()
    assert second['total'] is None and second['items'][0]['id']=='other'
    assert ordered_media_ids.cache_info().hits>before
    with core.db() as c:
        c.execute("UPDATE media SET taken='2026-01-01' WHERE id='other'")
    fresh=http.get('/api/media',params=params).json()
    assert fresh['items'][0]['id']=='other'
