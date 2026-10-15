import {useEffect,useId,useRef,useState} from "react";
import {createPortal} from "react-dom";
import {isIOSStandalone} from "./iosExport";
import SafariDownload from "./SafariDownload";
import {Download,X,Share2,LoaderCircle,ArrowLeft} from "lucide-react";
import {exportUrl,exportName,prepareShareFile,type ExportFormat} from "./mediaTransfer";

export default function SaveMedia({id,name,kind,onOpenChange}:{id:string;name:string;kind:string;onOpenChange:(open:boolean)=>void}){
 const [open,setOpen]=useState(false),[mode,setMode]=useState<"download"|"share">("download"),[format,setFormat]=useState<ExportFormat>("original");
 const [busy,setBusy]=useState(false),[sharing,setSharing]=useState(false),[file,setFile]=useState<File|null>(null),[message,setMessage]=useState("");
 const [progress,setProgress]=useState({bytes:0,total:0});
 const opener=useRef<HTMLElement|null>(null),panel=useRef<HTMLElement|null>(null),controller=useRef<AbortController|null>(null);
 const frame=useRef<HTMLIFrameElement|null>(null),alive=useRef(true);
 const key=useId().replace(/[^a-zA-Z0-9]/g,"");const frameName="dahan-download-"+key;
 const iosStandalone=isIOSStandalone();
 const native=window.isSecureContext&&typeof navigator.share==="function"&&typeof navigator.canShare==="function";
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;controller.current?.abort();};},[]);
 const close=()=>{controller.current?.abort();setOpen(false);setFile(null);onOpenChange(false);opener.current?.focus();};
 const show=(next:"download"|"share",button:HTMLButtonElement)=>{opener.current=button;setMode(next);setFormat(next==="share"?"preview":"original");setFile(null);setMessage("");setOpen(true);onOpenChange(true);};
 useEffect(()=>{
  const original=(event:Event)=>{if((event as CustomEvent<{id:string}>).detail?.id!==id)return;opener.current=document.activeElement instanceof HTMLElement?document.activeElement:null;setMode("download");setFormat("original");setMessage("");setOpen(true);onOpenChange(true);};
  window.addEventListener("dahan:save-original",original);return()=>window.removeEventListener("dahan:save-original",original);
 },[id,onOpenChange]);
 useEffect(()=>{if(open)panel.current?.querySelector<HTMLButtonElement>('button')?.focus();},[open]);
 useEffect(()=>{
  setFile(null);setMessage("");setProgress({bytes:0,total:0});
  if(!open||(!iosStandalone&&mode!=="share")||!native)return;
  const abort=new AbortController();controller.current=abort;setBusy(true);
  void prepareShareFile(id,name,format,abort.signal,(bytes,total)=>{if(!abort.signal.aborted)setProgress({bytes,total});}).then(next=>{
    if(abort.signal.aborted)return;
    if(!navigator.canShare({files:[next]}))throw new Error("Your phone cannot share this file format. Choose the JPEG preview or use the Safari download link below.");
    setFile(next);
  }).catch(error=>{if(!abort.signal.aborted)setMessage(error instanceof Error?error.message:String(error));}).finally(()=>{if(!abort.signal.aborted)setBusy(false);});
  return()=>{abort.abort();setBusy(false);};
 },[open,mode,format,id,name,native,iosStandalone]);
 const download=()=>{
  // iOS standalone downloads can replace the whole app even when targeted at
  // an iframe. Never issue an attachment navigation from that context.
  if(iosStandalone){setMessage("Use the image menu or the Safari download link below.");return;}
  const link=document.createElement("a");link.href=exportUrl(id,format);link.download=exportName(name,format);link.target=frameName;
  document.body.appendChild(link);link.click();link.remove();
  setMessage(`Download requested. Choose a save location if your browser asks. Dahan stays open; use Back to ${kind==="photo"?"photo":"video"} below when finished.`);
 };
 const share=()=>{
  if(!file||sharing)return;setSharing(true);setMessage("");
  try {
    // Call directly from this tap; fetching first would expire iPhone activation.
    const result=navigator.share({files:[file],title:name});
    void Promise.resolve(result).then(()=>{if(alive.current)setMessage(`Share sheet closed. You can return to your ${kind==="photo"?"photo":"video"}.`);}).catch(error=>{if(alive.current)setMessage(error?.name==="AbortError"?"Sharing cancelled. You are still in Dahan.":"The phone could not share this file. Try the JPEG preview or use the Safari download link below.");}).finally(()=>{if(alive.current)setSharing(false);});
  }catch{setSharing(false);setMessage("Sharing is unavailable here. Use the image menu or the Safari download link below.");}
 };
 const frameLoaded=()=>{try{const text=frame.current?.contentDocument?.body?.textContent;if(text){const data=JSON.parse(text);if(typeof data.detail==="string")setMessage(data.detail);}}catch{/* Download responses do not provide a document. */}};
 const preview=kind==="photo"&&format==="original"?`/api/media/${encodeURIComponent(id)}/display-original`:`/api/media/${encodeURIComponent(id)}/thumbnail?size=large`;
 return <>
  <button type="button" aria-label="Download" title="Download" onClick={e=>show("download",e.currentTarget)}><Download/></button>
  <button type="button" aria-label="Share" title="Share" onClick={e=>show("share",e.currentTarget)}><Share2/></button>
  {!iosStandalone&&<iframe hidden title="Media download" name={frameName} ref={frame} onLoad={frameLoaded}/>}
  {open&&createPortal(<div className="save-media-backdrop" onPointerDown={e=>{if(e.target===e.currentTarget&&!sharing)close();}}>
   <section ref={panel} className="save-media-sheet" role="dialog" aria-modal="true" aria-labelledby={key+"-save-title"} onKeyDown={e=>{
     e.stopPropagation();if(e.key==="Escape"&&!sharing){e.preventDefault();close();}
     if(e.key==="Tab"){const list=Array.from(panel.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),a[href]')||[]);const first=list[0],last=list[list.length-1];if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}}
   }}>
    <header><h2 id={key+"-save-title"}>{mode==="share"?"Share":"Download"} {kind==="photo"?"photo":"video"}</h2><button type="button" aria-label="Close save options" disabled={sharing} onClick={close}><X/></button></header>
    <p className="save-filename">{name}</p>
    <fieldset disabled={sharing}><legend>Choose a file</legend>
      <label><input type="radio" name={key+"-format"} checked={format==="original"} onChange={()=>setFormat("original")}/><span><strong>Original {kind==="video"?"video":"photo"}</strong><small>Original file, quality and metadata</small></span></label>
      <label><input type="radio" name={key+"-format"} checked={format==="preview"} onChange={()=>setFormat("preview")}/><span><strong>Largest preview · JPEG</strong><small>Up to 1,600 pixels{kind==="video"?" · still image from the video":" · smaller file for sharing"}</small></span></label>
    </fieldset>
    {(mode==="share"||iosStandalone)&&!native&&<>
      <p>Save or share the image below without leaving Dahan. Touch and hold it to open the phone’s image menu.</p>
      {(format==="preview"||kind==="photo")?<><img className="save-touch-preview" onError={()=>setMessage("This save view is unavailable. Try the JPEG preview or check that the source is online.")} src={preview} alt={format==="preview"?"Preview to save or share":"Full-resolution photo to save or share"}/><p>Choose Save to Photos or Share when offered. Dismiss that menu to return to Dahan; there is no need to open the downloaded file in Preview.</p>{format==="original"&&<p>This save view is a full-resolution browser-compatible image. {iosStandalone?"To keep the exact source format and metadata, use the Safari download link below.":"Download original below keeps the exact source format and metadata."}</p>}</>:<p>{iosStandalone?"The original video needs a file download in Safari on this connection. Use the link below, or choose Largest preview to save a still image inside Dahan.":"Download the original video to Files, then use the phone’s Share option there. The JPEG preview above shares a still image."}</p>}
    </>}
    {(mode==="share"||iosStandalone)&&native&&<>
      {busy&&<p role="status" className="save-preparing"><LoaderCircle className="spin"/>Preparing {format==="original"?"original":"preview"}… {progress.total>0?Math.min(100,Math.round(progress.bytes/progress.total*100))+"%":progress.bytes>0?(progress.bytes/1024**2).toFixed(1)+" MB":""}</p>}
      <button type="button" className="save-primary" disabled={!file||busy||sharing} onClick={share}><Share2/>{sharing?"Sharing…":mode==="download"?format==="original"?"Save or share original":"Save or share preview":format==="original"?"Share original":"Share preview"}</button>
      <p>Choose Save Image, Save Video, Save to Files or a sharing app when offered. Dismiss the share sheet to return to Dahan.</p>
    </>}
    {!iosStandalone&&<button type="button" className={mode==="download"?"save-primary":""} disabled={sharing} onClick={download}><Download/>{format==="original"?"Download original":"Download JPEG preview"}</button>}
    {iosStandalone&&(!native||(!busy&&!file)||message.includes("could not share")||message.includes("unavailable"))&&<SafariDownload id={id} name={name} kind={kind} format={format}/>}
    {message&&<p role="status" className="save-message">{message}</p>}
    <button type="button" className="save-return" disabled={sharing} onClick={close}><ArrowLeft/>Back to {kind==="photo"?"photo":"video"}</button>
   </section>
  </div>,document.body)}
 </>;
}
