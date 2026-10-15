import React,{useEffect,useMemo,useState} from 'react';
import {ArrowDown,ArrowUp,Users} from 'lucide-react';
type Person={id:number;name:string|null;count:number;cover:string};
type Sort='name'|'count';
type Direction='asc'|'desc';
type Preferences={known:boolean;unknown:boolean;sort:Sort;directions:Record<Sort,Direction>};
const storageKey='dahan.peopleBrowse.v1';
const defaults=():Preferences=>({known:true,unknown:true,sort:'name',directions:{name:'asc',count:'desc'}});
export const isKnownPerson=(person:Person)=>person.id>0&&!!person.name?.trim();
export const personLabel=(person:Person)=>person.name?.trim()||'Unnamed person '+person.id;
function readPreferences():Preferences{
 const result=defaults();
 try{
  const saved=JSON.parse(localStorage.getItem(storageKey)||'null');
  if(!saved||typeof saved!=='object')return result;
  if(typeof saved.known==='boolean')result.known=saved.known;
  if(typeof saved.unknown==='boolean')result.unknown=saved.unknown;
  if(!result.known&&!result.unknown){result.known=true;result.unknown=true;}
  if(saved.sort==='name'||saved.sort==='count')result.sort=saved.sort;
  for(const sort of ['name','count'] as const){const direction=saved.directions?.[sort];if(direction==='asc'||direction==='desc')result.directions[sort]=direction;}
 }catch{/* Defaults also work when browser storage is unavailable. */}
 return result;
}
export function usePeopleBrowse(people:Person[]){
 const [preferences,setPreferences]=useState(readPreferences);
 useEffect(()=>{try{localStorage.setItem(storageKey,JSON.stringify(preferences));}catch{}},[preferences]);
 const visible=useMemo(()=>{
  const collator=new Intl.Collator(undefined,{sensitivity:'base',numeric:true});
  const direction=preferences.directions[preferences.sort]==='asc'?1:-1;
  return people.filter(person=>isKnownPerson(person)?preferences.known:preferences.unknown).sort((a,b)=>{
   const name=collator.compare(personLabel(a),personLabel(b));
   if(preferences.sort==='name')return direction*name||a.id-b.id;
   return direction*(a.count-b.count)||name||a.id-b.id;
  });
 },[people,preferences]);
 const knownCount=people.filter(isKnownPerson).length;
 const toggle=(kind:'known'|'unknown')=>setPreferences(previous=>{
  if(previous[kind]&&!previous[kind==='known'?'unknown':'known'])return previous;
  return {...previous,[kind]:!previous[kind]};
 });
 return {preferences,visible,knownCount,unknownCount:people.length-knownCount,toggle,
  sort:(sort:Sort)=>setPreferences(previous=>({...previous,sort})),
  direction:(direction:Direction)=>setPreferences(previous=>({...previous,directions:{...previous.directions,[previous.sort]:direction}})),
 };
}
export default function PeopleBrowse({browse}:{browse:ReturnType<typeof usePeopleBrowse>}){
 const {preferences,visible,knownCount,unknownCount}=browse,direction=preferences.directions[preferences.sort];
 return <section className="people-browse" aria-label="People display options">
  <div className="people-browse-heading"><h2><Users size={20} aria-hidden="true"/>Browse people</h2><span role="status">{visible.length.toLocaleString()} of {(knownCount+unknownCount).toLocaleString()} people / groups</span></div>
  <div className="people-browse-controls">
   <div className="people-kind-switch" role="group" aria-label="Show people">
    <button aria-label="Known people" aria-pressed={preferences.known} disabled={preferences.known&&!preferences.unknown} title={preferences.known&&!preferences.unknown?'Enable Unknown people to show both groups':'Show or hide named people'} onClick={()=>browse.toggle('known')}>Known people<span>{knownCount.toLocaleString()}</span></button>
    <button aria-label="Unknown people" aria-pressed={preferences.unknown} disabled={preferences.unknown&&!preferences.known} title={preferences.unknown&&!preferences.known?'Enable Known people to show both groups':'Show or hide unnamed groups and unassigned faces'} onClick={()=>browse.toggle('unknown')}>Unknown people<span>{unknownCount.toLocaleString()}</span></button>
   </div>
   <label className="people-sort">Sort by<select aria-label="Sort people by" value={preferences.sort} onChange={event=>browse.sort(event.target.value as Sort)}><option value="name">Name</option><option value="count">Face count</option></select></label>
   <div className="people-direction-switch" role="group" aria-label="People sort order">
    <button aria-label="Ascending people order" aria-pressed={direction==='asc'} onClick={()=>browse.direction('asc')}><ArrowUp size={16} aria-hidden="true"/>{preferences.sort==='name'?'A–Z':'Smallest first'}</button>
    <button aria-label="Descending people order" aria-pressed={direction==='desc'} onClick={()=>browse.direction('desc')}><ArrowDown size={16} aria-hidden="true"/>{preferences.sort==='name'?'Z–A':'Largest first'}</button>
   </div>
  </div>
  <p>Enable both groups to show everyone. Face count is the number of faces assigned to each person or group. Choices are remembered on this browser.</p>
 </section>;
}
