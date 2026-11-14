const {chromium}=require(process.argv[2]||process.env.PLAYWRIGHT_MODULE||'playwright');
const http=require('http'),fs=require('fs'),path=require('path'),assert=require('assert/strict');
const artifactDir=fs.mkdtempSync(path.join(require('os').tmpdir(),'dahan-ui-'));const root=path.join(__dirname,'../frontend/dist');
const server=http.createServer((req,res)=>{const file=path.join(root,new URL(req.url,'http://local').pathname==='/'?'index.html':new URL(req.url,'http://local').pathname);try{res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(file));}catch{res.writeHead(404).end();}});
(async()=>{await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await chromium.launch({channel:'msedge',headless:true});try{
for(const viewport of [{width:1440,height:900},{width:390,height:844},{width:320,height:640}]){
 const page=await browser.newPage({viewport,reducedMotion:'reduce',hasTouch:viewport.width<=760,isMobile:viewport.width<=760});const errors=[];page.setDefaultTimeout(7000);page.on('pageerror',e=>{errors.push(e.message);console.log('PAGE ERROR',e.stack)});await page.clock.install();let job={id:'fixture',state:'completed',phase:'Matches ready for review',started_at:Date.now()/1000-60,finished_at:Date.now()/1000,updated_at:Date.now()/1000,result:{suggestions:1}};let releaseMedia;const mediaGate=new Promise(resolve=>releaseMedia=resolve);let releaseNeighbors;const neighborsGate=new Promise(resolve=>releaseNeighbors=resolve);let releaseDetail;const detailGate=new Promise(resolve=>releaseDetail=resolve);let offsetSeen=0;const imageRequests=[];
 let identity='qa';const accounts={qa:null,other:null};
 await page.route('**/api/**',async route=>{const u=new URL(route.request().url()),p=u.pathname;let json=[];
 if(p.endsWith('/people-preferences')&&route.request().method()==='PUT'){assert(!('selection' in route.request().postDataJSON()),'Selection must never be sent to the database');accounts[identity]=route.request().postDataJSON();json={people_browse:accounts[identity]};}
 else if(p==='/api/auth/me')json={people_browse:accounts[identity],id:identity,name:'QA',theme:'light',source_ids:null,source_names:null};
 else if(p==='/api/status')json={revision:1,total:240,counts:{ready:240},features:{}};
 else if(p==='/api/sync/status')json={running:false,runs:[],settings:{frequency:'daily',time:'02:00',weekday:0,month_day:1,timezone:'Asia/Jerusalem',auto_assign:false},next_due:null};
 else if(p==='/api/duplicates/status')json={jobs:[],reviews:[],trash_count:0};
 else if(p==='/api/sync/assignments')json={faces:[],actions:[]};
 else if(p==='/api/library/hierarchy')json={databases:[],sources:[],linked_sources:[]};
 else if(p==='/api/sources')json=[{phone:'Fixture',album:'Album',count:240},{phone:'Other phone',album:'Album',count:2}];
 else if(p==='/api/search/validate')json={valid:true};
 else if(p==='/api/media'){await mediaGate;const offset=Number(u.searchParams.get('offset')||0);offsetSeen=Math.max(offsetSeen,offset);json={total:240,items:Array.from({length:Math.min(Number(u.searchParams.get("limit")||80),240-offset)},(_,i)=>({id:'m'+(offset+i),name:'Photo '+i,phone:'Fixture',album:'Album',kind:offset+i===81?'video':'photo',taken:'2020-01-01',width:800,height:600,people_names:[]}))};}
 else if(/^\/api\/media\/m\d+\/neighbors$/.test(p)){const n=Number(p.split('/')[3].slice(1));const rows=Array.from({length:5},(_,i)=>Math.max(0,n-2)+i).filter(i=>i<240).map(i=>({id:'m'+i,previous:i?'m'+(i-1):null,next:i<239?'m'+(i+1):null,position:i+1,total:240}));json={...rows.find(r=>r.id==='m'+n),window:rows};}
 else if(/^\/api\/media\/m\d+$/.test(p)){const id=p.split('/')[3];json={id,name:'Photo '+id,phone:'Fixture',album:'Album',kind:id==='m81'?'video':'photo',taken:'2020-01-01',width:800,height:600,people_names:[],faces:[],metadata:{},duration:null,latitude:null,longitude:null};}
 else if(p.endsWith('/display-original')){imageRequests.push(u.href);return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1200"><rect width="1600" height="1200" fill="#aca"/></svg>'});}
 else if(p.includes('/thumbnail')){imageRequests.push(u.href);return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><rect width="800" height="600" fill="#abc"/></svg>'});}
 else if(p==='/api/people/operations/current')json=job;
 else if(p==='/api/people')json=[{id:1,name:'Maya',count:2,cover:'a'},{id:2,name:'Maya',count:9,cover:'b'},{id:3,name:'Alice',count:20,cover:'c'},{id:4,name:null,count:3,cover:'d'},{id:-1,name:'Unknown People',count:8,cover:'e'},{id:0,name:'Unassigned faces',count:1,cover:'f'},...Array.from({length:180},(_,i)=>({id:i+10,name:'Person '+i,count:1,cover:'f'}))];
 else if(p==='/api/people/suggestions')json=[{face_id:'f',person_id:1,name:'Maya',score:.9,confidence:'high'}];
 else if(p==='/api/place-options')json={options:[]};
 else if(p.includes('/matching'))json={};
 await route.fulfill({json});});


 releaseMedia();await page.goto('http://127.0.0.1:'+server.address().port);await page.locator('.media-tile').first().waitFor();
 await page.getByRole('button',{name:/^People\s*\d*$/}).click();await page.locator('.people-grid').waitFor();
 const card=page.locator('[data-person-card="60"] .person-card');await card.scrollIntoViewIfNeeded();
 const before=await card.boundingBox(),scrollBefore=await page.evaluate(()=>scrollY);
 const cdp=viewport.width<=760?await page.context().newCDPSession(page):null;
 const hold=async()=>{const box=await card.locator('img').boundingBox(),x=box.x+box.width/2,y=box.y+box.height/2;if(cdp)await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x,y}]});else{await page.mouse.move(x,y);await page.mouse.down();}await page.clock.runFor(700);if(cdp)await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});else await page.mouse.up();};
 await hold();await page.getByRole('region',{name:'Find photos with selected people'}).waitFor();
 assert(Math.abs((await card.boundingBox()).y-before.y)<=1,'Entering selection preserves portrait position');
 assert(Math.abs(await page.evaluate(()=>scrollY)-scrollBefore)<=1,'Entering selection preserves scroll offset');
 const floating=page.getByRole('region',{name:'Find photos with selected people'}),go=floating.getByRole('button',{name:'Find photos',exact:true});
 assert(await go.isEnabled());
 const box=await go.boundingBox();assert(box.x>=0&&box.x+box.width<=viewport.width&&box.y>=0&&box.y+box.height<=viewport.height,'Find photos stays in viewport');
 assert(await go.evaluate(e=>{const r=e.getBoundingClientRect();return e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));}),'Find button is unobstructed');
 await page.screenshot({path:path.join(artifactDir,'people-selection-floating-'+viewport.width+'.png')});
 await hold();await floating.waitFor({state:'hidden'});
 assert(Math.abs((await card.boundingBox()).y-before.y)<=1,'Exiting selection preserves portrait position');
 assert(Math.abs(await page.evaluate(()=>scrollY)-scrollBefore)<=1,'Exiting selection preserves scroll offset');
 await hold();const request=page.waitForRequest(r=>new URL(r.url()).pathname==='/api/media'&&new URL(r.url()).searchParams.get('expression')==='Includes("Person 50 [#60]")');await go.click();await request;await page.locator('.people-grid').waitFor({state:'hidden'});
 assert.deepEqual(errors,[]);console.log('PASS',viewport.width,'deep-scroll selection stays anchored and floating Find opens results');await page.close();
}
}finally{await browser.close();server.close();}console.log('ARTIFACTS',artifactDir);})().catch(e=>{console.error(e);process.exitCode=1;server.close();});
