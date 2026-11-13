import {useLayoutEffect} from "react";

// iOS can retain the old layout viewport and outer scroll offset after rotation.
// Keep the Library's only scroll surface inside the current visible viewport.
export default function useLibraryViewport(enabled:boolean) {
  useLayoutEffect(() => {
    if (!enabled) return;
    const mobile=window.matchMedia('(max-width:760px), (hover:none) and (pointer:coarse)');
    const root=document.documentElement;
    let frame=0;
    const update=()=>{
      if (!mobile.matches) {root.style.removeProperty('--library-viewport-height');return;}
      const viewport=window.visualViewport;
      if (viewport && Math.abs(viewport.scale-1)>.01) return;
      root.style.setProperty('--library-viewport-height',`${viewport?.height || window.innerHeight}px`);
      // Leave the gallery's own scroll position intact. Do not fight keyboard panning.
      if (!(document.activeElement instanceof HTMLElement && document.activeElement.matches('input,textarea,[contenteditable=true]')))
        window.scrollTo(0,0);
    };
    const schedule=()=>{cancelAnimationFrame(frame);frame=requestAnimationFrame(update);};
    update();
    window.addEventListener('resize',schedule);
    window.addEventListener('orientationchange',schedule);
    window.visualViewport?.addEventListener('resize',schedule);
    mobile.addEventListener('change',schedule);
    return()=>{
      cancelAnimationFrame(frame);
      window.removeEventListener('resize',schedule);
      window.removeEventListener('orientationchange',schedule);
      window.visualViewport?.removeEventListener('resize',schedule);
      mobile.removeEventListener('change',schedule);
      root.style.removeProperty('--library-viewport-height');
    };
  },[enabled]);
}
