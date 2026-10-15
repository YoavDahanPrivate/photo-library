import React from 'react';
import {ChevronsLeft,ChevronLeft,ChevronRight,ChevronsRight} from 'lucide-react';

export default function ReviewPager({page,total,size,onPage}:{page:number;total:number;size:number;onPage:(page:number)=>void}){
  const pages=Math.max(1,Math.ceil(total/size));
  return <div className="review-pagination">
    <span>{total?`${(page*size+1).toLocaleString()}–${Math.min(total,(page+1)*size).toLocaleString()} of ${total.toLocaleString()} matches`:'No matches to review'}</span>
    {pages>1&&<nav aria-label="Match pages">
      <button aria-label="First match page" disabled={!page} onClick={()=>onPage(0)}><ChevronsLeft size={17}/></button>
      <button aria-label="Previous match page" disabled={!page} onClick={()=>onPage(page-1)}><ChevronLeft size={17}/></button>
      <span>Page {page+1} of {pages}</span>
      <button aria-label="Next match page" disabled={page>=pages-1} onClick={()=>onPage(page+1)}><ChevronRight size={17}/></button>
      <button aria-label="Last match page" disabled={page>=pages-1} onClick={()=>onPage(pages-1)}><ChevronsRight size={17}/></button>
    </nav>}
  </div>;
}
