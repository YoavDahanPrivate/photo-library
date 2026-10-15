export type SyncProgress=Record<string,string|number|boolean|null|undefined>;

export default function RunProgress({progress,state}:{progress:SyncProgress;state:string}) {
  const active=['running','pausing','cancelling'].includes(state);
  const total=typeof progress.total==='number'?progress.total:null;
  const processed=typeof progress.processed==='number'?progress.processed:0;
  const updated=typeof progress.updated_at==='string'?new Date(progress.updated_at):null;
  const waiting=active&&updated&&Date.now()-updated.getTime()>20000;
  const phase=progress.phase==='Reconciling files'?'Checking file contents':String(progress.phase||state);
  const stageUnit=phase.startsWith('Matching faces:')?String(progress.unit||'faces'):'files';
  return <div className="sync-progress-detail">
    <p><strong>{phase}</strong>{total!==null&&<> · {processed.toLocaleString()} / {total.toLocaleString()} {stageUnit} in this stage</>}</p>
    {active&&total!==null&&<progress max={Math.max(1,total)} value={processed} aria-label="Current stage progress"/>}
    {progress.phase==='Reading source folders'&&<p>{Number(progress.folders_checked||0).toLocaleString()} folders checked · {Number(progress.media_found||0).toLocaleString()} media files found. Total unknown while discovering folders.</p>}
    {progress.checkpoint_version!==1&&total===null&&typeof progress.inventory==='number'&&<p>{progress.inventory.toLocaleString()} media files found. Completed checking count is not available for this run yet.</p>}
    {progress.checkpoint_version!==1&&typeof progress.inventory==='number'&&!progress.reconciled&&<p>This run started before file-check checkpoints were available. Pause is safe; Resume will repeat the initial file-content checks.</p>}
    {!!progress.current_folder&&<p className="sync-current-path"><span>{active?'Current folder':'Last folder'}</span><code>{String(progress.current_folder)}</code></p>}
    {!!progress.current_file&&<p className="sync-current-path"><span>{active?'Current file':'Last file'}</span><code>{String(progress.current_file)}</code></p>}
    {!!progress.live_added&&<p>{Number(progress.live_added).toLocaleString()} new items registered during this scan{typeof progress.previews_published==='number'?` · ${progress.previews_published.toLocaleString()} previews processed`:''}. Ready previews appear in Library while scanning continues.</p>}
    {progress.preview_total_growing&&<p>Preparing a batch of previews. This total grows as more files are discovered; face recognition runs afterward.</p>}
    {!!progress.hashes_reused&&<p>{Number(progress.hashes_reused).toLocaleString()} completed file checks reused from this run’s checkpoint.</p>}
    {waiting&&<p role="status">Waiting for the current file or network operation to finish. Last progress: {updated.toLocaleTimeString()}.</p>}
    {state==='pausing'&&<p role="status">Pause requested. Waiting for the current operation to stop safely; then Resume will be available.</p>}
    {state==='cancelling'&&<p role="status">Stop requested. Waiting for a safe checkpoint; completed progress will be kept for Resume.</p>}
    {state==='paused'&&<p>Progress saved. Resume continues this run and checks source folders again for changes.</p>}
    {active&&<small>Counts are for this stage, not the whole sync. Network speed and media processing vary, so no reliable finish time is available yet.</small>}
  </div>;
}
