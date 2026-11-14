import {useEffect, useRef} from "react";
import {createPortal} from "react-dom";

const examples = [
  ['Include a person', 'Includes("Maya")', 'Find media containing Maya. Other people may also appear.'],
  ['Include two people', 'Includes("Maya" and "Daniel")', 'Both Maya and Daniel must appear; other people are allowed.'],
  ['Just these named people', 'Just("Maya" and "Daniel")', 'Both must appear, with no other named people. Unnamed faces are allowed.'],
  ['Only one person', 'Only("Maya")', 'Maya must be the only detected face. Face detection can miss people.'],
  ['A whole month', 'Aug 2024', 'Find media dated anywhere in August 2024. August 2024 works too.'],
  ['People during a date range', 'Includes("Maya") and between August 2024 and September 2024', 'Find Maya from August 1 through September 30, 2024, including both endpoints.'],
  ['Either person, photos only', '(Includes("Maya") or Includes("Daniel")) and MediaType("photo")', 'Find photos containing Maya, Daniel, or both. Parentheses keep the OR choices together.'],
  ['Landscape videos', 'MediaType("video") and Orientation("landscape")', 'Find videos that are wider than they are tall. Portrait and square are also supported.'],
  ['Exclude a person', 'Includes("Maya") and not Includes("Daniel")', 'Find Maya with no detected appearance of Daniel. Other people are allowed.'],
  ['Combine dates, people and orientation', '(Just("Maya") or Just("Daniel")) and date >= 2024-08-01 and date < 2024-09-01 and MediaType("photo") and not Orientation("square")', 'Find non-square photos from August 2024 with either Maya or Daniel as the only named person. Unnamed faces are allowed.'],
];

export default function SearchExamples({onClose}:{onClose:()=>void}) {
  const dialog=useRef<HTMLDialogElement>(null);
  useEffect(()=>{
    const previous=document.activeElement as HTMLElement|null;
    dialog.current?.showModal();
    return ()=>{dialog.current?.close();previous?.focus();};
  },[]);
  return createPortal(<dialog ref={dialog} className="search-examples" aria-labelledby="search-examples-title" onCancel={e=>{e.preventDefault();onClose();}} onClick={e=>{if(e.target===e.currentTarget){const r=e.currentTarget.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)onClose();}}}>
    <header><h2 id="search-examples-title">Search examples</h2><button type="button" autoFocus onClick={onClose} aria-label="Close search examples">Close</button></header>
    <div className="search-examples-content">
      <p>Copy an example into search and replace Maya and Daniel with saved names from your library. The include command is <code>Includes</code>.</p>
      <p><strong>AND</strong> requires both conditions. <strong>OR</strong> allows either or both. <strong>NOT</strong> excludes a condition. Use parentheses to group choices. <code>&amp;&amp;</code> and <code>||</code> also work for AND and OR.</p>
      <p className="small-note">Your source and toolbar filters still apply. Dates use the recorded capture date; estimated dates match overlapping periods. Video people searches use sampled frames, so people may appear at different times.</p>
      <ol>{examples.map(([title,query,description])=><li key={title}><h3>{title}</h3><code className="search-example-query">{query}</code><p>{description}</p></li>)}</ol>
    </div>
  </dialog>,document.body);
}
