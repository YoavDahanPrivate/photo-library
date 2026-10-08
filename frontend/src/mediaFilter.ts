export type MediaKind = '' | 'photo' | 'video' | 'custom';
type Node = {op:'and'|'or',left:Node,right:Node}|{op:'not',child:Node}|{op:'leaf',text:string};
function parse(text:string):Node {
 const tokens=text.match(/"(?:[^"\\]|\\.)*"|&&|\|\||[()]|[^\s()]+/g)||[];
 function tree(ts:string[]):Node {
  if(ts[0]==='('){let d=0,end=-1;for(let i=0;i<ts.length;i++){if(ts[i]==='(')d++;if(ts[i]===')')d--;if(d===0){end=i;break;}}if(end===ts.length-1)return tree(ts.slice(1,-1));}
  let depth=0,between=false;const and:number[]=[],or:number[]=[];
  ts.forEach((t,i)=>{const k=t.toLowerCase();if(t==='(')depth++;else if(t===')')depth--;else if(depth===0){if(k==='between')between=true;else if(k==='to'&&between)between=false;else if(k==='and'||k==='&&'){if(between)between=false;else and.push(i);}else if((k==='or'||k==='||')&&!(ts[i-1]?.toLowerCase()==='on'&&['after','before'].includes(ts[i+1]?.toLowerCase())))or.push(i);}});
  const split=or.at(-1)??and.at(-1);if(split!==undefined)return {op:or.length?'or':'and',left:tree(ts.slice(0,split)),right:tree(ts.slice(split+1))};
  if(ts[0]?.toLowerCase()==='not')return {op:'not',child:tree(ts.slice(1))};
  return {op:'leaf',text:ts.join(' ')};
 }
 return tree(tokens);
}
function media(n:Node):'photo'|'video'|null {
 if(n.op!=='leaf')return null;
 const s=n.text.toLowerCase();const match=s.match(/^mediatype\s*\(\s*"?(photo|video)"?\s*\)$/);
 if(match)return match[1] as 'photo'|'video';
 if(/^(only )?(photos?|images?)( only)?$/.test(s))return 'photo';
 if(/^(only )?videos?( only)?$/.test(s))return 'video';return null;
}
function strip(n:Node):string {
 if(media(n))return '';
 if(n.op==='leaf')return n.text;
 if(n.op==='not'){const c=strip(n.child);return c?'not ('+c+')':'';}
 const l=strip(n.left),r=strip(n.right);return l&&r?'('+l+' '+n.op+' '+r+')':l||r;
}
export function withMediaFilter(expression:string,kind:string):string {
 const rest=strip(parse(expression));const clause=kind?'MediaType('+JSON.stringify(kind)+')':'';
 return [rest,clause].filter(Boolean).map(s=>'('+s+')').join(' and ');
}
export function selectedMediaFilter(expression:string):MediaKind {
 const root=parse(expression);
 function allowed(n:Node,kind:string):number { // bit 1: may be false; bit 2: may be true
  const m=media(n);if(m)return m===kind?2:1;
  if(n.op==='leaf')return 3;
  if(n.op==='not'){const a=allowed(n.child,kind);return ((a&1)?2:0)|((a&2)?1:0);}
  const a=allowed(n.left,kind),b=allowed(n.right,kind);let out=0;
  for(const x of [false,true])for(const y of [false,true])if((a&(x?2:1))&&(b&(y?2:1)))out|=(n.op==='and'?x&&y:x||y)?2:1;
  return out;
 }
 const p=!!(allowed(root,'photo')&2),v=!!(allowed(root,'video')&2);
 if(p&&!v)return 'photo';if(v&&!p)return 'video';
 return strip(root)!==rootText(root)&&expression.trim()?'custom':'';
}
function rootText(n:Node):string {if(n.op==='leaf')return n.text;if(n.op==='not')return 'not ('+rootText(n.child)+')';return '('+rootText(n.left)+' '+n.op+' '+rootText(n.right)+')';}
