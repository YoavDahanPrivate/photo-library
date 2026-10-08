import PeopleNames from "./PeopleNames";
import DuplicateTools from "./DuplicateTools";
import React, {useEffect, useState} from "react";

type Settings = {frequency:string;time:string;weekday:number;month_day:number;timezone:string;auto_assign:boolean};
type Run = {id:string;started:string;finished:string|null;state:string;reason:string;error:string|null;progress:Record<string,string|number>};
type State = {settings:Settings;next_due:string|null;running:boolean;runs:Run[]};
async function request(path:string,method="GET",body?:unknown) {
  const r=await fetch("/api/sync"+path,{method,headers:{"Content-Type":"application/json"},...(body===undefined?{}:{body:JSON.stringify(body)})});
  const data=await r.json();
  if(!r.ok) throw Error(typeof data.detail==="string"?data.detail:JSON.stringify(data.detail||"Request failed"));
  return data;
}
export default function SyncSettings({onClose,hideFormatDuplicates,onHideFormatDuplicates,onPeopleChanged}:{onPeopleChanged:()=>void;onClose:()=>void;hideFormatDuplicates:boolean;onHideFormatDuplicates:(value:boolean)=>void}) {
  const [section,setSection]=useState<"sync"|"duplicates"|"trash"|"names">("sync");
  const [fileErrors,setFileErrors]=useState<{id:string;name:string;error:string}[]>([]);
  useEffect(()=>{let active=true;const refresh=()=>request("/errors").then(r=>{if(active)setFileErrors(r);}).catch(()=>{});refresh();const timer=setInterval(refresh,15000);return()=>{active=false;clearInterval(timer);};},[]);
  const [review,setReview]=useState<{faces:{id:string;name:string}[];actions:{id:number;created:string;count:number}[]}>({faces:[],actions:[]});
  useEffect(()=>{let active=true; const refresh=()=>request("/assignments").then(r=>{if(active)setReview(r);}).catch(()=>{});refresh();const timer=setInterval(refresh,15000);return()=>{active=false;clearInterval(timer);};},[]);
  const [data,setData]=useState<State|null>(null),[draft,setDraft]=useState<Settings|null>(null);
  const [error,setError]=useState(""),[message,setMessage]=useState(""),[busy,setBusy]=useState(false);
  useEffect(()=>{let active=true; const refresh=()=>request("/status").then((s:State)=>{if(active){setData(s);setDraft(d=>d||s.settings);}}).catch(e=>{if(active)setError(String(e));});
    refresh();const timer=setInterval(refresh,5000);return()=>{active=false;clearInterval(timer);};},[]);
  const changed=!!draft&&JSON.stringify(draft)!==JSON.stringify(data?.settings);
  const patch=(values:Partial<Settings>)=>setDraft(d=>d?{...d,...values}:d);
  const format=(value:string|null)=>value?new Date(value).toLocaleString(undefined,{timeZone:data?.settings.timezone}):"Not scheduled";
  const action=async(fn:()=>Promise<void>)=>{setBusy(true);setError("");setMessage("");try{await fn();}catch(e){setError(String(e));}finally{setBusy(false);}};
  return <section className="sync-settings" aria-labelledby="sync-title">
    <header><div><h1 id="sync-title">Library tools</h1><p>Keep your photo library up to date.</p></div><button onClick={onClose}>Back to library</button></header>
    <section className="library-display-settings" aria-label="Library display"><h2>Library display</h2><label className="sync-check"><input type="checkbox" checked={hideFormatDuplicates} onChange={e=>onHideFormatDuplicates(e.target.checked)}/>Hide HEIC/JPEG duplicate copies</label><p>Show one matching format copy in the library, preferring HEIC. Both files stay stored. This preference is saved automatically on this device.</p></section>
    <details className="iphone-app-help"><summary>Use Dahan without Safari’s browser bars</summary><p>On iPhone: open Dahan in Safari, tap Share, choose Add to Home Screen, enable Open as Web App if shown, and tap Add. Launch Dahan from that new icon.</p><p>The app stays in its own window. Expand shows the original photo; Collapse returns to the details view. Your iPhone may still show system status indicators.</p></details>
    <div className="sync-actions" role="group" aria-label="Library tools sections"><button aria-pressed={section==="sync"} onClick={()=>setSection("sync")}>Sync & recognition</button><button aria-pressed={section==="duplicates"} onClick={()=>setSection("duplicates")}>Duplicate cleanup</button><button aria-pressed={section==="trash"} onClick={()=>setSection("trash")}>Trash & restore</button><button aria-pressed={section==="names"} onClick={()=>setSection("names")}>People names</button></div>
    {error&&<p role="alert" className="error">{error}</p>}
    {!draft||!data?<p>Loading settings…</p>:<>
      <div hidden={section!=="sync"}>
      <form onSubmit={e=>{e.preventDefault();action(async()=>{const s=await request("/settings","PUT",draft);setData(s);setDraft(s.settings);setMessage("Settings saved.");});}}>
        <h2>Sync & recognition</h2>
        <div className="sync-fields">
          <label>Repeat<select value={draft.frequency} onChange={e=>patch({frequency:e.target.value})}>
            {["off","hourly","daily","weekly","monthly"].map(v=><option value={v} key={v}>{v.charAt(0).toUpperCase()+v.slice(1)}</option>)}
          </select></label>
          {draft.frequency!=="off"&&<label>{draft.frequency==="hourly"?"Minute past each hour":"Time of day"}
            {draft.frequency==="hourly"?<input type="number" min="0" max="59" value={Number(draft.time.slice(3))} onChange={e=>patch({time:"00:"+String(Number(e.target.value)).padStart(2,"0")})}/>:<input type="time" required value={draft.time} onChange={e=>patch({time:e.target.value})}/>}
          </label>}
          {draft.frequency==="weekly"&&<label>Day of week<select value={draft.weekday} onChange={e=>patch({weekday:Number(e.target.value)})}>
            {["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"].map((d,i)=><option key={d} value={i}>{d}</option>)}
          </select></label>}
          {draft.frequency==="monthly"&&<label>Day of month<input type="number" min="1" max="31" required value={draft.month_day} onChange={e=>patch({month_day:Number(e.target.value)})}/><small>Short months use their last day.</small></label>}
          <label>Timezone<input required value={draft.timezone} onChange={e=>patch({timezone:e.target.value})} list="sync-timezones"/><datalist id="sync-timezones"><option>Asia/Jerusalem</option><option>UTC</option><option>Europe/London</option><option>America/New_York</option></datalist></label>
        </div>
        <p>The backend must be running and the SSD connected. Missed scheduled runs are combined into one catch-up run after startup.</p>
        <h2>Face recognition</h2>
        <label className="sync-check"><input type="checkbox" checked={draft.auto_assign} onChange={e=>patch({auto_assign:e.target.checked})}/>Automatically assign high-confidence face matches</label>
        <p>Matches use saved named examples and strict similarity checks. Passes repeat until no more strong matches qualify. Automatic predictions never become trusted examples without your confirmation. Uncertain matches stay in People for review.</p>
        <div className="sync-actions"><button className="primary" type="submit" disabled={busy||!changed}>Save settings</button>{changed&&<span>Unsaved changes</span>}</div>
      </form>
      <section aria-label="Automatic face assignments"><h2>Automatic assignments</h2><p>Review up to 100 automatic face matches. Undoing a batch leaves later manual corrections intact and rejects those automatic matches from future runs.</p>
        {review.actions.map(a=><p key={a.id}>{format(a.created)} · {a.count} assignments <button disabled={busy} onClick={()=>action(async()=>{const result=await request("/assignments/"+a.id+"/undo","POST",{});setReview(await request("/assignments"));setMessage(result.restored+" assignments undone.");})}>Undo this batch</button></p>)}
        <div className="sync-faces">{review.faces.map(f=><figure key={f.id}><img src={"/api/faces/"+f.id+"/thumbnail"} alt={"Automatic match: "+f.name}/><figcaption>{f.name}</figcaption></figure>)}</div>
      </section>
      <section className="sync-status" aria-label="Sync status">
        <div className="sync-actions"><h2>Sync status</h2><button className="primary" disabled={busy||data.running} onClick={()=>action(async()=>{await request("/now","POST",{});setData(await request("/status"));setMessage("Sync started using saved settings.");})}>{data.running?"Sync running…":"Sync now"}</button></div>
        <p>Next scheduled sync: <strong>{format(data.next_due)}</strong> ({data.settings.timezone})</p>
        <p>Sync now starts a new scan using saved settings. Resume continues a saved run. Pause and Cancel finish the current file or matching pass before stopping; unfinished recognition resumes later. Scheduled sync waits while the latest run is paused or cancelled.</p>
        {message&&<p role="status">{message}</p>}
        <div aria-live="polite">{data.runs.length===0?<p>No sync runs yet.</p>:data.runs.map((r,i)=><article key={r.id} className="sync-run">
          <strong>{i===0?"Latest run":"Previous run"} · {r.state.replaceAll("_"," ")}</strong><p>{format(r.started)} · {r.reason}</p>
          <p>{r.progress.phase||r.state}{typeof r.progress.total==="number"&&" · "+(r.progress.processed||0)+" / "+r.progress.total+" files processed"}</p>
          {r.state==="running"&&typeof r.progress.total==="number"&&<progress max={Math.max(1,r.progress.total)} value={Number(r.progress.processed||0)} aria-label="Sync progress"/>}
          <p>{["added","changed","moved","missing","restored","deferred","assigned","passes","errors"].filter(k=>r.progress[k]!==undefined).map(k=>k+": "+r.progress[k]).join(" · ")}</p>
          <div className="sync-actions">
            {r.state==="running"&&["pause","cancel"].map(a=><button key={a} disabled={busy} onClick={()=>action(async()=>{await request("/runs/"+r.id+"/"+a,"POST",{});setData(await request("/status"));setMessage(a==="pause"?"Pause requested; saving a safe checkpoint.":"Cancel requested; progress will be kept for Resume.");})}>{a==="pause"?"Pause":"Cancel"}</button>)}
            {["paused","cancelled","interrupted","failed"].includes(r.state)&&<button disabled={busy||data.running} onClick={()=>action(async()=>{await request("/runs/"+r.id+"/resume","POST",{});setData(await request("/status"));setMessage("Resuming saved progress.");})}>Resume</button>}
          </div>
          {r.error&&<p role="alert">{r.error}</p>}
          {r.progress.errors? <p>Processing errors are retained on media records and retried on the next sync.</p>:null}
        </article>)}</div>
        {!!fileErrors.length&&<details><summary>Files needing attention (up to 50)</summary>{fileErrors.map(f=><p key={f.id}><strong>{f.name}</strong><br/>{f.error}</p>)}</details>}
      </section>
      </div>
      {section==="names"&&<PeopleNames onChanged={onPeopleChanged}/>}
      <div hidden={section==="sync"||section==="names"}><DuplicateTools syncRunning={data.running} view={section==="trash"?"trash":"duplicates"} onViewChange={setSection}/></div>
    </>}
  </section>;
}
