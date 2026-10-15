import React,{useEffect,useRef,useState} from 'react';
import {Layers,ArrowLeft,ArrowRight,Check,X} from 'lucide-react';
import {readApiResponse} from './ApiResponse';
export type ReviewSuggestion={face_id:string;person_id:number;name:string;score:number;source_person_id:number|null;confidence:'high'|'lower';media_id?:string;taken?:string|null};
type Group={id:string;person_id:number;name:string;count:number;minimum_similarity:number;representatives:string[];matches:ReviewSuggestion[];first_date:string|null;last_date:string|null};
type Result={groups:Group[];total_groups:number;grouped_faces:number;individual_faces:number;total_faces:number;analyzed_faces:number;offset:number;limit:number};
const image=(id:string)=>'/api/faces/'+encodeURIComponent(id)+'/thumbnail';
export default function ReviewGroups({collapsed,revision,person,working,approve}:{collapsed?:boolean;revision:number;person:string;working:boolean;approve:(matches:ReviewSuggestion[])=>Promise<boolean>}){
 const [cohesion,setCohesion]=useState('tight');
 const [open,setOpen]=useState(false),[result,setResult]=useState<Result|null>(null),[offset,setOffset]=useState(0),[loading,setLoading]=useState(false),[error,setError]=useState('');
 const [group,setGroup]=useState<Group|null>(null),[selected,setSelected]=useState<string[]>([]),[page,setPage]=useState(0),[saving,setSaving]=useState(false),[changed,setChanged]=useState(false);
 const dialog=useRef<HTMLDialogElement>(null),opener=useRef<HTMLElement|null>(null);
 useEffect(()=>{setOffset(0);},[person,revision,cohesion]);
 useEffect(()=>{
  if(!open)return;
  const abort=new AbortController();setLoading(true);setError('');
  fetch('/api/people/review-groups?offset='+offset+'&limit=4&cohesion='+cohesion+(person?'&person_id='+encodeURIComponent(person):''),{signal:abort.signal}).then(readApiResponse<Result>).then(value=>{if(!abort.signal.aborted){setResult(value);setLoading(false);}}).catch(error=>{if(!abort.signal.aborted){setError(String(error));setLoading(false);}});
  return()=>abort.abort();
 },[open,offset,person,revision,cohesion]);
 useEffect(()=>{if(group){setChanged(true);}},[revision]);
 useEffect(()=>{
  if(group){dialog.current?.showModal();}
  else{dialog.current?.close();opener.current?.focus({preventScroll:true});}
 },[group]);
 const close=()=>{if(!saving)setGroup(null);};
 const inspect=(value:Group)=>{opener.current=document.activeElement as HTMLElement;setSelected(value.matches.map(row=>row.face_id));setPage(0);setChanged(false);setError('');setGroup(value);};
 const pages=Math.ceil((group?.matches.length||0)/16);
 return <section className={"grouped-review"+(collapsed?" grouped-review-hidden":"")} aria-label="Grouped face review">
  <div className="grouped-review-heading"><div><h3><Layers size={19}/>Review similar faces together</h3><p>Inspect a cohesive set, leave out any wrong faces, and approve the selection as one reversible batch.</p></div><button className="outline" aria-expanded={open} onClick={()=>setOpen(value=>!value)}>{open?'Hide grouped review':'Try grouped review'}</button></div>
  {open&&<div className="grouped-review-body">
   <label className="review-group-density">Grouping<select aria-label="Grouping breadth" value={cohesion} disabled={loading} onChange={event=>setCohesion(event.target.value)}><option value="tight">Tighter similarity</option><option value="broader">Broader similarity · inspect carefully</option></select></label>
   {loading?<p role="status">Preparing similar-face groups…</p>:error?<p role="alert">{error} <button className="outline" onClick={()=>{setOpen(false);setTimeout(()=>setOpen(true),0);}}>Retry</button></p>:result&&<>
    <div className="grouped-review-summary"><strong>{result.grouped_faces.toLocaleString()} faces in {result.total_groups.toLocaleString()} review groups</strong><span>{result.individual_faces.toLocaleString()} faces remain for individual review</span></div>
    <p className="small-note">Grouping helps you review; it does not change recognition confidence or approve faces. {result.analyzed_faces<result.total_faces?`This pass analyzed ${result.analyzed_faces.toLocaleString()} of ${result.total_faces.toLocaleString()} faces; the rest remain available individually.`:''}</p>
    <div className="review-group-list">{result.groups.map(item=><article key={item.id} className="review-group-card"><div className="review-group-title"><strong>{item.name}</strong><span>{item.count} similar faces</span></div><div className="review-group-examples">{item.representatives.map((identity,index)=><figure key={identity}><img loading="lazy" src={image(identity)} alt={'Group example '+(index+1)}/><figcaption>{index===0?'Typical example':'Example '+(index+1)}</figcaption></figure>)}</div><p>{item.first_date||'Date unknown'}{item.last_date&&item.first_date!==item.last_date?' — '+item.last_date:''}</p><button className="outline" disabled={working} onClick={()=>inspect(item)}>Review all {item.count} faces</button></article>)}</div>
    {!result.total_groups&&<p>No cohesive groups are available in this filter. Individual review remains available below.</p>}
    {!!result.total_groups&&<nav className="review-group-pages" aria-label="Review group pages"><span>Groups {offset+1}–{Math.min(offset+4,result.total_groups)} of {result.total_groups}</span><button className="outline" aria-label="Previous group page" disabled={!offset} onClick={()=>setOffset(value=>Math.max(0,value-4))}><ArrowLeft size={16}/></button><button className="outline" aria-label="Next group page" disabled={offset+4>=result.total_groups} onClick={()=>setOffset(value=>value+4)}><ArrowRight size={16}/></button></nav>}
   </>}
  </div>}
  <dialog ref={dialog} className="review-group-dialog" aria-labelledby="review-group-title" onCancel={event=>{event.preventDefault();close();}} onClose={()=>{if(!saving)setGroup(null);}}>
   {group&&<><header><div><span className="eyebrow">REVIEW A SIMILAR-FACE GROUP</span><h2 id="review-group-title">Assign this set to {group.name}?</h2><p>{group.count} faces · Check the set and deselect any exceptions.</p></div><button className="outline" aria-label="Close group review" disabled={saving} onClick={close}><X size={18}/></button></header>
    {changed&&<p role="alert" className="review-group-warning">The library changed while this group was open. Close it and reopen a fresh group before approving.</p>}
    <div className="review-group-selection"><strong>{selected.length} of {group.count} selected across all pages</strong><button className="outline" disabled={saving} onClick={()=>setSelected(selected.length?[]:group.matches.map(row=>row.face_id))}>{selected.length?'Clear selection':'Select entire group'}</button></div>
    <div className="review-group-face-grid">{group.matches.slice(page*16,(page+1)*16).map(row=><label key={row.face_id} className={selected.includes(row.face_id)?'selected':''}><img src={image(row.face_id)} alt={'Face proposed as '+group.name}/><span><input type="checkbox" aria-label={'Include face '+row.face_id} checked={selected.includes(row.face_id)} disabled={saving} onChange={event=>setSelected(previous=>event.target.checked?[...previous,row.face_id]:previous.filter(identity=>identity!==row.face_id))}/>{row.taken?.slice(0,10)||'Date unknown'}</span></label>)}</div>
    {pages>1&&<nav className="review-group-pages" aria-label="Faces in group"><span>Faces {page*16+1}–{Math.min((page+1)*16,group.count)} of {group.count} · Page {page+1} of {pages}</span><button className="outline" aria-label="Previous faces page" disabled={!page||saving} onClick={()=>setPage(value=>value-1)}><ArrowLeft size={16}/></button><button className="outline" aria-label="Next faces page" disabled={page+1>=pages||saving} onClick={()=>setPage(value=>value+1)}><ArrowRight size={16}/></button></nav>}
    {error&&<p role="alert">{error}</p>}
    <footer><button className="outline" disabled={saving} onClick={close}>Back to groups</button><button className="primary" disabled={working||saving||changed||!selected.length} onClick={async()=>{setSaving(true);setError('');try{if(await approve(group.matches.filter(row=>selected.includes(row.face_id))))setGroup(null);else{setChanged(true);setError('Assignments could not be confirmed. Reopen a fresh group before retrying.');}}finally{setSaving(false);}}}><Check size={17}/>{saving?'Saving selected faces…':`Approve selected ${selected.length}`}</button></footer>
   </>}
  </dialog>
 </section>;
}
