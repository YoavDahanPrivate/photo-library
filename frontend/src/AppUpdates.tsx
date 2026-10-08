import React, {useEffect, useState} from 'react';
declare const __APP_VERSION__: string;

export default function AppUpdates({canReload}:{canReload:boolean}) {
  const [pending,setPending]=useState('');
  const [edited,setEdited]=useState(false);
  useEffect(()=>{
    let stopped=false, checking=false;
    let controller:AbortController|null=null;
    const dirty=()=>setEdited(true);
    const check=async()=>{
      if(document.visibilityState!=='visible'||checking)return;
      checking=true;
      controller=new AbortController();
      const requestController=controller;
      const timeout=setTimeout(()=>requestController.abort(),10000);
      try {
        const response=await fetch('/version.json?t='+Date.now(),{cache:'no-store',signal:requestController.signal});
        if(!response.ok)return;
        const data=await response.json();
        if(!stopped&&typeof data.version==='string'&&/^[a-f0-9-]{36}$/.test(data.version)&&data.version!==__APP_VERSION__)setPending(data.version);
      } catch { /* Offline or deploying: keep the current app usable. */ }
      finally {clearTimeout(timeout);checking=false;}
    };
    void check();
    const interval=setInterval(check,60000);
    window.addEventListener('pageshow',check);
    window.addEventListener('focus',check);
    window.addEventListener('online',check);
    document.addEventListener('visibilitychange',check);
    document.addEventListener('input',dirty);
    return()=>{stopped=true;controller?.abort();clearInterval(interval);window.removeEventListener('pageshow',check);window.removeEventListener('focus',check);window.removeEventListener('online',check);document.removeEventListener('visibilitychange',check);document.removeEventListener('input',dirty);};
  },[]);
  const reload=()=>{
    const url=new URL(window.location.href);
    url.searchParams.set('app-release',pending);
    window.location.replace(url.toString());
  };
  useEffect(()=>{
    if(!pending||!canReload||edited||new URL(window.location.href).searchParams.get("app-release")===pending)return;
    let lastActivity=Date.now();
    const activity=()=>{lastActivity=Date.now();};
    window.addEventListener('pointerdown',activity);window.addEventListener('keydown',activity);window.addEventListener('scroll',activity,true);
    const timer=setInterval(()=>{
      if(document.visibilityState==='visible'&&Date.now()-lastActivity>8000&&!document.querySelector('[role="dialog"],[aria-modal="true"]')&&!document.activeElement?.matches('input,textarea,select,[contenteditable="true"]'))reload();
    },1000);
    return()=>{clearInterval(timer);window.removeEventListener('pointerdown',activity);window.removeEventListener('keydown',activity);window.removeEventListener('scroll',activity,true);};
  },[pending,canReload,edited]);
  if(!pending)return null;
  return <div className="app-update-notice" role="status"><span><strong>A new version is ready</strong><small>{canReload&&!edited?'Updating automatically when idle…':'Update when you’re finished. Unsaved edits will be cleared.'}</small></span><button onClick={reload}>Update now</button></div>;
}
