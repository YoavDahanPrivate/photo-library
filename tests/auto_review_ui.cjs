const {chromium}=require(process.argv[2]||'playwright');
const fs=require('fs'),path=require('path'),http=require('http'),assert=require('assert/strict');
const root=path.resolve(__dirname,'../frontend/dist');
const output=process.env.DAHAN_QA_OUTPUT?path.resolve(process.env.DAHAN_QA_OUTPUT):fs.mkdtempSync(path.join(require('os').tmpdir(),'dahan-review-'));
fs.mkdirSync(output,{recursive:true});
const server=http.createServer((req,res)=>{
 const name=new URL(req.url,'http://localhost').pathname;
 const file=path.resolve(root,'.'+(name==='/'?'/index.html':name));
 if(!file.startsWith(root+path.sep)){res.writeHead(403).end();return;}
 try{res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':file.endsWith('.json')?'application/json':'text/html');res.end(fs.readFileSync(file));}catch{res.writeHead(404).end();}
});
const pause=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1050}}); const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.stack));
  let matches=Array.from({length:5000},(_,i)=>({face_id:'batch-'+i,person_id:1+i%2,name:i%2?'Daniel':'Maya',score:.9,margin:.3,source_person_id:3,confidence:'high'}));
  matches.push({face_id:'lower',person_id:1,name:'Maya',score:.6,margin:.1,source_person_id:null,confidence:'lower'});
  let bulk=0,singles=0,starts=0,cancels=0,autoStarts=0,job=null,failProgress=false;
  await page.context().route('**/api/**',async route=>{
   const request=route.request(),url=new URL(request.url()),pathname=url.pathname;let json=[];
   if(pathname==='/api/people/approve-suggestions'){
    bulk++;const body=request.postDataJSON();assert.equal(body.matches.length,5000);assert(body.matches.every(m=>m.source_person_id===3&&m.face_id!=='lower'));
    await pause(2300);matches=matches.filter(m=>m.confidence==='lower');json={ok:true,approved:5000};
   }else if(pathname==='/api/people/operations/auto-approve'){
    autoStarts++;job={id:(autoStarts===1?'c':'d').repeat(32),kind:'auto-approve',state:'running',phase:'Approving high-confidence matches',round:1,rounds_completed:0,approved_total:0,review_revision:0,processed:0,total:matches.filter(m=>m.confidence==='high').length,unit:'matches',started_at:Date.now()/1000,updated_at:Date.now()/1000};json=job;
   }else if(pathname==='/api/faces/correct'){singles++;json={ok:true};}
   else if(pathname==='/api/people/operations/reevaluate'){
    starts++;job={id:(starts===1?'a':'b').repeat(32),state:'running',phase:'Comparing faces',processed:250,total:1000,unit:'comparisons',started_at:Date.now()/1000,updated_at:Date.now()/1000};json=job;
   }else if(pathname==='/api/people/operations/current'){
    if(failProgress){await route.fulfill({status:503,json:{detail:'Fixture progress connection unavailable'}});return;}
    json=job;
   }else if(pathname.endsWith('/cancel')){cancels++;job={...job,stop_requested:true};json=job;}
   else if(pathname==='/api/people/suggestions')json=matches;
   else if(pathname==='/api/people')json=[{id:1,name:'Maya',count:2,cover:'a'},{id:2,name:'Daniel',count:1,cover:'b'}];
   else if(pathname==='/api/status')json={revision:0,total:1,counts:{ready:1},faces:5000,features:{}};
   else if(pathname==='/api/sync/status')json={running:false,runs:[]};
   else if(pathname==='/api/library/hierarchy')json={databases:[],sources:[],linked_sources:[]};
   else if(pathname==='/api/sources')json=[{phone:'Fixture',album:'Album',count:1}];
   else if(pathname==='/api/media')json={items:[],total:0};
   else if(pathname==='/api/place-options')json={options:[]};
   else if(pathname.includes('thumbnail')){await route.fulfill({contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j5l8AAAAASUVORK5CYII=','base64')});return;}
   await route.fulfill({json});
  });
  await page.goto('http://127.0.0.1:'+server.address().port+'/');
  await page.locator('.sidebar nav').getByRole('button',{name:/^People/}).click();
  const high=page.getByRole('region',{name:'High-confidence matches'});
  await high.getByRole('button',{name:'Approve all 5000',exact:true}).waitFor();

  const auto=high.getByRole('button',{name:'Auto approve high-confidence',exact:true});
  await auto.waitFor();assert.equal(await auto.isEnabled(),true);
  assert.equal(await page.getByRole('region',{name:'Lower-confidence matches'}).getByRole('button',{name:'Auto approve high-confidence',exact:true}).count(),0);
  await page.screenshot({path:path.join(output,'auto-approve-button.png')});
  await auto.click();
  await page.getByRole('button',{name:'Stop automatic approval',exact:true}).waitFor();
  assert.equal(autoStarts,1);assert.equal(bulk,0);assert.equal(starts,0);
  job={...job,approved_total:5000,rounds_completed:1,review_revision:1,phase:'Comparing faces',processed:250,total:1000,unit:'comparisons',updated_at:Date.now()/1000};
  matches=matches.filter(m=>m.confidence==='lower');
  await page.getByText('5,000 approved',{exact:true}).waitFor({timeout:10000});
  await high.getByRole('heading',{name:'High-confidence matches (0)',exact:true}).waitFor();
  assert.equal(await page.getByRole('progressbar',{name:'Automatic approval progress'}).getAttribute('value'),'25');
  const lower=matches[0];
  job={...job,round:2,review_revision:2,phase:'Approving high-confidence matches',processed:0,total:300,unit:'matches',updated_at:Date.now()/1000};
  matches=[...Array.from({length:300},(_,i)=>({face_id:'next-'+i,person_id:1,name:'Maya',score:.9,source_person_id:null,confidence:'high'})),lower];
  await high.getByRole('heading',{name:'High-confidence matches (300)',exact:true}).waitFor({timeout:10000});
  assert.equal(await high.locator('.suggestion-grid>div').count(),48);
  assert.equal(await auto.isDisabled(),true);
  job={...job,approved_total:5300,rounds_completed:2,review_revision:3,phase:'Comparing faces',processed:400,total:1000,unit:'comparisons',updated_at:Date.now()/1000};
  matches=[lower];
  await page.getByText('5,300 approved',{exact:true}).waitFor({timeout:10000});
  await page.screenshot({path:path.join(output,'auto-approval-running.png')});
  await page.reload();await page.getByText('5,300 approved',{exact:true}).waitFor();
  await page.setViewportSize({width:390,height:844});
  assert((await page.locator('body').evaluate(e=>e.scrollWidth))<=390);
  await page.screenshot({path:path.join(output,'auto-approval-mobile.png')});
  await page.setViewportSize({width:1440,height:1050});
  const observer=await page.context().newPage(); await observer.goto('http://127.0.0.1:'+server.address().port+'/'); await observer.getByText('5,300 approved',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Stop automatic approval',exact:true}).click();
  await observer.getByRole('button',{name:'Stopping…',exact:true}).waitFor({timeout:10000}); await observer.close();
  await page.getByRole('button',{name:'Stopping…',exact:true}).waitFor();
  await page.reload();await page.getByRole('button',{name:'Stopping…',exact:true}).waitFor();
  assert.equal(await page.getByRole('button',{name:'Stopping…',exact:true}).isDisabled(),true);
  job={...job,state:'cancelled',phase:'Auto approval stopped',processed:null,total:null,finished_at:Date.now()/1000,updated_at:Date.now()/1000};
  await page.getByText('Auto approval stopped',{exact:true}).waitFor({timeout:10000});
  await page.getByText('5,300 approved',{exact:true}).waitFor();
  assert.equal(cancels,1);
  console.log('Auto approval: rounds and totals update live, queue refreshes between rounds, lower matches stay manual, reload and Stop state survive, mobile fits');
  matches=[{face_id:'fresh',person_id:1,name:'Maya',score:.9,source_person_id:null,confidence:'high'},lower];
  await page.locator('.sidebar nav').getByRole('button',{name:/^People/}).click();
  await high.getByRole('heading',{name:'High-confidence matches (1)',exact:true}).waitFor();
  await auto.click();await page.getByText('0 approved',{exact:true}).waitFor();
  job={...job,state:'completed',phase:'Auto approval finished',approved_total:1,rounds_completed:1,review_revision:2,result:{approved:1,rounds:1,stop_reason:'no-high-confidence'},finished_at:Date.now()/1000,updated_at:Date.now()/1000};matches=[lower];
  await page.getByText('Auto approval finished',{exact:true}).waitFor({timeout:10000});
  await page.getByText('No more high-confidence matches remain in the visible library.',{exact:false}).waitFor();
  await high.getByRole('heading',{name:'High-confidence matches (0)',exact:true}).waitFor();
  assert.equal(autoStarts,2);assert.equal(bulk,0);assert.equal(singles,0);assert.deepEqual(errors,[]);
  console.log('Completed auto loop reports its result and stops; one-shot manual approval endpoints were never called by the browser');
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
