import React, {useEffect, useMemo, useState} from "react";
import AlbumLocation from "./AlbumLocation";

export type PreviewAssignment={relative:string;database:string;source:string;album:string;source_key?:string;album_key?:string};

export default function PreviewAssignments({samples,incomplete}:{samples:PreviewAssignment[];incomplete:boolean}){
  const [page,setPage]=useState(0),pageSize=10;
  const albums=useMemo(()=>{
    const groups=new Map<string,PreviewAssignment[]>();
    for(const sample of samples){
      const key=JSON.stringify([sample.source_key??sample.source,sample.album_key??sample.album]);
      const group=groups.get(key)||[];group.push(sample);groups.set(key,group);
    }
    return [...groups.values()];
  },[samples]);
  useEffect(()=>setPage(0),[samples]);
  if(!albums.length)return <p className="manager-note">No media assignments found in the inspected folders.</p>;
  const pages=Math.ceil(albums.length/pageSize),current=Math.min(page,pages-1),start=current*pageSize;
  const shown=albums.slice(start,start+pageSize).flat();
  const controls=(position:string)=><nav className="manager-preview-pages" aria-label={"Assignment preview pages · "+position}>
    <span>Page {current+1} of {pages}</span>
    <div className="manager-preview-page-buttons">
      <button type="button" aria-label="First preview page" title="First page" disabled={current===0} onClick={()=>setPage(0)}>«</button>
      <button type="button" aria-label="Previous preview page" title="Previous page" disabled={current===0} onClick={()=>setPage(current-1)}>‹</button>
      <button type="button" aria-label="Next preview page" title="Next page" disabled={current===pages-1} onClick={()=>setPage(current+1)}>›</button>
      <button type="button" aria-label="Last preview page" title="Last page" disabled={current===pages-1} onClick={()=>setPage(pages-1)}>»</button>
    </div>
  </nav>;
  return <div className="manager-assignment-pages">
    <p className="manager-note" role="status" aria-live="polite">Showing Albums {start+1}–{Math.min(start+pageSize,albums.length)} of {albums.length} found · up to 3 example files per Album.</p>
    <p className="manager-note">Every Album found in the inspected folders is available across these pages.{incomplete?" The folder scan is partial; sync may discover additional Albums outside this sample.":""}</p>
    {controls("top")}
    <div className="manager-preview-scroll"><table className="manager-table manager-preview-table"><thead><tr><th>Relative file</th><th>Database</th><th>Source</th><th>Album</th></tr></thead><tbody>{shown.map(sample=><tr key={sample.relative}><td>{sample.relative}</td><td>{sample.database}</td><td>{sample.source}</td><td><AlbumLocation album={sample.album} albumKey={sample.album_key} relative={sample.relative} sourceKey={sample.source_key}/></td></tr>)}</tbody></table></div>
    {controls("bottom")}
  </div>;
}
