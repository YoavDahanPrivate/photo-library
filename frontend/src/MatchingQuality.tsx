import React,{useEffect,useState} from 'react';
import {FlaskConical,Check,RotateCcw} from 'lucide-react';
import {readApiResponse} from './ApiResponse';

type Result={accepted:number;correct:number;mistakes:number;positive_examples:number;negative_examples:number};
type Report={id:string;created:string;eligible_people:number;additional_validation_matches:number;tuning_faces:number;validation_faces:number;note:string;people:{person_id:number;name:string;eligible:boolean;reference_photos:number;tuning_photos:number;validation_photos:number;proposed:{score:number;margin:number};baseline:Result;validation:Result;reason:string}[]};
type State={report:Report|null;active_id:string|null};
async function request(path='',body?:unknown){
 const response=await fetch('/api/people/calibration'+path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 return readApiResponse<State>(response);
}
export default function MatchingQuality({revision,working,calibrating,analyze,changed}:{revision:number;working:boolean;calibrating:boolean;analyze:()=>void;changed:()=>void}){
 const [open,setOpen]=useState(false),[state,setState]=useState<State>({report:null,active_id:null}),[error,setError]=useState(''),[saving,setSaving]=useState(false);
 const load=()=>request().then(value=>setState(value&&'report' in value?value:{report:null,active_id:null})).catch(e=>setError(String(e)));
 useEffect(()=>{if(open)void load();},[open,revision]);
 const apply=async(reset=false)=>{setSaving(true);setError('');try{await request(reset?'/reset':'/apply',reset?{}:{profile_id:state.report?.id,confirm:true});await load();changed();}catch(e){setError(String(e));}finally{setSaving(false);}};
 const report=state.report;
 return <details className="matching-quality" onToggle={event=>setOpen(event.currentTarget.open)}>
  <summary><FlaskConical size={18}/>Improve matching with saved examples<span>Analyze · review · enable</span></summary>
  {open&&<div className="matching-quality-body">
   <h3>Find more matches, with evidence</h3>
   <p>Test matching rules against saved faces held out by photograph. No face assignments change during analysis. A person keeps conservative rules unless separate tuning and validation examples support an adjustment.</p>
   <div className="builder-actions"><button className="outline" disabled={working||saving} onClick={analyze}><FlaskConical size={16}/>{calibrating?'Analyzing saved examples…':'Analyze matching quality'}</button>{state.active_id&&<button className="outline" disabled={working||saving} onClick={()=>void apply(true)}><RotateCcw size={16}/>Use conservative rules</button>}</div>
   {error&&<p role="alert">{error}</p>}
   {report&&<>
    <div className="matching-report-summary"><strong>{report.eligible_people} people with a validated adjustment</strong><span>{report.additional_validation_matches} additional correct matches in the held-back test</span><small>Results against saved labels, not a guaranteed accuracy percentage. {state.active_id===report.id?'These rules are enabled.':'This report has not been enabled.'}</small></div>
    <p className="small-note">{report.note}</p>
    <div className="matching-report-table"><table><thead><tr><th>Person</th><th>Reference photos</th><th>Validation photos</th><th>Correct: current → proposed</th><th>Observed wrong matches</th><th>Decision</th></tr></thead><tbody>{report.people.map(person=><tr key={person.person_id}><th>{person.name}</th><td>{person.reference_photos}</td><td>{person.validation_photos}</td><td>{person.baseline.correct} → {person.validation.correct}</td><td>{person.validation.mistakes}</td><td>{person.eligible?'Adjustment available':person.reason}</td></tr>)}</tbody></table></div>
    {report.eligible_people>0&&state.active_id!==report.id&&<div className="matching-enable"><p>Enabling applies these per-person rules on the next reevaluation. The high-confidence list is cleared until reevaluation completes. The automatic approval loop will use the enabled rules when you start it.</p><button className="primary" disabled={working||saving} onClick={()=>void apply()}><Check size={16}/>{saving?'Enabling…':'Enable reviewed matching rules'}</button></div>}
   </>}
  </div>}
 </details>;
}
