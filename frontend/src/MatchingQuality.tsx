import React,{useEffect,useState} from 'react';
import {FlaskConical,Check,RotateCcw} from 'lucide-react';
import {readApiResponse} from './ApiResponse';

type Result={accepted:number;correct:number;mistakes:number;positive_examples:number;negative_examples:number};
type Report={id:string;created:string;eligible_people:number;additional_validation_matches:number;tuning_faces:number;validation_faces:number;note:string;method?:string;reference_photos?:number;people:{person_id:number;name:string;eligible:boolean;retained?:boolean;conflicts?:{face_id:string;media_id:string;actual_name:string;proposed_name:string;open_set?:boolean}[];reference_photos:number;tuning_photos:number;validation_photos:number;proposed:{score:number;margin:number};baseline:Result;validation:Result;reason:string}[]};
type State={report:Report|null;active_id:string|null;effective_mode?:'conservative'|'calibrated';active_people?:number;mode_reason?:string;report_stale?:boolean};
async function request(path='',body?:unknown){
 const response=await fetch('/api/people/calibration'+path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 return readApiResponse<State>(response);
}
export default function MatchingQuality({openPhoto,revision,working,calibrating,analyze,changed}:{openPhoto?:(id:string)=>void;revision:number;working:boolean;calibrating:boolean;analyze:()=>void;changed:()=>void}){
 const [open,setOpen]=useState(false),[state,setState]=useState<State>({report:null,active_id:null}),[error,setError]=useState(''),[saving,setSaving]=useState(false),[loaded,setLoaded]=useState(false);
 const load=()=>request().then(value=>{setState(value&&'report' in value?value:{report:null,active_id:null});setLoaded(true);setError('');}).catch(e=>{setError(String(e));setLoaded(false);});
 useEffect(()=>{void load();},[revision]);
 const apply=async(reset=false)=>{setSaving(true);setError('');try{await request(reset?'/reset':'/apply',reset?{}:{profile_id:state.report?.id,confirm:true});await load();changed();}catch(e){setError(String(e));}finally{setSaving(false);}};
 const report=state.report;
 const calibrated=state.effective_mode?state.effective_mode==='calibrated':!!state.active_id;
 return <section className="matching-settings" aria-label="Matching rules">
 <div className={'matching-mode '+(calibrated?'calibrated':'conservative')}>
  <div><strong>{!loaded?'Checking matching rules…':`Matching rules: ${calibrated?'Calibrated':'Conservative'}`}</strong><p>{error||state.mode_reason||(calibrated?'Adjusted matching rules are enabled.':'Original conservative cutoffs are in use. A calibration report alone does not enable new rules.')}</p></div>
  <button className="outline" onClick={()=>setOpen(value=>!value)}>{calibrated?'Review matching rules':report?'Review recommended rules':'Improve matching'}</button>
 </div>
 <details className="matching-quality" open={open} onToggle={event=>setOpen(event.currentTarget.open)}>
  <summary><FlaskConical size={18}/>Improve matching with saved examples<span>Analyze · review · enable</span></summary>
  {open&&<div className="matching-quality-body">
   <h3>Find more matches, with evidence</h3>
   <p>Test matching rules against saved faces held out by photograph. Rejections also refine person-specific separation during ordinary reevaluation, independently of these base rules. No face assignments change during analysis. The study uses every eligible reference photo and up to 80 independent photos each for tuning and validation. It compares against the enabled rules. Existing validated rules can be retained; new adjustments need separate validation.</p>
   <div className="builder-actions"><button className="outline" disabled={working||saving} onClick={analyze}><FlaskConical size={16}/>{calibrating?'Analyzing saved examples…':'Analyze matching quality'}</button>{state.active_id&&<button className="outline" disabled={working||saving} onClick={()=>void apply(true)}><RotateCcw size={16}/>Use conservative rules</button>}</div>
   {error&&<p role="alert">{error}</p>}
   {report&&<>
    <div className="matching-report-summary"><strong>{report.eligible_people} people with a validated adjustment</strong><span>{report.additional_validation_matches} additional correct matches in the held-back test</span>{report.reference_photos!=null&&<small>{report.reference_photos.toLocaleString()} reference photos · {report.method==='full-photo-gallery-v2'?'Full reference gallery':'Experimental study'}</small>}<small>Results against saved labels, not a guaranteed accuracy percentage. {state.active_id===report.id&&calibrated?'These rules are enabled.':'This report has not been enabled.'}</small></div>
    {state.report_stale&&state.active_id!==report.id&&<p className="matching-stale" role="status">Reviews changed since this report. Run Analyze matching quality again before enabling it.</p>}
    {report.eligible_people>0&&state.active_id!==report.id&&<div className="matching-enable"><p>Enabling starts reevaluation with these rules. It changes suggestion confidence; it does not approve faces. Automatic approval stays under your control.</p><button className="primary" disabled={working||saving||!!state.report_stale} onClick={()=>void apply()}><Check size={16}/>{saving?'Enabling…':'Enable reviewed matching rules'}</button></div>}
    <p className="small-note">{report.note}</p>
    <div className="matching-report-table"><table><thead><tr><th>Person</th><th>Reference photos</th><th>Validation photos</th><th>Correct: current → trial</th><th>Trial wrong matches</th><th>Decision</th></tr></thead><tbody>{report.people.map(person=><tr key={person.person_id}><th>{person.name}</th><td>{person.reference_photos}</td><td>{person.validation_photos}</td><td>{person.baseline.correct} → {person.validation.correct}</td><td>{person.validation.mistakes}</td><td>{person.eligible?'Adjustment available':person.reason}{!!person.conflicts?.length&&<details className="matching-conflicts"><summary>Inspect conflicting examples ({person.conflicts.length})</summary>{person.conflicts.map(item=><figure key={item.face_id}><img src={'/api/faces/'+encodeURIComponent(item.face_id)+'/thumbnail'} alt="Conflicting saved example"/><figcaption>Saved as {item.actual_name}; {item.open_set?'with that identity omitted, the study proposed ':'study proposed '}{item.proposed_name}.</figcaption>{openPhoto&&<button className="outline" onClick={()=>openPhoto(item.media_id)}>Open photo</button>}</figure>)}</details>}</td></tr>)}</tbody></table></div>

   </>}
  </div>}
 </details>
 </section>;
}
