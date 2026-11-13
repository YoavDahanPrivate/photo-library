const {chromium}=require(process.argv[2]||'playwright');
const http=require('http'),fs=require('fs'),path=require('path'),assert=require('assert/strict');
const root=path.resolve(__dirname,'../frontend/dist');
const server=http.createServer((req,res)=>{const file=path.join(root,new URL(req.url,'http://local').pathname==='/'?'index.html':new URL(req.url,'http://local').pathname);try{res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(file));}catch{res.writeHead(404).end();}});
(async()=>{await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await chromium.launch({channel:'msedge',headless:true});try{
for(const viewport of [{width:1440,height:900},{width:1920,height:1080},{width:390,height:844}]){
 const page=await browser.newPage({viewport,reducedMotion:'reduce'});const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.clock.install();let job={id:'fixture',state:'completed',phase:'Matches ready for review',started_at:Date.now()/1000-60,finished_at:Date.now()/1000,updated_at:Date.now()/1000,result:{suggestions:1}};let offsetSeen=0;
 await page.route('**/api/**',async route=>{const u=new URL(route.request().url()),p=u.pathname;let json=[];
 if(p==='/api/auth/me')json={id:'qa',name:'QA',theme:'light',source_ids:null,source_names:null};
 else if(p==='/api/status')json={revision:1,total:240,counts:{ready:240},features:{}};
 else if(p==='/api/sync/status')json={running:false,runs:[]};
 else if(p==='/api/library/hierarchy')json={databases:[],sources:[],linked_sources:[]};
 else if(p==='/api/sources')json=[{phone:'Fixture',album:'Album',count:240}];
 else if(p==='/api/media'){const offset=Number(u.searchParams.get('offset')||0);offsetSeen=Math.max(offsetSeen,offset);json={total:240,items:Array.from({length:Math.min(80,240-offset)},(_,i)=>({id:'m'+(offset+i),name:'Photo '+i,phone:'Fixture',album:'Album',kind:'photo',taken:'2020-01-01',width:800,height:600,people_names:[]}))};}
 else if(p.includes('/thumbnail')){return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><rect width="800" height="600" fill="#abc"/></svg>'});}
 else if(p==='/api/people/operations/current')json=job;
 else if(p==='/api/people')json=[{id:1,name:'Maya',count:1}];
 else if(p==='/api/people/suggestions')json=[{face_id:'f',person_id:1,name:'Maya',score:.9,confidence:'high'}];
 else if(p==='/api/place-options')json={options:[]};
 else if(p.includes('/matching'))json={};
 await route.fulfill({json});});
 await page.goto('http://127.0.0.1:'+server.address().port);await page.locator('.media-tile').first().waitFor();await page.getByRole('button',{name:'Review matches',exact:true}).waitFor();
 await page.clock.runFor(29000);assert(await page.locator('.people-operation').isVisible());await page.clock.runFor(1400);assert.equal(await page.locator('.people-operation').count(),0);
 await page.evaluate(()=>{const el=document.querySelector('main.library-workspace-page');el.scrollTop=700;});await page.clock.runFor(100);
 assert(await page.locator('.master-search-header').evaluate(e=>e.getBoundingClientRect().bottom<100),'Search controls must scroll out');await page.getByRole('button',{name:'Back to search'}).waitFor();
 await page.screenshot({path:path.join(require('os').tmpdir(),`library-scroll-${viewport.width}.png`)});
 await page.evaluate(()=>{const el=document.querySelector('main.library-workspace-page');el.scrollTop=el.scrollHeight;el.dispatchEvent(new Event("scroll"));});await page.clock.runFor(200);await page.waitForFunction(()=>document.querySelectorAll('.media-tile').length>80);assert(offsetSeen>=80);
 await page.getByRole('button',{name:'Back to search'}).click();assert.equal(await page.locator('main.library-workspace-page').evaluate(e=>e.scrollTop),0);
 job={...job,id:'new-job'};await page.clock.runFor(5500);await page.getByRole('button',{name:'Review matches',exact:true}).click();await page.locator('.people-review-tools').waitFor();assert.equal(await page.locator('main.library-workspace-page').count(),0);
 await page.getByRole('button',{name:'Dismiss notification'}).click();assert.equal(await page.locator('.people-operation').count(),0);
 job={...job,id:'running',state:'running',processed:1,total:10};await page.clock.runFor(40000);assert(await page.locator('.people-operation').isVisible(),'Active work must remain visible');assert.deepEqual(errors,[]);console.log('PASS',viewport.width,'timer, polling, new notice, action, dismiss, ongoing progress, scroll, pagination, back to search');await page.close();
}
}finally{await browser.close();server.close();}})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
