import {useEffect,useRef,useState,type ReactNode} from 'react';
import {passkey,supported} from './Passkeys';
import './profiles.css';
export type PeoplePreferences={action:"search"|"edit";known:boolean;unknown:boolean;sort:"name"|"count";directions:Record<"name"|"count","asc"|"desc">};
export type Profile={id:string;name:string;theme:string;source_ids:string[]|null;source_names:string[]|null;last_login_at:string|null;people_browse?:PeoplePreferences|null;must_change?:boolean;tv_guest?:boolean};
export function currentProfileId(){return localStorage.getItem('dahan.profile')||'';}
async function call(path:string,method='GET',body?:unknown,signal?:AbortSignal){
 const r=await fetch('/api'+path,{method,signal,headers:{'Content-Type':'application/json'},...(body!==undefined?{body:JSON.stringify(body)}:{})});const data=await r.json();
 if(!r.ok)throw new Error(typeof data.detail==='string'?data.detail:'Check your entries and try again.');return data;
}
let preferenceQueue:Promise<unknown>=Promise.resolve();
export function saveProfilePreferences(id:string,theme:string,source_ids:string[],source_names:string[]){const task=preferenceQueue.catch(()=>{}).then(()=>call('/profiles/'+id+'/preferences','PUT',{theme,source_ids,source_names}));preferenceQueue=task;return task;}
export function savePeoplePreferences(id:string,preferences:PeoplePreferences){const task=preferenceQueue.catch(()=>{}).then(()=>call('/profiles/'+id+'/people-preferences','PUT',preferences));preferenceQueue=task;return task;}
export function recordProfileSearch(id:string,expression:string,source_names:string[]){return call('/profiles/'+id+'/searches','POST',{expression,source_names});}
const accountNames=['Yoav','Hila','Bar','Rotem','Guy','Drora','Guest'];
function SignInForm({onAccept}:{onAccept:(profile:Profile)=>void}){
 const rememberedId=currentProfileId();
 const mobile=window.matchMedia('(pointer: coarse)').matches&&navigator.maxTouchPoints>0;
 const automatic=mobile&&supported()&&!!rememberedId&&rememberedId!=='guest';
 const [username,setUsername]=useState(rememberedId||'yoav'),[password,setPassword]=useState('');
 const [mode,setMode]=useState<'passkey'|'password'>(automatic?'passkey':'password');
 const [remembered,setRemembered]=useState(!!rememberedId),[busy,setBusy]=useState(false),[verifying,setVerifying]=useState(false),[failed,setFailed]=useState(false),[error,setError]=useState('');
 const attempted=useRef(false),attempt=useRef<AbortController|null>(null),checking=useRef(false);
 const displayName=accountNames.find(n=>n.toLowerCase()===username)||username;
 function usePassword(){
  if(checking.current)return;
  attempted.current=true;attempt.current?.abort();attempt.current=null;
  setBusy(false);setMode('password');setError('');setPassword('');
 }
 async function signInWithPasskey(auto=false){
  if(attempt.current||checking.current||!username)return;
  attempted.current=true;
  const controller=new AbortController();attempt.current=controller;
  setBusy(true);setMode('passkey');setFailed(false);setError('');
  try{
   const options=await call('/auth/passkeys/login/options','POST',{username},controller.signal);
   if(controller.signal.aborted)return;
   const credential=await passkey({...options,timeout:60000},false,controller.signal);
   if(controller.signal.aborted)return;
   checking.current=true;setVerifying(true);
   const profile=await call('/auth/passkeys/login/verify','POST',{credential});
   if(!controller.signal.aborted)onAccept(profile);
  }catch(e){
   if(controller.signal.aborted)return;
   const message=e instanceof Error?e.message:String(e);
   if(auto&&message==='Sign in with your password to enable a passkey first.'){
    setMode('password');
   }else{
    setFailed(true);
    setError(e instanceof DOMException&&(e.name==='NotAllowedError'||e.name==='AbortError')?'Face ID / fingerprint was not completed. Try again, use your password, or switch accounts.':message);
   }
  }finally{
   if(attempt.current===controller){attempt.current=null;checking.current=false;setVerifying(false);setBusy(false);}
  }
 }
 useEffect(()=>{
  const timer=setTimeout(()=>{if(automatic&&!attempted.current)void signInWithPasskey(true);},0);
  return()=>{clearTimeout(timer);attempt.current?.abort();};
 },[]);
 async function switchUser(){
  if(checking.current)return;
  usePassword();checking.current=true;setBusy(true);
  try{
   await call('/auth/logout','POST');
   localStorage.removeItem('dahan.profile');setRemembered(false);setUsername('');setFailed(false);
  }catch(e){setError(e instanceof Error?e.message:String(e));}
  finally{checking.current=false;setBusy(false);}
 }
 async function signInWithPassword(){
  if(checking.current||busy)return;
  checking.current=true;setBusy(true);setError('');
  try{onAccept(await call('/auth/login','POST',{username,password}));}
  catch(e){setError(e instanceof Error?e.message:String(e));}
  finally{checking.current=false;setBusy(false);}
 }
 return <>
  {mode==='passkey'?<div className="remembered-signin">
   <h2>Welcome back, {displayName}</h2>
   <p>{busy?'Confirm sign-in on your phone.':'Sign in to your library with Face ID or fingerprint.'}</p>
   <button disabled={busy||!supported()} onClick={()=>void signInWithPasskey()}>{failed?'Try Face ID / fingerprint again':'Sign in with Face ID / fingerprint'}</button>
   <button className="account-secondary" disabled={verifying} onClick={usePassword}>Use password</button>
   <button className="account-secondary" disabled={verifying} onClick={()=>void switchUser()}>Sign out / switch user</button>
  </div>:<>
   <form onSubmit={e=>{e.preventDefault();void signInWithPassword();}}>
    <label>Your account<select required disabled={busy} autoComplete="username" value={username} onChange={e=>{setUsername(e.target.value);setPassword('');setError('');setFailed(false);}}><option value="" disabled>Choose an account</option>{accountNames.map(n=><option key={n} value={n.toLowerCase()}>{n}</option>)}</select></label>
    <label>Password<input type="password" autoComplete="current-password" value={password} onChange={e=>setPassword(e.target.value)} required maxLength={1024}/></label><button disabled={busy||!username}>Sign in</button>
   </form>
   {username&&username!=='guest'&&<button className="account-secondary" disabled={busy||!supported()} onClick={()=>void signInWithPasskey()}>Sign in with Face ID / fingerprint</button>}
   {remembered&&<button className="account-secondary" disabled={busy} onClick={()=>void switchUser()}>Sign out / switch user</button>}
  </>}
  {username!=='guest'&&<small>Enable Face ID / fingerprint in Account settings after signing in. Your phone may also offer its screen-lock PIN.</small>}
  {busy&&<p role="status">{verifying?'Finishing sign-in…':'Please wait…'}</p>}
  {error&&<p role="alert" className="account-error">{error}</p>}
 </>;
}
export function ProfileShell({children}:{children:(profile:Profile,account:()=>void)=>ReactNode}){
 const [active,setActive]=useState<Profile|null>(null),[ready,setReady]=useState(false),[settings,setSettings]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
 const [current,setCurrent]=useState(''),[next,setNext]=useState(''),[confirm,setConfirm]=useState(''),[keys,setKeys]=useState<{id:string;created_at:string}[]>([]);
 const started=useRef(false);
 function clear(){setCurrent('');setNext('');setConfirm('');}
 function accept(p:Profile){localStorage.setItem('dahan.profile',p.id);localStorage.setItem('dahan.theme',p.theme);for(const [key,value] of [['dahan.sourceIds.v2',p.source_ids],['dahan.sources.v1',p.source_names]] as const){if(value===null)localStorage.removeItem(key);else localStorage.setItem(key,JSON.stringify(value));}localStorage.removeItem('dahan.phones.v1');setActive(p);clear();}
 async function run(work:()=>Promise<void>){if(busy)return;setBusy(true);setError('');setNotice('');try{await work();}catch(e){setError(e instanceof DOMException&&e.name==='NotAllowedError'?'Passkey request cancelled or timed out. You can still use your password.':e instanceof Error?e.message:String(e));}finally{setBusy(false);}}
 useEffect(()=>{document.getElementById('dahan-startup')?.remove();window.dispatchEvent(new Event('dahan:ready'));if(started.current)return;started.current=true;fetch('/api/auth/me').then(async r=>{if(r.status===401)return;if(!r.ok)throw new Error('Cannot load your account. Refresh to retry.');accept(await r.json());}).catch(e=>setError(String(e))).finally(()=>setReady(true));},[]);
 useEffect(()=>{const expired=()=>{setActive(null);setSettings(false);clear();setError('Your session expired. Please sign in again.');};window.addEventListener('dahan:session-expired',expired);return()=>window.removeEventListener('dahan:session-expired',expired);},[]);
 async function loadKeys(){setKeys(await call('/auth/passkeys'));}
 async function logout(){await run(async()=>{await preferenceQueue.catch(()=>{});await call('/auth/logout','POST');localStorage.removeItem('dahan.profile');setActive(null);setSettings(false);clear();setKeys([]);});}
 const alerts=<>{busy&&<p role="status">Please wait…</p>}{error&&<p role="alert" className="account-error">{error}</p>}{notice&&<p role="status">{notice}</p>}</>;
 const changeForm=<form onSubmit={e=>{e.preventDefault();void run(async()=>{if(next!==confirm)throw new Error('New passwords do not match.');await preferenceQueue.catch(()=>{});const p=await call('/auth/password','POST',{current_password:current,new_password:next});setActive(p);clear();setNotice('Password changed. Other sessions were signed out.');});}}>
  <label>Current password<input type="password" autoComplete="current-password" value={current} onChange={e=>setCurrent(e.target.value)} required maxLength={1024}/></label>
  <label>New password<input type="password" autoComplete="new-password" value={next} onChange={e=>setNext(e.target.value)} required minLength={10} maxLength={1024}/></label>
  <label>Confirm new password<input type="password" autoComplete="new-password" value={confirm} onChange={e=>setConfirm(e.target.value)} required minLength={10} maxLength={1024}/></label>
  <small>At least 10 characters. Choose a password different from your initial password.</small><button disabled={busy}>Change password</button>
 </form>;
 if(!ready)return <main className="profile-welcome"><p role="status">Opening your account…</p></main>;
 if(!active)return <main className="profile-welcome"><section className="account-card"><span className="profile-eyebrow">DAHAN · FAMILY LIBRARY</span><h1>Welcome back</h1><p>Sign in to restore your theme and search sources.</p>
 {location.protocol!=='https:'?<div className="secure-signin"><p>Open our secure website to sign in with your password or passkey.</p><a className="secure-signin-link" href="https://dahanphotos.com/"><strong>dahanphotos.com</strong><span>Continue to secure sign-in →</span></a></div>:<SignInForm onAccept={accept}/ >}{alerts}</section></main>;
 if(active.must_change&&active.id!=='guest')return <main className="profile-welcome"><section className="account-card"><span className="profile-eyebrow">{active.name} · FIRST SIGN-IN</span><h1>Choose your own password</h1><p>Replace your initial password before opening the library.</p>{changeForm}{alerts}<button className="account-secondary" disabled={busy} onClick={()=>void logout()}>Sign out</button></section></main>;
 return <div key={active.id}>{children(active,()=>void run(async()=>{await preferenceQueue.catch(()=>{});setSettings(true);clear();if(active.id!=='guest')await loadKeys();}))}{settings&&<div className="account-overlay"><section className="account-card" role="dialog" aria-modal="true" aria-labelledby="account-heading"><h1 id="account-heading">{active.name} · Account</h1><button disabled={busy} className="account-secondary" onClick={()=>{setSettings(false);clear();setError('');}}>Back to photos</button><>{active.id==='guest'?<div><h2>{active.tv_guest?"TV Guest access":"Guest account"}</h2><p>{active.tv_guest?"This TV is automatically using Guest on your home network.":"Guest uses a shared password. Password changes and Face ID / fingerprint sign-in are unavailable for this account."}</p><a className="secure-signin-link" href="https://dahanphotos.com/"><strong>dahanphotos.com</strong><span>Sign in to a personal account →</span></a>{!active.tv_guest&&<button className="account-secondary" disabled={busy} onClick={()=>void logout()}>Sign out / switch user</button>}</div>:<><h2>Change password</h2>{changeForm}<h2>Face ID / fingerprint</h2><p>Save a passkey to sign in with your device. Biometric data stays on your device; it may also offer its PIN.</p><button disabled={busy||!supported()||location.hostname!=='dahanphotos.com'} onClick={()=>void run(async()=>{if(!current)throw new Error('Enter your current password above to enable a passkey.');const o=await call('/auth/passkeys/register/options','POST',{password:current});const credential=await passkey(o,true);await call('/auth/passkeys/register/verify','POST',{credential});setCurrent('');await loadKeys();setNotice('Passkey enabled for your next sign-in.');})}>Enable Face ID / fingerprint</button><small>Enter your current password above to add or remove a passkey. Use dahanphotos.com for passkeys.</small>
 {keys.length?<ul className="account-keys">{keys.map((k,i)=><li key={k.id}><span>Passkey {i+1} · {new Date(k.created_at).toLocaleDateString()}</span><button className="account-secondary" disabled={busy} onClick={()=>void run(async()=>{if(!current)throw new Error('Enter your current password above to remove a passkey.');await call('/auth/passkeys/'+encodeURIComponent(k.id)+'/remove','POST',{password:current});setCurrent('');await loadKeys();setNotice('Passkey removed. Other sessions were signed out.');})}>Remove</button></li>)}</ul>:<p>No passkeys enabled yet.</p>}{alerts}<button className="account-secondary" disabled={busy} onClick={()=>void logout()}>Sign out / switch user</button></>}</></section></div>}</div>;
}
