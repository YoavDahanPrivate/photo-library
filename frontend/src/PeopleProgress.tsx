import React,{useEffect,useState} from 'react';
import {LoaderCircle,CheckCircle2,AlertCircle,Square} from 'lucide-react';

export type PeopleOperation={id:string;kind?:'reevaluate'|'auto-approve';state:'queued'|'running'|'completed'|'cancelled'|'failed'|'interrupted';phase:string;started_at:number;updated_at:number;finished_at?:number;processed:number|null;total:number|null;unit?:string;error?:string;round?:number;rounds_completed?:number;approved_total?:number;review_revision?:number;stop_requested?:boolean;result?:{evaluated?:number;suggestions?:number;saved_people?:number;approved?:number;rounds?:number;stop_reason?:string}};

function duration(seconds:number){
  const value=Math.max(0,Math.floor(seconds));
  return value<60?`${value}s`:`${Math.floor(value/60)}m ${value%60}s`;
}

export default function PeopleProgress({operation,approving,approvalCount,connection,onCancel}:{operation:PeopleOperation|null;approving:boolean;approvalCount:number;connection:string;onCancel:()=>Promise<void>}){
  const [now,setNow]=useState(()=>Date.now()/1000);
  const [approvalStarted,setApprovalStarted]=useState(()=>Date.now()/1000);
  const [cancelling,setCancelling]=useState(false);
  useEffect(()=>{if(approving)setApprovalStarted(Date.now()/1000);},[approving]);
  useEffect(()=>{setCancelling(false);},[operation?.id,operation?.state]);
  const running=operation?.state==='queued'||operation?.state==='running';
  const automatic=operation?.kind==='auto-approve';
  const stopping=cancelling||operation?.stop_requested;
  useEffect(()=>{
    if(!running&&!approving)return;
    setNow(Date.now()/1000);
    const timer=setInterval(()=>setNow(Date.now()/1000),1000);
    return()=>clearInterval(timer);
  },[running,approving]);
  if(!operation&&!approving)return null;
  const failed=operation?.state==='failed'||operation?.state==='interrupted';
  const percent=!approving&&running&&operation?.total&&operation.processed!==null?Math.min(100,Math.floor(100*operation.processed/operation.total)):null;
  const elapsed=approving?now-approvalStarted:(operation?.finished_at||now)-(operation?.started_at||now);
  const message=approving?'Waiting for the server to confirm the complete batch.':operation?.error||(running?
    stopping?'Stopping at a safe point. Completed approvals will stay saved.':automatic?'Approve high-confidence matches → reevaluate → repeat. You can keep browsing.':'Reevaluation is running in the background. You can keep browsing.':
    automatic?operation?.state==='completed'?'No more high-confidence matches remain in the visible library. Lower-confidence matches are left for review.':'Stopped. Completed approvals are saved; unapproved matches remain for review.':
    operation?.state==='completed'?`${operation.result?.suggestions?.toLocaleString()||0} matches ready for review. No faces assigned automatically.`:'Existing assignments and previously saved suggestions are kept.');
  return <section className="people-operation" aria-label="Face review progress" aria-busy={approving||running}>
    <div className="people-operation-heading">
      {approving||running?<LoaderCircle className="people-operation-spinner" size={21}/>:failed?<AlertCircle size={21}/>:<CheckCircle2 size={21}/>}
      <div><strong>{approving?`Saving ${approvalCount.toLocaleString()} assignments`:automatic&&running?`Auto approval · ${operation?.phase}`:operation?.phase}</strong>
        <p role="status" aria-live="polite">{message}</p>
      </div>
      <span className="people-operation-time">{duration(elapsed)} elapsed</span>
    </div>
    {automatic&&!approving&&<div className="people-auto-totals">
      <strong>{(operation?.approved_total||0).toLocaleString()} approved</strong>
      <span>{operation?.round?`Round ${operation.round} · `:''}{operation?.rounds_completed||0} completed {(operation?.rounds_completed||0)===1?'round':'rounds'}</span>
    </div>}
    {(running||approving)&&<>
      <progress aria-label={approving?'Saving assignments':automatic?'Automatic approval progress':'Reevaluation progress'} max={100} value={percent===null?undefined:percent}/>
      <div className="people-operation-details">
        <span>{percent!==null?`${percent}% · ${operation!.processed!.toLocaleString()} of ${operation!.total!.toLocaleString()} ${operation?.unit||'items'} in this phase`:approving?'Assignments are saved together; confirmation follows the commit.':'Counting work for this phase…'}</span>
        {running&&!approving&&<button className="outline people-stop-button" disabled={!!stopping} onClick={()=>{setCancelling(true);void onCancel().catch(()=>setCancelling(false));}}><Square size={13} aria-hidden="true"/>{stopping?'Stopping…':automatic?'Stop automatic approval':'Stop reevaluation'}</button>}
      </div>
      {connection?<p role="alert">{connection} Reconnecting to progress…</p>:running&&now-(operation?.updated_at||now)>10?<p className="small-note">Waiting for the worker’s next update. Reading or saving the catalogue can take longer while storage is busy.</p>:null}
    </>}
  </section>;
}
