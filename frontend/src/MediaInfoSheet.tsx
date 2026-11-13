import React,{useEffect,useRef,useState} from 'react';

export default function MediaInfoSheet({children}:{children:React.ReactNode}){
 const [mobile,setMobile]=useState(()=>window.matchMedia('(max-width:760px), (hover:none) and (pointer:coarse)').matches);
 const [open,setOpen]=useState(false),[offset,setOffset]=useState<number|null>(null);
 const sheet=useRef<HTMLElement>(null);
 const gesture=useRef<{y:number;start:number;last:number;moved:boolean}|null>(null);
 const ignoreClick=useRef(false);
 useEffect(()=>{
   const query=window.matchMedia('(max-width:760px), (hover:none) and (pointer:coarse)');
   const update=()=>{setMobile(query.matches);if(gesture.current)ignoreClick.current=true;gesture.current=null;setOffset(null);};
   query.addEventListener('change',update);window.addEventListener('resize',update);window.visualViewport?.addEventListener('resize',update);
   return()=>{query.removeEventListener('change',update);window.removeEventListener('resize',update);window.visualViewport?.removeEventListener('resize',update);};
 },[]);
 const travel=()=>{const el=sheet.current;if(!el)return 0;const css=getComputedStyle(el);return Math.max(0,el.getBoundingClientRect().height-(parseFloat(css.getPropertyValue('--sheet-peek'))||48)-(parseFloat(css.paddingBottom)||0));};
 return <aside ref={sheet} className={'viewer-info media-info-sheet'+(open?' sheet-open':'')+(offset!==null?' sheet-dragging':'')}
   style={mobile&&offset!==null?{transform:`translateY(${offset}px)`}:undefined}
   onKeyDown={e=>{if(mobile&&open&&e.key==='Escape'){e.stopPropagation();setOpen(false);}}}>
   <button className="media-info-handle" aria-label={open?'Hide photo information':'Show photo information'} aria-expanded={open}
     onPointerDown={e=>{if(!mobile)return;e.currentTarget.setPointerCapture(e.pointerId);const start=open?0:travel();gesture.current={y:e.clientY,start,last:start,moved:false};ignoreClick.current=false;}}
     onPointerMove={e=>{const g=gesture.current;if(!g)return;const delta=e.clientY-g.y;if(Math.abs(delta)>6)g.moved=true;if(g.moved){g.last=Math.max(0,Math.min(travel(),g.start+delta));setOffset(g.last);}}}
     onPointerUp={e=>{const g=gesture.current;if(!g)return;gesture.current=null;if(g.moved){ignoreClick.current=true;const delta=e.clientY-g.y;setOpen(Math.abs(delta)>35?delta<0:g.last<travel()/2);}setOffset(null);}}
     onPointerCancel={()=>{gesture.current=null;setOffset(null);ignoreClick.current=true;}}
     onClick={()=>{if(ignoreClick.current){ignoreClick.current=false;return;}setOpen(v=>!v);}}>
     <span className="media-info-grip"/><span className="media-info-label">{open?'Swipe down to return to photo':'Information'}<span aria-hidden="true"> {open?'⌄':'⌃'}</span></span>
   </button>
   <div className="media-info-content" inert={mobile&&!open&&offset===null} aria-hidden={mobile&&!open&&offset===null}
     onClick={e=>{if(mobile&&(e.target as HTMLElement).closest('.viewer-face-entry button'))setOpen(false);}}>{children}</div>
 </aside>;
}
