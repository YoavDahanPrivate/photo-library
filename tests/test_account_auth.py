import hashlib,json,secrets,time
import cbor2,pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes
from fastapi.testclient import TestClient
from tests.test_catalogue import client

@pytest.fixture
def account(client):
    old,core=client
    c=TestClient(old.app,base_url='https://localhost',headers={'Origin':'http://127.0.0.1'})
    return c,core

def login(c,user='yoav',password='Yoav1919'):
    r=c.post('/api/auth/login',json={'username':user,'password':password});assert r.status_code==200,r.text;return r

def change(c,old='Yoav1919',new='a private test password'):
    r=c.post('/api/auth/password',json={'current_password':old,'new_password':new});assert r.status_code==200,r.text;return r

def test_password_lifecycle_and_isolation(account):
    c,core=account
    assert c.get('/api/media').status_code==401
    assert c.get('/api/media/0/thumbnail').status_code==401
    assert login(c).json()['must_change']
    assert c.get('/api/media').status_code==403
    token=c.cookies.get('dahan_account')
    assert c.post('/api/auth/password',json={'current_password':'wrong','new_password':'a private test password'}).status_code==401
    assert not change(c).json()['must_change']
    assert c.get('/api/media').status_code==200
    prefs={'theme':'plum','source_ids':[],'source_names':[]}
    assert c.put('/api/profiles/yoav/preferences',json=prefs).status_code==200
    assert c.put('/api/profiles/hila/preferences',json=prefs).status_code==403
    assert c.get('/api/profiles/hila/activity').status_code==403
    assert c.post('/api/profiles/hila/select').status_code==403
    assert c.post('/api/profiles/yoav/searches',json={'expression':'Includes("Maya")'}).status_code==200
    thumbs=core.DATA/'thumbs';thumbs.mkdir(exist_ok=True);(thumbs/'0-small.jpg').write_bytes(b'\xff\xd8test')
    assert c.get('/api/media/0/thumbnail?size=small&activity=download&profile_id=hila').status_code==200
    assert c.get('/api/profiles/yoav/activity').json()[0]['kind']=='download_requested'
    with core.db() as db:
        assert db.execute("SELECT count(*) FROM user_activity WHERE profile_id='hila'").fetchone()[0]==0
        assert db.execute('SELECT count(*) FROM account_passwords').fetchone()[0]==7
        for r in db.execute('SELECT password_hash FROM account_passwords'):assert '1919' not in r[0]
    stranger=TestClient(c.app,base_url='https://localhost');stranger.cookies.set('dahan_account',token)
    assert stranger.get('/api/auth/me').status_code==401
    c.post('/api/auth/logout');assert c.get('/api/media').status_code==401
    assert c.post('/api/auth/login',json={'username':'yoav','password':'Yoav1919'}).status_code==401
    login(c,password='a private test password');assert c.get('/api/auth/me').json()['theme']=='plum'
    assert c.get('/api/auth/me').json()['source_ids']==[]
    assert c.post('/api/auth/logout',headers={'origin':'https://evil.invalid'}).status_code==403

def credential(c,register=True,private=None,kid=None,origin=None,uv=True,count=1):
    from backend import account_auth as a
    options=c.post('/api/auth/passkeys/'+('register' if register else 'login')+'/options',json={'password':'a private test password'} if register else {'username':'yoav'})
    assert options.status_code==200,options.text
    private=private or ec.generate_private_key(ec.SECP256R1());kid=kid or secrets.token_bytes(24)
    cd=json.dumps({'type':'webauthn.create' if register else 'webauthn.get','challenge':options.json()['challenge'],'origin':origin or a.ORIGIN,'crossOrigin':False}).encode()
    flags=(1|4 if uv else 1)|(64 if register else 0)
    auth=hashlib.sha256(a.RP.encode()).digest()+bytes([flags])+(0 if register else count).to_bytes(4,'big')
    if register:
        pub=private.public_key().public_numbers()
        cose=cbor2.dumps({1:2,3:-7,-1:1,-2:pub.x.to_bytes(32,'big'),-3:pub.y.to_bytes(32,'big')})
        auth+=bytes(16)+len(kid).to_bytes(2,'big')+kid+cose
        response={'clientDataJSON':a.encode(cd),'attestationObject':a.encode(cbor2.dumps({'fmt':'none','attStmt':{},'authData':auth}))}
    else:
        response={'clientDataJSON':a.encode(cd),'authenticatorData':a.encode(auth),'signature':a.encode(private.sign(auth+hashlib.sha256(cd).digest(),ec.ECDSA(hashes.SHA256()))),'userHandle':a.encode(b'yoav')}
    return {'credential':{'id':a.encode(kid),'rawId':a.encode(kid),'type':'public-key','response':response}},private,kid

