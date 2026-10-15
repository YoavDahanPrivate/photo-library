export function isIOSStandalone(){
 const ios=/iPad|iPhone|iPod/.test(navigator.userAgent)||(/Macintosh/.test(navigator.userAgent)&&navigator.maxTouchPoints>1);
 return ios&&((navigator as Navigator&{standalone?:boolean}).standalone===true||window.matchMedia('(display-mode: standalone)').matches);
}
export function safariDownloadUrl(id:string,name:string,kind:string,format:string){
 const url=new URL('/download.html',window.location.origin);
 url.search=new URLSearchParams({id,name,kind,format}).toString();
 return url.href;
}
