"""Individual password sessions and verified WebAuthn passkeys for Dahan."""
import base64, hashlib, hmac, json, secrets, time, re
from ipaddress import ip_address, ip_network
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from webauthn import (generate_registration_options, verify_registration_response,
                      generate_authentication_options, verify_authentication_response)
from webauthn.helpers import options_to_json
from webauthn.helpers.structs import (AuthenticatorSelectionCriteria, ResidentKeyRequirement,
                                     UserVerificationRequirement, PublicKeyCredentialDescriptor)
from .core import db
from . import user_profiles

router=APIRouter(prefix='/api/auth',tags=['accounts'])
COOKIE='dahan_account'
FLOW='dahan_passkey_flow'
RP='dahanphotos.com'
ORIGIN='https://'+RP
TTL=12*3600

def digest(value): return hashlib.sha256(value.encode()).hexdigest()
def encode(value): return base64.urlsafe_b64encode(value).rstrip(b'=').decode()
def decode(value): return base64.urlsafe_b64decode(value+'='*((-len(value))%4))
def hash_password(value):
    salt=secrets.token_bytes(16)
    return 'pbkdf2_sha256$600000$'+encode(salt)+'$'+encode(hashlib.pbkdf2_hmac('sha256',value.encode(),salt,600000))
def check_password(value, stored):
    try:
        algorithm,iterations,salt,expected=stored.split('$')
        return algorithm=='pbkdf2_sha256' and hmac.compare_digest(hashlib.pbkdf2_hmac('sha256',value.encode(),decode(salt),int(iterations)),decode(expected))
    except (ValueError,TypeError): return False
DUMMY=hash_password(secrets.token_urlsafe(32))

