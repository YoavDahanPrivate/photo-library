import {useEffect,useRef,useState} from 'react';
export type MetadataInfo={embedded_date_field?:string|null;date_source?:string;date_precision?:string;date_end?:string|null;date_approximate?:boolean;location_source?:string;location_precision?:string;location_label?:string|null;embedded_taken?:string|null;embedded_latitude?:number|null;embedded_longitude?:number|null;file_created?:number|null;file_modified?:number|null;imported_at?:string|null};
export function captureLabel(m:{taken:string|null}&MetadataInfo){
  if(!m.taken)return 'Unknown — no capture date found';
  const value=m.taken.length<=10?m.taken:new Date(m.taken).toLocaleString();
  return `${m.date_approximate?'Approximately ':''}${value}${m.date_end?' to '+m.date_end:''}${m.date_source==='manual'?' · entered by user':''}`;
}
async function request(path:string,body?:unknown){
  const r=await fetch('/api'+path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data=await r.json();if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:'Check the date/location fields and retry.');return data;
}
type Preview={token:string;matched:number;changed:number;skipped:number;samples:{id:string;name:string;source:string;album:string;taken:string|null;before:MetadataInfo;after:any;after_taken:string|null;after_location:string}[]};
export function MetadataEditor({query='',ids=[],count,onSaved,onClose}:{query?:string;ids?:string[];count:number;onSaved:()=>void;onClose?:()=>void}){
  const [dateValue,setDate]=useState(''),[dateEnd,setDateEnd]=useState(''),[approx,setApprox]=useState(false);
  const [location,setLocation]=useState(''),[point,setPoint]=useState(false),[lat,setLat]=useState(''),[lon,setLon]=useState('');
  const [placeId,setPlaceId]=useState(''),[places,setPlaces]=useState<{id:string;label:string;country:string}[]>([]);
  const [mode,setMode]=useState('fill_missing'),[preview,setPreview]=useState<Preview|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
  const generation=useRef(0);
  useEffect(()=>{generation.current++;setPreview(null);setError('');setBusy(false);},[query,ids.join('|')]);
  useEffect(()=>{const c=new AbortController();fetch('/api/place-options',{signal:c.signal}).then(r=>{if(!r.ok)throw Error('Could not load saved place names');return r.json();}).then(d=>setPlaces(d.options)).catch(e=>{if(e.name!=='AbortError')setError(e.message);});return()=>c.abort();},[]);
  const invalidate=()=>{generation.current++;setPreview(null);setError('');setNotice('');};
  async function makePreview(restore?:string){
    const version=++generation.current;setBusy(true);setError('');setNotice('');setPreview(null);
    try{
      const body:any={media_ids:ids,mode};
      if(restore)body.restore=restore;
      else{
        if(dateValue.trim())body.date={value:dateValue.trim(),...(dateEnd.trim()?{end:dateEnd.trim()}:{}),approximate:approx};
        if(location.trim()||point)body.location={label:location.trim(),...(placeId?{place_id:placeId}:{}),...(point?{latitude:lat.trim()?Number(lat):null,longitude:lon.trim()?Number(lon):null}:{})};
      }
      if(!restore&&!body.date&&!body.location)throw Error('Enter a date or location first.');
      if(point&&!restore&&(!lat.trim()||!lon.trim()||!Number.isFinite(Number(lat))||!Number.isFinite(Number(lon))))throw Error('Enter both latitude and longitude for a point.');
      const result=await request('/metadata/preview?'+query,body);
      if(version===generation.current)setPreview(result);
    }catch(e){if(version===generation.current)setError(e instanceof Error?e.message:String(e));}
    finally{if(version===generation.current)setBusy(false);}
  }
  async function confirm(){
    if(!preview)return;const version=generation.current;setBusy(true);setError('');
    try{const result=await request('/metadata/confirm',{token:preview.token,confirm:true});if(version===generation.current){setPreview(null);setNotice(`${result.changed} media updated. Original files preserved.`);onSaved();}}
    catch(e){if(version===generation.current)setError(e instanceof Error?e.message:String(e));}
    finally{if(version===generation.current)setBusy(false);}
  }
  const matches=location.trim()?places.filter(p=>(p.label+' '+p.country).toLocaleLowerCase().includes(location.toLocaleLowerCase())).slice(0,8):[];
  return <section className="metadata-editor" aria-label="Edit dates and locations">
    <div className="metadata-heading"><h3>Edit dates &amp; locations</h3>{onClose&&<button disabled={busy} onClick={onClose}>Close editor</button>}</div>
    <p>{ids.length?`${ids.length} selected media`:`All ${count.toLocaleString()} matching media in the current view`}. Preview the affected files before saving. Blank fields stay as they are.</p>
    <fieldset disabled={busy}><legend>Capture date</legend><div className="metadata-fields"><label>Date or start of range<input aria-label="Capture date or year" placeholder="1978, 1978-06 or 1978-06-15" value={dateValue} maxLength={10} onChange={e=>{invalidate();setDate(e.target.value);}}/></label><label>End of range · optional<input aria-label="Capture date range end" placeholder="1980 or 1978-08" value={dateEnd} maxLength={10} onChange={e=>{invalidate();setDateEnd(e.target.value);}}/></label></div><label className="metadata-check"><input type="checkbox" checked={approx} onChange={e=>{invalidate();setApprox(e.target.checked);}}/>Approximate / estimated date</label><small>Year and month values keep their precision. File timestamps never become capture dates automatically.</small></fieldset>
    <fieldset disabled={busy}><legend>Location</legend><label>Place name<input aria-label="Location place name" placeholder="Paris, France — or a family place name" value={location} onChange={e=>{invalidate();setLocation(e.target.value);setPlaceId('');}}/></label>{!!matches.length&&!placeId&&<div className="metadata-place-options" aria-label="Saved place suggestions">{matches.map(p=><button key={p.id} onClick={()=>{invalidate();setLocation(p.label);setPlaceId(p.id);}}>{p.label}{p.country?' · '+p.country:''}</button>)}</div>}<label className="metadata-check"><input type="checkbox" checked={point} onChange={e=>{invalidate();setPoint(e.target.checked);}}/>I know the coordinates of this point</label>{point&&<div className="metadata-fields"><label>Latitude<input aria-label="Location latitude" type="number" step="any" min="-90" max="90" value={lat} onChange={e=>{invalidate();setLat(e.target.value);}}/></label><label>Longitude<input aria-label="Location longitude" type="number" step="any" min="-180" max="180" value={lon} onChange={e=>{invalidate();setLon(e.target.value);}}/></label></div>}<small>A place name is searchable without a map pin. Coordinates add a pin labelled as a manual location.</small></fieldset>
    <label>How to apply<select aria-label="Metadata overwrite mode" value={mode} disabled={busy} onChange={e=>{invalidate();setMode(e.target.value);}}><option value="fill_missing">Fill missing values only · preserve existing metadata</option><option value="replace">Correct existing values · replace after confirmation</option></select></label>
    <div className="metadata-actions"><button className="primary" disabled={busy||!count} onClick={()=>void makePreview()}>Preview metadata changes</button><details><summary>Restore embedded values</summary><p>Remove manual overrides for this selection. An absent embedded value becomes unknown.</p>{['date','location','both'].map(v=><button key={v} disabled={busy||!count} onClick={()=>void makePreview(v)}>Preview restoring {v==='both'?'date & location':v}</button>)}</details></div>
    {error&&<p role="alert" className="error">{error}</p>}{notice&&<p role="status">{notice}</p>}
    {preview&&<section className="metadata-preview" aria-label="Metadata change preview"><h4>{preview.changed.toLocaleString()} media will change · {preview.skipped.toLocaleString()} preserved</h4>{mode==='replace'&&<p>Existing capture dates or locations may be replaced by the values below. Embedded values remain available to restore.</p>}<div className="metadata-preview-scroll"><table><thead><tr><th>File / Album</th><th>Current</th><th>After saving</th></tr></thead><tbody>{preview.samples.map(s=><tr key={s.id}><td>{s.name}<small>{s.source} · {s.album}</small></td><td>{captureLabel({taken:s.taken,...s.before})}<small>{s.before.location_label||s.before.location_source==='embedded'?'Location: '+(s.before.location_label||'embedded GPS'):'Location unknown'}</small></td><td>{s.after.date?`${s.after.date.approximate?'Approximately ':''}${s.after.date.value}${s.after.date.end?' to '+s.after.date.end:''}`:s.after_taken||'Unknown capture date'}<small>{s.after.location?`${s.after.location.label||'Manual point'}${s.after.location.latitude===undefined?' · place only':` · ${s.after.location.latitude}, ${s.after.location.longitude}`}`:s.after_location}</small></td></tr>)}</tbody></table></div><button className="primary" disabled={busy||!preview.changed} onClick={()=>void confirm()}>Confirm changes to {preview.changed.toLocaleString()} media</button><button disabled={busy} onClick={()=>setPreview(null)}>Cancel preview</button></section>}
  </section>;
}
export default function MetadataTools({query,selected,selecting,onSelecting,onSelectLoaded,onClear,count,onSaved,revision}:{query:string;selected:string[];selecting:boolean;onSelecting:(v:boolean)=>void;onSelectLoaded:()=>void;onClear:()=>void;count:number;onSaved:()=>void;revision:number}){
  const [editing,setEditing]=useState(false),[target,setTarget]=useState('matching'),[history,setHistory]=useState<{id:number;description:string;created:string}[]>([]),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const refresh=()=>request('/metadata/history').then(setHistory).catch(e=>setError(e.message));
  useEffect(()=>{void refresh();},[revision]);
  return <div className="metadata-tools"><div className="metadata-actions"><button aria-pressed={selecting} onClick={()=>onSelecting(!selecting)}>{selecting?'Finish selecting':'Select photos & videos'}</button>{selecting&&<><span>{selected.length} selected</span><button onClick={onSelectLoaded}>Select loaded results</button><button onClick={onClear}>Clear selection</button></>}<button className="primary" onClick={()=>{setTarget(selected.length?'selected':'matching');setEditing(!editing);}}>{editing?'Close date/location editor':'Edit dates & locations'}</button>{history.length>0&&<button disabled={busy} onClick={async()=>{setBusy(true);setError('');try{await request('/metadata/undo/'+history[0].id,{});onSaved();void refresh();}catch(e){setError(e instanceof Error?e.message:String(e));}finally{setBusy(false);}}}>Undo last date/location edit</button>}</div>{error&&<p role="alert" className="error">{error}</p>}{editing&&<><label>Edit target<select aria-label="Metadata edit target" value={target} onChange={e=>setTarget(e.target.value)}><option value="matching">All {count.toLocaleString()} matching results</option><option value="selected" disabled={!selected.length}>{selected.length} selected photos &amp; videos</option></select></label><MetadataEditor key={target} query={query} ids={target==='selected'?selected:[]} count={target==='selected'?selected.length:count} onSaved={()=>{onSaved();void refresh();}} onClose={()=>setEditing(false)}/></>}</div>;
}
