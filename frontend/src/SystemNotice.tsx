import {useEffect,useState,type ReactNode} from 'react';

/** Stable noticeKey prevents polling renders from restarting the 30-second lifetime. */
export default function SystemNotice({noticeKey,children,className='',onDismiss}:{noticeKey:string;children:ReactNode;className?:string;onDismiss?:()=>void}) {
  const [phase,setPhase]=useState<'visible'|'fading'|'hidden'>('visible');
  useEffect(()=>{
    setPhase('visible');
    const fade=setTimeout(()=>setPhase('fading'),30000);
    const hide=setTimeout(()=>setPhase('hidden'),30300);
    return()=>{clearTimeout(fade);clearTimeout(hide);};
  },[noticeKey]);
  if(phase==='hidden')return null;
  return <div className={`system-notice ${className} ${phase==='fading'?'is-fading':''}`}>
    <div className="system-notice-content">{children}</div>
    <button type="button" className="system-notice-dismiss" aria-label="Dismiss notification" onClick={()=>{setPhase('hidden');onDismiss?.();}}>×</button>
  </div>;
}
