import pytest
from tests.test_catalogue import client
from tests.test_search_people import ids


def test_natural_phone_names_and_canonicalization(client):
    c,core=client
    with core.db() as db:
        db.execute("UPDATE media SET phone='iPhoneX Hila' WHERE id='1'")
    assert ids(c,'Yoav 14ProMax and Maya')=={'0'}
    assert ids(c,'IPHoneX Hila and Maya and after 2025')=={'1'}
    assert ids(c,'Phone("Yoav 14ProMax") and Maya')=={'0'}
    result=c.get('/api/search/validate',params={'expression':'Yoav 14ProMax and Maya and after 2025'}).json()
    assert result['expression']=='Phone("Yoav14ProMax") and Includes("Maya") and after 2025'
    assert ids(c,result['expression'])=={'0'}
    for value in ['All Phone','All phones','All devices','AllPhones()']:
        assert ids(c,value)=={'0','1','2'}
        assert ids(c,value+' and Maya')=={'0','1'}
    assert ids(c,'(Yoav 14ProMax or iPhoneX Hila) and Maya')=={'0','1'}
    assert ids(c,'not Yoav 14ProMax and Maya')=={'1'}


def test_phone_person_ambiguity_and_quoted_operators(client):
    c,core=client
    with core.db() as db:
        db.execute("INSERT INTO people(id,name) VALUES(10,'Yoav14ProMax')")
        db.execute("UPDATE media SET phone='Mom and Dad' WHERE id='1'")
    assert c.get('/api/search/validate',params={'expression':'Yoav14ProMax'}).status_code==422
    assert ids(c,'Phone("Yoav14ProMax")')=={'0','2'}
    assert ids(c,'Phone("Mom and Dad") and Maya')=={'1'}
    assert ids(c,'Person("Yoav14ProMax")')==set()
