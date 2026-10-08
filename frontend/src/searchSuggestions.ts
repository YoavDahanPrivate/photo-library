import {dateSuggestions,datePhrases} from "./dateSuggestions";
export type SearchItem={label:string;value:string;kind:string;aliases?:string[]};
export type Suggestion={label:string;kind:string;insert:string;start:number;end:number;caret?:number};
export const normalizeSearch=(s:string)=>s.normalize("NFKD").replace(/[\u0300-\u036f]/g,"").toLowerCase().trim();
export const deviceKey=(s:string)=>normalizeSearch(s).replace(/[^\p{L}\p{N}]/gu,"");
const commands=["Includes","Only","Just","Person","Place","Phone","Album","MediaType","Orientation","Text","Area","Location","AllPhones","date"];
const personCommands=["includes","only","just","person"];
export function searchSuggestions(text:string,cursor:number,items:SearchItem[]):Suggestion[]{
 const before=text.slice(0,cursor),stack:string[]=[];
 const tokens=[...before.matchAll(/"(?:[^"\\]|\\.)*(?:"|$)|[\w]+|[()]/g)];
 let previous="",quoteStart=-1;
 for(const t of tokens){const value=t[0];if(value.startsWith('"')){if(!/^"(?:[^"\\]|\\.)*"$/.test(value))quoteStart=t.index!;previous="";continue;}if(value==="("){stack.push(previous.toLowerCase());previous="";}else if(value===")"){stack.pop();previous="";}else previous=value;}
 const context=stack[stack.length-1]||"";
 let start=cursor,end=cursor,fragment="";
 if(quoteStart>=0){start=quoteStart;let i=cursor;for(;i<text.length;i++){if(text[i]==="\\"){i++;continue;}if(text[i]==='"'){i++;break;}}end=i;fragment=text.slice(start+1,cursor);}
 else {
  const boundary=/(?:\b(?:and|or|not)\b|&&|\|\||[()])\s*/gi;let match:RegExpExecArray|null,last=0;
  while((match=boundary.exec(before)))last=match.index+match[0].length;
  start=last;while(/\s/.test(text[start]||"")&&start<cursor)start++;
  end=cursor;while(end<text.length && !/[()]/.test(text[end]) && !/^(?:\s+(?:and|or)\b|\s*(?:&&|\|\|))/.test(text.slice(end)))end++;
  while(end>cursor && /\s/.test(text[end-1]))end--;
  fragment=text.slice(start,cursor).trim();
 }
 const needle=normalizeSearch(fragment),out:Suggestion[]=[];
 const matches=(item:SearchItem)=>[item.label,...item.aliases||[]].some(v=>(item.kind==="Device"?deviceKey(v).includes(deviceKey(needle)):normalizeSearch(v).includes(needle)));
 let candidates=items;
 if(personCommands.includes(context))candidates=items.filter(i=>i.kind==="Person");
 else if(context==="place")candidates=items.filter(i=>i.kind==="Country"||i.kind==="City");
 else if(context==="phone")candidates=items.filter(i=>i.kind==="Device" && i.value!=="__all_phones__");
 else if(context==="album")candidates=items.filter(i=>i.kind==="Album");
 else if(context==="mediatype")candidates=["photo","video"].map(v=>({label:v,value:v,kind:"Media type"}));
 else if(context==="orientation")candidates=["portrait","landscape","square"].map(v=>({label:v,value:v,kind:"Orientation"}));
 else if(context==="location")candidates=[{label:"unknown",value:"unknown",kind:"Location"}];
 else if(["area","text"].includes(context))return [];
 const inArgument=!!context;
 if(!inArgument && quoteStart<0){const dates=dateSuggestions(text,cursor);if(dates!==null)return dates;}
 if(!inArgument && quoteStart<0){
  for(const phrase of datePhrases.filter(p=>p.startsWith(needle))){out.push({label:phrase,kind:"Date phrase",insert:phrase+" ",start,end});}
  for(const command of commands.filter(c=>c.toLowerCase().startsWith(needle))){
   const insert=command==="AllPhones"?"AllPhones()":command==="date"?'date >= ':text.slice(end).trimStart().startsWith("(")?command:command+'("")';
   out.push({label:command,kind:"Command",insert,start,end,caret:insert.endsWith('("")')?insert.length-2:insert.length});
  }
  if(!needle && before.trimEnd().endsWith(")"))return ["and","or","not"].map(op=>({label:op,kind:"Operator",insert:op+" ",start:cursor,end:cursor}));
 }
 const rank=(item:SearchItem)=>{const values=[item.label,...item.aliases||[]].map(normalizeSearch);return values.includes(needle)?0:values.some(v=>v.startsWith(needle))?1:2;};
 for(const item of candidates.filter(matches).sort((a,b)=>rank(a)-rank(b)||a.label.localeCompare(b.label))){
  const q=JSON.stringify(item.value);
  const insert=item.value==="__all_phones__"?"AllPhones()":inArgument?q:item.kind==="Person"?'Includes('+q+')':item.kind==="Country"||item.kind==="City"?'Place('+q+')':item.kind==="Media"?'MediaType('+q+')':item.kind==="Device"?'Phone('+q+')':'Album('+q+')';
  out.push({label:item.label,kind:item.kind,insert,start,end});
 }
 return out.slice(0,12);
}
export function acceptSuggestion(text:string,s:Suggestion){const value=text.slice(0,s.start)+s.insert+text.slice(s.end);return {value,cursor:s.start+(s.caret??s.insert.length)};}
