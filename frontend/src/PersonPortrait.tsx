import {useEffect,useId,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {Check,ImagePlus,Users,X} from 'lucide-react';
import {readApiResponse} from './ApiResponse';
import ReviewPagination from './ReviewPagination';

export type PortraitPerson={id:number;name:string|null;cover:string|null;portrait_custom?:boolean;automatic_cover?:string|null};
type Choice={id:string;media_id:string;name:string;kind:string;taken:string|null;timestamp:number|null;available:boolean};
type Page={person:PortraitPerson;total:number;offset:number;limit:number;items:Choice[]};
const image=(id:string)=>'/api/faces/'+encodeURIComponent(id)+'/thumbnail';

export default function PersonPortrait({person,onClose,onSaved}:{person:PortraitPerson;onClose:()=>void;onSaved:(value:PortraitPerson)=>void}){
 const [data,setData]=useState<Page|null>(null),[offset,setOffset]=useState(0),[selected,setSelected]=useState<string|null>(null);
 const [loading,setLoading]=useState(true),[saving,setSaving]=useState(false),[error,setError]=useState(''),[refresh,setRefresh]=useState(0);
 const [broken,setBroken]=useState<Set<string>>(new Set());
 const panel=useRef<HTMLElement|null>(null),initial=useRef(true),alive=useRef(true);
 const heading=useId();
 useEffect(()=>{
  alive.current=true;
  const opener=document.activeElement instanceof HTMLElement?document.activeElement:null,root=document.getElementById('root'),inert=root?.inert,overflow=document.body.style.overflow;
  if(root)root.inert=true;document.body.style.overflow='hidden';panel.current?.querySelector<HTMLButtonElement>('button')?.focus();
  return()=>{alive.current=false;if(root)root.inert=!!inert;document.body.style.overflow=overflow;opener?.focus();};
 },[]);
 useEffect(()=>{
  const controller=new AbortController();setLoading(true);setError('');
  fetch(`/api/people/${person.id}/portrait?offset=${offset}&limit=30`,{signal:controller.signal}).then(readApiResponse).then((next:Page)=>{
   if(controller.signal.aborted)return;
   if(offset>=next.total&&offset>0){setOffset(Math.max(0,Math.floor((next.total-1)/30)*30));return;}
   setData(next);if(initial.current){setSelected(next.person.portrait_custom?next.person.cover:null);initial.current=false;}
  }).catch(e=>{if(!controller.signal.aborted)setError(e instanceof Error?e.message:String(e));}).finally(()=>{if(!controller.signal.aborted)setLoading(false);});
  return()=>controller.abort();
 },[person.id,offset,refresh]);
 const save=async()=>{
  setSaving(true);setError('');
  try{
   const response=await fetch(`/api/people/${person.id}/portrait`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({face_id:selected})});
   const result=await readApiResponse(response) as PortraitPerson;
   if(alive.current)onSaved(result);
  }catch(e){if(alive.current)setError(e instanceof Error?e.message:String(e));}
  finally{if(alive.current)setSaving(false);}
 };
 const current=data?.person,preview=selected||(current?.automatic_cover??(!current?.portrait_custom?current?.cover:null));
 const changed=!!current&&selected!==(current.portrait_custom?current.cover:null);
 return createPortal(<div className="portrait-backdrop" onPointerDown={e=>{if(e.target===e.currentTarget&&!saving)onClose();}}>
  <section className="portrait-picker" role="dialog" aria-modal="true" aria-labelledby={heading} ref={panel} onKeyDown={e=>{
   e.stopPropagation();if(e.key==='Escape'&&!saving){e.preventDefault();onClose();}
   if(e.key==='Tab'){const list=Array.from(panel.current?.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],input:not(:disabled)')||[]),first=list[0],last=list[list.length-1];if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}}
  }}>
   <header className="portrait-header"><div><span className="eyebrow">PERSON PORTRAIT</span><h2 id={heading}>Choose portrait</h2><p>{person.name?.trim()||'Unnamed person'}</p></div><button type="button" className="outline portrait-close" aria-label="Close portrait picker" disabled={saving} onClick={onClose}><X size={21}/></button></header>
   <div className="portrait-content"><aside className="portrait-preview">
    <div className="portrait-circle">{preview&&!broken.has(preview)?<img src={image(preview)} alt="Portrait preview" onError={()=>setBroken(old=>new Set([...old,preview]))}/>:<Users size={55} aria-label="No portrait preview"/>}</div>
    <strong>{person.name?.trim()||'Unnamed person'}</strong><span>{selected?'Your selected portrait':'Automatic portrait'}</span>
    <p>This portrait represents this person throughout Dahan. Face assignments and recognition stay the same.</p>
    <button className="outline" type="button" aria-pressed={selected===null} disabled={saving||loading} onClick={()=>setSelected(null)}>Use automatic</button>
   </aside><div className="portrait-options">
    <div className="portrait-options-heading"><h3>Choose from assigned faces</h3>{data&&<span>{data.total.toLocaleString()} faces</span>}</div>
    <p className="small-note">Choose a clear face, then save. Choices include photos and video frames from visible Databases.</p>
    {error&&<div className="portrait-error" role="alert"><p>{error}</p><button className="outline" disabled={saving} onClick={()=>setRefresh(v=>v+1)}>Refresh choices</button></div>}
    {loading?<p role="status">Loading portrait choices…</p>:data?.items.length?<div className="portrait-choices" aria-label="Portrait choices">{data.items.map((item,index)=>{
     const unavailable=!item.available||broken.has(item.id),isSelected=selected===item.id;
     return <button key={item.id} type="button" className={'portrait-choice'+(isSelected?' selected':'')} aria-label={`Choose portrait ${offset+index+1}: ${item.name}`} aria-pressed={isSelected} disabled={saving||unavailable} onClick={()=>setSelected(item.id)}>
      <div>{unavailable?<ImagePlus size={30} aria-hidden="true"/>:<img src={image(item.id)} loading="lazy" alt="" onError={()=>setBroken(old=>new Set([...old,item.id]))}/>}<span className="portrait-choice-check" aria-hidden="true">{isSelected&&<Check size={17}/>}</span></div>
      <small>{unavailable?'Preview unavailable':item.taken?.slice(0,10)||'Date unknown'}{item.kind==='video'?' · Video':''}</small>
     </button>;
    })}</div>:!error&&<p role="status">No assigned faces are available in visible Databases. Assign faces to this person first.</p>}
    {data&&data.total>0&&<ReviewPagination offset={offset} total={data.total} disabled={saving||loading} onChange={setOffset}/>}
   </div></div>
   <footer className="portrait-footer"><p>Saved for everyone using this library. You can change it anytime or use Undo last change.</p><div><button className="outline" disabled={saving} onClick={onClose}>Cancel</button><button className="primary" disabled={saving||loading||!changed||!!selected&&broken.has(selected)} onClick={()=>void save()}>{saving?'Saving…':'Save portrait'}</button></div></footer>
  </section>
 </div>,document.body);
}
