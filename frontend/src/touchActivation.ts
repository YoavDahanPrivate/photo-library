/** Consume only the compatibility click belonging to an already-handled touch.
 * A new pointer/keyboard action immediately removes the guard, so a fast second
 * interaction is never blocked. This also prevents tapping through a removed
 * suggestion or closing dialog onto the controls underneath it.
 */
export function consumeTouchClick(){
 let timer:ReturnType<typeof setTimeout>;
 const cleanup=()=>{
  clearTimeout(timer);
  document.removeEventListener('click',click,true);
  document.removeEventListener('pointerdown',cleanup,true);
  document.removeEventListener('keydown',cleanup,true);
 };
 const click=(event:MouseEvent)=>{event.preventDefault();event.stopImmediatePropagation();cleanup();};
 document.addEventListener('click',click,true);
 document.addEventListener('pointerdown',cleanup,true);
 document.addEventListener('keydown',cleanup,true);
 timer=setTimeout(cleanup,500);
}
