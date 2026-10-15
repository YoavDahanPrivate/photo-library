const {chromium}=require(process.argv[2]||'playwright');
const fs=require('fs'),path=require('path'),http=require('http'),assert=require('assert/strict');
const root=path.resolve(__dirname,'../frontend/dist'),output=process.env.DAHAN_QA_OUTPUT||require('os').tmpdir();fs.mkdirSync(output,{recursive:true});
const server=http.createServer((req,res)=>{const name=new URL(req.url,'http://localhost').pathname,file=path.resolve(root,'.'+(name==='/'?'/index.html':name));if(!file.startsWith(root+path.sep)){res.writeHead(403).end();return;}try{res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(file));}catch{res.writeHead(404).end();}});
(async()=>{await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',error=>errors.push(error.stack));
 const people=[{id:1,name:'Zoe',count:100,cover:'a'},{id:2,name:'Anna',count:50,cover:'b'},{id:3,name:'No pending',count:200,cover:'c'},...Array.from({length:26},(_,i)=>({id:i+4,name:'Person '+String(i).padStart(2,'0'),count:26-i,cover:'d'}))];
 let matches=[...Array.from({length:60},(_,i)=>({face_id:'zoe-'+i,person_id:1,name:'Zoe',score:.65,confidence:'lower',source_person_id:null})),{face_id:'anna-high',person_id:2,name:'Anna',score:.9,confidence:'high',source_person_id:null},{face_id:'anna-low',person_id:2,name:'Anna',score:.65,confidence:'lower',source_person_id:null},...people.slice(3).map(row=>({face_id:'other-'+row.id,person_id:row.id,name:row.name,score:.65,confidence:'lower',source_person_id:null}))];
 let writes=[],groupQueries=[],job=null,restarts=0;
 await page.route('**/api/**',async route=>{
  const req=route.request(),url=new URL(req.url()),name=url.pathname;let value=[];
  if(name==='/api/people/suggestions')value=matches;
  else if(name==='/api/people/approve-suggestions'){const selected=req.postDataJSON().matches;writes.push(selected);assert(selected.every(row=>row.person_id===1));const ids=new Set(selected.map(row=>row.face_id));matches=matches.filter(row=>!ids.has(row.face_id));value={ok:true,approved:selected.length};}
  else if(name==='/api/people/review-groups'){groupQueries.push(url.searchParams.get('person_id'));value={groups:[],total_groups:0,grouped_faces:0,total_faces:0,individual_faces:0,analyzed_faces:0,offset:0,limit:4};}
  else if(name==='/api/people/calibration')value={report:null,active_id:null,effective_mode:'conservative'};
  else if(name==='/api/people/operations/current')value=job;
  else if(name==='/api/people/operations/reevaluate'){restarts++;job={id:'e'.repeat(32),kind:'reevaluate',state:'running',phase:'Comparing updated faces',started_at:Date.now()/1000,updated_at:Date.now()/1000,processed:0,total:10};value=job;}
  else if(name==='/api/people')value=people;
  else if(name==='/api/status')value={revision:0,total:1,counts:{ready:1},faces:88,features:{}};
  else if(name==='/api/sync/status')value={running:false,runs:[]};
  else if(name==='/api/library/hierarchy')value={databases:[],sources:[],linked_sources:[]};
  else if(name==='/api/sources')value=[{phone:'Fixture',album:'Album',count:1}];
  else if(name==='/api/media')value={items:[],total:0};
  else if(name==='/api/place-options')value={options:[]};
  else if(name.includes('thumbnail')){await route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120"><rect width="120" height="120" fill="#e8eee0"/><ellipse cx="60" cy="48" rx="25" ry="30" fill="#afc5a6"/><path d="M15 120 Q15 78 60 78 Q105 78 105 120" fill="#7c9b73"/></svg>'});return;}
  else if(req.method()!=='GET')throw Error('Unexpected API write '+name);
  await route.fulfill({json:value});
 });
 await page.goto('http://127.0.0.1:'+server.address().port+'/');await page.locator('.sidebar nav').getByRole('button',{name:/^People/}).click();
 await page.getByRole('checkbox',{name:'Refresh matches after reviewing'}).uncheck();
 await page.getByRole('button',{name:'Review by person',exact:true}).click();
 const chooser=page.getByRole('region',{name:'Review by person',exact:true}),cards=chooser.locator('.person-review-card');
 await cards.first().waitFor();assert.equal(await cards.count(),24);assert.match(await cards.first().textContent(),/Zoe/);assert.match(await cards.nth(1).textContent(),/Anna/);
 await chooser.getByRole('button',{name:'Last people page',exact:true}).click();assert.equal(await cards.count(),4);await chooser.getByRole('button',{name:'First people page',exact:true}).click();
 await chooser.getByRole('checkbox',{name:'Only people with suggestions'}).uncheck();assert.match(await cards.first().textContent(),/No pending/);await chooser.getByRole('button',{name:'Review suggestions for No pending',exact:true}).click();await chooser.getByText('You’ve reviewed all current suggestions',{exact:false}).waitFor();assert.equal(writes.length,0);
 await chooser.getByRole('button',{name:'Choose another person',exact:true}).click();await chooser.getByRole('checkbox',{name:'Only people with suggestions'}).check();
 await chooser.getByRole('searchbox',{name:'Find a person to review'}).fill('zo');assert.equal(await cards.count(),1);await chooser.getByRole('searchbox',{name:'Find a person to review'}).fill('no such name');await chooser.getByText('No people match this search.',{exact:true}).waitFor();await chooser.getByRole('searchbox',{name:'Find a person to review'}).fill('');
 await page.screenshot({path:path.join(output,'person-review-chooser-desktop.png')});
 await chooser.getByRole('button',{name:'Review suggestions for Zoe',exact:true}).click();
 const lower=page.getByRole('region',{name:'Lower-confidence matches'});await lower.getByRole('heading',{name:'Lower-confidence matches (60)',exact:true}).waitFor();assert.equal(await lower.locator('.suggestion-grid>div').count(),48);assert.equal(await page.getByRole('button',{name:'Not Anna',exact:true}).count(),0);assert.equal(await page.getByRole('button',{name:'Auto approve high-confidence',exact:true}).count(),0);
 await page.getByRole('button',{name:'Try grouped review',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.grouped-review-body')?.textContent.includes('No cohesive groups'));assert.deepEqual(groupQueries,['1']);
 await lower.getByRole('button',{name:'Select this page (48)',exact:true}).click();await chooser.getByRole('button',{name:'Next person · Anna',exact:true}).click();await lower.getByRole('button',{name:/^Assign 0 selected matches/}).waitFor();await lower.getByRole('heading',{name:'Lower-confidence matches (1)',exact:true}).waitFor();
 await chooser.getByRole('button',{name:'Choose another person',exact:true}).click();await chooser.getByRole('button',{name:'Review suggestions for Zoe',exact:true}).click();await lower.getByRole('button',{name:'Expand lower-confidence review',exact:true}).click();await page.locator('.review-workspace-header').waitFor();assert(await chooser.isVisible());await page.screenshot({path:path.join(output,'person-review-expanded-desktop.png')});
 await lower.getByRole('button',{name:'Select this page (48)',exact:true}).click();await lower.getByRole('button',{name:/^Assign 48 selected matches/}).click();await page.locator('.review-confidence-switch').getByRole('button',{name:/Lower-confidence.*12/}).waitFor();assert.equal(writes.length,1);assert.equal(writes[0].length,48);
 await lower.getByRole('button',{name:'Approve all 12',exact:true}).click();await chooser.getByText('You’ve reviewed all current suggestions',{exact:false}).waitFor();assert.equal(writes.length,2);assert.equal(writes[1].length,12);assert.equal(matches.filter(row=>row.person_id===2).length,2,'Other people untouched');assert.match(await chooser.locator('h3').textContent(),/Zoe/,'No silent person change');
 await chooser.getByRole('button',{name:'Choose another person',exact:true}).click();await page.setViewportSize({width:390,height:844});await page.waitForTimeout(100);assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await page.screenshot({path:path.join(output,'person-review-chooser-mobile.png')});
 await chooser.getByRole('button',{name:'Review suggestions for Anna',exact:true}).click();assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await page.screenshot({path:path.join(output,'person-review-selected-mobile.png')});
 await page.getByRole('button',{name:'Catalogue review',exact:true}).click();assert.equal(await chooser.count(),0);await lower.getByRole('heading',{name:'Lower-confidence matches (27)',exact:true}).waitFor();assert.equal(await page.getByRole('combobox',{name:'Filter suggested person'}).inputValue(),'');assert.deepEqual(errors,[]);
 // Reproduce an empty backend queue and failed operation, rather than hiding existing rows.
 matches=[];job={id:'f'.repeat(32),kind:'reevaluate',state:'failed',phase:'Reevaluation stopped',error:'Face corrections changed during matching. Please retry.',started_at:Date.now()/1000,updated_at:Date.now()/1000,finished_at:Date.now()/1000,processed:null,total:null};
 await page.reload();await page.locator('.mobile-nav').getByRole('button',{name:'People',exact:true}).click();
 await page.getByText('Matching stopped before the suggestions could be refreshed.',{exact:false}).waitFor();await page.getByRole('button',{name:'Reevaluate matches',exact:true}).waitFor();
 await page.getByRole('button',{name:'Review by person',exact:true}).click();await chooser.getByText('No people currently have suggestions to review.',{exact:false}).waitFor();assert(await page.getByRole('button',{name:'Reevaluate unassigned faces',exact:true}).isVisible());
 await page.screenshot({path:path.join(output,'person-review-empty-recovery-mobile.png')});
 await page.getByRole('button',{name:'Reevaluate matches',exact:true}).click();assert.equal(restarts,1);assert.equal(writes.length,2);
 matches=[{face_id:'recovered',person_id:1,name:'Zoe',score:.65,confidence:'lower',source_person_id:null}];job={...job,state:'completed',phase:'Matches ready for review',updated_at:Date.now()/1000,finished_at:Date.now()/1000,result:{suggestions:1,assigned:0}};
 await chooser.getByRole('button',{name:'Review suggestions for Zoe',exact:true}).waitFor({timeout:15000});assert.equal(writes.length,2,'Recovery must not approve anything');assert.deepEqual(errors,[]);
 console.log('Empty queue recovery in both modes: actionable failed job, explicit reevaluation, refreshed person list and zero extra assignments passed');
 console.log('Person review: ranking, search, all people pages, empty/completed states, selected-person groups, cross-person selection clearing, exact scoped approvals across match pages, expanded review, catalogue return and mobile passed');
 }finally{await browser.close();await new Promise(resolve=>server.close(resolve));}})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
