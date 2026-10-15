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
  const page=await browser.newPage({viewport:{width:1440,height:1050}});const errors=[];page.on('pageerror',e=>errors.push(e.stack));
  let matches=Array.from({length:5000},(_,i)=>({face_id:'batch-'+i,person_id:1+i%2,name:i%2?'Daniel':'Maya',score:.9,margin:.3,source_person_id:3,confidence:'high'}));
  matches.push({face_id:'lower',person_id:1,name:'Maya',score:.6,margin:.1,source_person_id:null,confidence:'lower'});
  let bulk=0,singles=0,starts=0,cancels=0,job=null,failProgress=false;
  await page.route('**/api/**',async route=>{
   const request=route.request(),url=new URL(request.url()),pathname=url.pathname;let json=[];
   if(pathname==='/api/people/approve-suggestions'){
    bulk++;const body=request.postDataJSON();assert.equal(body.matches.length,5000);assert(body.matches.every(m=>m.source_person_id===3&&m.face_id!=='lower'));
    await pause(2300);matches=matches.filter(m=>m.confidence==='lower');json={ok:true,approved:5000};
   }else if(pathname==='/api/faces/correct'){singles++;json={ok:true};}
   else if(pathname==='/api/people/operations/reevaluate'){
    starts++;job={id:(starts===1?'a':'b').repeat(32),state:'running',phase:'Comparing faces',processed:250,total:1000,unit:'comparisons',started_at:Date.now()/1000,updated_at:Date.now()/1000};json=job;
   }else if(pathname==='/api/people/operations/current'){
    if(failProgress){await route.fulfill({status:503,json:{detail:'Fixture progress connection unavailable'}});return;}
    json=job;
   }else if(pathname.endsWith('/cancel')){cancels++;job={...job,state:'cancelled',phase:'Reevaluation stopped',finished_at:Date.now()/1000,updated_at:Date.now()/1000};json=job;}
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
  assert.equal(await high.locator('.suggestion-grid>div').count(),48);
  assert((await page.locator('*').count())<3000,'Review DOM should stay bounded');
  await high.getByRole('button',{name:'Last match page'}).click();
  await high.getByText('4,993–5,000 of 5,000 matches').waitFor();
  assert.equal(await high.locator('.suggestion-grid>div').count(),8);
  await high.getByRole('button',{name:'First match page'}).click();
  await page.evaluate(()=>{window.testBeats=0;window.testTimer=setInterval(()=>window.testBeats++,20);});
  await high.getByRole('button',{name:'Approve all 5000',exact:true}).click();
  await page.getByRole('progressbar',{name:'Saving assignments'}).waitFor();
  assert.equal(await page.getByRole('progressbar',{name:'Saving assignments'}).getAttribute('value'),null);
  await page.getByText('1s elapsed',{exact:true}).waitFor();
  await page.screenshot({path:path.join(output,'people-approval-progress.png')});
  await page.getByText('Saved 5,000 assignments.',{exact:false}).waitFor();
  assert.equal(bulk,1);assert.equal(singles,0);assert.equal(starts,0);
  assert((await page.evaluate(()=>window.testBeats))>30,'Page event loop must remain alive while approving');
  console.log('5000 matches: 48 cards per page; all pages reachable; one full-selection approval; animated elapsed progress; event loop responsive');
  await page.getByRole('button',{name:'Reevaluate unassigned faces',exact:true}).click();
  const bar=page.getByRole('progressbar',{name:'Reevaluation progress'});
  await bar.waitFor();assert.equal(await bar.getAttribute('value'),'25');
  await page.getByText('25% · 250 of 1,000 comparisons in this phase').waitFor();
  await page.screenshot({path:path.join(output,'people-reevaluation-progress.png')});
  await page.locator('.sidebar nav').getByRole('button',{name:'Library',exact:true}).click();
  await bar.waitFor();
  await page.reload();await bar.waitFor();assert.equal(await bar.getAttribute('value'),'25');
  await page.setViewportSize({width:390,height:844});
  assert((await page.locator('body').evaluate(e=>e.scrollWidth))<=390,'Progress must fit mobile viewport');
  await page.screenshot({path:path.join(output,'people-progress-mobile.png')});
  await page.setViewportSize({width:1440,height:1050});
  failProgress=true;
  await page.getByText('Reconnecting to progress…',{exact:false}).waitFor({timeout:10000});
  failProgress=false;
  await page.getByRole('button',{name:'Stop reevaluation',exact:true}).click();
  await page.getByText('Reevaluation stopped',{exact:true}).waitFor({timeout:10000});
  assert.equal(cancels,1);
  console.log('Reevaluation: measured percentage, browse while working, reload recovery, offline progress warning, mobile layout and cancellation passed');
  await page.locator('.sidebar nav').getByRole('button',{name:/^People/}).click();
  await page.getByRole('button',{name:'Reevaluate unassigned faces',exact:true}).click();
  job={...job,state:'completed',phase:'Matches ready for review',result:{evaluated:10,suggestions:1,saved_people:2},finished_at:Date.now()/1000,updated_at:Date.now()/1000};
  matches=[{face_id:'new',person_id:1,name:'Maya',score:.9,source_person_id:null,confidence:'high'}];
  await high.getByRole('heading',{name:'High-confidence matches (1)',exact:true}).waitFor({timeout:10000});
  assert.equal(starts,2);assert.deepEqual(errors,[]);
  console.log('Completed worker refreshes suggestions once; no browser errors');
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