def migrate(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS account_passwords(profile_id TEXT PRIMARY KEY REFERENCES user_profiles(id),password_hash TEXT NOT NULL,must_change INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS account_sessions(token_hash TEXT PRIMARY KEY,profile_id TEXT NOT NULL REFERENCES user_profiles(id),expires REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS account_attempts(key TEXT NOT NULL,at REAL NOT NULL);
    CREATE INDEX IF NOT EXISTS account_attempts_key ON account_attempts(key,at);
    CREATE TABLE IF NOT EXISTS account_passkeys(id TEXT PRIMARY KEY,profile_id TEXT NOT NULL REFERENCES user_profiles(id),public_key BLOB NOT NULL,sign_count INTEGER NOT NULL,name TEXT NOT NULL,created_at TEXT NOT NULL,last_used_at TEXT);
    CREATE TABLE IF NOT EXISTS account_challenges(token_hash TEXT PRIMARY KEY,profile_id TEXT NOT NULL,kind TEXT NOT NULL,challenge BLOB NOT NULL,session_hash TEXT,expires REAL NOT NULL);
    ''')
    for name in user_profiles.NAMES:
        if not c.execute('SELECT 1 FROM account_passwords WHERE profile_id=?',(name.lower(),)).fetchone():
            c.execute('INSERT INTO account_passwords(profile_id,password_hash) VALUES(?,?)',(name.lower(),hash_password(name+'1919')))

# Browser identification is convenience, not proof of device identity. Only direct
# RFC1918 LAN peers qualify; loopback proxies and forwarded requests never do.
TV_BROWSER = re.compile(r"smart[ -]?tv|smarttv|hbbtv|tizen|web0s|webos|netcast|viera|bravia|googletv|google tv|android tv|appletv|roku|aft[a-z0-9]+", re.I)
LAN_NETWORKS = tuple(ip_network(n) for n in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16'))

def lan_tv(request):
    if any(h in request.headers for h in ('forwarded','x-forwarded-for','x-forwarded-host','x-forwarded-proto','cf-connecting-ip','cf-ray','x-dahan-tunnel')):
        return False
    try:
        peer=ip_address(request.client.host)
    except (ValueError, AttributeError):
        return False
    return any(peer in network for network in LAN_NETWORKS) and bool(TV_BROWSER.search(request.headers.get('user-agent','')))

def session(request, allow_initial=False):
    token=request.cookies.get(COOKIE,'')
    with db() as c:
        row=c.execute('SELECT s.profile_id,s.token_hash,p.must_change FROM account_sessions s JOIN account_passwords p ON p.profile_id=s.profile_id WHERE s.token_hash=? AND s.expires>?',(digest(token),time.time())).fetchone()
    if not row:
        if lan_tv(request):
            if request.url.path.startswith('/api/auth/') and request.url.path not in ('/api/auth/me','/api/auth/logout'):
                raise HTTPException(403,'Sign in securely to manage account credentials.')
            return {'profile_id':'guest','token_hash':None,'must_change':False,'tv_guest':True}
        raise HTTPException(401,'Please sign in.')
    if row['must_change'] and not allow_initial: raise HTTPException(403,'Change your initial password first.')
    return dict(row)

def guard(request):
    path=request.url.path
    if not path.startswith('/api/') or path=='/api/health': return None
    if request.method not in ('GET','HEAD','OPTIONS') and not request.headers.get('origin'):
        return JSONResponse({'detail':'Origin required'},status_code=403)
    if path.startswith('/api/auth/'): return None
    try:
        identity=session(request)
        request.state.profile_id=identity['profile_id']
        if path.startswith('/api/profiles/') and path.split('/')[3]!=identity['profile_id']:
            raise HTTPException(403,'This profile belongs to another user.')
    except HTTPException as e:
        return JSONResponse({'detail':e.detail},status_code=e.status_code)
    return None

def rate(request, account=''):
    # CF-Connecting-IP is overwritten by Cloudflare; direct LAN access is rate-limited too.
    ip=request.headers.get('cf-connecting-ip') or request.client.host
    keys=['ip:'+ip,'account:'+account]
    now=time.time()
    with db() as c:
        c.execute('DELETE FROM account_attempts WHERE at<?',(now-900,))
        if c.execute('SELECT count(*) FROM account_attempts WHERE key IN (?,?)',keys).fetchone()[0]>=20 or c.execute('SELECT count(*) FROM account_attempts').fetchone()[0]>=300:
            raise HTTPException(429,'Too many attempts. Please wait 15 minutes.')
        c.executemany('INSERT INTO account_attempts(key,at) VALUES(?,?)',[(key,now) for key in keys])

def clear_rate(account, request):
    ip=request.headers.get('cf-connecting-ip') or request.client.host
    with db() as c: c.execute('DELETE FROM account_attempts WHERE key IN (?,?)',('account:'+account,'ip:'+ip))

def issue(request, identity, method):
    token=secrets.token_urlsafe(32)
    with db() as c:
        c.execute('DELETE FROM account_sessions WHERE expires<? OR token_hash=?',(time.time(),digest(request.cookies.get(COOKIE,''))))
        c.execute('INSERT INTO account_sessions VALUES(?,?,?)',(digest(token),identity,time.time()+TTL))
        c.execute('UPDATE user_profiles SET last_login_at=? WHERE id=?',(user_profiles.now(),identity))
        user_profiles.record(c,identity,'login',{'method':method})
        p=user_profiles.profile(c,identity)
        p['must_change']=bool(c.execute('SELECT must_change FROM account_passwords WHERE profile_id=?',(identity,)).fetchone()[0])
    response=JSONResponse(p)
    response.set_cookie(COOKIE,token,max_age=TTL,secure=True,httponly=True,samesite='strict',path='/')
    response.headers['Cache-Control']='no-store'
    return response

class Login(BaseModel):
    username:str=Field(max_length=80)
    password:str=Field(max_length=1024)
class PasswordChange(BaseModel):
    current_password:str=Field(max_length=1024)
    new_password:str=Field(min_length=10,max_length=1024)
class PasswordProof(BaseModel):
    password:str=Field(max_length=1024)
    name:str=Field(default='My device',max_length=80)
class Username(BaseModel):
    username:str=Field(max_length=80)
class Credential(BaseModel):
    credential:dict

@router.get('/users')
def users():
    return [{'id':n.lower(),'name':n} for n in user_profiles.NAMES]

@router.post('/login')
def login(body:Login,request:Request):
    identity=body.username.strip().lower()
    rate(request,identity)
    with db() as c: row=c.execute('SELECT password_hash FROM account_passwords WHERE profile_id=?',(identity,)).fetchone()
    if not check_password(body.password,row['password_hash'] if row else DUMMY): raise HTTPException(401,'Incorrect username or password.')
    clear_rate(identity, request)
    return issue(request,identity,'password')

@router.get('/me')
def me(request:Request):
    identity=session(request,True)
    with db() as c: p=user_profiles.profile(c,identity['profile_id'])
    return {**p,'must_change':bool(identity['must_change']),'tv_guest':identity.get('tv_guest',False)}

@router.post('/logout')
def logout(request:Request):
    with db() as c: c.execute('DELETE FROM account_sessions WHERE token_hash=?',(digest(request.cookies.get(COOKIE,'')),))
    response=JSONResponse({'ok':True});response.delete_cookie(COOKIE,path='/',secure=True,httponly=True,samesite='strict');return response

@router.post('/password')
def change_password(body:PasswordChange,request:Request):
    identity=session(request,True)['profile_id'];rate(request,identity)
    with db() as c:
        row=c.execute('SELECT password_hash FROM account_passwords WHERE profile_id=?',(identity,)).fetchone()
        if not check_password(body.current_password,row['password_hash']): raise HTTPException(401,'Current password is incorrect.')
        if body.new_password==body.current_password or body.new_password.lower() in [(n+'1919').lower() for n in user_profiles.NAMES]: raise HTTPException(400,'Choose a new password, not an initial password.')
        c.execute('UPDATE account_passwords SET password_hash=?,must_change=0 WHERE profile_id=?',(hash_password(body.new_password),identity))
        c.execute('DELETE FROM account_sessions WHERE profile_id=?',(identity,))
        c.execute('DELETE FROM account_challenges WHERE profile_id=?',(identity,))
        user_profiles.record(c,identity,'password_changed',{})
    clear_rate(identity, request)
    return issue(request,identity,'password_change')

def challenge_response(request,identity,kind,options,binding=None):
    token=secrets.token_urlsafe(32)
    with db() as c:
        c.execute('DELETE FROM account_challenges WHERE expires<? OR token_hash=?',(time.time(),digest(request.cookies.get(FLOW,''))))
        c.execute('INSERT INTO account_challenges VALUES(?,?,?,?,?,?)',(digest(token),identity,kind,options.challenge,binding,time.time()+300))
    response=JSONResponse(json.loads(options_to_json(options)))
    response.set_cookie(FLOW,token,max_age=300,secure=True,httponly=True,samesite='strict',path='/')
    return response

def consume(request,kind,binding=None):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        token=digest(request.cookies.get(FLOW,''))
        row=c.execute('SELECT * FROM account_challenges WHERE token_hash=?',(token,)).fetchone()
        c.execute('DELETE FROM account_challenges WHERE token_hash=?',(token,))
    if not row or row['kind']!=kind or row['expires']<time.time() or row['session_hash']!=binding:
        raise HTTPException(400,'Passkey request expired. Please try again.')
    return row

@router.post('/passkeys/register/options')
def register_options(body:PasswordProof,request:Request):
    auth=session(request);identity=auth['profile_id'];rate(request,identity)
    with db() as c:
        row=c.execute('SELECT password_hash FROM account_passwords WHERE profile_id=?',(identity,)).fetchone()
        if not check_password(body.password,row['password_hash']): raise HTTPException(401,'Current password is incorrect.')
        keys=c.execute('SELECT id FROM account_passkeys WHERE profile_id=?',(identity,)).fetchall()
        if len(keys)>=20: raise HTTPException(400,'Remove an unused passkey before adding another.')
    options=generate_registration_options(rp_id=RP,rp_name='Dahan Photos',user_id=identity.encode(),user_name=identity,user_display_name=identity.title(),exclude_credentials=[PublicKeyCredentialDescriptor(id=decode(k['id'])) for k in keys],authenticator_selection=AuthenticatorSelectionCriteria(resident_key=ResidentKeyRequirement.PREFERRED,user_verification=UserVerificationRequirement.REQUIRED))
    clear_rate(identity, request)
    return challenge_response(request,identity,'register',options,auth['token_hash'])

@router.post('/passkeys/register/verify')
def register_verify(body:Credential,request:Request):
    auth=session(request);flow=consume(request,'register',auth['token_hash'])
    if flow['profile_id']!=auth['profile_id']: raise HTTPException(403,'Wrong account')
    try: result=verify_registration_response(credential=body.credential,expected_challenge=flow['challenge'],expected_rp_id=RP,expected_origin=ORIGIN,require_user_verification=True)
    except Exception: raise HTTPException(400,'Passkey verification failed. Please try again.')
    with db() as c:
        if c.execute('SELECT 1 FROM account_passkeys WHERE id=?',(encode(result.credential_id),)).fetchone(): raise HTTPException(400,'This passkey is already registered.')
        c.execute('INSERT INTO account_passkeys VALUES(?,?,?,?,?,?,NULL)',(encode(result.credential_id),auth['profile_id'],result.credential_public_key,result.sign_count,'Passkey',user_profiles.now()))
        user_profiles.record(c,auth['profile_id'],'passkey_added',{})
    return {'ok':True}

@router.post('/passkeys/login/options')
def login_options(body:Username,request:Request):
    identity=body.username.strip().lower();rate(request,identity)
    with db() as c: keys=c.execute('SELECT id FROM account_passkeys WHERE profile_id=?',(identity,)).fetchall()
    if not keys: raise HTTPException(400,'Sign in with your password to enable a passkey first.')
    options=generate_authentication_options(rp_id=RP,allow_credentials=[PublicKeyCredentialDescriptor(id=decode(k['id'])) for k in keys],user_verification=UserVerificationRequirement.REQUIRED)
    return challenge_response(request,identity,'login',options)

@router.post('/passkeys/login/verify')
def login_verify(body:Credential,request:Request):
    flow=consume(request,'login')
    with db() as c: key=c.execute('SELECT * FROM account_passkeys WHERE id=? AND profile_id=?',(body.credential.get('id',''),flow['profile_id'])).fetchone()
    if not key: raise HTTPException(400,'Passkey verification failed.')
    try:
        result=verify_authentication_response(credential=body.credential,expected_challenge=flow['challenge'],expected_rp_id=RP,expected_origin=ORIGIN,credential_public_key=key['public_key'],credential_current_sign_count=key['sign_count'],require_user_verification=True)
        handle=body.credential.get('response',{}).get('userHandle')
        if handle and decode(handle)!=flow['profile_id'].encode(): raise ValueError('Wrong user handle')
    except Exception: raise HTTPException(400,'Passkey verification failed. Please try again.')
    with db() as c:
        updated=c.execute('UPDATE account_passkeys SET sign_count=?,last_used_at=? WHERE id=? AND sign_count=?',(result.new_sign_count,user_profiles.now(),key['id'],key['sign_count']))
        if updated.rowcount!=1: raise HTTPException(400,'Passkey changed. Please try again.')
    clear_rate(flow['profile_id'], request)
    return issue(request,flow['profile_id'],'passkey')

@router.get('/passkeys')
def list_keys(request:Request):
    identity=session(request)['profile_id']
    with db() as c: return [dict(r) for r in c.execute('SELECT id,name,created_at,last_used_at FROM account_passkeys WHERE profile_id=?',(identity,))]

@router.post('/passkeys/{key_id}/remove')
def remove_key(key_id:str,body:PasswordProof,request:Request):
    identity=session(request)['profile_id'];rate(request,identity)
    with db() as c:
        row=c.execute('SELECT password_hash FROM account_passwords WHERE profile_id=?',(identity,)).fetchone()
        if not check_password(body.password,row['password_hash']): raise HTTPException(401,'Current password is incorrect.')
        c.execute('DELETE FROM account_passkeys WHERE id=? AND profile_id=?',(key_id,identity))
        c.execute('DELETE FROM account_sessions WHERE profile_id=? AND token_hash<>?',(identity,digest(request.cookies.get(COOKIE,''))))
        user_profiles.record(c,identity,'passkey_removed',{})
    clear_rate(identity, request)
    return {'ok':True}
