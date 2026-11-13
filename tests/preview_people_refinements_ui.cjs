const {chromium}=require(process.argv[2]||process.env.PLAYWRIGHT_MODULE||'playwright');
const http=require('http'),fs=require('fs'),path=require('path'),assert=require('assert/strict');
const artifactDir=fs.mkdtempSync(path.join(require('os').tmpdir(),'dahan-ui-'));const root=path.join(__dirname,'../frontend/dist');
const server=http.createServer((req,res)=>{const file=path.join(root,new URL(req.url,'http://local').pathname==='/'?'index.html':new URL(req.url,'http://local').pathname);try{res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(file));}catch{res.writeHead(404).end();}});
(async()=>{await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await chromium.launch({channel:'msedge',headless:true});try{
for(const viewport of [{width:1440,height:900},{width:390,height:844},{width:320,height:640}]){
 const page=await browser.newPage({viewport,reducedMotion:'reduce',hasTouch:viewport.width<=760,isMobile:viewport.width<=760});const errors=[];page.setDefaultTimeout(7000);page.on('pageerror',e=>{errors.push(e.message);console.log('PAGE ERROR',e.stack)});await page.clock.install();let job={id:'fixture',state:'completed',phase:'Matches ready for review',started_at:Date.now()/1000-60,finished_at:Date.now()/1000,updated_at:Date.now()/1000,result:{suggestions:1}};let releaseMedia;const mediaGate=new Promise(resolve=>releaseMedia=resolve);let releaseNeighbors;const neighborsGate=new Promise(resolve=>releaseNeighbors=resolve);let releaseDetail;const detailGate=new Promise(resolve=>releaseDetail=resolve);let offsetSeen=0;const imageRequests=[];
 await page.route('**/api/**',async route=>{const u=new URL(route.request().url()),p=u.pathname;let json=[];
 if(p==='/api/auth/me')json={id:'qa',name:'QA',theme:'light',source_ids:null,source_names:null};
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
 else if(p==='/api/people')json=[{id:1,name:'Maya',count:1}];
 else if(p==='/api/people/suggestions')json=[{face_id:'f',person_id:1,name:'Maya',score:.9,confidence:'high'}];
 else if(p==='/api/place-options')json={options:[]};
 else if(p.includes('/matching'))json={};
 await route.fulfill({json});});
 await page.addInitScript(()=>{Object.defineProperty(navigator,'canShare',{configurable:true,value:()=>true});Object.defineProperty(navigator,'share',{configurable:true,value:async data=>{window.__sharedNames=data.files.map(f=>f.name);}});});
 await page.goto('http://127.0.0.1:'+server.address().port);
 await page.locator('.results-loading-banner').waitFor();
 assert.equal(await page.getByText('Loading your moments…',{exact:true}).count(),0);
 assert.equal(await page.locator('.results-loading-banner').count(),1);
 const banner=await page.locator('.results-loading-banner').boundingBox(),top=await page.locator('.library-topbar').boundingBox();
 assert(banner.y>=top.y+top.height+10,'Popup border must clear the complete header');
 assert(banner.x>=0&&banner.x+banner.width<=viewport.width,'Popup must fit viewport');
 assert(await page.locator('.results-loading-banner').evaluate(e=>{const r=e.getBoundingClientRect();e.style.pointerEvents='auto';const hit=!!document.elementFromPoint(r.x+r.width/2,r.y+2)?.closest('.results-loading-banner');e.style.pointerEvents='';return hit}),'Top edge must be unobstructed');
 await page.screenshot({path:path.join(artifactDir,'loading-popup-'+viewport.width+'.png')});
 releaseMedia();await page.locator('.media-tile').first().waitFor();await page.locator('.results-loading-banner').waitFor({state:'hidden'});console.log('PASS',viewport.width,'single popup, full top edge, clears after results');


 await page.clock.runFor(21000);
 assert(await page.getByRole('button',{name:'People maintenance',exact:true}).isVisible());
 assert(await page.getByRole('button',{name:'People maintenance',exact:true}).locator('.tools-attention-dot').isVisible());
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Header fits screen');
 await page.getByRole('button',{name:/^People\s*\d*$/}).click();await page.locator('.people-grid').waitFor();
 assert.equal(await page.getByText('Keep your people up to date',{exact:true}).count(),0,'People page prioritizes portraits');assert(await page.locator('.people-grid').isVisible());
 await page.getByRole('button',{name:'People maintenance',exact:true}).click();await page.clock.runFor(100);await page.getByText('Keep your people up to date',{exact:true}).waitFor();assert.equal(new URL(page.url()).hash,'#tools/people');
 assert(await page.locator('.people-review-tools').isVisible());assert(await page.getByRole('button',{name:/^Library tools/}).locator('.tools-attention-dot').isVisible());
 await page.screenshot({path:path.join(artifactDir,'people-tools-'+viewport.width+'.png')});
 await page.getByRole('button',{name:/^People\s*\d*$/}).click();await page.getByRole('button',{name:'Library',exact:true}).click();await page.locator('.media-tile').first().waitFor();

 // Navigate just beyond the first gallery page, then close: the target must be loaded and revealed.
 await page.locator('[data-media-id="m79"] .photo-card').click();await page.getByRole('button',{name:'Next image or video',exact:true}).click();await page.locator('.viewer .incoming-frame img[alt="Photo m80"]').waitFor();
 await page.getByRole('button',{name:'Close viewer',exact:true}).click();await page.locator('.viewer-overlay').waitFor({state:'hidden'});await page.clock.runFor(100);
 await page.locator('[data-media-id="m80"]').waitFor();await page.clock.runFor(100);
 const visible=await page.locator('[data-media-id="m80"]').evaluate(e=>{const b=e.getBoundingClientRect(),h=document.querySelector('.library-topbar').getBoundingClientRect();return b.bottom>h.bottom&&b.top<innerHeight-64});assert(visible,'Last preview item is visible on returning');
 if(viewport.width<=760){
 await page.locator('[data-media-id="m80"] .photo-card').tap();await page.locator('.viewer-overlay').waitFor();
 // Resize in the middle of a sheet drag: an old inline offset must not hide it.
 let h=await page.locator('.media-info-handle').boundingBox();await page.mouse.move(h.x+h.width/2,h.y+24);await page.mouse.down();await page.mouse.move(h.x+h.width/2,h.y-90);await page.setViewportSize({width:844,height:390});await page.clock.runFor(100);await page.mouse.up();assert.equal(await page.locator('.media-info-sheet').evaluate(e=>e.style.transform),'');
 for(const size of [{width:844,height:390},viewport,{width:932,height:430},viewport]){
 await page.setViewportSize(size);await page.clock.runFor(100);const grip=await page.locator('.media-info-handle').boundingBox();assert(grip.y>=0&&grip.y+grip.height<=size.height,'Sheet handle stays onscreen across rotations');
 }
 const cdp=await page.context().newCDPSession(page);const box=await page.locator('.media-viewport').boundingBox();const x=box.x+box.width/2,y=box.y+box.height*.6;
  await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x,y}]});await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x,y:y-130}]});await page.clock.runFor(50);await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await page.locator('.viewer-overlay').waitFor({state:'hidden'});await page.clock.runFor(100);assert.equal(await page.locator('.viewer-overlay').count(),0,'Swipe up closes without click-through');
 await page.locator('[data-media-id="m81"] .photo-card').click();await page.locator('.viewer-overlay').waitFor();const v=await page.locator('.media-viewport').boundingBox();const vx=v.x+v.width*.25,vy=v.y+v.height*.7;await page.clock.runFor(100);
 await cdp.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:vx,y:vy}]});await cdp.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:vx,y:vy-130}]});await page.clock.runFor(50);await cdp.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});await page.locator('.viewer-overlay').waitFor({state:'hidden'});await page.clock.runFor(100);

 }
 assert.deepEqual(errors,[]);await page.screenshot({path:path.join(artifactDir,'rainbow-header-'+viewport.width+'.png')});console.log('PASS',viewport.width,'People-first browsing, maintenance attention, last-preview return, swipe and rotation');await page.close();
}
}finally{await browser.close();server.close();}console.log('ARTIFACTS',artifactDir);})().catch(e=>{console.error(e);process.exit(1)});
