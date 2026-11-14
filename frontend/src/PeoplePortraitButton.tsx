import {useEffect,useRef,type ButtonHTMLAttributes} from 'react';
import {consumeTouchClick} from './touchActivation';

type Props=ButtonHTMLAttributes<HTMLButtonElement>&{onLongPress?:()=>void};

export default function PeoplePortraitButton({onLongPress,onClick,disabled,children,...props}:Props){
 const gesture=useRef<{id:number;x:number;y:number;timer:ReturnType<typeof setTimeout>|null;handled:boolean}|null>(null);
 const suppressClick=useRef(false);
 const latestLongPress=useRef(onLongPress);
 latestLongPress.current=onLongPress;
 const cancel=()=>{
  const current=gesture.current;
  if(current?.timer){clearTimeout(current.timer);current.timer=null;}
 };
 useEffect(()=>{
  const cancelScroll=()=>{if(gesture.current){cancel();suppressClick.current=true;}};
  document.addEventListener('scroll',cancelScroll,true);
  window.addEventListener('blur',cancelScroll);
  return()=>{cancel();document.removeEventListener('scroll',cancelScroll,true);window.removeEventListener('blur',cancelScroll);};
 },[]);
 useEffect(()=>{cancel();gesture.current=null;},[disabled,!!onLongPress]);
 return <button {...props} disabled={disabled}
  onPointerDown={event=>{
   cancel();gesture.current=null;suppressClick.current=false;
   if(!onLongPress||disabled||!event.isPrimary||event.button!==0)return;
   const current={id:event.pointerId,x:event.clientX,y:event.clientY,timer:null as ReturnType<typeof setTimeout>|null,handled:false};
   gesture.current=current;
   event.currentTarget.setPointerCapture(event.pointerId);
   current.timer=setTimeout(()=>{current.timer=null;current.handled=true;suppressClick.current=true;latestLongPress.current?.();},550);
  }}
  onPointerMove={event=>{const current=gesture.current;if(current&&current.id===event.pointerId&&Math.hypot(event.clientX-current.x,event.clientY-current.y)>10){cancel();suppressClick.current=true;}}}
  onPointerUp={event=>{
   const current=gesture.current;if(!current||current.id!==event.pointerId)return;
   cancel();gesture.current=null;
   if(current.handled||suppressClick.current){event.preventDefault();consumeTouchClick();}
  }}
  onPointerCancel={()=>{cancel();gesture.current=null;suppressClick.current=true;}}
  onLostPointerCapture={()=>{cancel();gesture.current=null;}}
  onContextMenu={event=>{if(onLongPress)event.preventDefault();}}
  onDragStart={event=>{if(onLongPress){event.preventDefault();cancel();suppressClick.current=true;}}}
  onKeyDown={()=>{cancel();gesture.current=null;suppressClick.current=false;}}
  onClick={event=>{if(suppressClick.current){event.preventDefault();event.stopPropagation();return;}onClick?.(event);}}
 >{children}</button>;
}
