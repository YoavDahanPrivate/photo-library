import pytest
from tests.test_catalogue import client
from tests.test_search_people import ids
from backend.search_dates import period

@pytest.mark.parametrize('text,expected', [
 ('May 2025',('2025-05-01','2025-05-31')), ('May 21. 2024',('2024-05-21','2024-05-21')),
 ('21st May 2024',('2024-05-21','2024-05-21')),('Feb. 2024',('2024-02-01','2024-02-29')),
 ('2025',('2025-01-01','2025-12-31')),('2026-04',('2026-04-01','2026-04-30')),
 ('May 21, 2024',('2024-05-21','2024-05-21')),('2024-05-21',('2024-05-21','2024-05-21')),
])
def test_period(text,expected):
    assert period(text)==expected


def test_natural_boundaries(client):
    c,core=client
    with core.db() as db:
        db.execute("UPDATE media SET taken='2025-05-31T23:59:59' WHERE id='0'")
        db.execute("UPDATE media SET taken='2025-06-01T00:00:00' WHERE id='1'")
        db.execute("UPDATE media SET taken='2026-04-30T23:59:59' WHERE id='2'")
    assert ids(c,'after May 2025 and before April 2026')=={'1'}
    assert ids(c,'between May 2025 and April 2026')=={'0','1','2'}
    assert ids(c,'between June 2025 to March 2026')=={'1'}
    assert ids(c,'in May 2025')=={'0'}
    assert ids(c,'during April 2026')=={'2'}
    assert ids(c,'on May 31st, 2025')=={'0'}
    assert ids(c,'since June 2025')=={'1','2'}
    assert ids(c,'until May 2025')=={'0'}
    assert ids(c,'on or after June 2025 and on or before April 2026')=={'1','2'}
    assert ids(c,'date >= 2025-06 and date < 2026-04')=={'1'}
    assert ids(c,'> May 31. 2025')=={'1','2'}
    assert ids(c,'Maya and between May 2025 and April 2026')=={'0','1'}
    assert ids(c,'(before June 2025 or in April 2026) and not in June 2025')=={'0','2'}
    with core.db() as db:
        db.execute("UPDATE media SET taken=NULL WHERE id='2'")
    assert ids(c,'date != 2025-05')=={'1'}

@pytest.mark.parametrize('text', ['after February 30 2024','between May 2026 and April 2025','after May', 'before 2025-13','between May 2025','> nonsense','after 0000','in 21/05/2025'])
def test_invalid_dates(client,text):
    c,_=client
    assert c.get('/api/search/validate',params={'expression':text}).status_code==422


@pytest.mark.parametrize('op,expected', [('<',set()),('<=',{'0','1'}),('>',{'2'}),('>=',{'0','1','2'}),('=',{'0','1'}),('==',{'0','1'}),('!=',{'2'})])
def test_symbol_operators(client,op,expected):
    c,core=client
    with core.db() as db:
        db.execute("UPDATE media SET taken='2025-05-01T12:00:00' WHERE id='0'")
        db.execute("UPDATE media SET taken='2025-05-31T23:59:59' WHERE id='1'")
        db.execute("UPDATE media SET taken='2025-06-01T00:00:00' WHERE id='2'")
    assert ids(c,op+' May 2025')==expected
    assert ids(c,'date '+op+' May 2025')==expected
