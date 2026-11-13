function bytes(s:string):ArrayBuffer{return Uint8Array.from(atob(s.replace(/-/g,'+').replace(/_/g,'/')),c=>c.charCodeAt(0)).buffer;}
function b64(v:ArrayBuffer){return btoa(String.fromCharCode(...new Uint8Array(v))).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');}
export const supported=()=>window.isSecureContext&&!!window.PublicKeyCredential;
export async function passkey(o:any,create:boolean){
 const publicKey={...o,challenge:bytes(o.challenge)};
 if(create){publicKey.user={...o.user,id:bytes(o.user.id)};publicKey.excludeCredentials=o.excludeCredentials?.map((k:any)=>({...k,id:bytes(k.id)}));}
 else publicKey.allowCredentials=o.allowCredentials?.map((k:any)=>({...k,id:bytes(k.id)}));
 const k=await (create?navigator.credentials.create({publicKey}):navigator.credentials.get({publicKey})) as PublicKeyCredential|null;
 if(!k)throw new Error('Passkey request cancelled.');
 const r:any=k.response;
 const response:any={clientDataJSON:b64(r.clientDataJSON)};
 for(const field of (create?['attestationObject']:['authenticatorData','signature','userHandle']))response[field]=r[field]?b64(r[field]):null;
 if(create)response.transports=r.getTransports?.()||[];
 return {id:k.id,rawId:b64(k.rawId),type:k.type,response,clientExtensionResults:k.getClientExtensionResults()};
}
