import React,{useEffect,useState} from 'react';
import {ArrowLeft,ArrowRight,Search,Users} from 'lucide-react';
type Person={id:number;name:string|null;count:number;cover:string};
type Match={person_id:number;name:string;confidence:'high'|'lower'};
export default function PersonReview({people,matches,person,working,choose}:{people:Person[];matches:Match[];person:string;working:boolean;choose:(id:string)=>void}){
 const [query,setQuery]=useState(''),[pendingOnly,setPendingOnly]=useState(true),[page,setPage]=useState(0);
 const counts=new Map<number,{high:number;lower:number}>();
 for(const match of matches){const count=counts.get(match.person_id)||{high:0,lower:0};count[match.confidence]++;counts.set(match.person_id,count);}
 const known=new Map(people.filter(row=>row.id>0&&row.name?.trim()).map(row=>[row.id,row]));
 for(const match of matches)if(!known.has(match.person_id))known.set(match.person_id,{id:match.person_id,name:match.name,count:0,cover:''});
 const ranked=Array.from(known.values()).sort((a,b)=>b.count-a.count||(a.name||'').localeCompare(b.name||'')||a.id-b.id);
 const pending=(id:number)=>{const count=counts.get(id);return (count?.high||0)+(count?.lower||0);};
 const current=known.get(Number(person)),currentCount=counts.get(Number(person))||{high:0,lower:0};
 const next=ranked.find(row=>String(row.id)!==person&&pending(row.id)>0);
 const filtered=ranked.filter(row=>(!pendingOnly||pending(row.id)>0)&&(row.name||'').toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
 const size=24,last=Math.max(0,Math.ceil(filtered.length/size)-1),safePage=Math.min(page,last);
 useEffect(()=>setPage(0),[query,pendingOnly]);
 return <section className="person-review" aria-label="Review by person">
  {person?<div className="person-review-current">
   <div className="person-review-identity">{current?.cover?<img src={'/api/faces/'+encodeURIComponent(current.cover)+'/thumbnail'} alt=""/>:<Users size={30} aria-hidden="true"/>}<div><p className="person-review-eyebrow">Reviewing suggestions for</p><h3>{current?.name||matches.find(row=>String(row.person_id)===person)?.name||'Selected person'}</h3><p>{(current?.count||0).toLocaleString()} confirmed faces · {pending(Number(person)).toLocaleString()} pending suggestions</p></div></div>
   <div className="person-review-actions"><button className="outline" disabled={working} onClick={()=>choose('')}><ArrowLeft size={16}/>Choose another person</button><button className="outline" disabled={working||!next} onClick={()=>next&&choose(String(next.id))}>Next person{next?' · '+next.name:''}<ArrowRight size={16}/></button></div>
   {!pending(Number(person))?<p className="person-review-complete" role="status">You’ve reviewed all current suggestions for this person. New matches may appear after reevaluation.</p>:<p className="small-note">{currentCount.high.toLocaleString()} high-confidence · {currentCount.lower.toLocaleString()} lower-confidence. Review either list below; every approval applies only to this person.</p>}
  </div>:<>
   <div className="person-review-heading"><div><h3>Start with someone familiar</h3><p>Most confirmed faces first, across all visible databases. Choose a person to focus on their suggested matches.</p></div><span className="person-review-total">{ranked.filter(row=>pending(row.id)>0).length.toLocaleString()} people with suggestions</span></div>
   <div className="person-review-filters"><label className="person-review-search"><Search size={18} aria-hidden="true"/><input aria-label="Find a person to review" type="search" placeholder="Find a person…" value={query} onChange={event=>setQuery(event.target.value)}/></label><label><input type="checkbox" checked={pendingOnly} onChange={event=>setPendingOnly(event.target.checked)}/>Only people with suggestions</label></div>
   <div className="person-review-list" aria-label="People ranked by confirmed faces">{filtered.slice(safePage*size,(safePage+1)*size).map(row=>{const count=counts.get(row.id);return <button key={row.id} className="person-review-card" disabled={working} onClick={()=>choose(String(row.id))} aria-label={'Review suggestions for '+row.name}>
    {row.cover?<img src={'/api/faces/'+encodeURIComponent(row.cover)+'/thumbnail'} loading="lazy" alt=""/>:<Users size={28} aria-hidden="true"/>}<span className="person-review-card-info"><strong>{row.name}</strong><small>{row.count.toLocaleString()} confirmed faces</small><span>{pending(row.id).toLocaleString()} {pending(row.id)===1?'suggestion':'suggestions'} <small>· {count?.lower||0} lower-confidence</small></span></span><ArrowRight size={18} aria-hidden="true"/>
   </button>;})}</div>
   {!filtered.length&&<p role="status">{query?'No people match this search.':pendingOnly?'No people currently have suggestions to review. Turn off the filter to see everyone.':'Named people will appear here after you identify faces.'}</p>}
   {!!filtered.length&&<div className="person-review-pager"><span>People {safePage*size+1}–{Math.min((safePage+1)*size,filtered.length)} of {filtered.length.toLocaleString()}</span><button className="outline" disabled={safePage===0} onClick={()=>setPage(0)} aria-label="First people page">«</button><button className="outline" disabled={safePage===0} onClick={()=>setPage(safePage-1)} aria-label="Previous people page">‹</button><span>Page {safePage+1} of {last+1}</span><button className="outline" disabled={safePage===last} onClick={()=>setPage(safePage+1)} aria-label="Next people page">›</button><button className="outline" disabled={safePage===last} onClick={()=>setPage(last)} aria-label="Last people page">»</button></div>}
  </>}
 </section>;
}
