import React,{useLayoutEffect,useState} from 'react';

export default function ResultsLoadingNotice({busy}:{busy:boolean}){
 const [position,setPosition]=useState<{top:number;center:number}|null>(null);
 useLayoutEffect(()=>{
   const header=document.querySelector('.library-topbar');
   const update=()=>{const box=header?.getBoundingClientRect();setPosition({top:Math.max(0,box?.bottom||0)+12,center:box?box.left+box.width/2:window.innerWidth/2});};
   update();const observer=new ResizeObserver(update);if(header)observer.observe(header);
   window.addEventListener('resize',update);window.addEventListener('scroll',update,true);
   return()=>{observer.disconnect();window.removeEventListener('resize',update);window.removeEventListener('scroll',update,true);};
 },[]);
 if(!position)return null;
 return <div className="results-loading-anchor results-loading-floating" style={{'--loading-top':position.top+'px','--loading-center':position.center+'px'} as React.CSSProperties}>
   <div className="results-loading-banner" role="status" aria-live="polite">
     <span className="results-loading-spinner" aria-hidden="true"/>
     <div><strong>{busy?'Preparing your search…':'Results loading…'}</strong><span>{busy?'Checking your search criteria':'Updating photos and videos for your search'}</span></div>
     <div className="results-loading-progress" aria-hidden="true"/>
   </div>
 </div>;
}
