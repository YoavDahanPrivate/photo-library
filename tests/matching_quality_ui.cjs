const {chromium}=require(process.argv[2]||'playwright');
const fs=require('fs'),path=require('path'),http=require('http'),assert=require('assert/strict');
const root=path.resolve(__dirname,'../frontend/dist');
const server=http.createServer((req,res)=>{const name=new URL(req.url,'http://localhost').pathname;const file=path.resolve(root,'.'+(name==='/'?'/index.html':name));if(!file.startsWith(root+path.sep)){res.writeHead(403).end();return;}try{res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(file));}catch{res.writeHead(404).end();}});
(async()=>{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1100}}),errors=[];page.on('pageerror',error=>errors.push(error.stack));
  let matches=Array.from({length:96},(_,index)=>({face_id:'match-'+index,person_id:index<60?1:2,name:index<60?'Maya':'Daniel',score:.65,margin:.10,support:2,score_cutoff:.7,margin_cutoff:.12,source_person_id:null,confidence:'lower',media_id:'photo-'+index,taken:'2020-01-'+String(1+Math.floor(index/15)).padStart(2,'0')}));
  let approved=[],job=null,starts=0,report=null,enabled=null,analyzes=0,rejections=0;
  await page.route('**/api/**',async route=>{
   const request=route.request(),url=new URL(request.url()),name=url.pathname;let value=[];
   if(name==='/api/people/suggestions')value=matches;
   else if(name==='/api/people/approve-suggestions'){
    const body=request.postDataJSON();approved.push(body.matches);const ids=new Set(body.matches.map(row=>row.face_id));matches=matches.filter(row=>!ids.has(row.face_id));value={approved:ids.size,ok:true};
   }else if(name==='/api/people/reject-suggestion'){
    const body=request.postDataJSON();assert.equal(body.face_id,'reject-this');assert.equal(body.person_id,1);rejections++;matches=matches.filter(row=>row.face_id!==body.face_id).map(row=>row.person_id===1?{...row,confidence:'lower'}:row);value={ok:true,learning_pending:true,confidence_invalidated_for:1};
   }else if(name==='/api/people/calibration')value={report,active_id:enabled};
   else if(name==='/api/people/calibration/apply'){
    assert.equal(request.postDataJSON().confirm,true);assert.equal(request.postDataJSON().profile_id,'fixture-profile');enabled='fixture-profile';value={ok:true};
   }else if(name==='/api/people/operations/calibrate'){
    analyzes++;job={id:'c'.repeat(32),kind:'calibrate',state:'running',phase:'Testing held-back photographs',processed:1,total:10,unit:'faces',started_at:Date.now()/1000,updated_at:Date.now()/1000};value=job;
    setTimeout(()=>{report={id:'fixture-profile',created:'2026-10-15',eligible_people:1,additional_validation_matches:20,tuning_faces:100,validation_faces:100,note:'Fixture: saved labels can contain mistakes.',people:[{person_id:1,name:'Maya',eligible:true,reference_photos:40,tuning_photos:30,validation_photos:30,proposed:{score:.6,margin:.08},baseline:{correct:10},validation:{correct:30,mistakes:0},reason:'Held-back improvement'}]};job={...job,state:'completed',phase:'Calibration ready to review',updated_at:Date.now()/1000,result:{profile_id:'fixture-profile'}};},100);
   }else if(name==='/api/people/operations/reevaluate'){starts++;job={id:'a'.repeat(32),kind:'reevaluate',state:'running',phase:'Comparing updated faces',processed:1,total:10,unit:'comparisons',started_at:Date.now()/1000,updated_at:Date.now()/1000};value=job;}
   else if(name==='/api/people/operations/current')value=job;
   else if(name==='/api/people')value=[{id:1,name:'Maya',count:2,cover:'a'},{id:2,name:'Daniel',count:1,cover:'b'}];
   else if(name==='/api/status')value={revision:0,total:1,counts:{ready:1},faces:96,features:{}};
   else if(name==='/api/sync/status')value={running:false,runs:[]};
   else if(name==='/api/library/hierarchy')value={databases:[],sources:[],linked_sources:[]};
   else if(name==='/api/sources')value=[{phone:'Fixture',album:'Album',count:1}];
   else if(name==='/api/media')value={items:[],total:0};
   else if(name==='/api/place-options')value={options:[]};
   else if(name.includes('thumbnail')){await route.fulfill({contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j5l8AAAAASUVORK5CYII=','base64')});return;}
   await route.fulfill({json:value});
  });
  await page.goto('http://127.0.0.1:'+server.address().port+'/');
  await page.locator('.sidebar nav').getByRole('button',{name:/^People/}).click();
  const lower=page.getByRole('region',{name:'Lower-confidence matches'});
  await lower.getByRole('button',{name:'Approve all 96',exact:true}).waitFor();
  await page.getByText('Matching rules: Conservative',{exact:true}).waitFor();
  await page.getByRole('checkbox',{name:'Refresh matches after reviewing'}).uncheck();
  await page.getByRole('combobox',{name:'Filter suggested person'}).selectOption('1');
  await lower.getByRole('button',{name:'Approve all 60',exact:true}).waitFor();
  await page.getByRole('combobox',{name:'Match review order'}).selectOption('dates');
  const cards=lower.locator('.suggestion-grid>div');assert.equal(await cards.count(),48);
  const dates=await cards.locator('small:not(.match-evidence)').allTextContents();assert.equal(new Set(dates.slice(0,4)).size,4);
  await lower.getByRole('button',{name:'Select this page (48)',exact:true}).click();
  const first=cards.first().getByRole('checkbox');await first.uncheck();
  await lower.getByRole('button',{name:/^Assign 47 selected matches/}).click();
  await lower.getByRole('button',{name:/^Assign 0 selected matches/}).waitFor();
  assert.equal(approved.length,1);assert.equal(approved[0].length,47);assert(approved[0].every(row=>row.person_id===1));
  assert.equal(starts,0,'Refresh was explicitly disabled');
  await page.locator('.matching-quality>summary').click();
  await page.getByRole('button',{name:'Analyze matching quality',exact:true}).click();
  await page.getByRole('button',{name:'Enable reviewed matching rules',exact:true}).waitFor({timeout:15000});
  assert.equal(analyzes,1);assert.equal(enabled,null);assert.equal(approved.length,1,'Analysis must not approve faces');
  await page.getByRole('button',{name:'Enable reviewed matching rules',exact:true}).click();
  await page.getByRole('button',{name:'Use conservative rules',exact:true}).waitFor();
  await page.getByText('Matching rules: Calibrated',{exact:true}).waitFor();
  assert.equal(enabled,'fixture-profile');assert.equal(approved.length,1);
  await page.waitForFunction(()=>document.querySelector('.people-operation')?.textContent.includes('Comparing updated faces'),{},{timeout:10000});
  assert.equal(starts,1,'Enabling matching rules must automatically reevaluate');
  job={...job,state:'completed',phase:'Matches ready for review',updated_at:Date.now()/1000,result:{suggestions:matches.length}};
  await page.waitForFunction(()=>{const checkbox=document.querySelector('.review-card-selection input');return checkbox&&!checkbox.disabled;},{},{timeout:15000});
  await page.getByRole('checkbox',{name:'Refresh matches after reviewing'}).check();
  await lower.locator('.suggestion-grid>div').first().getByRole('checkbox').check();
  await lower.getByRole('button',{name:/^Assign 1 selected matches/}).click();
  await page.waitForFunction(()=>document.querySelector('.people-operation')?.textContent.includes('Comparing updated faces'),{},{timeout:15000});
  assert.equal(starts,2);assert.equal(approved.length,2,'Background refresh must not approve anything');
  // A job started elsewhere can complete between polls. Its queue still needs refreshing.
  matches.push({face_id:'external',person_id:1,name:'Maya',score:.65,margin:.1,support:2,confidence:'lower',source_person_id:null});
  job={...job,id:'d'.repeat(32),state:'completed',phase:'Matches ready for review',updated_at:Date.now()/1000,result:{suggestions:matches.length}};
  await lower.getByRole('heading',{name:'Lower-confidence matches (13)',exact:true}).waitFor({timeout:15000});
  await page.getByRole('checkbox',{name:'Refresh matches after reviewing'}).uncheck();
  matches=[{face_id:'reject-this',person_id:1,name:'Maya',score:.8,margin:.2,support:2,confidence:'high',source_person_id:null},{face_id:'similar-maya',person_id:1,name:'Maya',score:.79,margin:.2,support:2,confidence:'high',source_person_id:null},{face_id:'other-daniel',person_id:2,name:'Daniel',score:.9,margin:.3,support:2,confidence:'high',source_person_id:null}];
  job={...job,id:'e'.repeat(32),result:{suggestions:matches.length}};
  await page.getByRole('combobox',{name:'Filter suggested person'}).selectOption('');
  const high=page.getByRole('region',{name:'High-confidence matches'});
  await high.getByRole('heading',{name:'High-confidence matches (3)',exact:true}).waitFor({timeout:15000});
  await high.locator('.suggestion-grid>div').filter({has:page.getByRole('checkbox',{name:'Select match reject-this',exact:true})}).getByRole('button',{name:'Not Maya',exact:true}).click();
  await page.getByText('Rejection saved. Reevaluate to apply it to similar faces.',{exact:false}).waitFor();
  await high.getByRole('heading',{name:'High-confidence matches (1)',exact:true}).waitFor();
  await lower.getByRole('heading',{name:'Lower-confidence matches (1)',exact:true}).waitFor();
  assert.equal(rejections,1);assert.equal(starts,2,'Refresh was disabled; the rejected face is not automatically assigned');
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Mobile layout overflow');
  assert.deepEqual(errors,[]);
  console.log('Matching quality: person filter, date variety, exact selected batch, report preview/enable, visible active rules, automatic reevaluation on enable, background/external-job refresh, rejection demotion/explanation and mobile layout passed');
 }finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error);process.exitCode=1;});
