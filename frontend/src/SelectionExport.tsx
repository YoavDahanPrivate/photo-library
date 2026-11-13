import {useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {Share2,Download,X} from 'lucide-react';
import {exportUrl,prepareShareFile,SHARE_LIMIT,type ExportFormat} from './mediaTransfer';

export default function SelectionExport({ids}:{ids:string[]}){
 const [open,setOpen]=useState(false),[busy,setBusy]=useState(false),[files,setFiles]=useState<File[]>([]),[message,setMessage]=useState(''),[format,setFormat]=useState<ExportFormat>('preview');
 const abort=useRef<AbortController|null>(null),opener=useRef<HTMLElement|null>(null),panel=useRef<HTMLElement|null>(null);
 const native=window.isSecureContext&&typeof navigator.share==='function'&&typeof navigator.canShare==='function';
 useEffect(()=>()=>abort.current?.abort(),[]);
 const close=()=>{abort.current?.abort();setOpen(false);setBusy(false);setFiles([]);opener.current?.focus();};
 useEffect(()=>{if(open)panel.current?.querySelector<HTMLButtonElement>('button')?.focus();},[open]);
 const prepare=async()=>{
  const controller=new AbortController();abort.current=controller;setBusy(true);setFiles([]);setMessage('');
  try{const ready:File[]=[];let total=0;
   for(const id of ids){
    setMessage(`Preparing ${ready.length+1} of ${ids.length}…`);
    const detail=await fetch('/api/media/'+encodeURIComponent(id),{signal:controller.signal});if(!detail.ok)throw Error('Could not read a selected item. Check its source and retry.');
    const media=await detail.json();const file=await prepareShareFile(id,media.name||id,format,controller.signal,()=>{});
    total+=file.size;if(total>SHARE_LIMIT)throw Error('This selection is too large to share together. Select fewer items or download them individually.');ready.push(file);
   }
   if(controller.signal.aborted)return;
   if(!navigator.canShare({files:ready}))throw Error('This browser cannot share this selection together. Use the individual save options below.');
   setFiles(ready);setMessage('Ready. Open the share sheet to choose a sharing app or Save Images / Save to Photos when offered.');
  }catch(e){if(!controller.signal.aborted)setMessage(e instanceof Error?e.message:String(e));}
  finally{if(!controller.signal.aborted)setBusy(false);}
 };
 const share=()=>{if(!files.length)return;void navigator.share({files,title:'Dahan selected media'}).catch(e=>setMessage(e?.name==='AbortError'?'Sharing cancelled. Your selection is still here.':'Sharing failed. Try fewer items or save individually.'));};
 return <>
 <button disabled={!ids.length} onClick={e=>{opener.current=e.currentTarget;setOpen(true);setMessage('');}}><Share2 size={16}/>Share / save selected</button>
 {open&&createPortal(<div className="selection-export-backdrop" onPointerDown={e=>{if(e.target===e.currentTarget)close();}}><section ref={panel} className="selection-export-panel" role="dialog" aria-modal="true" aria-label="Share and save selection" onKeyDown={e=>{e.stopPropagation();if(e.key==='Escape')close();if(e.key==='Tab'){const nodes=Array.from(panel.current?.querySelectorAll<HTMLElement>('button:not(:disabled),select,a[href]')||[]),first=nodes[0],last=nodes[nodes.length-1];if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}}}}>
 <header><strong>{ids.length} selected · Share & save</strong><button aria-label="Close selection save options" onClick={close}><X size={18}/></button></header>
 <label>File format<select aria-label="Selection file format" value={format} disabled={busy} onChange={e=>{setFormat(e.target.value as ExportFormat);setFiles([]);setMessage('');}}><option value="preview">JPEG images · up to 1,600px</option><option value="original">Original photos & videos</option></select></label>
 {format==='preview'&&<p>Photos are saved as JPEG previews. Videos provide a still image; choose Originals to save the video.</p>}
 {native?<><button disabled={busy} onClick={()=>void prepare()}><Download size={16}/>{busy?'Preparing…':'Prepare selected files'}</button><button disabled={!files.length||busy} onClick={share}><Share2 size={16}/>Share / Save to Photos</button></>:<p>Use Download for each file below. On a phone, touch and hold an image to choose Save to Photos or Share when offered.</p>}
 {message&&<p role="status">{message}</p>}
 <details><summary>Individual downloads & image saves</summary>{ids.map((id,i)=><div className="selection-export-item" key={id}>{!native&&format==='preview'&&<img loading="lazy" src={'/api/media/'+encodeURIComponent(id)+'/thumbnail?size=large'} alt={'Selected image '+(i+1)}/>}<a href={exportUrl(id,format)} download={format==='preview'?`Dahan-${id}.jpg`:undefined}>Download {format==='preview'?'image':'original'} {i+1}</a></div>)}</details>
 <button onClick={close}>Back to selection</button>
 </section></div>,document.body)}
 </>;
}
