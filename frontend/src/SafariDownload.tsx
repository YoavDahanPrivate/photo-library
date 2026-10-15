import {useRef,useState} from 'react';
import {safariDownloadUrl} from './iosExport';

export default function SafariDownload({id,name,kind,format}:{id:string;name:string;kind:string;format:string}){
 const field=useRef<HTMLTextAreaElement|null>(null),[message,setMessage]=useState('');
 const url=safariDownloadUrl(id,name,kind,format);
 const select=()=>{field.current?.focus();field.current?.select();field.current?.setSelectionRange(0,url.length);};
 const copy=async()=>{try{if(!navigator.clipboard?.writeText)throw new Error();await navigator.clipboard.writeText(url);setMessage('Link copied. Open Safari and paste it into the address bar.');}catch{select();setMessage('Touch and hold the selected link and choose Copy. Then open Safari and paste it into the address bar.');}};
 return <section className="save-safari" aria-label="Download safely in Safari">
  <h3>Exact file · download in Safari</h3>
  <p>An iPhone home-screen file download can hide Dahan’s return controls. Use Safari for the file download, then switch back to Dahan Photos.</p>
  <ol><li>Copy the link below.</li><li>Open the Safari app and paste it into its address bar.</li><li>Download there, then switch back to Dahan Photos. This photo or video stays open here.</li></ol>
  <textarea ref={field} aria-label="Safari download link" value={url} readOnly rows={3} onFocus={select}/>
  <button type="button" onClick={()=>void copy()}>Copy Safari download link</button>
  {message&&<p role="status">{message}</p>}
 </section>;
}
