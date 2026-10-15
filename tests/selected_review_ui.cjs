const {chromium}=require(process.argv[2]||'playwright');
const fs=require('fs'),path=require('path'),http=require('http'),assert=require('assert/strict');
const root=path.resolve(__dirname,'../frontend/dist'),output=process.env.DAHAN_QA_OUTPUT||require('os').tmpdir();fs.mkdirSync(output,{recursive:true});
const server=http.createServer((req,res)=>{const name=new URL(req.url,'http://localhost').pathname,file=path.resolve(root,'.'+(name==='/'?'/index.html':name));if(!file.startsWith(root+path.sep)){res.writeHead(403).end();return;}try{res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(file));}catch{res.writeHead(404).end();}});
(async()=>{await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',error=>errors.push(error.stack));
 const make=(id,person,confidence)=>({face_id:id,person_id:person,name:person===1?'Maya':'Daniel',confidence,score:confidence==='high'?.9:.65,source_person_id:3});
 let matches=[make('h0',1,'high'),make('h1',2,'high'),make('h2',1,'high'),...Array.from({length:60},(_,i)=>make('l'+i,1+i%2,'lower'))];
 const approvals=[],rejections=[];let failNext=false;
 await page.route('**/api/**',async route=>{
  const req=route.request(),url=new URL(req.url()),name=url.pathname;let value=[];
  if(name==='/api/people/suggestions')value=matches;
  else if(name==='/api/people/approve-suggestions'){const chosen=req.postDataJSON().matches;approvals.push(chosen);const ids=new Set(chosen.map(row=>row.face_id));matches=matches.filter(row=>!ids.has(row.face_id));value={approved:chosen.length,ok:true};}
  else if(name==='/api/people/reject-suggestions'){
   if(failNext){failNext=false;await route.fulfill({status:409,json:{detail:'Some matches changed or are unavailable. No changes made; refresh the matches before rejecting again.'}});return;}
   const chosen=req.postDataJSON().matches;rejections.push(chosen);const ids=new Set(chosen.map(row=>row.face_id)),people=new Set(chosen.map(row=>row.person_id));matches=matches.filter(row=>!ids.has(row.face_id)).map(row=>people.has(row.person_id)?{...row,confidence:'lower'}:row);value={rejected:chosen.length,ok:true,confidence_invalidated_for:[...people]};
  }else if(name==='/api/people/calibration')value={report:null,active_id:null,effective_mode:'conservative'};
  else if(name==='/api/people/operations/current')value=null;
  else if(name==='/api/people')value=[{id:1,name:'Maya',count:100,cover:'a'},{id:2,name:'Daniel',count:50,cover:'b'}];
  else if(name==='/api/status')value={revision:0,total:1,counts:{ready:1},faces:63,features:{}};
  else if(name==='/api/sync/status')value={running:false,runs:[]};
  else if(name==='/api/library/hierarchy')value={databases:[],sources:[],linked_sources:[]};
  else if(name==='/api/sources')value=[{phone:'Fixture',album:'Album',count:1}];
  else if(name==='/api/media')value={items:[],total:0};
  else if(name==='/api/place-options')value={options:[]};
  else if(name.includes('thumbnail')){await route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120"><rect width="120" height="120" fill="#e8eee0"/><ellipse cx="60" cy="48" rx="25" ry="30" fill="#afc5a6"/><path d="M15 120 Q15 78 60 78 Q105 78 105 120" fill="#7c9b73"/></svg>'});return;}
  else if(req.method()!=='GET')throw Error('Unexpected write '+name);
  await route.fulfill({json:value});
 });
 await page.goto('http://127.0.0.1:'+server.address().port+'/');await page.locator('.sidebar nav').getByRole('button',{name:/^People/}).click();await page.getByRole('checkbox',{name:'Refresh matches after reviewing'}).uncheck();
 const high=page.getByRole('region',{name:'High-confidence matches'}),lower=page.getByRole('region',{name:'Lower-confidence matches'});
 const assign=region=>region.locator('.selected-assign'),reject=region=>region.locator('.selected-reject');
 await assign(high).waitFor();assert(await assign(high).isDisabled());assert(await reject(high).isDisabled());assert(await assign(lower).isDisabled());assert(await reject(lower).isDisabled());
 for(const region of [high,lower])assert(await region.locator('.approval-actions').getByRole('button',{name:/Select this page/}).count()===1);
 await high.getByRole('checkbox',{name:'Select match h0',exact:true}).check();await lower.getByRole('checkbox',{name:'Select match l0',exact:true}).check();
 assert(!(await assign(high).isDisabled()));assert(!(await reject(high).isDisabled()));await assign(high).click();
 await high.getByRole('heading',{name:'High-confidence matches (2)',exact:true}).waitFor();assert.deepEqual(approvals[0],[{face_id:'h0',person_id:1,source_person_id:3}]);assert(await lower.getByRole('checkbox',{name:'Select match l0',exact:true}).isChecked());
 await high.getByRole('checkbox',{name:'Select match h1',exact:true}).check();await lower.getByRole('checkbox',{name:'Select match l1',exact:true}).check();await lower.getByRole('button',{name:'Last match page',exact:true}).click();await lower.getByRole('checkbox',{name:'Select match l59',exact:true}).check();
 assert.match(await reject(lower).getAttribute('aria-label'),/^Reject 3 selected matches for their suggested people$/);await reject(lower).click();
 await high.getByRole('heading',{name:'High-confidence matches (0)',exact:true}).waitFor();assert.deepEqual(rejections[0].map(row=>row.face_id).sort(),['l0','l1','l59']);assert(rejections[0].every(row=>row.source_person_id===3));assert.deepEqual([...new Set(rejections[0].map(row=>row.person_id))].sort(),[1,2]);
 assert.match(await assign(lower).getAttribute('aria-label'),/^Assign 1 selected matches to Daniel$/);await assign(lower).click();assert.deepEqual(approvals[1],[{face_id:'h1',person_id:2,source_person_id:3}]);await page.getByText('Saved 1 assignments.',{exact:false}).waitFor();
 await page.getByRole('button',{name:'Review by person',exact:true}).click();await page.getByRole('button',{name:'Review suggestions for Maya',exact:true}).click();await lower.getByRole('checkbox',{name:'Select match l2',exact:true}).check();assert.match(await assign(lower).textContent(),/Assign to Maya/);assert.match(await reject(lower).textContent(),/Not Maya/);
 await lower.getByRole('button',{name:'Expand lower-confidence review',exact:true}).click();await page.screenshot({path:path.join(output,'selected-review-desktop.png')});
 await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await page.screenshot({path:path.join(output,'selected-review-mobile.png')});
 await reject(lower).click();await page.getByText('Rejected 1 suggested matches.',{exact:false}).waitFor();assert.deepEqual(rejections[1],[{face_id:'l2',person_id:1,source_person_id:3}]);assert(await assign(lower).isDisabled());assert(await reject(lower).isDisabled());
 await lower.getByRole('checkbox',{name:'Select match l4',exact:true}).check();failNext=true;await reject(lower).click();await page.getByText('Some matches changed or are unavailable.',{exact:false}).waitFor();assert.equal(rejections.length,2);assert.equal(approvals.length,2);assert(matches.some(row=>row.face_id==='l4'));assert.deepEqual(errors,[]);
 console.log('Selected review: disabled/active controls in both panels, adjacent page selection, independent confidence selections, cross-page mixed-person rejection, named-person actions, high-flag demotion, stale batch recovery and mobile passed');
 }finally{await browser.close();await new Promise(resolve=>server.close(resolve));}})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
