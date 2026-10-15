import SaveMedia from "./SaveMedia";
import React,{useEffect,useRef,useState} from "react";
import {X,Maximize,Minimize,Download,ChevronLeft,ChevronRight,Plus,Minus,RotateCcw,Play,Pause,Volume2,VolumeX,LoaderCircle,UserRoundPlus} from "lucide-react";
type Props={kind:string;expanded:boolean;onToggleExpanded:()=>void;onClose:()=>void;onEditFaces:()=>void;direction:"next"|"previous"|"none";departingImage:string;id:string;name:string;width:number;height:number;imageUrl:string;videoUrl:string;previous:string|null;next:string|null;position:number|null;total:number;busy:boolean;onNavigate:(id:string,swiped?:boolean)=>Promise<boolean|void>};
export default function MediaViewerStage(p:Props){
 const [saveOpen,setSaveOpen]=useState(false);
 const [controls,setControls]=useState(true),[highReady,setHighReady]=useState(false),[highError,setHighError]=useState(false);
 const [zoom,setZoom]=useState(1),[pan,setPan]=useState({x:0,y:0}),[box,setBox]=useState({w:0,h:0}),[intrinsic,setIntrinsic]=useState({w:p.width||1,h:p.height||1});
 const [departing,setDeparting]=useState(!!p.departingImage&&p.direction!=="none");
 const [localVideo,setLocalVideo]=useState(""),[playingVideo,setPlayingVideo]=useState(false),[videoError,setVideoError]=useState(""),[videoLoading,setVideoLoading]=useState(false);
 const [playing,setPlaying]=useState(false),[muted,setMuted]=useState(false),[time,setTime]=useState(0),[duration,setDuration]=useState(0);
 const viewport=useRef<HTMLDivElement>(null),video=useRef<HTMLVideoElement>(null),hideTimer=useRef<ReturnType<typeof setTimeout>|undefined>(undefined),alive=useRef(true);
 const pointers=useRef(new Map<number,{x:number;y:number}>()),pinch=useRef<{distance:number;zoom:number}|null>(null),wasPinch=useRef(false);
 const drag=useRef<{x:number;y:number;px:number;py:number;started:number}|null>(null),lastTap=useRef(0),pointerKind=useRef("mouse"),wheelSwipe=useRef({amount:0,last:0,navigated:0});
 const [swipeX,setSwipeX]=useState(0),[settling,setSettling]=useState(false),[dragging,setDragging]=useState(false);
 const swipeAxis=useRef<"x"|"y"|null>(null),swipeOffset=useRef(0),swipeTimer=useRef<ReturnType<typeof setTimeout>|undefined>(undefined),swipeLocked=useRef(false);
 useEffect(()=>()=>clearTimeout(swipeTimer.current),[]);
 const moveSwipe=(x:number)=>{swipeOffset.current=x;setSwipeX(x);};
 const settleSwipe=(target:number,id:string|null=null)=>{
   setDragging(false);setSettling(true);swipeLocked.current=true;moveSwipe(target);
   const delay=window.matchMedia('(prefers-reduced-motion: reduce)').matches?0:220;
   clearTimeout(swipeTimer.current);swipeTimer.current=setTimeout(async()=>{
     if(id){const success=await p.onNavigate(id,true);if(!alive.current)return;moveSwipe(0);}
     else moveSwipe(0);
     setSettling(false);swipeLocked.current=false;
   },delay);
 };
 const highWanted=p.kind==="photo"&&p.expanded;
 const activeVideo=(playingVideo||!!p.videoUrl||!!localVideo)&&p.expanded?"/api/media/"+p.id+"/original":localVideo||p.videoUrl;
 const reveal=()=>{setControls(true);clearTimeout(hideTimer.current);hideTimer.current=setTimeout(()=>setControls(false),2800);};
 useEffect(()=>{alive.current=true;reveal();return()=>{alive.current=false;clearTimeout(hideTimer.current);};},[]);
 useEffect(()=>{const el=viewport.current;if(!el)return;const observer=new ResizeObserver(entries=>{const r=entries[0].contentRect;setBox({w:r.width,h:r.height});});observer.observe(el);return()=>observer.disconnect();},[]);
 useEffect(()=>{setZoom(1);setPan({x:0,y:0});reveal();},[p.expanded]);
 const fit=Math.min(box.w/intrinsic.w,box.h/intrinsic.h),w=intrinsic.w*fit,h=intrinsic.h*fit;
 const clamp=(point:{x:number;y:number},scale=zoom)=>({x:Math.max(-Math.max(0,(w*scale-box.w)/2),Math.min(Math.max(0,(w*scale-box.w)/2),point.x)),y:Math.max(-Math.max(0,(h*scale-box.h)/2),Math.min(Math.max(0,(h*scale-box.h)/2),point.y))});
 const changeZoom=(value:number,anchor?:{x:number;y:number})=>{const scale=Math.max(1,Math.min(6,value));setZoom(scale);setPan(old=>clamp(anchor?{x:anchor.x-(anchor.x-old.x)*scale/zoom,y:anchor.y-(anchor.y-old.y)*scale/zoom}:old,scale));};
 useEffect(()=>{setPan(old=>clamp(old));},[box.w,box.h,intrinsic.w,intrinsic.h]);
 const navigate=(id:string|null)=>{if(id&&!p.busy)p.onNavigate(id);};
 useEffect(()=>{
   const el=viewport.current;if(!el)return;
   const wheel=(e:WheelEvent)=>{e.preventDefault();reveal();const now=Date.now();
     if(Math.abs(e.deltaX)>Math.abs(e.deltaY)*1.5&&zoom===1&&!e.ctrlKey){
       const s=wheelSwipe.current;if(now-s.last>250)s.amount=0;s.last=now;s.amount+=e.deltaX;
       if(Math.abs(s.amount)>90&&now-s.navigated>700){navigate(s.amount>0?p.next:p.previous);s.amount=0;s.navigated=now;}
     }else{const r=el.getBoundingClientRect();changeZoom(zoom*Math.exp(-e.deltaY*.003),{x:e.clientX-r.left-r.width/2,y:e.clientY-r.top-r.height/2});}
   };
   el.addEventListener("wheel",wheel,{passive:false});return()=>el.removeEventListener("wheel",wheel);
 },[zoom,pan,box,p.next,p.previous,p.busy]);
 useEffect(()=>{const key=(e:KeyboardEvent)=>{if(saveOpen)return;
   if((e.target as HTMLElement)?.closest('input,textarea,select,video,[contenteditable]'))return;
   if(e.key==="ArrowLeft"){e.preventDefault();navigate(p.previous);}if(e.key==="ArrowRight"){e.preventDefault();navigate(p.next);}
   if(e.key==="+"||e.key==="="){e.preventDefault();changeZoom(zoom+.5);reveal();}if(e.key==="-"){e.preventDefault();changeZoom(zoom-.5);reveal();}if(e.key==="0"){changeZoom(1);reveal();}
 };window.addEventListener("keydown",key);return()=>window.removeEventListener("keydown",key);},[p.previous,p.next,p.busy,zoom,saveOpen]);
 const startVideo=async()=>{
   setVideoError("");setPlayingVideo(true);setVideoLoading(true);reveal();
   if(p.expanded)return;
   try{const r=await fetch("/api/media/"+p.id+"/preview",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});const data=await r.json();if(!r.ok)throw Error(data.detail||"Could not prepare video");if(alive.current)setLocalVideo(data.url);}
   catch(e){if(alive.current){setVideoLoading(false);setPlayingVideo(false);setVideoError(String(e));}}
 };
 useEffect(()=>{if(playingVideo&&!p.expanded&&!localVideo&&!p.videoUrl)void startVideo();},[p.expanded]);
 const style={width:w||"100%",height:h||"100%",transform:"translate("+pan.x+"px,"+pan.y+"px) scale("+zoom+")"};
 const resetGesture=()=>{pointers.current.clear();pinch.current=null;drag.current=null;wasPinch.current=false;swipeAxis.current=null;};
 const button=(label:string,icon:React.ReactNode,action:()=>void,disabled=false)=><button type="button" aria-label={label} title={label} onClick={action} disabled={disabled}>{icon}</button>;
 return <div className={"media-stage gentle-viewer"+((controls||saveOpen)?" controls-visible":"")} onPointerMove={e=>{if(e.pointerType==="mouse")reveal();}}>
   <div ref={viewport} className={"media-viewport"+(zoom>1?" pannable":"")+(p.expanded?" expanded-gestures":"")} aria-label="Media preview"
     onDoubleClick={e=>{if(pointerKind.current==="mouse"){changeZoom(zoom>1?1:2);reveal();}}}
     onPointerDown={e=>{if(swipeLocked.current||p.busy)return;setSettling(false);swipeAxis.current=null;pointerKind.current=e.pointerType;e.currentTarget.setPointerCapture(e.pointerId);pointers.current.set(e.pointerId,{x:e.clientX,y:e.clientY});drag.current={x:e.clientX,y:e.clientY,px:pan.x,py:pan.y,started:Date.now()};if(pointers.current.size===2){moveSwipe(0);setDragging(false);wasPinch.current=true;const [a,b]=[...pointers.current.values()];pinch.current={distance:Math.hypot(a.x-b.x,a.y-b.y),zoom};}}}
     onPointerMove={e=>{if(!pointers.current.has(e.pointerId))return;pointers.current.set(e.pointerId,{x:e.clientX,y:e.clientY});if(pointers.current.size===2&&pinch.current){const [a,b]=[...pointers.current.values()];const r=e.currentTarget.getBoundingClientRect();changeZoom(pinch.current.zoom*Math.hypot(a.x-b.x,a.y-b.y)/Math.max(1,pinch.current.distance),{x:(a.x+b.x)/2-r.left-r.width/2,y:(a.y+b.y)/2-r.top-r.height/2});}else if(drag.current&&zoom>1)setPan(clamp({x:drag.current.px+e.clientX-drag.current.x,y:drag.current.py+e.clientY-drag.current.y}));else if(drag.current&&!wasPinch.current&&zoom===1){const dx=e.clientX-drag.current.x,dy=e.clientY-drag.current.y;if(!swipeAxis.current&&Math.hypot(dx,dy)>8)swipeAxis.current=Math.abs(dx)>Math.abs(dy)*1.2?'x':'y';if(swipeAxis.current==='x'){setDragging(true);setDeparting(false);const available=dx<0?p.next:p.previous;moveSwipe(available?Math.max(-box.w,Math.min(box.w,dx)):dx*.22);}}}}
     onPointerUp={e=>{if(!wasPinch.current&&drag.current){const dx=e.clientX-drag.current.x,dy=e.clientY-drag.current.y;
       if(zoom===1&&swipeAxis.current==='x'){const target=dx<0?p.next:p.previous;const speed=Math.abs(dx)/Math.max(1,Date.now()-drag.current.started);const commit=target&&(Math.abs(dx)>Math.max(55,box.w*.22)||(Math.abs(dx)>28&&speed>.45));settleSwipe(commit?(dx<0?-box.w:box.w):0,commit?target:null);}
       else if(Math.hypot(dx,dy)<10){const now=Date.now();if(e.pointerType!=="mouse"&&now-lastTap.current<320){changeZoom(zoom>1?1:2);lastTap.current=0;}else lastTap.current=now;reveal();}
     }pointers.current.delete(e.pointerId);if(!pointers.current.size)resetGesture();else{drag.current=null;pinch.current=null;}}}
     onPointerCancel={()=>{if(swipeOffset.current)settleSwipe(0);resetGesture();}}>
     {departing&&!dragging&&!settling&&<div className={"departing-frame motion-"+p.direction} onAnimationEnd={()=>setDeparting(false)}><img src={p.departingImage} alt="" aria-hidden="true"/></div>}
     {(dragging||settling)&&[[-1,p.previous],[1,p.next]].map(([side,id])=>id&&<div key={String(side)} className="swipe-neighbor" style={{transform:'translateX('+(Number(side)*box.w+swipeX)+'px)',transition:settling?'transform 220ms cubic-bezier(.2,.7,.2,1)':'none'}} aria-hidden="true"><img src={'/api/media/'+id+'/thumbnail?size=large'} alt="" draggable={false}/></div>)}
     <div className={"incoming-frame motion-"+p.direction+(dragging||settling?" finger-tracking":"")} style={dragging||settling?{animation:'none',transform:'translateX('+swipeX+'px)',transition:settling?'transform 220ms cubic-bezier(.2,.7,.2,1)':'none'}:undefined}>
       {activeVideo?<video ref={video} style={style} src={activeVideo} autoPlay playsInline muted={muted}
         onLoadStart={()=>setVideoLoading(true)} onWaiting={()=>setVideoLoading(true)} onCanPlay={()=>setVideoLoading(false)}
         onError={()=>{setVideoLoading(false);setVideoError(p.expanded?"This browser cannot play the original codec. Collapse for a compatible preview, or download the original.":"Video preview unavailable. Try Download.");}}
         onLoadedMetadata={e=>{setIntrinsic({w:e.currentTarget.videoWidth||p.width,h:e.currentTarget.videoHeight||p.height});setDuration(Number.isFinite(e.currentTarget.duration)?e.currentTarget.duration:0);}}
         onTimeUpdate={e=>setTime(e.currentTarget.currentTime)} onPlay={()=>setPlaying(true)} onPause={()=>setPlaying(false)}/>
       :<img style={style} src={highWanted&&highReady?"/api/media/"+p.id+"/display-original":p.imageUrl} alt={p.name} draggable={false} onLoad={e=>setIntrinsic({w:e.currentTarget.naturalWidth,h:e.currentTarget.naturalHeight})}/>}
     </div>
     {highWanted&&!highReady&&!highError&&<img className="high-resolution-loader" src={"/api/media/"+p.id+"/display-original"} alt="" aria-hidden="true" onLoad={()=>setHighReady(true)} onError={()=>setHighError(true)}/>}
   </div>
   <button type="button" className="viewer-close-control" aria-label="Close viewer" onClick={e=>{e.stopPropagation();p.onClose();}}><X/></button>
   <div className="viewer-overlay-controls overlay-top">
     <span className="viewer-position">{p.position?p.position.toLocaleString()+" / "+p.total.toLocaleString():""}</span>
     {button(p.expanded?"Collapse fullscreen view":"Expand to fullscreen",p.expanded?<Minimize/>:<Maximize/>,p.onToggleExpanded)}
     <SaveMedia id={p.id} name={p.name} kind={p.kind} onOpenChange={setSaveOpen}/>
     {p.kind==="photo"&&button("Add or edit faces",<UserRoundPlus/>,p.onEditFaces)}
   </div>
   <div className="viewer-overlay-controls overlay-previous">{button("Previous image or video",<ChevronLeft/>,()=>navigate(p.previous),!p.previous||p.busy)}</div>
   <div className="viewer-overlay-controls overlay-next">{button("Next image or video",<ChevronRight/>,()=>navigate(p.next),!p.next||p.busy)}</div>
   {(p.busy||(highWanted&&!highReady&&!highError)||videoLoading)&&<div className="media-loading" role="status"><LoaderCircle className="spin" size={18}/>{p.busy?"Loading image…":videoLoading?"Loading video…":"Loading original resolution…"}</div>}
   {((highWanted&&highError)||videoError)&&<div className="media-load-error" role="status">{videoError||"Original unavailable. Showing large preview; try Download."}</div>}
   {p.kind==="video"&&!activeVideo&&!videoLoading&&<div className="viewer-overlay-controls overlay-play">{button(p.expanded?"Play original video":"Play video preview",<Play/>,()=>void startVideo())}</div>}
   <div className="viewer-overlay-controls overlay-bottom">
     {activeVideo&&<div className="overlay-playback">{button(playing?"Pause video":"Play video",playing?<Pause/>:<Play/>,()=>{if(video.current?.paused)void video.current.play().catch(()=>setPlaying(false));else video.current?.pause();})}<input aria-label="Video position" type="range" min="0" max={duration||1} step="0.1" value={time} onChange={e=>{if(video.current)video.current.currentTime=Number(e.target.value);setTime(Number(e.target.value));}}/>{button(muted?"Unmute":"Mute",muted?<VolumeX/>:<Volume2/>,()=>setMuted(v=>!v))}</div>}
     <div className="overlay-zoom">{button("Zoom out",<Minus/>,()=>changeZoom(zoom-.5),zoom<=1)}<output aria-label="Zoom level">{Math.round(zoom*100)}%</output>{button("Zoom in",<Plus/>,()=>changeZoom(zoom+.5),zoom>=6)}{button("Fit to view",<RotateCcw/>,()=>changeZoom(1))}</div>
   </div>
 </div>;
}
