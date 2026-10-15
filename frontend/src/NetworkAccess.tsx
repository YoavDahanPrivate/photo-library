import {readApiResponse} from "./ApiResponse";
import React, {useEffect, useRef, useState} from "react";

type Saved={server:string;saved:boolean;username:string};
export const networkFolder=(root:string)=>/^[/\\]{2}[^/\\]+[/\\][^/\\]+/.test(root.trim());
async function access(path:string,body?:unknown,signal?:AbortSignal){
  const response=await fetch("/api/databases/access"+path,{method:body===undefined?"GET":"POST",signal,headers:{"Content-Type":"application/json"},...(body===undefined?{}:{body:JSON.stringify(body)})});
  return readApiResponse(response);
}

export default function NetworkAccess({root,disabled,onConnected}:{root:string;disabled:boolean;onConnected:()=>void}){
  const currentRoot=useRef(root);currentRoot.current=root;
  const [capability,setCapability]=useState<{available:boolean;reason:string|null}|null>(null);
  const [saved,setSaved]=useState<Saved|null>(null),[username,setUsername]=useState(""),[password,setPassword]=useState("");
  const [remember,setRemember]=useState(true),[working,setWorking]=useState(false),[error,setError]=useState(""),[message,setMessage]=useState("");
  useEffect(()=>{
    const controller=new AbortController();setPassword("");setUsername("");setSaved(null);setError("");setMessage("");
    const timer=setTimeout(async()=>{try{
      const c=await access("/capabilities",undefined,controller.signal);if(controller.signal.aborted)return;setCapability(c);
      if(c.available){const s:Saved=await access("/status",{root},controller.signal);if(!controller.signal.aborted){setSaved(s);setUsername(s.username);}}
    }catch(e){if(!controller.signal.aborted)setError(String(e));}},300);
    return()=>{clearTimeout(timer);controller.abort();};
  },[root]);
  const busy=disabled||working;
  const connect=async()=>{
    const submitted=password,submittedRoot=root;setPassword("");setWorking(true);setError("");setMessage("");
    try{
      const result=await access("/connect",{root,username,password:submitted,remember});
      const status=await access("/status",{root});
      if(currentRoot.current!==submittedRoot)return;
      setSaved(status);
      setMessage(result.used_existing?"This folder is readable using the existing Windows connection. Continue with Preview assignments. The entered credentials were not verified or saved; any previously saved access remains unchanged.":result.saved?"Folder access tested. Credentials saved for future syncs and other folders on this server.":"Folder access tested. These credentials were not saved; any previously saved access remains unchanged.");
      onConnected();
    }catch(e){if(currentRoot.current===submittedRoot)setError(String(e));}finally{setWorking(false);}
  };
  const useExisting=async()=>{
    const submittedRoot=root;setWorking(true);setError('');setMessage('');setPassword('');
    try{await access('/use-existing',{root});if(currentRoot.current!==submittedRoot)return;setMessage('Windows already provides readable access to this folder. Continue with Preview assignments. No new credentials were saved.');onConnected();}
    catch(e){if(currentRoot.current===submittedRoot)setError(e instanceof Error?e.message:String(e));}finally{setWorking(false);}
  };
  const forget=async()=>{
    const submittedRoot=root;
    setWorking(true);setError("");setMessage("");setPassword("");
    try{await access("/forget",{root});if(currentRoot.current!==submittedRoot)return;setSaved(saved?{...saved,saved:false,username:""}:null);setMessage("Saved access forgotten for all folders on this server. Windows may keep an existing connection open until sign-out; no share was disconnected.");}
    catch(e){if(currentRoot.current===submittedRoot)setError(String(e));}finally{setWorking(false);}
  };
  return <section className="manager-network-access" aria-label="Network folder access"><h4>Network folder access</h4>
    {!capability?<p>Checking whether credentials can be managed here…</p>:!capability.available?<p>{capability.reason}</p>:<>
      <p>{saved?.saved?<>Saved access for <strong>{saved.server}</strong> as <strong>{saved.username}</strong>. Dahan uses it automatically.</>:"First try the existing Windows connection. If this folder requires another login, enter its username and password and test access."}</p>
      <div className="manager-network-fields"><label>Network username<input aria-label="Network username" disabled={busy} maxLength={256} autoComplete="off" placeholder="SERVER\username or user@domain" value={username} onChange={e=>setUsername(e.target.value)}/></label>
      <label>Network password<input aria-label="Network password" disabled={busy} type="password" autoComplete="new-password" value={password} onChange={e=>setPassword(e.target.value)} onKeyDown={e=>{if(e.key==="Enter"){e.preventDefault();if(username.trim()&&password&&!busy)connect();}}}/></label></div>
      <label className="manager-toggle"><input type="checkbox" disabled={busy} checked={remember} onChange={e=>setRemember(e.target.checked)}/><span>Remember for future syncs on this computer · until forgotten or replaced</span></label>
      <p className="manager-note">Saved in Windows Credential Manager for the account running Dahan, and reused for other folders on the same server. Passwords are not stored in the catalogue or browser. Programs running as that Windows account can retrieve them; use an account with only the folder permissions Dahan needs.</p>
      <p className="manager-note">Windows allows one account per server connection. If another account is already connected and can read this folder, Dahan uses that connection. It cannot verify or remember a different password through that existing connection.</p>
      <div className="sync-actions"><button type="button" disabled={busy} onClick={useExisting}>Use current Windows access</button><button type="button" disabled={busy||!username.trim()||!password} onClick={connect}>{working?"Checking access…":"Test folder access"}</button>{saved?.saved&&<button type="button" disabled={busy} onClick={forget}>Forget saved access</button>}</div>
    </>}
    {error&&<p role="alert" className="error">{error}</p>}{message&&<p role="status">{message}</p>}
  </section>;
}