def test_passkey_verified_lifecycle(account):
    c,core=account;login(c);change(c)
    body,private,kid=credential(c)
    r=c.post('/api/auth/passkeys/register/verify',json=body);assert r.status_code==200,r.text
    assert c.post('/api/auth/passkeys/register/verify',json=body).status_code==400
    assert len(c.get('/api/auth/passkeys').json())==1
    c.post('/api/auth/logout')
    body,_,_=credential(c,False,private,kid)
    r=c.post('/api/auth/passkeys/login/verify',json=body);assert r.status_code==200,r.text
    assert r.json()['id']=='yoav'
    assert c.post('/api/auth/passkeys/login/verify',json=body).status_code==400
    assert c.get('/api/media').status_code==200
    from backend.account_auth import encode
    assert c.post('/api/auth/passkeys/'+encode(kid)+'/remove',json={'password':'a private test password'}).status_code==200
    assert c.get('/api/auth/passkeys').json()==[]
    assert c.post('/api/auth/passkeys/login/options',json={'username':'yoav'}).status_code==400

@pytest.mark.parametrize('origin,uv',[('https://evil.invalid',True),(None,False)])
def test_passkey_rejects_wrong_origin_or_no_verification(account,origin,uv):
    c,_=account;login(c);change(c)
    body,_,_=credential(c,origin=origin,uv=uv)
    assert c.post('/api/auth/passkeys/register/verify',json=body).status_code==400
    assert c.get('/api/auth/passkeys').json()==[]

def test_expired_challenge_and_rate_limit(account):
    c,core=account;login(c);change(c);body,_,_=credential(c)
    with core.db() as db:db.execute('UPDATE account_challenges SET expires=?',(time.time()-1,))
    assert c.post('/api/auth/passkeys/register/verify',json=body).status_code==400
    for _ in range(25):r=c.post('/api/auth/login',json={'username':'guest','password':'wrong'})
    assert r.status_code==429

TV_UA='Mozilla/5.0 (SMART-TV; Linux; Tizen 6.0) SamsungBrowser/4.0 TV Safari/537.36'

def tv_client(account, peer='192.168.1.25', ua=TV_UA, headers=None):
    c,_=account
    return TestClient(c.app,base_url='http://localhost',client=(peer,12345),headers={'user-agent':ua,'origin':'http://localhost',**(headers or {})})

def test_direct_tv_guest(account):
    c=tv_client(account)
    me=c.get('/api/auth/me');assert me.status_code==200,me.text
    assert me.json()['id']=='guest' and me.json()['tv_guest'] and not me.json()['must_change']
    assert c.get('/api/media').status_code==200
    assert c.put('/api/profiles/guest/preferences',json={'theme':'plum','source_ids':[],'source_names':[]}).status_code==200
    assert c.get('/api/profiles/yoav/activity').status_code==403
    assert c.get('/api/auth/passkeys').status_code==403
    assert c.post('/api/auth/password',json={'current_password':'Guest1919','new_password':'other password'}).status_code==403
    assert c.get('/api/auth/me').json()['theme']=='plum'

