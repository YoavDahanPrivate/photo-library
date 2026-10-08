import ReviewPagination from "./ReviewPagination";
import TrashPanel from "./TrashPanel";
import React,{useEffect,useState} from "react";
type Member={id:string;name:string;path:string;phone:string;taken:string;bytes:number;available:boolean;extension?:string;width?:number;height?:number};
type Group={id:string;keeper:string;members:Member[];taken:string;mode?:string};
type Job={id:string;kind:string;state:string;error:string|null;progress:{mode?:string;keep_format?:string;extra_copies?:number;checked?:number;processed?:number;total?:number;groups?:number;completed?:number;error_count?:number;errors?:{id?:string;name?:string;error:string}[]}};
async function request(path:string,body?:unknown){
 const r=await fetch("/api/duplicates"+path,body===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
 const data=await r.json();if(!r.ok)throw Error(typeof data.detail==="string"?data.detail:JSON.stringify(data.detail));return data;
}
export default function DuplicateTools({syncRunning,view,onViewChange}:{syncRunning:boolean;view:"duplicates"|"trash";onViewChange:(view:"duplicates"|"trash")=>void}){
 const [jobs,setJobs]=useState<Job[]>([]);
 const [reviews,setReviews]=useState<Job[]>([]),[mode,setMode]=useState("exact"),[keepFormat,setKeepFormat]=useState("heic");
 const [groups,setGroups]=useState<Group[]>([]),[total,setTotal]=useState(0),[offset,setOffset]=useState(0);
 const [selected,setSelected]=useState<string[]>([]),[busy,setBusy]=useState(false),[error,setError]=useState(""),[message,setMessage]=useState("");
 const [trashCount,setTrashCount]=useState(0);
 const [groupsLoading,setGroupsLoading]=useState(false);
 const [allIds,setAllIds]=useState<string[]>([]),[extraTotal,setExtraTotal]=useState(0),[selectionLoading,setSelectionLoading]=useState(false);
 const detection=reviews.find(j=>(j.progress.mode||"exact")===mode);
 const running=jobs.some(j=>j.state==="running");
 const signature=jobs.map(j=>j.id+":"+j.state).join("|");
 useEffect(()=>{let active=true;const refresh=async()=>{try{const s=await request("/status");if(active){setJobs(s.jobs);setReviews(s.reviews||s.jobs.filter((j:Job)=>j.kind==="detect"&&["completed","completed_with_issues"].includes(j.state)));setTrashCount(s.trash_count);}}catch(e){if(active)setError(String(e));}};void refresh();const timer=setInterval(refresh,3000);return()=>{active=false;clearInterval(timer);};},[]);
 useEffect(()=>{setOffset(0);setSelected([]);setGroups([]);setTotal(0);setAllIds([]);setExtraTotal(0);},[detection?.id]);
 useEffect(()=>{if(!detection){setGroups([]);setTotal(0);setSelected([]);return;}let active=true;setGroupsLoading(true);request("/groups?job_id="+detection.id+"&offset="+offset).then(r=>{if(active){setGroups(r.groups);setTotal(r.total);}}).catch(e=>{if(active)setError(String(e));}).finally(()=>{if(active)setGroupsLoading(false);});return()=>{active=false;};},[detection?.id,offset,signature]);
 useEffect(()=>{if(!detection){setAllIds([]);return;}let active=true;setSelectionLoading(true);request("/selection?job_id="+detection.id).then(r=>{if(active){setAllIds(r.media_ids);setExtraTotal(r.extra_total);const available=new Set<string>(r.media_ids);setSelected(old=>old.filter(id=>available.has(id)));}}).catch(e=>{if(active)setError(String(e));}).finally(()=>{if(active)setSelectionLoading(false);});return()=>{active=false;};},[detection?.id,signature]);
 const act=async(path:string,body:unknown,notice:string)=>{setBusy(true);setError("");try{await request(path,body);setMessage(notice);setSelected([]);setJobs((await request("/status")).jobs);}catch(e){setError(String(e));}finally{setBusy(false);}};
 const blocked=busy||running||syncRunning;
 return <section className="duplicate-tools" aria-labelledby="duplicate-title">
  <div hidden={view!=="duplicates"}><h2 id="duplicate-title">Remove duplicates</h2>
  <label className="duplicate-mode">Find<select aria-label="Duplicate matching mode" disabled={busy||running} value={mode} onChange={e=>{setMode(e.target.value);setSelected([]);setGroups([]);setTotal(0);setAllIds([]);setExtraTotal(0);setGroupsLoading(true);}}><option value="exact">Exact file duplicates</option><option value="heic_jpeg">Likely HEIC / JPEG copies</option></select></label>
  {mode==="exact"?<p>Matches require identical file contents and matching recorded dates. HEIC/JPEG conversions have different file contents and are excluded. Files without a recorded date are skipped.</p>:<><p>Find HEIC and JPEG versions with the same phone, filename stem, capture time, width and height. These are likely copies based on metadata; their image contents are not compared. Review possible edits before removing a version.</p><label className="duplicate-mode">Format to keep<select aria-label="Format to keep" disabled={busy||running} value={keepFormat} onChange={e=>setKeepFormat(e.target.value)}><option value="heic">HEIC</option><option value="jpeg">JPEG</option></select></label><p>Applies to the next check. Each result shows the copy kept. People tags and corrections stay with their own copy and can be recovered with Restore.</p></>}
  <p>Selected uploaded files move to recoverable trash inside their phone folder. One copy remains in the library. Use Trash & restore to recover removed copies; storage space is not freed by moving to trash.</p>
  <button disabled={blocked} onClick={()=>act("/detect",{mode,keep_format:keepFormat},"Duplicate check started. Progress is shown below; you can keep browsing your library.")}>Find duplicates</button>
  <button onClick={()=>onViewChange("trash")}>Trash & restore ({trashCount.toLocaleString()})</button></div>
  {syncRunning&&<p>Pause sync before starting cleanup. Your library stays available.</p>}
  {error&&<p role="alert" className="error">{error}</p>}
  {message&&<p role="status">{message}</p>}
  {jobs.slice(0,3).map(j=><article className="sync-run" key={j.id}>
    <strong>{j.kind==="detect"?(j.progress.mode==="heic_jpeg"?"HEIC / JPEG check":"Exact-file check"):j.kind==="remove"?"Move to trash":"Restore"} · {j.state.replaceAll("_"," ")}</strong>
    <p>{j.progress.total!==undefined?((j.progress.checked??j.progress.processed??0)+" / "+j.progress.total+" files"):""}{j.progress.groups!==undefined?" · "+j.progress.groups+" duplicate groups":""}{j.progress.completed!==undefined?" · "+j.progress.completed+" completed":""}</p>
    {j.state==="running"&&j.progress.total!==undefined&&<progress aria-label="Duplicate operation progress" max={Math.max(1,j.progress.total)} value={j.progress.checked??j.progress.processed??0}/>}
    {j.error&&<p role="alert">{j.error}</p>}
    {!!j.progress.error_count&&<details><summary>{j.progress.error_count} files need attention</summary>{j.progress.errors?.map((e,i)=><p key={i}>{e.name||e.id}: {e.error}</p>)}</details>}
  </article>)}
  <div hidden={view!=="duplicates"}>{detection&&(groupsLoading||selectionLoading?<p role="status">Loading review…</p>:<div>
    <p><strong>{detection.progress.mode==="heic_jpeg"?"Metadata review · keeping "+(detection.progress.keep_format||"heic").toUpperCase():"Exact-file review"}</strong></p>
    <h3>Review proposed removals · {total.toLocaleString()} groups · {extraTotal.toLocaleString()} extra copies</h3>
    <p>Inspect each extra copy and select the ones to remove. Every group keeps the marked copy. Files are checked again before moving. Select all covers every result page; your individual deselections remain when you change pages.</p>
    <div className="sync-actions">
      <button disabled={blocked||selectionLoading||!allIds.length} onClick={()=>setSelected(allIds)}>Select all extra copies ({allIds.length.toLocaleString()})</button>
      <button disabled={blocked||selectionLoading} onClick={()=>setSelected(old=>[...new Set([...old,...groups.flatMap(g=>g.members.filter(m=>m.id!==g.keeper&&m.available&&allIds.includes(m.id)).map(m=>m.id))])])}>Select this page</button>
      <button disabled={blocked||!selected.length} onClick={()=>setSelected([])}>Deselect all</button>
      <button className="primary" disabled={blocked||!selected.length} onClick={()=>act("/remove",{job_id:detection.id,media_ids:selected},"Moving reviewed copies to recoverable trash. You can keep browsing.")}>Remove {selected.length} selected {selected.length===1?"copy":"copies"}</button>
    </div>
    <p role="status">{selected.length.toLocaleString()} of {allIds.length.toLocaleString()} available extra copies selected across all pages. One copy per group is kept.</p>
    <ReviewPagination offset={offset} total={total} onChange={setOffset} disabled={blocked||groupsLoading}/>
    {groups.map(g=><article className="duplicate-group" key={g.id}>
      <h4>{g.members.length} {g.mode==="heic_jpeg"?"likely format copies":"exact copies"} · {g.taken}</h4><p className="small-note">{g.mode==="heic_jpeg"?"Reason: same phone, filename stem, capture time and dimensions; both HEIC and JPEG present. Metadata match, not verified identical images.":"Reason: identical file contents and matching recorded date."}</p>
      <div className="duplicate-copies">{g.members.map(m=><label key={m.id} className={"duplicate-copy"+(m.id===g.keeper?" keep-copy":"")}>
        <img src={"/api/media/"+m.id+"/thumbnail?size=small"} alt={m.name} loading="lazy"/>
        <span>{m.id===g.keeper?<strong>Keep this copy{m.extension?" · "+m.extension.slice(1).toUpperCase():""}</strong>:<span><input type="checkbox" aria-label={"Remove "+m.path} checked={selected.includes(m.id)} disabled={blocked||!m.available} onChange={e=>setSelected(old=>e.target.checked?[...old,m.id]:old.filter(id=>id!==m.id))}/> {m.available?"Remove this copy":"No longer in library"}</span>}<br/>{m.name}<br/><small>{m.path}<br/>{m.bytes.toLocaleString()} bytes{m.width&&m.height?" · "+m.width+" × "+m.height:""}</small></span>
      </label>)}</div>
    </article>)}
    {!total&&<p>No matching groups were found in this check.</p>}

  </div>)}
  {!detection&&!running&&<p>Run Find duplicates to create a review for this matching mode.</p>}
  </div>{view==="trash"&&<TrashPanel blocked={blocked} signature={signature} onRestore={ids=>act("/restore",{media_ids:ids},"Restoring selected copies. You can keep browsing the library.")}/>}
 </section>;
}
