import { useEffect, useMemo, useState } from "react";

type Feature = { geometry: { type: string; coordinates: number[][][] | number[][][][] } };
let boundaries: Promise<Feature[]> | undefined;
function loadBoundaries() {
  return boundaries ??= fetch('/api/map/countries').then(async r => {
    if (!r.ok) throw Error('Map unavailable');
    return (await r.json()).features as Feature[];
  }).catch(e => { boundaries = undefined; throw e; });
}

export default function LocationMap({latitude,longitude,city,country}:{latitude:number;longitude:number;city?:string|null;country?:string|null}) {
  const [features,setFeatures]=useState<Feature[]>([]), [failed,setFailed]=useState(false), [span,setSpan]=useState(12);
  useEffect(()=>{let active=true;loadBoundaries().then(v=>{if(active)setFeatures(v)}).catch(()=>{if(active)setFailed(true)});return()=>{active=false}},[]);
  const paths=useMemo(()=>features.flatMap(f=>{
    const polygons=f.geometry.type==='Polygon'?[f.geometry.coordinates as number[][][]]:f.geometry.coordinates as number[][][][];
    return polygons.flatMap(polygon=>{
      // Unwrap each polygon around the media longitude to handle the date line.
      const first=polygon[0]?.[0]?.[0] ?? 0;
      const offset=360*Math.round((longitude-first)/360);
      const rings=polygon.map(ring=>{let last=first;return ring.map(([lon,lat])=>{lon+=360*Math.round((last-lon)/360);last=lon;return [lon+offset,lat]})});
      return [-360,0,360].map(shift=>rings.map(ring=>ring.map(([lon,lat],i)=>`${i?'L':'M'}${180+(lon+shift-longitude)*360/span},${110+(latitude-lat)*360/span}`).join(' ')+'Z').join(' '));
    });
  }),[features,latitude,longitude,span]);
  const label=[city&&`Near ${city}`,country].filter(Boolean).join(', ') || 'Capture location';
  return <figure className="location-mini-map">
    <figcaption><strong>{label}</strong></figcaption>
    {failed?<p role="status">Offline map unavailable. The capture location is saved.</p>:<div className="location-map-canvas">
      <svg viewBox="0 0 360 220" role="img" aria-label={`Map showing where this was taken: ${label}`}>
        <rect width="360" height="220" fill="#e4eff0"/>
        {paths.map((d,i)=><path key={i} d={d} fill="#e6eadb" stroke="#aab99c" strokeWidth="0.8" fillRule="evenodd"/>)}
        <circle cx="180" cy="110" r="17" fill="#295c4330"/>
        <path d="M180 110 C175 103 169 98 169 91 A11 11 0 1 1 191 91 C191 98 185 103 180 110Z" fill="#28533e" stroke="white" strokeWidth="2"/>
        <circle cx="180" cy="91" r="3.5" fill="white"/>
      </svg>
      {!features.length&&<span className="location-map-loading" role="status">Loading map…</span>}
      <div className="location-map-controls"><button aria-label="Zoom location map in" disabled={span<=3} onClick={()=>setSpan(v=>Math.max(3,v/2))}>+</button><button aria-label="Zoom location map out" disabled={span>=360} onClick={()=>setSpan(v=>Math.min(360,v*2))}>−</button></div>
    </div>}
    <small>Offline regional map · <a href="https://www.naturalearthdata.com/" target="_blank" rel="noreferrer">Natural Earth</a></small>
  </figure>
}
