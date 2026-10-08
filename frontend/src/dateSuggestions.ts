import type {Suggestion} from "./searchSuggestions";
export const datePhrases=["after","before","between","since","until","on","in","during","on or after","on or before"];
const months=["January","February","March","April","May","June","July","August","September","October","November","December"];
const tidy=(s:string)=>s.toLowerCase().replace(/(\d)(st|nd|rd|th)\b/g,"$1").replace(/[.,]/g," ").replace(/\s+/g," ").trim();
function calendarChoices(fragment:string,now:Date):string[]{
 const f=tidy(fragment),year=now.getFullYear();
 if(/^\d{4}$/.test(f))return [+f>0?f:""].filter(Boolean);
 if(/^\d{4}-\d{2}(?:-\d{2})?$/.test(f))return [f];
 const dayFirst=f.match(/^(\d{1,2})\s+([a-z]*)(?:\s+(\d{1,4}))?$/);
 const named=f.match(/^([a-z]*)(?:\s+(\d{1,4}))?(?:\s+(\d{1,4}))?$/);
 if(!named && !dayFirst)return [];
 const monthPrefix=dayFirst?dayFirst[2]:named![1];
 const day=dayFirst?+dayFirst[1]:named![3] || (named![2] && named![2].length<=2)?+named![2]:null;
 const yearPrefix=dayFirst?dayFirst[3]||"":named![3]||((named![2]?.length??0)>2?named![2]:"")||"";
 const years=yearPrefix.length===4?[+yearPrefix]:Array.from({length:12},(_,i)=>year-i).filter(y=>String(y).startsWith(yearPrefix));
 const out:string[]=[];
 // Month-first order keeps suggestions relevant while typing a month name.
 for(const y of years)for(const m of months.filter(m=>m.toLowerCase().startsWith(monthPrefix))){
  if(y<1 || y>9999 || day!==null && (day<1||day>new Date(y,months.indexOf(m)+1,0).getDate()))continue;
  out.push(dayFirst?day+" "+m+" "+y:m+(day!==null?" "+day:"")+" "+y);
 }
 return out;
}
export function dateSuggestions(text:string,cursor:number,now=new Date()):Suggestion[]|null{
 // Mask quoted data so a person's name such as "After May" stays a person.
 const before=text.slice(0,cursor),safe=before.replace(/"(?:[^"\\]|\\.)*(?:"|$)/g,m=>" ".repeat(m.length));
 const starts=/(?:^|[()]|\b(?:and|or|not)\b|&&|\|\|)\s*((?:date\s+)?(?:on\s+or\s+after|on\s+or\s+before|after|before|between|since|until|through|on|in|during)\s+|(?:date\s+)?(?:>=|<=|==|!=|>|<|=)\s*)/gi;
 let match:RegExpExecArray|null,last:RegExpExecArray|null=null;
 while((match=starts.exec(safe)))last=match;
 if(!last)return null;
 const op=last[1].toLowerCase().trim().replace(/^date\s+/,""),begin=last.index+last[0].length;
 let start=begin,fragment=before.slice(begin),second=false;
 if(op==="between"){
  const separator=/\s+(?:and|to)\s+/i.exec(fragment);
  if(separator){start=begin+separator.index+separator[0].length;fragment=before.slice(start);second=true;}
 }
 if(/[()"]|\b(?:and|or|not)\b|&&|\|\|/i.test(fragment))return null;
 let end=cursor;
 while(end<text.length && !/[()]/.test(text[end]) && !/^\s+(?:and|or|to)\b|^\s*(?:&&|\|\|)/i.test(text.slice(end)))end++;
 while(end>cursor && /\s/.test(text[end-1]))end--;
 const choices=calendarChoices(fragment,now);
 return choices.slice(0,12).map(value=>{
  const needsAnd=op==="between"&&!second&&!/^\s+(?:and|to)\b/i.test(text.slice(end));
  const hint=op==="between"?(second?"Through this date / month":"From this date / month"):['after','>'].includes(op)?"After this day / month":['before','<'].includes(op)?"Before this day / month":"Includes this day / month";
  return {label:value,kind:hint,insert:value+(needsAnd?" and ":""),start,end};
 });
}
