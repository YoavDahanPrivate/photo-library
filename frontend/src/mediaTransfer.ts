import {readApiResponse} from "./ApiResponse";
export type ExportFormat="original"|"preview";
export const SHARE_LIMIT=128*1024*1024;
export const exportUrl=(id:string,format:ExportFormat)=>`/api/media/${encodeURIComponent(id)}/${format==="original"?"original?download=true":"thumbnail?size=large"}`;
export function exportName(name:string,format:ExportFormat){
  const safe=name.split(/[\\/]/).pop()?.replace(/[\u0000-\u001f]/g,"")||"Dahan media";
  return format==="original"?safe:safe.replace(/\.[^.]+$/,"")+"-preview.jpg";
}
export async function prepareShareFile(id:string,name:string,format:ExportFormat,signal:AbortSignal,progress:(bytes:number,total:number)=>void){
  const response=await fetch(exportUrl(id,format),{signal});
  if(!response.ok)await readApiResponse(response);
  const total=Number(response.headers.get("content-length"))||0;
  const tooLarge=()=>new Error("This file is too large to prepare for sharing here. Use the Safari download link to save the original to Files, or choose the JPEG preview.");
  if(total>SHARE_LIMIT){await response.body?.cancel();throw tooLarge();}
  const reader=response.body?.getReader();const chunks:BlobPart[]=[];let bytes=0;
  try {
    if(reader){
      while(true){
        const part=await reader.read();if(part.done)break;
        bytes+=part.value.byteLength;
        if(bytes>SHARE_LIMIT){await reader.cancel();throw tooLarge();}
        chunks.push(part.value);progress(bytes,total);
      }
    }else{const blob=await response.blob();if(blob.size>SHARE_LIMIT)throw tooLarge();chunks.push(blob);}
  } finally {reader?.releaseLock();}
  if(signal.aborted)throw new DOMException("Preparation cancelled","AbortError");
  const mime=format==="preview"?"image/jpeg":response.headers.get("content-type")?.split(";")[0]||"application/octet-stream";
  return new File(chunks,exportName(name,format),{type:mime});
}
