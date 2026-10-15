import React,{useEffect,useRef,useState} from "react";
import type {Preview} from "./DatabaseSettings";
import AlbumLocation from "./AlbumLocation";
export type PreviewFolder={relative:string;direct_media:number|null;children:number|null;readable:boolean|null;source:string;album:string;role:string;source_key?:string;album_key?:string};
async function request(path:string,body?:unknown){
 const r=await fetch('/api/databases/folder-discovery'+path,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)})});
 const p=await r.json();if(!r.ok)throw Error(typeof p.detail==='string'?p.detail:'Folder discovery could not start');return p;
}
export default function FolderDiscovery({preview,onComplete}:{preview:Preview;onComplete:(value:Preview)=>void}){
 const [state,setState]=useState('idle'),[error,setError]=useState(''),[progress,setProgress]=useState({directories:0,entries:0,media_names:0,current:''}),[page,setPage]=useState(0);
 const begin=useRef<()=>void>(()=>{}),cancel=useRef<()=>void>(()=>{}),callback=useRef(onComplete);callback.current=onComplete;
 useEffect(()=>{
  let active=true,generation=0,key:string|null=null,timer:ReturnType<typeof setTimeout>|undefined;
  setPage(0);setError('');setState(preview.inspection?.kind==='directory_tree'?'complete':'idle');
  const poll=async(id:string)=>{try{
    const result=await request('/'+id);if(!active||id!==key)return;
    if(result.progress)setProgress(result.progress);setState(result.state);
    if(result.state==='complete'&&result.preview){callback.current({...result.preview,auto_interpretation:preview.auto_interpretation});return;}
    if(result.state==='failed'){setError(result.error||'Folder discovery failed');return;}
    if(result.state==='running')timer=setTimeout(()=>poll(id),700);
  }catch(e){if(active&&id===key){setState('failed');setError(String(e));}}};
  begin.current=()=>{const version=++generation;setState('running');setError('');setProgress({directories:0,entries:0,media_names:0,current:'Connecting'});
    (async()=>{try{const result=await request('',{root:preview.root,interpretation:preview.auto_interpretation?'auto':preview.interpretation,alias:preview.alias,source_aliases:preview.source_aliases,exclusions:preview.exclusions});
      if(!active||version!==generation){await request('/'+result.id+'/cancel',{});return;}key=result.id;await poll(result.id);
    }catch(e){if(active){setState('failed');setError(String(e));}}})();
  };
  cancel.current=()=>{generation++;const id=key;key=null;clearTimeout(timer);if(id)void request('/'+id+'/cancel',{}).catch(()=>{});setState('cancelled');};
  if(preview.inspection?.truncated&&preview.inspection.kind==='directory_sample')begin.current();
  return()=>{active=false;clearTimeout(timer);if(key)void request('/'+key+'/cancel',{}).catch(()=>{});};
 },[preview.token]);
 const folders=preview.folder_tree||[],pages=Math.max(1,Math.ceil(folders.length/20)),current=Math.min(page,pages-1),start=current*20;
 return <section aria-label="Folder tree discovery" className="manager-folder-discovery">
  <h4>Folder tree · {folders.length.toLocaleString()} folders found</h4>
  <p className="manager-note">All photos and videos at every depth below this Database are included during sync, except excluded folders or paused Sources. A container folder with no media of its own can contain Albums deeper in its tree.</p>
  {state==='running'?<><p role="status">Discovering the complete folder tree… {progress.directories.toLocaleString()} folders checked · {progress.entries.toLocaleString()} entries · {progress.media_names.toLocaleString()} media filenames. Current: {progress.current}</p><button type="button" onClick={()=>cancel.current()}>Cancel folder discovery</button></>:<>
    <p role="status" className="manager-note">{preview.inspection?.kind==='directory_tree'&&!preview.inspection.truncated?'Complete accessible folder tree discovered. Media files were not opened.':state==='cancelled'?'Discovery cancelled. The quick preview remains available.':'This folder list comes from the quick scan and may be incomplete.'}</p>
    {(preview.inspection?.kind!=='directory_tree'||preview.inspection.truncated)&&<button type="button" onClick={()=>begin.current()}>Find all folders</button>}
  </>}
  {error&&<p role="alert" className="error">{error}</p>}
  {!!folders.length&&<><nav className="manager-preview-pages" aria-label="Folder tree pages"><span>Folders {start+1}–{Math.min(start+20,folders.length)} of {folders.length} · Page {current+1} of {pages}</span><div className="manager-preview-page-buttons">
    <button type="button" title="First folder page" aria-label="First folder page" disabled={current===0} onClick={()=>setPage(0)}>«</button><button type="button" title="Previous folder page" aria-label="Previous folder page" disabled={current===0} onClick={()=>setPage(current-1)}>‹</button><button type="button" title="Next folder page" aria-label="Next folder page" disabled={current===pages-1} onClick={()=>setPage(current+1)}>›</button><button type="button" title="Last folder page" aria-label="Last folder page" disabled={current===pages-1} onClick={()=>setPage(pages-1)}>»</button>
  </div></nav><div className="manager-preview-scroll"><table className="manager-table manager-preview-table"><thead><tr><th>Folder</th><th>Source</th><th>Album / role</th><th>Contents here</th></tr></thead><tbody>{folders.slice(start,start+20).map(folder=><tr key={folder.relative}><td>{folder.relative==='.'?'Database root':folder.relative}</td><td>{folder.source}</td><td>{folder.direct_media||preview.interpretation==='single_album'?<AlbumLocation album={folder.album} albumKey={folder.album_key} relative={folder.relative} sourceKey={folder.source_key} directory/>:folder.role}</td><td>{folder.readable===false?'Unavailable':folder.readable===null?'Not inspected yet':folder.direct_media?folder.direct_media.toLocaleString()+' media filenames':folder.children?'Subfolders only · descendants included':'Empty folder'}</td></tr>)}</tbody></table></div></>}
 </section>;
}