@pytest.mark.parametrize('peer,ua,headers',[
 ('127.0.0.1',TV_UA,{}),('8.8.8.8',TV_UA,{}),('::1',TV_UA,{}),
 ('192.168.1.25','Mozilla/5.0 Chrome/130 Safari/537.36',{}),
 ('192.168.1.25',TV_UA,{'cf-connecting-ip':'192.168.1.25'}),
 ('192.168.1.25',TV_UA,{'x-forwarded-for':'192.168.1.25'}),
 ('192.168.1.25',TV_UA,{'x-dahan-tunnel':'1'}),
])
def test_guest_excludes_desktop_public_and_proxy(account,peer,ua,headers):
    c=tv_client(account,peer,ua,headers)
    assert c.get('/api/auth/me').status_code==401
    assert c.get('/api/media').status_code==401

@pytest.mark.parametrize('ua',['Mozilla/5.0 (Web0S; Linux/SmartTV) AppleWebKit/537.36','Mozilla/5.0 HbbTV/1.5.1','Mozilla/5.0 (Linux; Android 9; BRAVIA)'])
def test_tv_browser_families(account,ua):
    assert tv_client(account,ua=ua).get('/api/auth/me').json()['tv_guest']


def test_drora_initial_password(account):
    c, _ = account
    assert {'id':'drora','name':'Drora'} in c.get('/api/auth/users').json()
    result = login(c, 'drora', 'Drora1919').json()
    assert result['name'] == 'Drora' and result['must_change']
    assert c.get('/api/media').status_code == 403
    assert not change(c, 'Drora1919', 'Drora private test password').json()['must_change']


def test_guest_fixed_password_only(account):
    c, core = account
    assert c.post('/api/auth/login',json={'username':'guest','password':'Guest1919'}).status_code == 401
    result = login(c, 'guest', 'Guest123456').json()
    assert not result['must_change']
    assert c.get('/api/media').status_code == 200
    assert c.post('/api/auth/password',json={'current_password':'Guest123456','new_password':'different password'}).status_code == 403
    assert c.post('/api/auth/passkeys/register/options',json={'password':'Guest123456'}).status_code == 403
    assert c.post('/api/auth/passkeys/register/verify',json={'credential':{}}).status_code == 403
    assert c.post('/api/auth/passkeys/login/options',json={'username':'Guest'}).status_code == 403
    assert c.get('/api/auth/passkeys').status_code == 403
    assert c.post('/api/auth/passkeys/fake/remove',json={'password':'Guest123456'}).status_code == 403
    from backend import account_auth
    with core.db() as db:
        old_hash = db.execute("SELECT password_hash FROM account_passwords WHERE profile_id='guest'").fetchone()[0]
        account_auth.migrate(db)
        assert db.execute("SELECT password_hash FROM account_passwords WHERE profile_id='guest'").fetchone()[0] == old_hash
    assert c.get('/api/auth/me').status_code == 200


def test_guest_policy_migrates_existing_credentials_once(account):
    c, core = account
    from backend import account_auth
    with core.db() as db:
        db.execute("DELETE FROM account_policy_migrations WHERE id='guest-password-only-v1'")
        db.execute("UPDATE account_passwords SET password_hash=?,must_change=1 WHERE profile_id='guest'", (account_auth.hash_password('old guest password'),))
        db.execute("INSERT INTO account_sessions VALUES('old-guest','guest',?)", (time.time()+100,))
        db.execute("INSERT INTO account_passkeys VALUES('guest-key','guest',X'00',0,'old',?,NULL)", ('2026-01-01',))
        personal = db.execute("SELECT password_hash FROM account_passwords WHERE profile_id='yoav'").fetchone()[0]
        account_auth.migrate(db)
        assert not db.execute("SELECT 1 FROM account_sessions WHERE profile_id='guest'").fetchone()
        assert not db.execute("SELECT 1 FROM account_passkeys WHERE profile_id='guest'").fetchone()
        assert db.execute("SELECT password_hash FROM account_passwords WHERE profile_id='yoav'").fetchone()[0] == personal
    assert not login(c,'guest','Guest123456').json()['must_change']
